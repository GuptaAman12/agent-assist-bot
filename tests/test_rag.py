import json
import os
import time

import pytest

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
    assert len(on_disk) == 2


def test_remove_entry_unknown_id(rag_environment):
    kb = rag_environment["kb"]
    assert kb.remove_entry("nope") is False


def _bump_mtime(path):
    future = time.time() + 5
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
