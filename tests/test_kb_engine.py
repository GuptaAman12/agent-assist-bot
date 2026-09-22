"""
E2E: Knowledge base engine — hot-reload, incremental re-encoding, fail-open
resilience, and soft-delete lifecycle.

These tests exercise the real KnowledgeBase class (with FakeSentenceTransformer)
against a temp JSON file on disk.  They verify the engine behaviors that the
HTTP API depends on but can't directly observe:

- Hot reload detects external file edits via mtime
- Incremental encoding only re-encodes changed entries (performance)
- Broken JSON files don't crash the service (fail-open)
- IDs are stable across reloads
- Soft deletes work correctly at the engine level

The _bump_mtime() pattern is required because NTFS timestamp granularity
caused flaky tests — preserve it.
"""
import json
import os
import threading
import time

import pytest
import torch

from app.services import rag


def _bump_mtime(path, delta_sec=5):
    future = time.time() + delta_sec
    os.utime(path, (future, future))


class TestHotReload:
    """Verify that external edits to knowledge_base.json are detected and
    applied without restart."""

    def test_external_edit_adds_entry_without_restart(self, rag_environment):
        """An admin hand-edits the JSON file.  The next query should pick up
        the new entry without any explicit reload call."""
        kb = rag_environment["kb"]
        model = rag_environment["model"]
        kb_path = rag_environment["kb_path"]
        dim = rag_environment["dim"]
        new_idx = len(rag_environment["entries"])

        # Externally append a new entry to the JSON file
        on_disk = json.loads(kb_path.read_text(encoding="utf-8"))
        on_disk.append({"question": "cancel subscription", "response": "go to billing settings"})
        kb_path.write_text(json.dumps(on_disk), encoding="utf-8")
        _bump_mtime(kb_path)

        model.set_vector(rag._embed_text("cancel subscription", "go to billing settings"), new_idx, dim)
        assert kb.reload_if_changed() is True
        assert kb.count == 4

    def test_broken_json_keeps_serving_last_good_state(self, rag_environment):
        """If someone writes broken JSON, the KB should keep serving the
        last known-good state rather than crashing — fail-open behavior."""
        kb = rag_environment["kb"]
        model = rag_environment["model"]
        kb_path = rag_environment["kb_path"]
        dim = rag_environment["dim"]

        # Corrupt the file
        kb_path.write_text("{ this is not valid JSON ...", encoding="utf-8")
        _bump_mtime(kb_path)

        # Reload should fail but not crash
        assert kb.reload_if_changed() is False
        assert kb.count == 3  # still has the old entries

        # Queries still work against the old data
        model.set_vector("how do I reset my password", 0, dim)
        text, score = kb.best_match("how do I reset my password")
        assert text == "go to login page"
        assert score > 0.9

    def test_internal_write_does_not_trigger_self_reload(self, rag_environment):
        """When the KB writes to the file itself (e.g. via add_entry),
        it should NOT trigger a reload on the next query — the mtime
        is touched to prevent this."""
        kb = rag_environment["kb"]
        model = rag_environment["model"]
        dim = rag_environment["dim"]
        new_idx = len(rag_environment["entries"])

        model.set_vector(rag._embed_text("new q", "new a"), new_idx, dim)
        kb.add_entry("new q", "new a")

        # No reload should be needed
        assert kb.reload_if_changed() is False


class TestIncrementalEncoding:
    """Verify that reloads only re-encode entries that actually changed."""

    def test_only_modified_entries_re_encoded(self, rag_environment):
        """When one entry's response changes, only that entry should be
        re-encoded by the embedding model — the others should keep their
        exact same vectors."""
        kb = rag_environment["kb"]
        model = rag_environment["model"]
        kb_path = rag_environment["kb_path"]
        dim = rag_environment["dim"]

        old_vectors = [row.clone() for row in kb._corpus_embeddings]

        # Modify only the second entry
        on_disk = json.loads(kb_path.read_text(encoding="utf-8"))
        on_disk[1]["response"] = "see your balance online"
        kb_path.write_text(json.dumps(on_disk), encoding="utf-8")
        _bump_mtime(kb_path)

        model.set_vector(rag._embed_text("check balance", "see your balance online"), 3, dim)

        encode_calls = []
        orig_encode = model.encode

        def recording_encode(sentences, convert_to_tensor=False):
            texts = [sentences] if isinstance(sentences, str) else list(sentences)
            encode_calls.extend(texts)
            return orig_encode(sentences, convert_to_tensor=convert_to_tensor)

        model.encode = recording_encode
        assert kb.reload_if_changed() is True

        # Only the changed entry was re-encoded
        assert len(encode_calls) == 1
        assert "see your balance online" in encode_calls[0]

        # Untouched entries kept their exact vectors
        assert torch.equal(kb._corpus_embeddings[0], old_vectors[0])
        assert torch.equal(kb._corpus_embeddings[2], old_vectors[2])
        # Changed entry has a new vector
        assert not torch.equal(kb._corpus_embeddings[1], old_vectors[1])

    def test_question_change_triggers_re_encoding(self, rag_environment):
        """Changing just the question (not the response) should still trigger
        re-encoding because question+response are embedded together."""
        kb = rag_environment["kb"]
        model = rag_environment["model"]
        kb_path = rag_environment["kb_path"]
        dim = rag_environment["dim"]

        on_disk = json.loads(kb_path.read_text(encoding="utf-8"))
        on_disk[0]["question"] = "how do I change my password"
        kb_path.write_text(json.dumps(on_disk), encoding="utf-8")
        _bump_mtime(kb_path)

        changed_text = rag._embed_text("how do I change my password", "go to login page")
        model.set_vector(changed_text, 3, dim)

        encode_calls = []
        orig_encode = model.encode

        def recording_encode(sentences, convert_to_tensor=False):
            texts = [sentences] if isinstance(sentences, str) else list(sentences)
            encode_calls.extend(texts)
            return orig_encode(sentences, convert_to_tensor=convert_to_tensor)

        model.encode = recording_encode
        assert kb.reload_if_changed() is True
        assert encode_calls == [changed_text]

    def test_no_encoding_when_content_unchanged(self, rag_environment):
        """Bumping the file mtime without changing content should trigger
        a reload but zero model.encode() calls."""
        kb = rag_environment["kb"]
        model = rag_environment["model"]
        kb_path = rag_environment["kb_path"]

        encode_calls = []
        orig_encode = model.encode

        def recording_encode(sentences, convert_to_tensor=False):
            texts = [sentences] if isinstance(sentences, str) else list(sentences)
            encode_calls.extend(texts)
            return orig_encode(sentences, convert_to_tensor=convert_to_tensor)

        model.encode = recording_encode

        _bump_mtime(kb_path, delta_sec=10)
        assert kb.reload_if_changed() is True
        assert encode_calls == []  # no encoding happened


class TestIDStability:
    """Verify that entry IDs are stable across reloads and deduplication."""

    def test_ids_persist_through_multiple_reloads(self, rag_environment):
        """IDs assigned on first load should survive multiple forced reloads."""
        kb = rag_environment["kb"]
        kb_path = rag_environment["kb_path"]

        ids_original = [e["id"] for e in kb.snapshot()]
        assert len(set(ids_original)) == 3

        _bump_mtime(kb_path)
        kb.reload_if_changed()
        _bump_mtime(kb_path, delta_sec=10)
        kb.reload_if_changed()

        assert [e["id"] for e in kb.snapshot()] == ids_original

    def test_duplicate_and_invalid_ids_resolved(self, rag_environment):
        """Loading a file with duplicate IDs, numeric IDs, empty IDs, and
        missing IDs should result in all entries getting unique string IDs."""
        kb = rag_environment["kb"]
        kb_path = rag_environment["kb_path"]

        kb_path.write_text(json.dumps([
            {"id": "dup", "response": "first"},
            {"id": "dup", "response": "second"},
            {"id": 123, "response": "numeric"},
            {"id": "", "response": "empty"},
            {"response": "missing"},
        ]), encoding="utf-8")
        _bump_mtime(kb_path)

        kb.reload_if_changed()
        ids = [e["id"] for e in kb.snapshot()]
        assert len(set(ids)) == 5  # all unique
        assert ids[0] == "dup"  # first occurrence keeps its id

        # IDs persisted back to disk
        on_disk = json.loads(kb_path.read_text(encoding="utf-8"))
        assert [e["id"] for e in on_disk] == ids


class TestSoftDeleteLifecycle:
    """Verify soft-delete, restore, and snapshot filtering at the engine level."""

    def test_soft_delete_hides_from_active_but_searchable_with_flag(self, rag_environment):
        """Soft-deleted entries should be invisible in normal snapshots and
        search results, but visible with include_deleted=True."""
        kb = rag_environment["kb"]
        kb_path = rag_environment["kb_path"]

        entry_id = kb.snapshot()[0]["id"]
        assert kb.remove_entry(entry_id) is True
        assert kb.count == 2

        # Not in active snapshot
        active_ids = [e["id"] for e in kb.snapshot()]
        assert entry_id not in active_ids

        # Visible with include_deleted
        all_ids = [e["id"] for e in kb.snapshot(include_deleted=True)]
        assert entry_id in all_ids

        # Persisted to disk with deleted_at
        on_disk = json.loads(kb_path.read_text(encoding="utf-8"))
        deleted = next(e for e in on_disk if e["id"] == entry_id)
        assert deleted.get("deleted_at")

    def test_restore_brings_entry_back(self, rag_environment):
        """Restoring a soft-deleted entry should make it active again."""
        kb = rag_environment["kb"]

        entry_id = kb.snapshot()[0]["id"]
        kb.remove_entry(entry_id)
        assert kb.count == 2

        restored = kb.restore_entry(entry_id)
        assert restored is not None
        assert kb.count == 3
        assert entry_id in [e["id"] for e in kb.snapshot()]

    def test_add_entry_persists_and_is_searchable(self, rag_environment):
        """A new entry should be immediately searchable via the vector index."""
        kb = rag_environment["kb"]
        model = rag_environment["model"]
        kb_path = rag_environment["kb_path"]
        dim = rag_environment["dim"]
        new_idx = len(rag_environment["entries"])

        model.set_vector(rag._embed_text("new question", "new answer text"), new_idx, dim)
        created = kb.add_entry("new question", "new answer text")
        assert created["response"] == "new answer text"
        assert kb.count == 4

        # Persisted to disk
        on_disk = json.loads(kb_path.read_text(encoding="utf-8"))
        assert on_disk[-1]["response"] == "new answer text"

        # Searchable
        model.set_vector("query for new entry", new_idx, dim)
        text, _ = kb.best_match("query for new entry")
        assert text == "new answer text"


class TestThreadSafety:
    """Verify that the KB's RLock allows safe concurrent access."""

    def test_lock_is_reentrant_no_deadlock(self, rag_environment):
        """The KB uses RLock so nested lock acquisition (which can happen
        in real code paths) doesn't deadlock."""
        kb = rag_environment["kb"]

        done = threading.Event()

        def nested():
            with kb._lock:
                with kb._lock:
                    kb.snapshot()
            done.set()

        t = threading.Thread(target=nested, daemon=True)
        t.start()
        assert done.wait(timeout=5), "nested lock acquisition deadlocked"
