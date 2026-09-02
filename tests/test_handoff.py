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
