import os

os.environ.setdefault("ASSEMBLYAI_API_KEY", "test-assembly-key")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")

import json
import tempfile
from pathlib import Path

import pytest

# Ensure env vars are visible to app.config before anything imports it.
import app.config  # noqa: E402  (must run after os.environ setup)
from app.services import rag as rag_module  # noqa: E402


class FakeSentenceTransformer:
    """Deterministic stand-in: registered strings map to one-hot vectors,
    everything else maps to the zero vector (cosine sim 0)."""

    def __init__(self):
        self._vectors = {}

    def set_vector(self, text: str, index: int, dim: int) -> None:
        vec = [0.0] * dim
        vec[index] = 1.0
        self._vectors[text] = vec

    def set_zero_vector(self, text: str, dim: int) -> None:
        self._vectors[text] = [0.0] * dim

    def encode(self, sentences, convert_to_tensor=False):
        import torch

        single = isinstance(sentences, str)
        if single:
            sentences = [sentences]
        dim = next(iter(self._vectors.values()), None)
        dim = len(dim) if dim else 8
        rows = [self._vectors.get(s) or [0.0] * dim for s in sentences]
        result = torch.tensor(rows, dtype=torch.float32)
        return result[0] if single else result


class FakeKnowledgeBase:
    """Stands in for app.services.rag.KnowledgeBase in API tests (no model load)."""

    def __init__(self):
        self._entries = [
            {"id": "e1", "question": "reset password", "response": "context one"},
            {"id": "e2", "question": "check balance", "response": "context two"},
        ]
        self.match_result = ("context one", 0.8)
        self._next_id = 100

    @property
    def count(self):
        return len(self._entries)

    def snapshot(self):
        return [dict(e) for e in self._entries]

    def best_match(self, query):
        return self.match_result

    def add_entry(self, question, response):
        if not response.strip():
            raise ValueError("'response' must be a non-empty string")
        entry = {"id": f"e{self._next_id}", "question": question, "response": response}
        self._next_id += 1
        self._entries.append(entry)
        return dict(entry)

    def update_entry(self, entry_id, question, response):
        if not response.strip():
            raise ValueError("'response' must be a non-empty string")
        for e in self._entries:
            if e["id"] == entry_id:
                e["question"] = question
                e["response"] = response
                return dict(e)
        return None

    def remove_entry(self, entry_id):
        for i, e in enumerate(self._entries):
            if e["id"] == entry_id:
                del self._entries[i]
                return True
        return False

    def reload(self):
        return True


@pytest.fixture
def fake_kb_factory():
    def make(entries):
        kb = FakeKnowledgeBase()
        kb._entries = [dict(e) for e in entries]
        return kb
    return make


@pytest.fixture
def client(monkeypatch):
    from app.main import app
    from fastapi.testclient import TestClient

    monkeypatch.setattr("app.main.KnowledgeBase", FakeKnowledgeBase)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def rag_environment(monkeypatch, tmp_path):
    """Real KnowledgeBase over a temp JSON + fake embedding model."""
    kb_path = tmp_path / "knowledge_base.json"
    entries = [
        {"question": "reset password", "response": "go to login page"},
        {"question": "check balance", "response": "check your dashboard"},
        {"question": "update address", "response": "edit profile settings"},
    ]
    kb_path.write_text(json.dumps(entries), encoding="utf-8")

    monkeypatch.setattr(rag_module.config, "KNOWLEDGE_BASE_PATH", kb_path)
    dim = len(entries) + 1  # headroom for entries added during tests
    model = FakeSentenceTransformer()
    for i, e in enumerate(entries):
        model.set_vector(e["response"], i, dim)
    monkeypatch.setattr(rag_module, "SentenceTransformer", lambda name: model)

    kb = rag_module.KnowledgeBase()
    return {"kb": kb, "model": model, "kb_path": kb_path, "entries": entries, "dim": dim}


@pytest.fixture
def tts_env(monkeypatch, tmp_path):
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    monkeypatch.setattr("app.services.tts.config.STATIC_DIR", static_dir)
    return {"static_dir": static_dir}
