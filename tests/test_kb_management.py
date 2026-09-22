"""
E2E: Knowledge base CRUD lifecycle, import/export round-trip, soft-delete and
restore, pagination, and audit trail.

Each test walks through a realistic admin workflow rather than testing
individual operations in isolation.
"""
import json

import pytest


class TestKBLifecycle:
    """Full CRUD lifecycle through the HTTP API."""

    def test_create_update_delete_restore_lifecycle(self, client):
        """An admin creates an entry, edits it, deletes it (soft), verifies
        it's hidden, then restores it.  The full undo workflow."""
        # Create
        r = client.post("/kb", json={"question": "How do I reset MFA?", "response": "Go to Security > 2FA > Reset."})
        assert r.status_code == 200
        entry = r.json()
        entry_id = entry["id"]
        assert entry["question"] == "How do I reset MFA?"

        # Verify it appears in listing
        entries = client.get("/kb").json()["entries"]
        assert entry_id in [e["id"] for e in entries]

        # Update
        r = client.put(f"/kb/{entry_id}", json={
            "question": "How do I reset two-factor authentication?",
            "response": "Navigate to Settings > Security > 2FA and click Reset.",
        })
        assert r.status_code == 200
        assert "two-factor" in r.json()["question"]

        # Verify update persisted
        entries = client.get("/kb").json()["entries"]
        updated = next(e for e in entries if e["id"] == entry_id)
        assert "two-factor" in updated["question"]

        # Delete (soft)
        r = client.delete(f"/kb/{entry_id}")
        assert r.status_code == 200
        assert "undo_token" in r.json()

        # Verify hidden from normal listing but visible with include_deleted
        normal_ids = [e["id"] for e in client.get("/kb").json()["entries"]]
        assert entry_id not in normal_ids
        all_ids = [e["id"] for e in client.get("/kb?include_deleted=true").json()["entries"]]
        assert entry_id in all_ids

        # Restore
        r = client.post(f"/kb/{entry_id}/restore")
        assert r.status_code == 200
        assert r.json()["id"] == entry_id
        # Back in normal listing
        assert entry_id in [e["id"] for e in client.get("/kb").json()["entries"]]

    def test_cannot_restore_active_or_nonexistent_entry(self, client):
        """Restoring an entry that isn't deleted, or doesn't exist, returns 404."""
        # e1 is active — restoring it should fail
        assert client.post("/kb/e1/restore").status_code == 404
        # Nonexistent
        assert client.post("/kb/phantom/restore").status_code == 404

    def test_validation_rejects_empty_response(self, client):
        """Both create and update reject entries with blank responses."""
        assert client.post("/kb", json={"question": "q", "response": "   "}).status_code == 422
        assert client.put("/kb/e1", json={"question": "q", "response": ""}).status_code == 422

    def test_update_and_delete_unknown_id_returns_404(self, client):
        assert client.put("/kb/nope", json={"response": "r"}).status_code == 404
        assert client.delete("/kb/nope").status_code == 404


class TestKBPagination:
    """Pagination through a larger dataset."""

    def test_paginate_through_full_dataset(self, client):
        """Add entries to create a 7-item dataset, then page through it
        verifying each page gets the right slice and total count stays correct."""
        # Start with 2 entries (e1, e2), add 5 more
        for i in range(5):
            client.post("/kb", json={"question": f"page-q{i}", "response": f"page-r{i}"})

        total = client.get("/kb").json()["count"]
        assert total == 7

        # Page 1: 3 items
        p1 = client.get("/kb?limit=3&offset=0").json()
        assert len(p1["entries"]) == 3
        assert p1["count"] == 7
        assert p1["offset"] == 0

        # Page 2: 3 items
        p2 = client.get("/kb?limit=3&offset=3").json()
        assert len(p2["entries"]) == 3

        # Page 3: 1 remaining item
        p3 = client.get("/kb?limit=3&offset=6").json()
        assert len(p3["entries"]) == 1

        # Beyond range: empty
        p4 = client.get("/kb?limit=3&offset=100").json()
        assert len(p4["entries"]) == 0
        assert p4["count"] == 7  # total unchanged

        # All IDs across pages should be unique and cover the full set
        all_ids = [e["id"] for e in p1["entries"] + p2["entries"] + p3["entries"]]
        assert len(set(all_ids)) == 7


class TestKBImportExport:
    """Round-trip import/export and edge cases."""

    def test_export_import_roundtrip_preserves_data(self, client):
        """Export the current KB, import a different dataset, verify it
        replaced everything, then import the original back."""
        original = client.get("/kb/export").json()
        original_count = len(original)
        assert original_count >= 2  # fixture entries

        # Import a replacement
        new_data = [
            {"question": "What are your hours?", "response": "Mon-Fri 9-5 EST."},
            {"question": "How do I contact support?", "response": "Email help@example.com."},
            {"question": "Where are you located?", "response": "New York, NY."},
        ]
        r = client.post("/kb/import", json=new_data)
        assert r.status_code == 200
        assert r.json()["imported"] == 3

        # Verify replacement
        current = client.get("/kb").json()
        assert current["count"] == 3
        questions = {e["question"] for e in current["entries"]}
        assert "What are your hours?" in questions

        # Restore original
        r2 = client.post("/kb/import", json=original)
        assert r2.json()["imported"] == original_count

    def test_import_via_multipart_file_upload(self, client):
        """The import endpoint also accepts multipart file upload (for the
        drag-and-drop UI).  Verify it works with the {entries: [...]} wrapper."""
        payload = json.dumps({
            "entries": [
                {"question": "file-q1", "response": "file-r1"},
                {"question": "file-q2", "response": "file-r2"},
            ]
        }).encode()
        r = client.post("/kb/import", files={"file": ("kb.json", payload, "application/json")})
        assert r.status_code == 200
        assert r.json()["imported"] == 2

        # Restore fixture data
        client.post("/kb/import", json=[
            {"question": "reset password", "response": "context one"},
            {"question": "check balance", "response": "context two"},
        ])

    def test_import_rejects_entries_without_response(self, client):
        """Import validation should catch malformed entries."""
        r = client.post("/kb/import", json=[
            {"question": "good", "response": "valid"},
            {"question": "bad entry without response"},
        ])
        assert r.status_code == 422

    def test_export_is_downloadable_json_attachment(self, client):
        """Export should set Content-Disposition for file download."""
        r = client.get("/kb/export")
        assert r.status_code == 200
        assert "attachment" in r.headers.get("content-disposition", "")
        data = r.json()
        assert isinstance(data, list)
        assert all("response" in e for e in data)


class TestAuditTrail:
    """KB mutations should produce an audit trail."""

    def test_crud_operations_are_audit_logged(self, client, tmp_path, monkeypatch):
        """Create, update, and delete operations should each produce an audit
        log entry with action, entry_id, and request_id."""
        from app import config as app_config

        log_path = tmp_path / "audit_test.jsonl"
        monkeypatch.setattr(app_config, "AUDIT_LOG_PATH", log_path)

        # Create
        created = client.post("/kb", json={"question": "audit q", "response": "audit r"}).json()
        # Update
        client.put(f"/kb/{created['id']}", json={"question": "updated", "response": "updated r"})
        # Delete
        client.delete(f"/kb/{created['id']}")
        # Restore
        client.post(f"/kb/{created['id']}/restore")

        assert log_path.exists()
        lines = [json.loads(l) for l in log_path.read_text(encoding="utf-8").strip().splitlines()]
        actions = [l["action"] for l in lines]
        assert "kb_add" in actions
        assert "kb_update" in actions
        assert "kb_delete" in actions
        assert "kb_restore" in actions
        # Every entry has a request_id and timestamp
        assert all(l.get("request_id") for l in lines)
        assert all(l.get("ts") for l in lines)
        # Entry IDs tracked
        assert all(l.get("entry_id") == created["id"] for l in lines)
