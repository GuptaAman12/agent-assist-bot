import json
import logging
import math
import os
import re
import tempfile
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone

import torch
from sentence_transformers import SentenceTransformer, util

from .. import config

logger = logging.getLogger(__name__)


def _embed_text(question: str, response: str) -> str:
    """Text actually embedded: question + response.

    User queries ("how do I reset my password?") read like KB questions, not
    answers, so embedding the response alone misses the closest phrasing.
    """
    question = (question or "").strip()
    response = (response or "").strip()
    return f"{question}\n{response}" if question else response


def _active_embed_texts(entries: list[dict]) -> list[str]:
    return [
        _embed_text(e.get("question", ""), e["response"])
        for e in entries
        if not e.get("deleted_at")
    ]


def _tokenize(text: str) -> list[str]:
    """Tokenize query and document strings into lowercase word/code tokens.
    Preserves alphanumeric codes like ORD-123, ERR-403, and single digits."""
    return [t for t in re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", (text or "").lower()) if t]


class BM25Index:
    """Okapi BM25 index over a collection of active document texts."""

    def __init__(self, corpus: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.corpus_size = len(corpus)
        self.doc_tokens = [_tokenize(doc) for doc in corpus]
        self.doc_lens = [len(tokens) for tokens in self.doc_tokens]
        self.avgdl = sum(self.doc_lens) / self.corpus_size if self.corpus_size > 0 else 1.0

        self.doc_freqs: Counter[str] = Counter()
        self.term_freqs: list[Counter[str]] = []
        for tokens in self.doc_tokens:
            tf = Counter(tokens)
            self.term_freqs.append(tf)
            for term in tf:
                self.doc_freqs[term] += 1

        self.idf: dict[str, float] = {}
        for term, freq in self.doc_freqs.items():
            self.idf[term] = math.log(1.0 + (self.corpus_size - freq + 0.5) / (freq + 0.5))

    def score(self, query_tokens: list[str], doc_idx: int) -> float:
        """Raw BM25 score of a document for query tokens."""
        if not query_tokens or doc_idx >= self.corpus_size:
            return 0.0
        doc_len = self.doc_lens[doc_idx]
        tf_map = self.term_freqs[doc_idx]
        score = 0.0
        len_norm = 1.0 - self.b + self.b * (doc_len / self.avgdl)
        for term in query_tokens:
            if term not in tf_map:
                continue
            tf = tf_map[term]
            idf = self.idf.get(term, 0.0)
            score += idf * (tf * (self.k1 + 1.0)) / (tf + self.k1 * len_norm)
        return score

    def normalized_scores(self, query: str) -> list[float]:
        """Compute normalized BM25 scores in [0.0, 1.0] for all documents."""
        tokens = _tokenize(query)
        if not tokens or self.corpus_size == 0:
            return [0.0] * self.corpus_size

        raw_scores = [self.score(tokens, i) for i in range(self.corpus_size)]
        max_raw = max(raw_scores) if raw_scores else 0.0
        if max_raw <= 0.0:
            return [0.0] * self.corpus_size

        matching_terms = [t for t in set(tokens) if t in self.doc_freqs]
        if not matching_terms:
            return [0.0] * self.corpus_size

        denom = sum(self.idf.get(t, 0.0) for t in matching_terms)
        if denom <= 0.0:
            denom = max_raw

        return [min(1.0, max(0.0, s / denom)) for s in raw_scores]


class KnowledgeBase:
    def __init__(self) -> None:
        # RLock: nested acquisition by the same thread is safe (plain Lock
        # would deadlock). Cross-thread mutual exclusion is unchanged.
        self._lock = threading.RLock()
        self._model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
        self._mtime = 0.0
        # All entries including soft-deleted, each dict: {id, question, response, deleted_at}
        self._entries: list[dict] = []
        self._corpus_embeddings = None
        self._bm25: BM25Index | None = None
        self.reload()

    def _rebuild_bm25(self) -> None:
        active = [e for e in self._entries if not e.get("deleted_at")]
        corpus = [_embed_text(e.get("question", ""), e["response"]) for e in active]
        self._bm25 = BM25Index(corpus)

    @property
    def count(self) -> int:
        with self._lock:
            return sum(1 for e in self._entries if not e.get("deleted_at"))

    def snapshot(self, include_deleted: bool = False) -> list[dict]:
        with self._lock:
            result = []
            for e in self._entries:
                if not include_deleted and e.get("deleted_at"):
                    continue
                result.append({"id": e["id"], "question": e.get("question", ""), "response": e["response"]})
            return result

    def snapshot_with_deleted(self) -> list[dict]:
        with self._lock:
            return [
                {"id": e["id"], "question": e.get("question", ""), "response": e["response"], "deleted_at": e.get("deleted_at")}
                for e in self._entries
            ]

    def reload_if_changed(self) -> bool:
        try:
            current_mtime = os.stat(config.KNOWLEDGE_BASE_PATH).st_mtime
        except OSError:
            return False
        if current_mtime == self._mtime:
            return False
        try:
            return self.reload()
        except (ValueError, OSError, json.JSONDecodeError):
            self._touch_mtime()
            return False

    def reload(self) -> bool:
        raw_entries = config.load_knowledge_base()
        normalized = []
        used_ids: set[str] = set()
        migrated = 0
        for raw in raw_entries:
            raw_id = raw.get("id")
            if isinstance(raw_id, str) and raw_id and raw_id not in used_ids:
                entry_id = raw_id
            else:
                # Missing, empty, non-string, or duplicate id: assign a fresh one.
                # Guard the (astronomically unlikely) collision within this file.
                entry_id = uuid.uuid4().hex[:8]
                while entry_id in used_ids:
                    entry_id = uuid.uuid4().hex[:8]
                migrated += 1
            used_ids.add(entry_id)
            normalized.append({
                "id": entry_id,
                "question": raw.get("question", ""),
                "response": raw["response"],
                "deleted_at": raw.get("deleted_at"),
            })
        new_active = [e for e in normalized if not e.get("deleted_at")]

        with self._lock:
            # Snapshot old rows by id so unchanged entries keep their vectors.
            old_rows: dict[str, tuple[str, torch.Tensor]] = {}
            old_active = [e for e in self._entries if not e.get("deleted_at")]
            emb = self._corpus_embeddings
            if emb is not None and emb.numel() > 0:
                for pos, e in enumerate(old_active):
                    if pos < emb.shape[0]:
                        old_rows[e["id"]] = (_embed_text(e.get("question", ""), e["response"]), emb[pos])
            need_idx = [
                i for i, e in enumerate(new_active)
                if e["id"] not in old_rows
                or old_rows[e["id"]][0] != _embed_text(e.get("question", ""), e["response"])
            ]

        # Encode only new/changed entries; never hold the lock during encode.
        fresh: dict[int, torch.Tensor] = {}
        if need_idx:
            vecs = self._model.encode(
                [_embed_text(new_active[i].get("question", ""), new_active[i]["response"]) for i in need_idx],
                convert_to_tensor=True,
            )
            for pos, i in enumerate(need_idx):
                fresh[i] = vecs[pos] if vecs.dim() == 2 else vecs

        rows = [fresh[i] if i in fresh else old_rows[new_active[i]["id"]][1] for i in range(len(new_active))]
        if rows:
            embeddings = torch.stack(rows)
        else:
            embeddings = torch.empty((0, 384))
            # Dummy shape - will be replaced on next add; best_matches handles empty
            # Use 0 rows; best_matches will return empty
            try:
                # Try to get real dim from model
                dim = self._model.get_sentence_embedding_dimension()
                embeddings = torch.empty((0, dim))
            except Exception:
                embeddings = torch.empty((0, 384))

        with self._lock:
            self._entries = normalized
            self._corpus_embeddings = embeddings
            self._rebuild_bm25()
            self._touch_mtime()
        if migrated:
            # Write the assigned ids back so they are stable across reloads.
            # _persist is atomic; re-touch mtime so our own write is not
            # mistaken for an external edit (which would trigger a reload).
            try:
                _persist([dict(e) for e in normalized])
            finally:
                self._touch_mtime()
            logger.info("migrated %d KB entries with stable ids", migrated)
        return True

    def add_entry(self, question: str, response: str) -> dict:
        response = response.strip()
        if not response:
            raise ValueError("'response' must be a non-empty string")
        entry = {"id": uuid.uuid4().hex[:8], "question": question.strip(), "response": response, "deleted_at": None}
        embedding = self._model.encode(_embed_text(entry["question"], response), convert_to_tensor=True)
        with self._lock:
            self._entries.append(entry)
            # Append to active embeddings
            if self._corpus_embeddings is None or self._corpus_embeddings.numel() == 0:
                # Rebuild from active to get correct shape
                self._corpus_embeddings = self._model.encode(_active_embed_texts(self._entries), convert_to_tensor=True)
            else:
                self._corpus_embeddings = torch.cat(
                    [self._corpus_embeddings, embedding.unsqueeze(0)]
                )
            self._rebuild_bm25()
            to_save = [dict(e) for e in self._entries]
        _persist(to_save)
        self._touch_mtime()
        return {"id": entry["id"], "question": entry["question"], "response": response}

    def update_entry(self, entry_id: str, question: str, response: str) -> dict | None:
        response = response.strip()
        if not response:
            raise ValueError("'response' must be a non-empty string")
        embedding = self._model.encode(_embed_text(question, response), convert_to_tensor=True)
        with self._lock:
            idx = next((i for i, e in enumerate(self._entries) if e["id"] == entry_id), None)
            if idx is None:
                return None
            if self._entries[idx].get("deleted_at"):
                return None
            self._entries[idx]["question"] = question.strip()
            self._entries[idx]["response"] = response
            # Update embedding: find position in active embeddings
            active_indices = [i for i, e in enumerate(self._entries) if not e.get("deleted_at")]
            try:
                emb_pos = active_indices.index(idx)
                self._corpus_embeddings[emb_pos] = embedding
            except ValueError:
                pass
            self._rebuild_bm25()
            to_save = [dict(e) for e in self._entries]
        _persist(to_save)
        self._touch_mtime()
        return {"id": entry_id, "question": question.strip(), "response": response}

    def remove_entry(self, entry_id: str) -> bool:
        with self._lock:
            idx = next((i for i, e in enumerate(self._entries) if e["id"] == entry_id), None)
            if idx is None:
                return False
            if self._entries[idx].get("deleted_at"):
                return False
            self._entries[idx]["deleted_at"] = datetime.now(timezone.utc).isoformat()
            # Rebuild embeddings without this entry
            active_texts = _active_embed_texts(self._entries)
            if active_texts:
                self._corpus_embeddings = self._model.encode(active_texts, convert_to_tensor=True)
            else:
                # Empty: keep 0-row tensor with correct dim
                try:
                    dim = self._model.get_sentence_embedding_dimension()
                    self._corpus_embeddings = torch.empty((0, dim))
                except Exception:
                    self._corpus_embeddings = torch.empty((0, 384))
            self._rebuild_bm25()
            to_save = [dict(e) for e in self._entries]
        _persist(to_save)
        self._touch_mtime()
        return True

    def restore_entry(self, entry_id: str) -> dict | None:
        with self._lock:
            idx = next((i for i, e in enumerate(self._entries) if e["id"] == entry_id), None)
            if idx is None:
                return None
            if not self._entries[idx].get("deleted_at"):
                return None  # not deleted
            self._entries[idx]["deleted_at"] = None
            # Rebuild embeddings to include restored
            self._corpus_embeddings = self._model.encode(_active_embed_texts(self._entries), convert_to_tensor=True)
            self._rebuild_bm25()
            to_save = [dict(e) for e in self._entries]
        _persist(to_save)
        self._touch_mtime()
        e = self._entries[idx]
        return {"id": e["id"], "question": e.get("question", ""), "response": e["response"]}

    def best_matches(self, query: str, k: int = 3) -> list[tuple[str, float]]:
        self.reload_if_changed()
        with self._lock:
            active = [e for e in self._entries if not e.get("deleted_at")]
            embeddings = self._corpus_embeddings
            if embeddings is None or embeddings.numel() == 0 or not active:
                return []
            query_embedding = self._model.encode(query, convert_to_tensor=True)
            scores_dense = util.pytorch_cos_sim(query_embedding, embeddings)[0]
            scores_bm25 = self._bm25.normalized_scores(query) if self._bm25 else [0.0] * len(active)

            hybrid_scores = []
            for i in range(len(active)):
                s_dense = max(0.0, scores_dense[i].item())
                s_bm25 = scores_bm25[i] if i < len(scores_bm25) else 0.0
                if s_bm25 > 0:
                    score = max(s_dense + 0.35 * s_bm25 * (1.0 - s_dense), s_bm25)
                else:
                    score = s_dense
                hybrid_scores.append(score)

            order = sorted(range(len(hybrid_scores)), key=lambda i: hybrid_scores[i], reverse=True)
            matches = []
            for idx in order:
                score = hybrid_scores[idx]
                if score < config.KB_MIN_SIMILARITY:
                    break
                matches.append((active[idx]["response"], round(float(score), 4)))
                if len(matches) >= k:
                    break
            return matches

    def best_match(self, query: str) -> tuple[str | None, float]:
        matches = self.best_matches(query, k=1)
        if not matches:
            return None, 0.0
        text, score = matches[0]
        return text, score

    def import_entries(self, entries: list[dict]) -> int:
        # Validate already done by caller, but ensure response exists
        normalized = []
        for raw in entries:
            if not isinstance(raw, dict) or "response" not in raw or not str(raw["response"]).strip():
                raise ValueError("Each entry must have a non-empty 'response'")
            entry_id = raw.get("id") or uuid.uuid4().hex[:8]
            normalized.append({
                "id": entry_id,
                "question": raw.get("question", ""),
                "response": str(raw["response"]).strip(),
                "deleted_at": raw.get("deleted_at"),
            })
        # Only keep active for embeddings, but persist all (including soft-deleted if provided)
        active_texts = _active_embed_texts(normalized)
        if active_texts:
            embeddings = self._model.encode(active_texts, convert_to_tensor=True)
        else:
            try:
                dim = self._model.get_sentence_embedding_dimension()
                embeddings = torch.empty((0, dim))
            except Exception:
                embeddings = torch.empty((0, 384))
        with self._lock:
            self._entries = normalized
            self._corpus_embeddings = embeddings
            self._rebuild_bm25()
            to_save = [dict(e) for e in self._entries]
        _persist(to_save)
        self._touch_mtime()
        return sum(1 for e in normalized if not e.get("deleted_at"))

    def _touch_mtime(self) -> None:
        try:
            self._mtime = os.stat(config.KNOWLEDGE_BASE_PATH).st_mtime
        except OSError:
            self._mtime = 0.0


def _persist(entries: list[dict]) -> None:
    path = config.KNOWLEDGE_BASE_PATH
    # Only persist id, question, response, deleted_at (if set)
    to_write = []
    for e in entries:
        out = {"id": e["id"], "question": e.get("question", ""), "response": e["response"]}
        if e.get("deleted_at"):
            out["deleted_at"] = e["deleted_at"]
        to_write.append(out)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(to_write, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
