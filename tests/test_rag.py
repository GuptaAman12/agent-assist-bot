import json
import os
import threading
import time

import pytest
import torch

from app.services import rag


def test_reload_loads_entries(rag_environment):
    kb = rag_environment["kb"]
    assert kb.count == 3
    ids = [e["id"] for e in kb.snapshot()]
    assert len(set(ids)) == 3


def test_best_match_above_threshold(rag_environment):
    kb = rag_environment["kb"]
    model = rag_environment["model"]
    dim = rag_environment["dim"]
    model.set_vector("how do I reset my password", 0, dim)
    text, score = kb.best_match("how do I reset my password")
    assert text == "go to login page"
    assert score > 0.9


def test_best_match_below_threshold_returns_none(rag_environment):
    kb = rag_environment["kb"]
    model = rag_environment["model"]
    dim = rag_environment["dim"]
    model.set_zero_vector("gibberish query", dim)
    text, score = kb.best_match("gibberish query")
    assert text is None
    assert score < 0.45


def test_best_matches_returns_multiple_above_threshold(rag_environment):
    kb = rag_environment["kb"]
    model = rag_environment["model"]
    dim = rag_environment["dim"]
    # Superposition query: matches both entry 0 and entry 1 (cos sim ~0.707 each).
    model._vectors["query touching two topics"] = [1.0, 1.0] + [0.0] * (dim - 2)
    matches = kb.best_matches("query touching two topics", k=3)
    assert len(matches) == 2
    assert matches[0][0] == "go to login page"
    assert matches[1][0] == "check your dashboard"
    assert all(score >= 0.45 for _, score in matches)


def test_best_matches_respects_k(rag_environment):
    kb = rag_environment["kb"]
    model = rag_environment["model"]
    dim = rag_environment["dim"]
    model._vectors["query touching two topics"] = [1.0, 1.0] + [0.0] * (dim - 2)
    matches = kb.best_matches("query touching two topics", k=1)
    assert len(matches) == 1
    assert matches[0][0] == "go to login page"


def test_add_entry_persists_and_embeds(rag_environment):
    kb = rag_environment["kb"]
    model = rag_environment["model"]
    kb_path = rag_environment["kb_path"]
    dim = rag_environment["dim"]
    new_idx = rag_environment["entries"].__len__()

    model.set_vector("new answer text", new_idx, dim)
    created = kb.add_entry("new question", "new answer text")
    assert created["response"] == "new answer text"
    assert kb.count == 4

    on_disk = json.loads(kb_path.read_text(encoding="utf-8"))
    assert on_disk[-1]["response"] == "new answer text"

    model.set_vector("query for new entry", new_idx, dim)
    text, _ = kb.best_match("query for new entry")
    assert text == "new answer text"


def test_add_entry_rejects_empty_response(rag_environment):
    kb = rag_environment["kb"]
    with pytest.raises(ValueError):
        kb.add_entry("q", "   ")


def test_update_entry(rag_environment):
    kb = rag_environment["kb"]
    kb_path = rag_environment["kb_path"]
    entry_id = kb.snapshot()[0]["id"]
    updated = kb.update_entry(entry_id, "new q", "new resp")
    assert updated["response"] == "new resp"

    on_disk = json.loads(kb_path.read_text(encoding="utf-8"))
    assert on_disk[0]["response"] == "new resp"


def test_update_entry_unknown_id(rag_environment):
    kb = rag_environment["kb"]
    assert kb.update_entry("nope", "q", "r") is None


def test_remove_entry(rag_environment):
    kb = rag_environment["kb"]
    kb_path = rag_environment["kb_path"]
    entry_id = kb.snapshot()[0]["id"]
    assert kb.remove_entry(entry_id) is True
    assert kb.count == 2
    on_disk = json.loads(kb_path.read_text(encoding="utf-8"))
    assert len(on_disk) == 3
    deleted = [e for e in on_disk if e["id"] == entry_id][0]
    assert deleted.get("deleted_at")
    # Soft-deleted entry no longer appears in active snapshot
    assert entry_id not in [e["id"] for e in kb.snapshot()]
    assert entry_id in [e["id"] for e in kb.snapshot(include_deleted=True)]


def test_restore_entry(rag_environment):
    kb = rag_environment["kb"]
    kb_path = rag_environment["kb_path"]
    entry_id = kb.snapshot()[0]["id"]
    kb.remove_entry(entry_id)
    assert kb.count == 2
    restored = kb.restore_entry(entry_id)
    assert restored is not None
    assert restored["id"] == entry_id
    assert kb.count == 3
    on_disk = json.loads(kb_path.read_text(encoding="utf-8"))
    restored_raw = [e for e in on_disk if e["id"] == entry_id][0]
    assert not restored_raw.get("deleted_at")
    assert kb.restore_entry("nope") is None


def test_remove_entry_unknown_id(rag_environment):
    kb = rag_environment["kb"]
    assert kb.remove_entry("nope") is False


def _bump_mtime(path, delta_sec=5):
    future = time.time() + delta_sec
    os.utime(path, (future, future))


def test_reload_if_changed_detects_external_edit(rag_environment):
    kb = rag_environment["kb"]
    model = rag_environment["model"]
    kb_path = rag_environment["kb_path"]
    dim = rag_environment["dim"]
    new_idx = rag_environment["entries"].__len__()

    new_entries = json.loads(kb_path.read_text(encoding="utf-8"))
    new_entries.append({"question": "external", "response": "external answer"})
    kb_path.write_text(json.dumps(new_entries), encoding="utf-8")
    _bump_mtime(kb_path)

    model.set_vector("external answer", new_idx, dim)
    assert kb.reload_if_changed() is True
    assert kb.count == 4


def test_reload_if_changed_keeps_stale_data_on_broken_file(rag_environment):
    kb = rag_environment["kb"]
    model = rag_environment["model"]
    dim = rag_environment["dim"]
    kb_path = rag_environment["kb_path"]
    kb_path.write_text("{ definitely not json", encoding="utf-8")
    _bump_mtime(kb_path)

    assert kb.reload_if_changed() is False
    assert kb.count == 3

    model.set_vector("how do I reset my password", 0, dim)
    assert kb.best_match("how do I reset my password")[0] == "go to login page"


def test_reload_assigns_and_persists_stable_ids(rag_environment):
    kb = rag_environment["kb"]
    kb_path = rag_environment["kb_path"]
    # Fixture file starts id-less; the constructor's initial reload() migrates it.
    on_disk = json.loads(kb_path.read_text(encoding="utf-8"))
    assert all(e.get("id") for e in on_disk)

    ids_before = [e["id"] for e in kb.snapshot()]
    _bump_mtime(kb_path)
    assert kb.reload_if_changed() is True
    ids_after = [e["id"] for e in kb.snapshot()]
    assert ids_before == ids_after
    # A second forced reload is equally stable (no churn).
    # Use a larger delta: back-to-back bumps can round to the same
    # NTFS timestamp, which would (correctly) report "unchanged".
    _bump_mtime(kb_path, delta_sec=10)
    assert kb.reload_if_changed() is True
    assert [e["id"] for e in kb.snapshot()] == ids_before


def test_reload_dedupes_and_normalizes_ids(rag_environment):
    kb = rag_environment["kb"]
    kb_path = rag_environment["kb_path"]
    kb_path.write_text(
        json.dumps([
            {"id": "dup", "response": "first"},
            {"id": "dup", "response": "second"},
            {"id": 123, "response": "third"},
            {"id": "", "response": "fourth"},
            {"response": "fifth"},
        ]),
        encoding="utf-8",
    )
    _bump_mtime(kb_path)
    assert kb.reload_if_changed() is True

    ids = [e["id"] for e in kb.snapshot()]
    assert len(set(ids)) == 5
    assert ids[0] == "dup"  # first occurrence keeps its id
    on_disk = json.loads(kb_path.read_text(encoding="utf-8"))
    assert [e["id"] for e in on_disk] == ids


def test_ids_stable_after_own_write(rag_environment):
    kb = rag_environment["kb"]
    model = rag_environment["model"]
    dim = rag_environment["dim"]
    new_idx = rag_environment["entries"].__len__()

    before = [e["id"] for e in kb.snapshot()]
    model.set_vector("own answer", new_idx, dim)
    kb.add_entry("own q", "own answer")
    assert kb.reload_if_changed() is False
    after = [e["id"] for e in kb.snapshot()]
    assert before == after[:3]


def test_reload_only_reencodes_changed_rows(rag_environment):
    kb = rag_environment["kb"]
    model = rag_environment["model"]
    dim = rag_environment["dim"]
    kb_path = rag_environment["kb_path"]

    ids_before = [e["id"] for e in kb.snapshot()]
    old_vectors = [row.clone() for row in kb._corpus_embeddings]

    # Rewrite the file keeping ids, changing only the second response.
    on_disk = json.loads(kb_path.read_text(encoding="utf-8"))
    on_disk[1]["response"] = "see your balance online"
    kb_path.write_text(json.dumps(on_disk), encoding="utf-8")
    _bump_mtime(kb_path)

    model.set_vector("see your balance online", 3, dim)
    calls = []
    orig_encode = model.encode

    def recording_encode(sentences, convert_to_tensor=False):
        texts = [sentences] if isinstance(sentences, str) else list(sentences)
        calls.extend(texts)
        return orig_encode(sentences, convert_to_tensor=convert_to_tensor)

    model.encode = recording_encode
    assert kb.reload_if_changed() is True

    # Only the changed response was (re-)encoded; nothing else touched the model.
    assert calls == ["see your balance online"]
    # IDs unchanged, and untouched rows kept their exact vectors.
    assert [e["id"] for e in kb.snapshot()] == ids_before
    assert torch.equal(kb._corpus_embeddings[0], old_vectors[0])
    assert torch.equal(kb._corpus_embeddings[2], old_vectors[2])
    assert not torch.equal(kb._corpus_embeddings[1], old_vectors[1])
    # Retrieval still resolves against the updated text.
    model.set_vector("query balance", 3, dim)
    assert kb.best_match("query balance")[0] == "see your balance online"


def test_reload_skips_encoding_when_nothing_changed(rag_environment):
    kb = rag_environment["kb"]
    model = rag_environment["model"]
    kb_path = rag_environment["kb_path"]

    calls = []
    orig_encode = model.encode

    def recording_encode(sentences, convert_to_tensor=False):
        texts = [sentences] if isinstance(sentences, str) else list(sentences)
        calls.extend(texts)
        return orig_encode(sentences, convert_to_tensor=convert_to_tensor)

    model.encode = recording_encode
    before = kb._corpus_embeddings.clone()
    _bump_mtime(kb_path, delta_sec=10)
    assert kb.reload_if_changed() is True
    assert calls == []
    assert torch.equal(kb._corpus_embeddings, before)
    assert [e["id"] for e in kb.snapshot()] == [e["id"] for e in kb.snapshot()]


def test_lock_is_reentrant(rag_environment):
    kb = rag_environment["kb"]
    assert type(kb._lock).__name__ == "RLock"

    done = threading.Event()

    def nested():
        with kb._lock:
            with kb._lock:
                kb.snapshot()  # nested locked call, as future refactors may do
        done.set()

    t = threading.Thread(target=nested, daemon=True)
    t.start()
    assert done.wait(timeout=5), "nested lock acquisition deadlocked"
