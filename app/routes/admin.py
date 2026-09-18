import secrets

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import config
from ..dependencies import ADMIN_SESSIONS

router = APIRouter()


def _login_page(error: str | None = None) -> str:
    error_html = (
        f'<p class="error-banner" style="margin-top:14px">{error}</p>' if error else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin Login</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/style.css?v=62">
<script>(function(){{var t=null;try{{t=localStorage.getItem('theme')}}catch(e){{}}var d=t==='dark'||(!t&&window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.setAttribute('data-theme',d?'dark':'light')}})();</script>
</head>
<body>
<header class="topbar"><div class="brand"><span class="brand-mark">K</span><span class="brand-name">Agent Assist</span><span class="brand-tag">Admin</span></div></header>
<main style="max-width:380px;margin:80px auto;padding:0 18px;">
  <section class="card">
    <h2 class="card-title">Knowledge base login</h2>
    <p class="kb-hint">Enter the ADMIN_TOKEN to manage the knowledge base.</p>
    <form method="post" action="/kb-admin/login">
      <input type="password" name="token" placeholder="ADMIN_TOKEN" autocomplete="current-password" required style="width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:8px;background:var(--surface-2);color:var(--text);font-size:14px;"/>
      <button type="submit" class="btn-primary" style="margin-top:12px;">Sign in</button>
    </form>
    {error_html}
  </section>
</main>
</body>
</html>"""


@router.post("/kb-admin/login")
def kb_admin_login(token: str = Form(...)):
    if not config.ADMIN_TOKEN:
        return RedirectResponse("/static/kb.html", status_code=303)
    if token != config.ADMIN_TOKEN:
        return HTMLResponse(_login_page(error="Invalid admin token"), status_code=401)
    session_id = secrets.token_urlsafe(24)
    ADMIN_SESSIONS[session_id] = True
    response = RedirectResponse("/static/kb.html", status_code=303)
    response.set_cookie(
        config.ADMIN_COOKIE_NAME,
        session_id,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 3600,
        path="/",
    )
    return response


@router.post("/kb-admin/logout")
def kb_admin_logout(request: Request):
    session_id = request.cookies.get(config.ADMIN_COOKIE_NAME)
    if session_id:
        ADMIN_SESSIONS.pop(session_id, None)
    response = RedirectResponse("/static/kb.html", status_code=303)
    response.delete_cookie(config.ADMIN_COOKIE_NAME, path="/")
    return response
