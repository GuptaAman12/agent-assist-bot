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
    monkeypatch.setattr("app.main.llm_service.generate_response", lambda s, q: "answer")
    r = client.post("/assist/", json={"transcript": "how do i reset", "intent": "unknown"})
    assert r.status_code == 200
    body = r.json()
    assert body["response"] == "answer"
    assert body["ai_takeover"] is False
    assert body["source"] == "context one"
    assert body["kb_score"] == 0.8
    assert body["audio_url"] is None
    assert body["tts_engine"] is None


def test_assist_no_match(client, monkeypatch):
    client.app.state.knowledge_base.match_result = (None, 0.12)

    called = {"llm": False}

    def fake_generate(s, q):
        called["llm"] = True
        return "should not be called"

    monkeypatch.setattr("app.main.llm_service.generate_response", fake_generate)
    r = client.post("/assist/", json={"transcript": "gibberish", "intent": "unknown"})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] is None
    assert body["ai_takeover"] is False
    assert body["kb_score"] == 0.12
    assert body["tts_engine"] is None
    assert "not sure" in body["response"].lower()
    assert not called["llm"]


def test_assist_takeover_generates_audio(client, monkeypatch):
    monkeypatch.setattr("app.main.llm_service.generate_response", lambda s, q: "answer")
    monkeypatch.setattr("app.main.synthesize", lambda t: ("out.wav", "groq-orpheus"))
    r = client.post("/assist/", json={"transcript": "reset my password", "intent": "password_reset"})
    assert r.status_code == 200
    body = r.json()
    assert body["ai_takeover"] is True
    assert body["audio_url"] == "/static/out.wav"
    assert body["tts_engine"] == "groq-orpheus"


def test_assist_non_takeover_no_audio(client, monkeypatch):
    monkeypatch.setattr("app.main.llm_service.generate_response", lambda s, q: "answer")
    monkeypatch.setattr("app.main.synthesize", lambda t: ("out.wav", "groq-orpheus"))
    r = client.post("/assist/", json={"transcript": "refund please", "intent": "refund_request"})
    assert r.json()["ai_takeover"] is False
    assert r.json()["audio_url"] is None


def test_assist_llm_error_maps_502(client, monkeypatch):
    from app.services.llm import LLMError

    def boom(s, q):
        raise LLMError("groq down")

    monkeypatch.setattr("app.main.llm_service.generate_response", boom)
    r = client.post("/assist/", json={"transcript": "hi", "intent": "unknown"})
    assert r.status_code == 502


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
