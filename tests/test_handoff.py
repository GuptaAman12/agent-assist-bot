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
