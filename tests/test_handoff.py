import pytest

from app.services import handoff


def test_webhook_delivery(monkeypatch):
    monkeypatch.setattr(handoff.config, "HANDOFF_WEBHOOK_URL", "https://hooks.example.com/t")
    monkeypatch.setattr(handoff.config, "HANDOFF_EMAIL_TO", "")
    sent = {}

    class FakeResp:
        def raise_for_status(self):
            pass

    def fake_post(url, **kwargs):
        sent["url"] = url
        sent["json"] = kwargs["json"]
        return FakeResp()

    monkeypatch.setattr(handoff.requests, "post", fake_post)
    ticket_id = handoff.create_ticket(
        reason="speak_to_agent",
        transcript="talk to a real person",
        intents=["speak_to_agent"],
        assistant_response="An agent will help.",
    )
    assert ticket_id
    assert sent["url"] == "https://hooks.example.com/t"
    assert sent["json"]["reason"] == "speak_to_agent"
    assert sent["json"]["transcript"] == "talk to a real person"
    assert sent["json"]["intents"] == ["speak_to_agent"]


def test_webhook_failure_returns_none(monkeypatch):
    monkeypatch.setattr(handoff.config, "HANDOFF_WEBHOOK_URL", "https://hooks.example.com/t")
    monkeypatch.setattr(handoff.config, "HANDOFF_EMAIL_TO", "")

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(handoff.requests, "post", boom)
    assert handoff.create_ticket(reason="no_match", transcript="q", intents=[], assistant_response="r") is None


def test_email_delivery(monkeypatch):
    monkeypatch.setattr(handoff.config, "HANDOFF_WEBHOOK_URL", "")
    monkeypatch.setattr(handoff.config, "HANDOFF_EMAIL_TO", "support@example.com")
    monkeypatch.setattr(handoff.config, "HANDOFF_EMAIL_FROM", "bot@example.com")
    monkeypatch.setattr(handoff.config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(handoff.config, "SMTP_PORT", 587)
    monkeypatch.setattr(handoff.config, "SMTP_USER", "")
    sent = {}

    def fake_send_email(payload):
        sent["payload"] = payload

    monkeypatch.setattr(handoff, "_send_email", fake_send_email)
    ticket_id = handoff.create_ticket(reason="no_match", transcript="q", intents=[], assistant_response="r")
    assert ticket_id
    assert sent["payload"]["reason"] == "no_match"


def test_no_delivery_configured_still_records(monkeypatch):
    monkeypatch.setattr(handoff.config, "HANDOFF_WEBHOOK_URL", "")
    monkeypatch.setattr(handoff.config, "HANDOFF_EMAIL_TO", "")
    ticket_id = handoff.create_ticket(reason="no_match", transcript="q", intents=[], assistant_response="r")
    assert ticket_id  # recorded locally, never raises


def test_webhook_retries_and_succeeds(monkeypatch, tmp_path):
    monkeypatch.setattr(handoff.config, "HANDOFF_WEBHOOK_URL", "https://hooks.example.com/t")
    monkeypatch.setattr(handoff.config, "HANDOFF_EMAIL_TO", "")
    monkeypatch.setattr(handoff.config, "HANDOFF_QUEUE_PATH", tmp_path / "queue.jsonl")
    calls = {"n": 0}

    class FakeResp:
        def raise_for_status(self):
            pass

    def fake_post(*a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return FakeResp()

    monkeypatch.setattr(handoff.requests, "post", fake_post)
    monkeypatch.setattr(handoff.time, "sleep", lambda s: None)
    monkeypatch.setattr(handoff.random, "uniform", lambda a, b: 0)
    ticket_id = handoff.create_ticket(reason="speak_to_agent", transcript="q", intents=[], assistant_response="r")
    assert ticket_id
    assert calls["n"] == 3


def test_webhook_queues_to_disk_after_retries(monkeypatch, tmp_path):
    monkeypatch.setattr(handoff.config, "HANDOFF_WEBHOOK_URL", "https://hooks.example.com/t")
    monkeypatch.setattr(handoff.config, "HANDOFF_EMAIL_TO", "")
    queue_path = tmp_path / "queue.jsonl"
    monkeypatch.setattr(handoff.config, "HANDOFF_QUEUE_PATH", queue_path)

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(handoff.requests, "post", boom)
    monkeypatch.setattr(handoff.time, "sleep", lambda s: None)
    monkeypatch.setattr(handoff.random, "uniform", lambda a, b: 0)
    ticket_id = handoff.create_ticket(reason="no_match", transcript="q", intents=[], assistant_response="r")
    assert ticket_id is None
    # Queued payload should exist on disk
    assert queue_path.exists()
    import json

    line = queue_path.read_text(encoding="utf-8").strip().splitlines()[0]
    data = json.loads(line)
    assert data["reason"] == "no_match"


def test_get_queued_tickets_empty_and_corrupt(monkeypatch, tmp_path):
    queue_path = tmp_path / "queue.jsonl"
    monkeypatch.setattr(handoff.config, "HANDOFF_QUEUE_PATH", queue_path)

    # Missing file returns []
    assert handoff.get_queued_tickets() == []

    # Corrupt lines are skipped gracefully
    queue_path.write_text("not json\n{\"ticket_id\": \"t1\", \"reason\": \"no_match\"}\n\n{broken\n", encoding="utf-8")
    tickets = handoff.get_queued_tickets()
    assert len(tickets) == 1
    assert tickets[0]["ticket_id"] == "t1"


def test_replay_ticket_success_and_failure(monkeypatch, tmp_path):
    queue_path = tmp_path / "queue.jsonl"
    monkeypatch.setattr(handoff.config, "HANDOFF_QUEUE_PATH", queue_path)
    monkeypatch.setattr(handoff.config, "HANDOFF_WEBHOOK_URL", "https://hooks.example.com/t")
    monkeypatch.setattr(handoff.config, "HANDOFF_EMAIL_TO", "")

    ticket_data = {"ticket_id": "t1", "reason": "no_match", "transcript": "help"}
    handoff._queue_to_disk(ticket_data)
    assert len(handoff.get_queued_tickets()) == 1

    # Replay with delivery failure -> kept in queue
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(handoff.requests, "post", boom)
    res = handoff.replay_ticket("t1")
    assert res["success"] is False
    assert res["error"] == "delivery_failed"
    assert len(handoff.get_queued_tickets()) == 1

    # Replay with delivery success -> removed from queue
    class FakeResp:
        def raise_for_status(self):
            pass

    monkeypatch.setattr(handoff.requests, "post", lambda *a, **k: FakeResp())
    res = handoff.replay_ticket("t1")
    assert res["success"] is True
    assert res["remaining"] == 0
    assert len(handoff.get_queued_tickets()) == 0


def test_replay_ticket_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(handoff.config, "HANDOFF_QUEUE_PATH", tmp_path / "queue.jsonl")
    res = handoff.replay_ticket("nonexistent")
    assert res["success"] is False
    assert res["error"] == "not_found"


def test_replay_all_queued(monkeypatch, tmp_path):
    queue_path = tmp_path / "queue.jsonl"
    monkeypatch.setattr(handoff.config, "HANDOFF_QUEUE_PATH", queue_path)
    monkeypatch.setattr(handoff.config, "HANDOFF_WEBHOOK_URL", "https://hooks.example.com/t")

    handoff._queue_to_disk({"ticket_id": "t1", "reason": "no_match"})
    handoff._queue_to_disk({"ticket_id": "t2", "reason": "speak_to_agent"})
    assert len(handoff.get_queued_tickets()) == 2

    # t1 succeeds, t2 fails
    class FakeResp:
        def raise_for_status(self):
            pass

    def partial_post(url, json, **kwargs):
        if json["ticket_id"] == "t1":
            return FakeResp()
        raise RuntimeError("t2 failed")

    monkeypatch.setattr(handoff.requests, "post", partial_post)
    summary = handoff.replay_all_queued()
    assert summary["replayed"] == 1
    assert summary["failed"] == 1
    assert summary["remaining"] == 1

    remaining = handoff.get_queued_tickets()
    assert len(remaining) == 1
    assert remaining[0]["ticket_id"] == "t2"


def test_dismiss_ticket(monkeypatch, tmp_path):
    queue_path = tmp_path / "queue.jsonl"
    monkeypatch.setattr(handoff.config, "HANDOFF_QUEUE_PATH", queue_path)

    handoff._queue_to_disk({"ticket_id": "t1", "reason": "no_match"})
    handoff._queue_to_disk({"ticket_id": "t2", "reason": "speak_to_agent"})

    assert handoff.dismiss_ticket("t1") is True
    assert handoff.dismiss_ticket("t1") is False  # already dismissed
    remaining = handoff.get_queued_tickets()
    assert len(remaining) == 1
    assert remaining[0]["ticket_id"] == "t2"


def test_worker_start_stop(monkeypatch):
    monkeypatch.setattr(handoff.config, "HANDOFF_RETRY_INTERVAL_SEC", 300)
    handoff.stop_worker()  # ensure clean state
    handoff.start_worker()
    assert handoff._worker_thread is not None
    assert handoff._worker_thread.is_alive()
    handoff.stop_worker()
    assert handoff._worker_thread is None
