import pytest

from app.services.transcription import TranscriptionError, TranscriptionTimeout


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_request_id_header_present(client):
    r = client.get("/health")
    assert r.headers.get("X-Request-ID")


def test_request_ids_unique_per_request(client):
    first = client.get("/health").headers["X-Request-ID"]
    second = client.get("/health").headers["X-Request-ID"]
    assert first and second and first != second


def test_structured_log_includes_request_id(client, caplog):
    import logging

    from app.logging import get_access_logger

    with caplog.at_level(logging.INFO, logger=get_access_logger().name):
        client.get("/health")

    matched = [rec for rec in caplog.records if rec.getMessage() == "request completed"]
    assert matched
    assert all(getattr(rec, "req_id", None) for rec in matched)
    assert all(getattr(rec, "req_status", None) == 200 for rec in matched)


def test_root_redirects(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (301, 307)
    assert "/static/index.html" in r.headers["location"]


def test_transcribe_success(client, monkeypatch):
    def fake_transcribe(path):
        assert path  # temp file path is passed through
        return "I forgot my password"

    monkeypatch.setattr("app.main.transcription_service.transcribe_file", fake_transcribe)
    r = client.post("/transcribe/", files={"file": ("test.wav", b"RIFFfake", "audio/wav")})
    assert r.status_code == 200
    assert r.json() == {"transcript": "I forgot my password", "intent": "password_reset"}


def test_transcribe_upstream_error_maps_502(client, monkeypatch):
    def boom(path):
        raise TranscriptionError("AssemblyAI upload failed")

    monkeypatch.setattr("app.main.transcription_service.transcribe_file", boom)
    r = client.post("/transcribe/", files={"file": ("test.wav", b"RIFFfake", "audio/wav")})
    assert r.status_code == 502
    assert "upload failed" in r.json()["detail"]


def test_transcribe_timeout_maps_504(client, monkeypatch):
    def boom(path):
        raise TranscriptionTimeout("timed out")

    monkeypatch.setattr("app.main.transcription_service.transcribe_file", boom)
    r = client.post("/transcribe/", files={"file": ("test.wav", b"RIFFfake", "audio/wav")})
    assert r.status_code == 504


def test_transcribe_rejects_unsupported_type(client):
    r = client.post("/transcribe/", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415
    assert "Unsupported file type" in r.json()["detail"]


def test_transcribe_rejects_oversize_declared(client, monkeypatch):
    monkeypatch.setattr("app.config.MAX_UPLOAD_BYTES", 50)
    r = client.post("/transcribe/", files={"file": ("big.wav", b"x" * 100, "audio/wav")})
    assert r.status_code == 413
    assert "too large" in r.json()["detail"].lower()


def test_transcribe_rejects_oversize_streamed(client, monkeypatch):
    monkeypatch.setattr("app.config.MAX_UPLOAD_BYTES", 50)
    # No content-length declared; cap enforced while streaming.
    r = client.post(
        "/transcribe/",
        files={"file": ("big.wav", b"x" * 100, "audio/wav")},
        headers={"content-length": ""},
    )
    assert r.status_code == 413


def test_transcribe_accepts_known_audio_type(client, monkeypatch):
    def fake_transcribe(path):
        return "some text"

    monkeypatch.setattr("app.main.transcription_service.transcribe_file", fake_transcribe)
    r = client.post("/transcribe/", files={"file": ("call.mp3", b"fake", "audio/mpeg")})
    assert r.status_code == 200


def test_assist_match_shape(client, monkeypatch):
    monkeypatch.setattr("app.main.llm_service.generate_response", lambda s, q, history=None: "answer")
    r = client.post("/assist/", json={"transcript": "how do i reset", "intent": "unknown"})
    assert r.status_code == 200
    body = r.json()
    assert body["response"] == "answer"
    assert body["ai_takeover"] is False
    assert body["source"] == "context one"
    assert body["sources"] == ["context one", "context two"]
    assert body["kb_score"] == 0.8
    assert body["audio_url"] is None
    assert body["tts_engine"] is None


def test_assist_no_match(client, monkeypatch):
    client.app.state.knowledge_base.matches_result = []

    called = {"llm": False}

    def fake_generate(s, q, history=None):
        called["llm"] = True
        return "should not be called"

    monkeypatch.setattr("app.main.llm_service.generate_response", fake_generate)
    r = client.post("/assist/", json={"transcript": "gibberish", "intent": "unknown"})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] is None
    assert body["sources"] == []
    assert body["ai_takeover"] is False
    assert body["kb_score"] is None
    assert body["tts_engine"] is None
    assert "not sure" in body["response"].lower()
    assert not called["llm"]


def test_assist_takeover_generates_audio(client, monkeypatch):
    monkeypatch.setattr("app.main.llm_service.generate_response", lambda s, q, history=None: "answer")
    monkeypatch.setattr("app.main.synthesize", lambda t: ("out.wav", "groq-orpheus"))
    r = client.post("/assist/", json={"transcript": "reset my password", "intent": "password_reset"})
    assert r.status_code == 200
    body = r.json()
    assert body["ai_takeover"] is True
    assert body["audio_url"] == "/static/out.wav"
    assert body["tts_engine"] == "groq-orpheus"


def test_assist_non_takeover_no_audio(client, monkeypatch):
    monkeypatch.setattr("app.main.llm_service.generate_response", lambda s, q, history=None: "answer")
    monkeypatch.setattr("app.main.synthesize", lambda t: ("out.wav", "groq-orpheus"))
    r = client.post("/assist/", json={"transcript": "refund please", "intent": "refund_request"})
    assert r.json()["ai_takeover"] is False
    assert r.json()["audio_url"] is None


def test_assist_mixed_issue_takes_over(client, monkeypatch):
    # Two issues, both automatable -> AI voice takeover should happen.
    monkeypatch.setattr("app.main.llm_service.generate_response", lambda s, q, history=None: "answer")
    monkeypatch.setattr("app.main.synthesize", lambda t: ("out.wav", "groq-orpheus"))
    r = client.post(
        "/assist/",
        json={
            "transcript": "How do I change my email address? And the app is not working, it keeps crashing.",
            "intent": "update_email",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ai_takeover"] is True
    assert body["audio_url"] == "/static/out.wav"


def test_assist_llm_error_maps_502(client, monkeypatch):
    from app.services.llm import LLMError

    def boom(s, q, history=None):
        raise LLMError("groq down")

    monkeypatch.setattr("app.main.llm_service.generate_response", boom)
    r = client.post("/assist/", json={"transcript": "hi", "intent": "unknown"})
    assert r.status_code == 502


def test_assist_forwards_history_to_llm(client, monkeypatch):
    captured = {}

    def fake_generate(s, q, history=None):
        captured["history"] = history
        return "answer"

    monkeypatch.setattr("app.main.llm_service.generate_response", fake_generate)
    r = client.post(
        "/assist/",
        json={
            "transcript": "what about my order?",
            "intent": "unknown",
            "history": [
                {"transcript": "I want to cancel my order", "response": "Go to order history."},
                {"transcript": "where is it now?", "response": "It shipped yesterday."},
            ],
        },
    )
    assert r.status_code == 200
    assert captured["history"] == [
        {"transcript": "I want to cancel my order", "response": "Go to order history."},
        {"transcript": "where is it now?", "response": "It shipped yesterday."},
    ]


def test_assist_no_match_with_history_answers_from_conversation(client, monkeypatch):
    # No KB match, but a follow-up with history -> LLM is called, not the canned reply.
    client.app.state.knowledge_base.matches_result = []
    captured = {}

    def fake_generate(s, q, history=None):
        captured["context"] = s
        captured["history"] = history
        return "answer"

    monkeypatch.setattr("app.main.llm_service.generate_response", fake_generate)
    r = client.post(
        "/assist/",
        json={
            "transcript": "what about my order from earlier?",
            "intent": "unknown",
            "history": [
                {"transcript": "I want to cancel my order", "response": "Go to order history."},
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["response"] == "answer"
    assert body["source"] is None
    assert body["sources"] == []
    assert body["kb_score"] is None
    assert "previously said" in captured["context"]
    assert captured["history"][0]["transcript"] == "I want to cancel my order"


def test_kb_list(client):
    r = client.get("/kb")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert body["entries"][0]["id"] == "e1"


def test_kb_add_and_delete(client):
    r = client.post("/kb", json={"question": "q", "response": "r"})
    assert r.status_code == 200
    created = r.json()
    assert created["id"]

    r = client.get("/kb")
    assert r.json()["count"] == 3

    r = client.delete(f"/kb/{created['id']}")
    assert r.status_code == 200
    assert r.json()["count"] == 2


def test_kb_add_empty_response_422(client):
    r = client.post("/kb", json={"question": "q", "response": "   "})
    assert r.status_code == 422


def test_kb_update(client):
    r = client.put("/kb/e1", json={"question": "new q", "response": "new r"})
    assert r.status_code == 200
    assert r.json() == {"id": "e1", "question": "new q", "response": "new r"}

    assert client.get("/kb").json()["entries"][0]["response"] == "new r"


def test_kb_update_unknown_404(client):
    r = client.put("/kb/nope", json={"response": "r"})
    assert r.status_code == 404


def test_kb_delete_unknown_404(client):
    r = client.delete("/kb/nope")
    assert r.status_code == 404


def test_kb_reload(client):
    r = client.post("/kb/reload")
    assert r.status_code == 200
    assert r.json()["reloaded"] is True


def test_kb_open_when_no_admin_token(client):
    r = client.get("/kb")
    assert r.status_code == 200


def test_kb_requires_token_when_configured(client, monkeypatch):
    monkeypatch.setattr("app.config.ADMIN_TOKEN", "s3cret")

    r = client.get("/kb")
    assert r.status_code == 401

    r = client.get("/kb", headers={"X-Admin-Token": "wrong"})
    assert r.status_code == 401

    r = client.get("/kb", headers={"X-Admin-Token": "s3cret"})
    assert r.status_code == 200


def test_kb_mutations_require_token(client, monkeypatch):
    monkeypatch.setattr("app.config.ADMIN_TOKEN", "s3cret")

    r = client.post("/kb", json={"response": "x"})
    assert r.status_code == 401

    r = client.post(
        "/kb",
        json={"response": "x"},
        headers={"X-Admin-Token": "s3cret"},
    )
    assert r.status_code == 200

    r = client.put("/kb/e1", json={"response": "x"})
    assert r.status_code == 401

    r = client.delete("/kb/e1")
    assert r.status_code == 401


def test_kb_page_gated_when_admin_token_set(client, monkeypatch):
    monkeypatch.setattr("app.config.ADMIN_TOKEN", "s3cret")

    r = client.get("/static/kb.html")
    assert r.status_code == 200
    assert "Knowledge base login" in r.text
    assert "kb-add-form" not in r.text


def test_kb_login_sets_cookie_and_serves_page(client, monkeypatch):
    monkeypatch.setattr("app.config.ADMIN_TOKEN", "s3cret")

    r = client.post("/kb-admin/login", data={"token": "wrong"})
    assert r.status_code == 401

    r = client.post("/kb-admin/login", data={"token": "s3cret"}, follow_redirects=False)
    assert r.status_code == 303
    assert "admin_token" in r.headers["set-cookie"]

    r = client.get("/static/kb.html")
    assert r.status_code == 200
    assert "kb-add-form" in r.text

    r = client.get("/kb")
    assert r.status_code == 200


def test_kb_session_invalidated_on_restart(client, monkeypatch):
    monkeypatch.setattr("app.config.ADMIN_TOKEN", "s3cret")
    from app.main import ADMIN_SESSIONS

    client.post("/kb-admin/login", data={"token": "s3cret"})
    assert client.get("/kb").status_code == 200

    # Simulate an app restart: server-side sessions are wiped.
    ADMIN_SESSIONS.clear()

    r = client.get("/kb")
    assert r.status_code == 401
    assert "Knowledge base login" in client.get("/static/kb.html").text


def test_kb_logout_revokes_session(client, monkeypatch):
    monkeypatch.setattr("app.config.ADMIN_TOKEN", "s3cret")
    from app.main import ADMIN_SESSIONS

    client.post("/kb-admin/login", data={"token": "s3cret"})
    assert client.get("/kb").status_code == 200

    client.post("/kb-admin/logout", follow_redirects=False)
    assert ADMIN_SESSIONS == {}
    assert client.get("/kb").status_code == 401


def test_kb_page_open_when_no_admin_token(client):
    r = client.get("/static/kb.html")
    assert r.status_code == 200
    assert "kb-add-form" in r.text


def test_assist_speak_to_agent_opens_handoff(client, monkeypatch):
    monkeypatch.setattr("app.main.llm_service.generate_response", lambda s, q, history=None: "answer")
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return "ticket123"

    monkeypatch.setattr("app.main.handoff_service.create_ticket", fake_create)
    r = client.post(
        "/assist/",
        json={"transcript": "I want to talk to a real person about my refund.", "intent": "speak_to_agent"},
    )
    assert r.status_code == 200
    assert r.json()["handoff"] is True
    assert captured["reason"] == "speak_to_agent"


def test_assist_no_match_opens_handoff(client, monkeypatch):
    client.app.state.knowledge_base.matches_result = []
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return "ticket123"

    monkeypatch.setattr("app.main.handoff_service.create_ticket", fake_create)
    r = client.post(
        "/assist/",
        json={"transcript": "quantum pineapple submarine", "intent": "unknown"},
    )
    assert r.status_code == 200
    assert r.json()["handoff"] is True
    assert captured["reason"] == "no_match"


def test_assist_normal_no_handoff(client, monkeypatch):
    monkeypatch.setattr("app.main.llm_service.generate_response", lambda s, q, history=None: "answer")
    called = {"create": False}

    def fake_create(**kwargs):
        called["create"] = True
        return "t"

    monkeypatch.setattr("app.main.handoff_service.create_ticket", fake_create)
    r = client.post(
        "/assist/",
        json={"transcript": "reset my password", "intent": "password_reset"},
    )
    assert r.status_code == 200
    assert r.json()["handoff"] is False
    assert not called["create"]


def test_kb_pagination(client):
    # Add 3 entries to have 5 total (2 initial + 3)
    for i in range(3):
        client.post("/kb", json={"question": f"q{i}", "response": f"r{i}"})
    r = client.get("/kb?limit=2&offset=0")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 5
    assert len(data["entries"]) == 2
    assert data["limit"] == 2
    assert data["offset"] == 0
    r2 = client.get("/kb?limit=2&offset=2")
    assert len(r2.json()["entries"]) == 2
    r3 = client.get("/kb?limit=2&offset=4")
    assert len(r3.json()["entries"]) == 1
    # offset beyond total returns empty
    r4 = client.get("/kb?limit=10&offset=10")
    assert len(r4.json()["entries"]) == 0


def test_kb_soft_delete_and_restore(client):
    r = client.post("/kb", json={"question": "to delete", "response": "temp"})
    entry_id = r.json()["id"]
    assert client.get("/kb").json()["count"] == 3
    r = client.delete(f"/kb/{entry_id}")
    assert r.status_code == 200
    assert r.json()["count"] == 2
    assert "undo_token" in r.json()
    # Deleted entry not in active list
    ids = [e["id"] for e in client.get("/kb").json()["entries"]]
    assert entry_id not in ids
    # But visible with include_deleted
    r = client.get("/kb?include_deleted=true")
    assert entry_id in [e["id"] for e in r.json()["entries"]]
    # Restore
    r = client.post(f"/kb/{entry_id}/restore")
    assert r.status_code == 200
    assert client.get("/kb").json()["count"] == 3
    # Restore non-deleted -> 404
    r = client.post(f"/kb/{entry_id}/restore")
    assert r.status_code == 404
    r = client.post("/kb/nonexistent/restore")
    assert r.status_code == 404
