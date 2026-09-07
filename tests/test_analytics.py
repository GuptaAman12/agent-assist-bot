import json
import logging

from app.logging import JsonFormatter
from app.services import analytics as analytics_service


def _analytics_lines(tmp_path):
    path = tmp_path / "analytics.log.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_no_match_logs_query_and_counts(client, tmp_path, monkeypatch):
    client.app.state.knowledge_base.matches_result = []
    monkeypatch.setattr("app.main.handoff_service.create_ticket", lambda **k: "t9")
    r = client.post("/assist/", json={"transcript": "quantum pineapple submarine", "intent": "unknown"})
    assert r.status_code == 200

    lines = _analytics_lines(tmp_path)
    assert len(lines) == 1
    line = lines[0]
    assert line["event"] == "no_match"
    assert line["transcript"] == "quantum pineapple submarine"
    assert line["from_history"] is False
    assert line["handoff"] is True
    assert line["ticket_id"] == "t9"
    assert "request_id" in line and line["request_id"]

    body = client.get("/stats").json()
    assert body["counters"]["no_match"] == 1
    assert body["counters"]["handoff:no_match"] == 1


def test_no_match_with_history_flagged(client, tmp_path, monkeypatch):
    client.app.state.knowledge_base.matches_result = []
    monkeypatch.setattr("app.main.llm_service.generate_response", lambda s, q, history=None: "answer")
    r = client.post(
        "/assist/",
        json={
            "transcript": "what about my order?",
            "intent": "unknown",
            "history": [{"transcript": "cancel my order", "response": "Go here."}],
        },
    )
    assert r.status_code == 200

    lines = _analytics_lines(tmp_path)
    assert [line["event"] for line in lines] == ["no_match", "assist"]
    assert lines[0]["event"] == "no_match"
    assert lines[0]["from_history"] is True
    assert lines[0]["handoff"] is False
    assert lines[1]["llm"] is True
    assert client.get("/stats").json()["counters"]["no_match"] == 1


def test_transcript_truncated(client, tmp_path, monkeypatch):
    client.app.state.knowledge_base.matches_result = []
    monkeypatch.setattr("app.main.handoff_service.create_ticket", lambda **k: None)  # delivery failed
    long_text = "word " * 500
    r = client.post("/assist/", json={"transcript": long_text, "intent": "unknown"})
    assert r.status_code == 200
    assert r.json()["handoff"] is False
    lines = _analytics_lines(tmp_path)
    assert len(lines[0]["transcript"]) <= analytics_service.MAX_TRANSCRIPT_CHARS
    assert lines[0]["handoff"] is False
    assert client.get("/stats").json()["counters"].get("handoff:no_match") is None


def test_assist_markers_and_counters(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.llm_service.generate_response", lambda s, q, history=None: "answer")
    monkeypatch.setattr("app.main.synthesize", lambda t: ("out.wav", "groq-orpheus"))
    # password_reset -> takeover (tts groq), no handoff
    r = client.post("/assist/", json={"transcript": "reset my password", "intent": "password_reset"})
    assert r.status_code == 200
    # refund_request -> no takeover (tts none), no handoff
    r = client.post("/assist/", json={"transcript": "refund please", "intent": "refund_request"})
    assert r.status_code == 200

    lines = _analytics_lines(tmp_path)
    assert [line["event"] for line in lines] == ["assist", "assist"]
    assert lines[0]["llm"] is True
    assert lines[0]["tts_engine"] == "groq-orpheus"
    assert lines[0]["kb_score"] == 0.8
    assert lines[0]["handoff"] is False
    assert lines[1]["tts_engine"] is None

    counters = client.get("/stats").json()["counters"]
    assert counters["llm_calls"] == 2
    assert counters["tts:groq-orpheus"] == 1
    assert counters["tts:none"] == 1
    assert "handoff:speak_to_agent" not in counters


def test_speak_to_agent_handoff_counted(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.llm_service.generate_response", lambda s, q, history=None: "answer")
    monkeypatch.setattr("app.main.handoff_service.create_ticket", lambda **k: "t1")
    r = client.post(
        "/assist/",
        json={"transcript": "I want to talk to a real person about my refund.", "intent": "speak_to_agent"},
    )
    assert r.status_code == 200
    assert r.json()["handoff"] is True
    counters = client.get("/stats").json()["counters"]
    assert counters["handoff:speak_to_agent"] == 1
    lines = _analytics_lines(tmp_path)
    assert lines[-1]["handoff"] is True
    assert lines[-1]["ticket_id"] == "t1"


def test_transcribe_counted(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.transcription_service.transcribe_file", lambda p: "hello")
    r = client.post("/transcribe/", files={"file": ("test.wav", b"RIFFfake", "audio/wav")})
    assert r.status_code == 200
    lines = _analytics_lines(tmp_path)
    assert len(lines) == 1
    assert lines[0]["event"] == "transcribe"
    assert lines[0]["intent"] == "unknown"
    assert client.get("/stats").json()["counters"]["transcribe_requests"] == 1


def test_stats_shape_and_kb_count(client):
    body = client.get("/stats").json()
    assert set(body) == {"counters", "kb_count"}
    assert body["kb_count"] == 2  # FakeKnowledgeBase entries
    assert body["counters"] == {}


def test_stats_requires_token_when_configured(client, monkeypatch):
    monkeypatch.setattr("app.config.ADMIN_TOKEN", "s3cret")
    assert client.get("/stats").status_code == 401
    r = client.get("/stats", headers={"X-Admin-Token": "s3cret"})
    assert r.status_code == 200
    assert "counters" in r.json()


def test_log_event_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.analytics.config.ANALYTICS_LOG_PATH", tmp_path)  # a dir, not a file
    analytics_service.log_event("assist", intents=[])
    analytics_service.log_no_match("hi", [])
    analytics_service.record("x")
    assert analytics_service.snapshot() == {"x": 1, "no_match": 1}


def test_formatter_keeps_handoff_fields():
    record = logging.LogRecord(
        name="app.handoff",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="handoff ticket sent to webhook",
        args=(),
        exc_info=None,
    )
    record.req_id = "abc123"
    record.ticket_id = "ticket123"
    record.reason = "no_match"
    out = json.loads(JsonFormatter().format(record))
    assert out["ticket_id"] == "ticket123"
    assert out["reason"] == "no_match"
    assert out["req_id"] == "abc123"
