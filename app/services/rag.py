import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone

import torch
from sentence_transformers import SentenceTransformer, util

from .. import config


class KnowledgeBase:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
        self._mtime = 0.0
        # All entries including soft-deleted, each dict: {id, question, response, deleted_at}
        self._entries: list[dict] = []
        self._corpus_embeddings = None
        self.reload()

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
        for raw in raw_entries:
            entry_id = raw.get("id") or uuid.uuid4().hex[:8]
            normalized.append({
                "id": entry_id,
                "question": raw.get("question", ""),
                "response": raw["response"],
                "deleted_at": raw.get("deleted_at"),
            })
        active_responses = [e["response"] for e in normalized if not e.get("deleted_at")]
        if active_responses:
            embeddings = self._model.encode(active_responses, convert_to_tensor=True)
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
            self._touch_mtime()
        return True

    def add_entry(self, question: str, response: str) -> dict:
        response = response.strip()
        if not response:
            raise ValueError("'response' must be a non-empty string")
        entry = {"id": uuid.uuid4().hex[:8], "question": question.strip(), "response": response, "deleted_at": None}
        embedding = self._model.encode(response, convert_to_tensor=True)
        with self._lock:
            self._entries.append(entry)
            # Append to active embeddings
            if self._corpus_embeddings is None or self._corpus_embeddings.numel() == 0:
                # Rebuild from active to get correct shape
                active_resp = [e["response"] for e in self._entries if not e.get("deleted_at")]
                self._corpus_embeddings = self._model.encode(active_resp, convert_to_tensor=True)
            else:
                self._corpus_embeddings = torch.cat(
                    [self._corpus_embeddings, embedding.unsqueeze(0)]
                )
            to_save = [dict(e) for e in self._entries]
        _persist(to_save)
        self._touch_mtime()
        return {"id": entry["id"], "question": entry["question"], "response": response}

    def update_entry(self, entry_id: str, question: str, response: str) -> dict | None:
        response = response.strip()
        if not response:
            raise ValueError("'response' must be a non-empty string")
        embedding = self._model.encode(response, convert_to_tensor=True)
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
            active_responses = [e["response"] for e in self._entries if not e.get("deleted_at")]
            if active_responses:
                self._corpus_embeddings = self._model.encode(active_responses, convert_to_tensor=True)
            else:
                # Empty: keep 0-row tensor with correct dim
                try:
                    dim = self._model.get_sentence_embedding_dimension()
                    self._corpus_embeddings = torch.empty((0, dim))
                except Exception:
                    self._corpus_embeddings = torch.empty((0, 384))
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
            active_responses = [e["response"] for e in self._entries if not e.get("deleted_at")]
            self._corpus_embeddings = self._model.encode(active_responses, convert_to_tensor=True)
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
            # Copy for thread safety outside lock? Use embeddings under lock
            # Compute outside lock to avoid blocking? Keep simple: compute inside.
            query_embedding = self._model.encode(query, convert_to_tensor=True)
            scores = util.pytorch_cos_sim(query_embedding, embeddings)[0]
            order = sorted(range(scores.numel()), key=lambda i: scores[i].item(), reverse=True)
            matches = []
            for idx in order:
                score = scores[idx].item()
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
