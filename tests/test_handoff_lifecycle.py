"""
E2E: Handoff escalation, ticket queue management, and replay lifecycle.

Tests the end-to-end flow from a customer request triggering a handoff,
through ticket queuing, listing, replaying (with success and failure),
and dismissal.
"""
import json

import pytest


class TestHandoffEscalation:
    """Verify that assist requests correctly escalate to human agents."""

    def test_speak_to_agent_creates_ticket_and_returns_id(self, client, monkeypatch):
        """When a customer explicitly asks for a human, /assist/ should:
        1. Still generate an LLM response (for the suggested response card)
        2. Create a handoff ticket
        3. Return handoff=true with the ticket_id
        """
        ticket_args = {}

        def capture_ticket(**kwargs):
            ticket_args.update(kwargs)
            return "HDO-001"

        monkeypatch.setattr("app.services.llm.generate_response", lambda s, q, history=None: "Let me transfer you.")
        monkeypatch.setattr("app.services.handoff.create_ticket", capture_ticket)

        r = client.post("/assist/", json={
            "transcript": "This is really frustrating, I need to talk to a real person right now",
            "intent": "speak_to_agent",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["handoff"] is True
        assert body["ticket_id"] == "HDO-001"
        assert body["response"] == "Let me transfer you."
        assert ticket_args["reason"] == "speak_to_agent"
        assert "frustrating" in ticket_args["transcript"].lower()

    def test_no_match_without_history_creates_handoff(self, client, monkeypatch):
        """A completely unrecognizable query with no prior conversation
        should escalate to human support."""
        client.app.state.knowledge_base.matches_result = []
        monkeypatch.setattr("app.services.handoff.create_ticket", lambda **k: "HDO-NOMATCH")

        r = client.post("/assist/", json={
            "transcript": "I need help with something very unusual involving quantum computing",
            "intent": "unknown",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["handoff"] is True
        assert body["ticket_id"] == "HDO-NOMATCH"

    def test_handoff_failure_returns_false_with_no_ticket_id(self, client, monkeypatch):
        """When the handoff service fails to deliver (webhook down, no email),
        handoff should be false and ticket_id null — the canned response
        is still returned."""
        client.app.state.knowledge_base.matches_result = []
        monkeypatch.setattr("app.services.handoff.create_ticket", lambda **k: None)

        r = client.post("/assist/", json={
            "transcript": "some weird query nobody understands",
            "intent": "unknown",
        })
        body = r.json()
        assert body["handoff"] is False
        assert body["ticket_id"] is None
        assert "not sure" in body["response"].lower()


class TestHandoffQueueManagement:
    """Test the admin-facing handoff queue lifecycle through the HTTP API."""

    def test_queue_lifecycle_add_list_replay_dismiss(self, client, monkeypatch):
        """Full queue lifecycle:
        1. Queue some tickets (simulating webhook failures)
        2. List them (newest first, with pagination)
        3. Replay one successfully → removed from queue
        4. Replay one that fails → stays in queue
        5. Dismiss remaining → removed
        """
        from app.services import handoff as handoff_service

        # Queue 3 tickets
        handoff_service._queue_to_disk({"ticket_id": "Q1", "reason": "no_match", "transcript": "query 1"})
        handoff_service._queue_to_disk({"ticket_id": "Q2", "reason": "speak_to_agent", "transcript": "query 2"})
        handoff_service._queue_to_disk({"ticket_id": "Q3", "reason": "no_match", "transcript": "query 3"})

        # List: should have 3, newest first
        listing = client.get("/handoff/queue").json()
        assert listing["count"] == 3
        assert listing["tickets"][0]["ticket_id"] == "Q3"

        # Pagination: 2 per page
        page1 = client.get("/handoff/queue?limit=2&offset=0").json()
        assert len(page1["tickets"]) == 2
        page2 = client.get("/handoff/queue?limit=2&offset=2").json()
        assert len(page2["tickets"]) == 1

        # Replay Q1 successfully
        class FakeResp:
            def raise_for_status(self):
                pass

        monkeypatch.setattr("app.services.handoff.requests.post", lambda *a, **k: FakeResp())
        monkeypatch.setattr("app.services.handoff.config.HANDOFF_WEBHOOK_URL", "https://hooks.example.com/t")

        r = client.post("/handoff/queue/replay?ticket_id=Q1")
        assert r.status_code == 200
        assert r.json()["success"] is True

        # Q1 removed from queue
        remaining = client.get("/handoff/queue").json()
        remaining_ids = [t["ticket_id"] for t in remaining["tickets"]]
        assert "Q1" not in remaining_ids
        assert remaining["count"] == 2

        # Replay Q2 but delivery fails → 502
        monkeypatch.setattr("app.services.handoff.requests.post", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
        r = client.post("/handoff/queue/replay?ticket_id=Q2")
        assert r.status_code == 502

        # Q2 still in queue
        assert client.get("/handoff/queue").json()["count"] == 2

        # Dismiss Q3
        r = client.delete("/handoff/queue/Q3")
        assert r.status_code == 200
        assert r.json()["deleted"] == "Q3"

        # Double-dismiss → 404
        assert client.delete("/handoff/queue/Q3").status_code == 404

    def test_replay_nonexistent_ticket_returns_404(self, client):
        r = client.post("/handoff/queue/replay?ticket_id=GHOST-999")
        assert r.status_code == 404

    def test_replay_all_partially_succeeds(self, client, monkeypatch):
        """Batch replay: some succeed, some fail.  Only failures remain."""
        from app.services import handoff as handoff_service

        handoff_service._queue_to_disk({"ticket_id": "ALL1", "reason": "no_match"})
        handoff_service._queue_to_disk({"ticket_id": "ALL2", "reason": "speak_to_agent"})
        handoff_service._queue_to_disk({"ticket_id": "ALL3", "reason": "no_match"})

        class FakeResp:
            def raise_for_status(self):
                pass

        def selective_post(url, json, **kwargs):
            if json.get("ticket_id") == "ALL2":
                raise RuntimeError("delivery down for ALL2")
            return FakeResp()

        monkeypatch.setattr("app.services.handoff.requests.post", selective_post)
        monkeypatch.setattr("app.services.handoff.config.HANDOFF_WEBHOOK_URL", "https://hooks.example.com/t")

        r = client.post("/handoff/queue/replay")
        assert r.status_code == 200
        body = r.json()
        assert body["replayed"] == 2  # ALL1 and ALL3 succeeded
        assert body["failed"] == 1  # ALL2 failed
        assert body["remaining"] == 1

        # Only ALL2 remains
        remaining = client.get("/handoff/queue").json()
        assert remaining["count"] == 1
        assert remaining["tickets"][0]["ticket_id"] == "ALL2"

    def test_handoff_queue_gated_by_admin_token(self, client, monkeypatch):
        """All queue endpoints are admin-protected."""
        monkeypatch.setattr("app.config.ADMIN_TOKEN", "s3cret")

        assert client.get("/handoff/queue").status_code == 401
        assert client.post("/handoff/queue/replay").status_code == 401
        assert client.delete("/handoff/queue/x").status_code == 401

        headers = {"X-Admin-Token": "s3cret"}
        assert client.get("/handoff/queue", headers=headers).status_code == 200
