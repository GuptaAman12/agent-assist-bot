import json
import os
import tempfile
import threading
import uuid

import torch
from sentence_transformers import SentenceTransformer, util

from .. import config


class KnowledgeBase:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
        self._mtime = 0.0
        self._entries: list[dict] = []
        self._ids: list[str] = []
        self._corpus_embeddings = None
        self.reload()

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [
                {"id": entry_id, "question": e.get("question", ""), "response": e["response"]}
                for entry_id, e in zip(self._ids, self._entries)
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
        entries = config.load_knowledge_base()
        embeddings = self._model.encode([e["response"] for e in entries], convert_to_tensor=True)
        ids = [uuid.uuid4().hex[:8] for _ in entries]
        with self._lock:
            self._entries = entries
            self._ids = ids
            self._corpus_embeddings = embeddings
            self._touch_mtime()
        return True

    def add_entry(self, question: str, response: str) -> dict:
        response = response.strip()
        if not response:
            raise ValueError("'response' must be a non-empty string")
        entry = {"question": question.strip(), "response": response}
        entry_id = uuid.uuid4().hex[:8]
        embedding = self._model.encode(response, convert_to_tensor=True)
        with self._lock:
            self._entries.append(entry)
            self._ids.append(entry_id)
            self._corpus_embeddings = torch.cat(
                [self._corpus_embeddings, embedding.unsqueeze(0)]
            )
            to_save = [dict(e) for e in self._entries]
        _persist(to_save)
        self._touch_mtime()
        return {"id": entry_id, "question": entry["question"], "response": response}

    def update_entry(self, entry_id: str, question: str, response: str) -> dict | None:
        response = response.strip()
        if not response:
            raise ValueError("'response' must be a non-empty string")
        entry = {"question": question.strip(), "response": response}
        embedding = self._model.encode(response, convert_to_tensor=True)
        with self._lock:
            if entry_id not in self._ids:
                return None
            idx = self._ids.index(entry_id)
            self._entries[idx] = entry
            self._corpus_embeddings[idx] = embedding
            to_save = [dict(e) for e in self._entries]
        _persist(to_save)
        self._touch_mtime()
        return {"id": entry_id, "question": entry["question"], "response": response}

    def remove_entry(self, entry_id: str) -> bool:
        with self._lock:
            if entry_id not in self._ids:
                return False
            idx = self._ids.index(entry_id)
            del self._ids[idx]
            del self._entries[idx]
            to_save = [dict(e) for e in self._entries]
        _persist(to_save)
        self.reload()
        return True

    def best_response(self, query: str) -> str:
        self.reload_if_changed()
        query_embedding = self._model.encode(query, convert_to_tensor=True)
        scores = util.pytorch_cos_sim(query_embedding, self._corpus_embeddings)[0]
        top_idx = scores.argmax().item()
        return self._entries[top_idx]["response"]

    def _touch_mtime(self) -> None:
        try:
            self._mtime = os.stat(config.KNOWLEDGE_BASE_PATH).st_mtime
        except OSError:
            self._mtime = 0.0


def _persist(entries: list[dict]) -> None:
    path = config.KNOWLEDGE_BASE_PATH
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
