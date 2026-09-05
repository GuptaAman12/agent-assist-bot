import time

from app.services import tts
from app.services.tts import prune_old_audio


def _make_audio(path, age_sec=0):
    path.write_bytes(b"fake-audio")
    if age_sec:
        old = time.time() - age_sec
        import os

        os.utime(path, (old, old))
    return path


def test_rate_limit_sets_retry_after(client, monkeypatch):
    monkeypatch.setattr("app.config.RATE_LIMIT_MAX_REQUESTS", 2)
    monkeypatch.setattr("app.config.RATE_LIMIT_WINDOW_SEC", 60)
    monkeypatch.setattr("app.main.llm_service.generate_response", lambda s, q, history=None: "answer")
    from app.main import _clear_rate_limit_state

    _clear_rate_limit_state()
    for _ in range(2):
        assert client.post("/assist/", json={"transcript": "hi", "intent": "unknown"}).status_code == 200
    r = client.post("/assist/", json={"transcript": "hi", "intent": "unknown"})
    assert r.status_code == 429
    retry_after = r.headers.get("retry-after")
    assert retry_after is not None and int(retry_after) >= 1
    _clear_rate_limit_state()


def test_rate_limit_xff_isolated_when_trusted(client, monkeypatch):
    monkeypatch.setattr("app.config.TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr("app.config.RATE_LIMIT_MAX_REQUESTS", 1)
    monkeypatch.setattr("app.main.llm_service.generate_response", lambda s, q, history=None: "answer")
    from app.main import _clear_rate_limit_state

    _clear_rate_limit_state()
    body = {"transcript": "hi", "intent": "unknown"}
    assert client.post("/assist/", json=body, headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    assert client.post("/assist/", json=body, headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 429
    # Different client IP gets its own bucket.
    assert client.post("/assist/", json=body, headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 200
    # First entry wins when proxies append.
    assert client.post("/assist/", json=body, headers={"X-Forwarded-For": "2.2.2.2, 10.0.0.1"}).status_code == 429
    _clear_rate_limit_state()


def test_rate_limit_xff_ignored_when_untrusted(client, monkeypatch):
    monkeypatch.setattr("app.config.TRUST_PROXY_HEADERS", False)
    monkeypatch.setattr("app.config.RATE_LIMIT_MAX_REQUESTS", 1)
    monkeypatch.setattr("app.main.llm_service.generate_response", lambda s, q, history=None: "answer")
    from app.main import _clear_rate_limit_state

    _clear_rate_limit_state()
    body = {"transcript": "hi", "intent": "unknown"}
    assert client.post("/assist/", json=body, headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    # Spoofed XFF must not grant a fresh bucket.
    assert client.post("/assist/", json=body, headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 429
    _clear_rate_limit_state()


def test_prune_ttl(tts_env, monkeypatch):
    monkeypatch.setattr("app.services.tts.config.AUDIO_TTL_SEC", 3600)
    monkeypatch.setattr("app.services.tts.config.AUDIO_MAX_FILES", 100)
    audio_dir = tts_env["static_dir"] / "audio"
    audio_dir.mkdir(exist_ok=True)
    old = _make_audio(audio_dir / "ai_response_old.wav", age_sec=7200)
    fresh = _make_audio(audio_dir / "ai_response_fresh.wav")
    keep = _make_audio(audio_dir / "notes.txt", age_sec=7200)

    assert prune_old_audio() == 1
    assert not old.exists()
    assert fresh.exists()
    assert keep.exists()  # only ai_response_*.* is managed


def test_prune_max_files_keeps_newest(tts_env, monkeypatch):
    monkeypatch.setattr("app.services.tts.config.AUDIO_TTL_SEC", 0)  # TTL off
    monkeypatch.setattr("app.services.tts.config.AUDIO_MAX_FILES", 2)
    audio_dir = tts_env["static_dir"] / "audio"
    audio_dir.mkdir(exist_ok=True)
    now = time.time()
    import os

    names = []
    for i in range(4):
        p = audio_dir / f"ai_response_2025010{i}_000000_0000000{i}.wav"
        p.write_bytes(b"x")
        os.utime(p, (now - (40 - i * 10), now - (40 - i * 10)))
        names.append(p)

    assert prune_old_audio() == 2
    assert not names[0].exists() and not names[1].exists()
    assert names[2].exists() and names[3].exists()


def test_prune_missing_dir_returns_zero(tts_env, monkeypatch):
    monkeypatch.setattr(
        "app.services.tts.config.AUDIO_DIR", tts_env["static_dir"] / "no-such-dir"
    )
    assert prune_old_audio() == 0


def test_synthesize_prunes_old_files(tts_env, monkeypatch):
    import io
    import wave

    def _wav():
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(b"\x00\x01" * 50)
        return buf.getvalue()

    monkeypatch.setattr(tts, "_groq_speech", lambda text: _wav())
    monkeypatch.setattr("app.services.tts.config.AUDIO_TTL_SEC", 0)  # TTL off
    monkeypatch.setattr("app.services.tts.config.AUDIO_MAX_FILES", 2)
    audio_dir = tts_env["static_dir"] / "audio"
    audio_dir.mkdir(exist_ok=True)
    _make_audio(audio_dir / "ai_response_20200101_000000_aaaaaaaa.wav", age_sec=9999)
    _make_audio(audio_dir / "ai_response_20200102_000000_bbbbbbbb.wav", age_sec=9999)

    filename, engine = tts.synthesize("hello there")
    assert engine == "groq-orpheus"
    remaining = sorted(p.name for p in audio_dir.glob("ai_response_*.*"))
    assert len(remaining) == 2
    assert filename in remaining
