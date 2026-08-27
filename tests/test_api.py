import pytest

from app.services.transcription import TranscriptionError, TranscriptionTimeout


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


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
