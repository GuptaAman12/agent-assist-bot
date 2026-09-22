"""
E2E: Admin authentication, session lifecycle, and authorization gating.

Tests the full auth flow from an external consumer's perspective: unauthenticated
requests blocked, login via form POST, session cookie propagation, logout revocation,
and session invalidation on restart.  Uses non-trivial multi-step scenarios.
"""
import pytest


class TestAdminAuthGating:
    """When ADMIN_TOKEN is configured, all protected endpoints must enforce it."""

    def test_full_auth_flow_login_use_api_logout_locked_out(self, client, monkeypatch):
        """Complete session lifecycle:
        1. Unauthenticated → 401
        2. Wrong token → 401
        3. Correct token → 303 redirect + session cookie
        4. Cookie-authenticated requests → 200
        5. Logout → 303
        6. Subsequent requests → 401 again
        """
        monkeypatch.setattr("app.config.ADMIN_TOKEN", "hunter2")

        # Step 1: Unauthenticated access blocked
        assert client.get("/kb").status_code == 401
        assert client.get("/stats").status_code == 401
        assert client.post("/kb", json={"response": "x"}).status_code == 401

        # Step 2: Wrong token rejected
        assert client.post("/kb-admin/login", data={"token": "wrong"}).status_code == 401

        # Step 3: Correct token → redirect with cookie
        login_r = client.post("/kb-admin/login", data={"token": "hunter2"}, follow_redirects=False)
        assert login_r.status_code == 303
        assert "admin_token" in login_r.headers.get("set-cookie", "")

        # Step 4: Session cookie propagates — API works
        assert client.get("/kb").status_code == 200
        add_r = client.post("/kb", json={"question": "test?", "response": "yes"})
        assert add_r.status_code == 200
        assert client.get("/stats").status_code == 200

        # Step 5: Logout
        logout_r = client.post("/kb-admin/logout", follow_redirects=False)
        assert logout_r.status_code == 303

        # Step 6: Locked out
        assert client.get("/kb").status_code == 401

    def test_header_token_bypasses_cookie_requirement(self, client, monkeypatch):
        """Programmatic clients (curl, integrations) should be able to use
        the X-Admin-Token header directly without going through login."""
        monkeypatch.setattr("app.config.ADMIN_TOKEN", "api-secret")

        # No cookie, no header → 401
        assert client.get("/kb").status_code == 401

        # Header auth works for reads and writes
        headers = {"X-Admin-Token": "api-secret"}
        assert client.get("/kb", headers=headers).status_code == 200
        assert client.post("/kb", json={"response": "via header"}, headers=headers).status_code == 200

    def test_session_lost_after_server_restart(self, client, monkeypatch):
        """Sessions are in-memory only.  A server restart (simulated by clearing
        ADMIN_SESSIONS) should invalidate all existing cookies."""
        from app.dependencies import ADMIN_SESSIONS

        monkeypatch.setattr("app.config.ADMIN_TOKEN", "s3cret")
        client.post("/kb-admin/login", data={"token": "s3cret"})
        assert client.get("/kb").status_code == 200

        # Simulate restart
        ADMIN_SESSIONS.clear()

        assert client.get("/kb").status_code == 401
        # Login page should be shown on protected pages
        r = client.get("/static/kb.html")
        assert "Knowledge base login" in r.text

    def test_auth_gates_transcribe_and_assist_when_token_set(self, client, monkeypatch):
        """ADMIN_TOKEN protects not just /kb but also /transcribe/ and /assist/."""
        monkeypatch.setattr("app.config.ADMIN_TOKEN", "s3cret")

        # Both endpoints gated
        assert client.post("/transcribe/", files={"file": ("x.wav", b"RIFF", "audio/wav")}).status_code == 401
        assert client.post("/assist/", json={"transcript": "hi", "intent": "unknown"}).status_code == 401

        # With correct header, they accept requests (transcribe may fail on
        # actual transcription, but auth is passed)
        monkeypatch.setattr("app.services.transcription.transcribe_file", lambda p: "hello")
        r = client.post(
            "/transcribe/",
            files={"file": ("x.wav", b"RIFF", "audio/wav")},
            headers={"X-Admin-Token": "s3cret"},
        )
        assert r.status_code == 200

    def test_kb_html_shows_login_form_when_unauthenticated(self, client, monkeypatch):
        """The KB editor page is server-side gated — unauthenticated users see
        the login form, not the editor UI."""
        monkeypatch.setattr("app.config.ADMIN_TOKEN", "s3cret")

        r = client.get("/static/kb.html")
        assert r.status_code == 200
        assert "Knowledge base login" in r.text
        assert "kb-add-form" not in r.text  # editor not exposed

    def test_kb_html_shows_editor_after_login(self, client, monkeypatch):
        """After successful login, the full KB editor is served."""
        monkeypatch.setattr("app.config.ADMIN_TOKEN", "s3cret")
        client.post("/kb-admin/login", data={"token": "s3cret"})

        r = client.get("/static/kb.html")
        assert r.status_code == 200
        assert "kb-add-form" in r.text


class TestOpenAccess:
    """When ADMIN_TOKEN is not set, everything should be accessible."""

    def test_all_endpoints_open_without_admin_token(self, client):
        """With empty ADMIN_TOKEN (default in tests), all endpoints are open."""
        assert client.get("/kb").status_code == 200
        assert client.get("/stats").status_code == 200
        assert client.get("/handoff/queue").status_code == 200

        r = client.get("/static/kb.html")
        assert r.status_code == 200
        assert "kb-add-form" in r.text  # editor fully visible
