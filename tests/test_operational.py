"""
E2E: Rate limiting and operational safeguards.

Tests that the sliding-window rate limiter correctly blocks excessive requests,
respects per-endpoint limits, handles reverse proxy headers, and that
infrastructure endpoints (health, request-id) work correctly.
"""
import pytest


class TestRateLimiting:
    """Per-IP sliding window rate limiting through the HTTP API."""

    def test_rate_limit_blocks_after_threshold_with_retry_header(self, client, monkeypatch):
        """After exceeding the request limit, the server returns 429 with a
        Retry-After header that the frontend can use for backoff."""
        monkeypatch.setattr("app.config.RATE_LIMIT_MAX_REQUESTS", 3)
        monkeypatch.setattr("app.config.RATE_LIMIT_WINDOW_SEC", 60)
        monkeypatch.setattr("app.services.llm.generate_response", lambda s, q, history=None: "answer")
        from app.dependencies import _clear_rate_limit_state
        _clear_rate_limit_state()

        # First 3 should pass
        for i in range(3):
            r = client.post("/assist/", json={"transcript": f"request {i}", "intent": "unknown"})
            assert r.status_code == 200

        # 4th should be blocked
        r = client.post("/assist/", json={"transcript": "one more", "intent": "unknown"})
        assert r.status_code == 429
        retry_after = r.headers.get("retry-after")
        assert retry_after is not None
        assert int(retry_after) >= 1

        _clear_rate_limit_state()

    def test_transcribe_has_separate_stricter_limit(self, client, monkeypatch):
        """The transcribe endpoint has its own (stricter) rate limit,
        independent of the general /assist/ limit."""
        monkeypatch.setattr("app.config.RATE_LIMIT_MAX_TRANSCRIBE", 2)
        monkeypatch.setattr("app.config.RATE_LIMIT_MAX_REQUESTS", 100)
        monkeypatch.setattr("app.config.RATE_LIMIT_WINDOW_SEC", 60)
        monkeypatch.setattr("app.services.transcription.transcribe_file", lambda p: "hello")
        from app.dependencies import _clear_rate_limit_state
        _clear_rate_limit_state()

        for _ in range(2):
            r = client.post("/transcribe/", files={"file": ("t.wav", b"RIFF" + b"\x00" * 20, "audio/wav")})
            assert r.status_code == 200

        r = client.post("/transcribe/", files={"file": ("t.wav", b"RIFF" + b"\x00" * 20, "audio/wav")})
        assert r.status_code == 429

        # But /assist/ should still work (separate bucket)
        monkeypatch.setattr("app.services.llm.generate_response", lambda s, q, history=None: "ok")
        r = client.post("/assist/", json={"transcript": "hi", "intent": "unknown"})
        assert r.status_code == 200

        _clear_rate_limit_state()

    def test_xff_header_isolates_clients_when_trusted(self, client, monkeypatch):
        """Behind a reverse proxy with TRUST_PROXY_HEADERS=True, each
        X-Forwarded-For IP gets its own rate-limit bucket.  Proxied headers
        use the first IP (leftmost = original client)."""
        monkeypatch.setattr("app.config.TRUST_PROXY_HEADERS", True)
        monkeypatch.setattr("app.config.RATE_LIMIT_MAX_REQUESTS", 1)
        monkeypatch.setattr("app.services.llm.generate_response", lambda s, q, history=None: "ok")
        from app.dependencies import _clear_rate_limit_state
        _clear_rate_limit_state()

        body = {"transcript": "hi", "intent": "unknown"}

        # Client A uses its quota
        assert client.post("/assist/", json=body, headers={"X-Forwarded-For": "10.0.0.1"}).status_code == 200
        assert client.post("/assist/", json=body, headers={"X-Forwarded-For": "10.0.0.1"}).status_code == 429

        # Client B has a fresh bucket
        assert client.post("/assist/", json=body, headers={"X-Forwarded-For": "10.0.0.2"}).status_code == 200

        # Multi-hop: "10.0.0.2, 192.168.1.1" → first IP = 10.0.0.2 (same as client B)
        assert client.post("/assist/", json=body, headers={"X-Forwarded-For": "10.0.0.2, 192.168.1.1"}).status_code == 429

        _clear_rate_limit_state()

    def test_xff_ignored_when_untrusted_prevents_spoofing(self, client, monkeypatch):
        """With TRUST_PROXY_HEADERS=False (default), spoofing X-Forwarded-For
        should NOT grant a fresh rate-limit bucket.  All requests share the
        direct socket IP."""
        monkeypatch.setattr("app.config.TRUST_PROXY_HEADERS", False)
        monkeypatch.setattr("app.config.RATE_LIMIT_MAX_REQUESTS", 1)
        monkeypatch.setattr("app.services.llm.generate_response", lambda s, q, history=None: "ok")
        from app.dependencies import _clear_rate_limit_state
        _clear_rate_limit_state()

        body = {"transcript": "hi", "intent": "unknown"}

        assert client.post("/assist/", json=body, headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
        # Spoofed different IP should NOT bypass the limit
        assert client.post("/assist/", json=body, headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 429

        _clear_rate_limit_state()


class TestInfrastructureEndpoints:
    """Health check, root redirect, request tracing, and voices."""

    def test_health_reports_service_status(self, client):
        """Health endpoint reports subsystem statuses.  With test keys set,
        the relevant services should report as online."""
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["services"]["api"]["status"] == "online"
        assert "rag" in body["services"]
        assert "handoff" in body["services"]

    def test_root_redirects_to_dashboard(self, client):
        """GET / should redirect to the frontend dashboard."""
        r = client.get("/", follow_redirects=False)
        assert r.status_code in (301, 307)
        assert "/static/index.html" in r.headers["location"]

    def test_every_response_has_unique_request_id(self, client):
        """Every response should include a unique X-Request-ID header for
        tracing and debugging."""
        ids = set()
        for _ in range(5):
            r = client.get("/health")
            rid = r.headers.get("X-Request-ID")
            assert rid
            ids.add(rid)
        assert len(ids) == 5

    def test_html_responses_have_no_store_cache_control(self, client):
        """HTML pages should have Cache-Control: no-store to prevent browsers
        from serving stale UI after deployments."""
        r = client.get("/static/index.html")
        assert "no-store" in r.headers.get("cache-control", "")

    def test_voices_endpoint_lists_available_voices(self, client):
        """The /voices endpoint should list available TTS voices."""
        r = client.get("/voices")
        assert r.status_code == 200
        body = r.json()
        assert "default" in body
        assert "voices" in body
        assert isinstance(body["voices"], list)
        assert len(body["voices"]) >= 6  # 6 Orpheus voices
