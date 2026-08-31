import os
import secrets
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .logging import get_access_logger, set_request_id, setup_logging
from .services import llm as llm_service
from .services import transcription as transcription_service
from .services.intent import detect_intent, detect_intents
from .services.rag import KnowledgeBase
from .services.tts import synthesize

setup_logging()
access_logger = get_access_logger()

# Server-side admin sessions: browser holds an opaque session id; restarting
# the app clears this dict, which logs every admin out (no session survives a restart).
ADMIN_SESSIONS: dict[str, str] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = config.missing_api_keys()
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)} (check your .env file)")
    app.state.knowledge_base = KnowledgeBase()
    yield


app = FastAPI(title="Agent Assist & Resolution Bot", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = uuid.uuid4().hex[:12]
    set_request_id(request_id)
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        if request.url.path.endswith(".html"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = request_id
    except Exception:
        access_logger.exception(
            "request failed",
            extra={
                "req_id": request_id,
                "req_method": request.method,
                "req_path": request.url.path,
            },
        )
        raise
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        access_logger.info(
            "request completed",
            extra={
                "req_id": request_id,
                "req_method": request.method,
                "req_path": request.url.path,
                "req_status": status_code,
                "req_duration_ms": duration_ms,
            },
        )
    return response


def _has_admin_access(request: Request) -> bool:
    if not config.ADMIN_TOKEN:
        return True
    if request.headers.get("X-Admin-Token") == config.ADMIN_TOKEN:
        return True
    session_id = request.cookies.get(config.ADMIN_COOKIE_NAME)
    return session_id in ADMIN_SESSIONS and ADMIN_SESSIONS[session_id] == config.ADMIN_TOKEN


@app.middleware("http")
async def guard_kb_page(request: Request, call_next):
    if request.url.path == "/static/kb.html" and not _has_admin_access(request):
        return HTMLResponse(_login_page())
    return await call_next(request)


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
<link rel="stylesheet" href="/static/style.css">
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


@app.post("/kb-admin/login")
def kb_admin_login(token: str = Form(...)):
    if not config.ADMIN_TOKEN:
        return RedirectResponse("/static/kb.html", status_code=303)
    if token != config.ADMIN_TOKEN:
        return HTMLResponse(_login_page(error="Invalid admin token"), status_code=401)
    session_id = secrets.token_urlsafe(24)
    ADMIN_SESSIONS[session_id] = config.ADMIN_TOKEN
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


@app.post("/kb-admin/logout")
def kb_admin_logout(request: Request):
    session_id = request.cookies.get(config.ADMIN_COOKIE_NAME)
    if session_id:
        ADMIN_SESSIONS.pop(session_id, None)
    response = RedirectResponse("/static/kb.html", status_code=303)
    response.delete_cookie(config.ADMIN_COOKIE_NAME, path="/")
    return response


@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")


class AssistRequest(BaseModel):
    transcript: str
    intent: str
    history: list[dict] = []


@app.post("/transcribe/")
def transcribe(file: UploadFile = File(...)):
    suffix = (Path(file.filename or "").suffix or "").lower()
    if suffix not in config.ALLOWED_UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(config.ALLOWED_UPLOAD_EXTENSIONS))
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{suffix or 'none'}'. Allowed: {allowed}",
        )

    try:
        declared_size = int(file.headers.get("content-length", "0"))
    except (TypeError, ValueError):
        declared_size = 0
    if declared_size > config.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {declared_size} bytes (max {config.MAX_UPLOAD_BYTES})",
        )

    fd, temp_path = tempfile.mkstemp(suffix=suffix or ".wav")
    try:
        with os.fdopen(fd, "wb") as f:
            while chunk := file.file.read(1024 * 1024):
                if f.tell() + len(chunk) > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large (max {config.MAX_UPLOAD_BYTES} bytes)",
                    )
                f.write(chunk)
        try:
            transcript = transcription_service.transcribe_file(temp_path)
        except transcription_service.TranscriptionTimeout as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except transcription_service.TranscriptionError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        os.unlink(temp_path)

    return {"transcript": transcript, "intent": detect_intent(transcript)}


@app.post("/assist/")
def assist_agent(request: AssistRequest):
    kb: KnowledgeBase = app.state.knowledge_base
    matches = kb.best_matches(request.transcript)

    if not matches and not request.history:
        return {
            "response": config.KB_NO_MATCH_RESPONSE,
            "ai_takeover": False,
            "source": None,
            "sources": [],
            "audio_url": None,
            "tts_engine": None,
            "kb_score": None,
        }

    if matches:
        sources = [text for text, _ in matches]
        context = "\n".join(f"[{i + 1}] {text}" for i, text in enumerate(sources))
        kb_score = matches[0][1]
    else:
        # No KB match, but the user is following up on an earlier exchange -
        # answer from the conversation history instead of the knowledge base.
        sources = []
        kb_score = None
        last = request.history[-1]
        context = (
            f"The user previously said: {last.get('transcript', '')}\n"
            f"The assistant previously said: {last.get('response', '')}"
        )

    try:
        response_text = llm_service.generate_response(context, request.transcript, request.history)
    except llm_service.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    ai_takeover = any(
        intent in config.SIMPLE_INTENTS for intent in detect_intents(request.transcript)
    )

    audio_url = None
    tts_engine = None
    if ai_takeover:
        filename, tts_engine = synthesize(response_text)
        audio_url = f"/static/{filename}"

    return {
        "response": response_text,
        "ai_takeover": ai_takeover,
        "source": sources[0] if sources else None,
        "sources": sources,
        "audio_url": audio_url,
        "tts_engine": tts_engine,
        "kb_score": kb_score,
    }


@app.get("/health")
def health():
    return {"status": "ok"}


class KBEntryRequest(BaseModel):
    question: str = ""
    response: str


def require_admin(request: Request, x_admin_token: str | None = Header(default=None)) -> None:
    if not config.ADMIN_TOKEN:
        return
    if x_admin_token == config.ADMIN_TOKEN:
        return
    session_id = request.cookies.get(config.ADMIN_COOKIE_NAME)
    if session_id in ADMIN_SESSIONS and ADMIN_SESSIONS[session_id] == config.ADMIN_TOKEN:
        return
    raise HTTPException(status_code=401, detail="Missing or invalid admin token")


@app.get("/kb", dependencies=[Depends(require_admin)])
def kb_list():
    kb: KnowledgeBase = app.state.knowledge_base
    entries = kb.snapshot()
    return {"count": len(entries), "entries": entries}


@app.post("/kb", dependencies=[Depends(require_admin)])
def kb_add(entry: KBEntryRequest):
    kb: KnowledgeBase = app.state.knowledge_base
    try:
        created = kb.add_entry(entry.question, entry.response)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return created


@app.put("/kb/{entry_id}", dependencies=[Depends(require_admin)])
def kb_update(entry_id: str, entry: KBEntryRequest):
    kb: KnowledgeBase = app.state.knowledge_base
    try:
        updated = kb.update_entry(entry_id, entry.question, entry.response)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Unknown entry id: {entry_id}")
    return updated


@app.delete("/kb/{entry_id}", dependencies=[Depends(require_admin)])
def kb_delete(entry_id: str):
    kb: KnowledgeBase = app.state.knowledge_base
    if not kb.remove_entry(entry_id):
        raise HTTPException(status_code=404, detail=f"Unknown entry id: {entry_id}")
    return {"deleted": entry_id, "count": kb.count}


@app.post("/kb/reload", dependencies=[Depends(require_admin)])
def kb_reload():
    kb: KnowledgeBase = app.state.knowledge_base
    kb.reload()
    return {"reloaded": True, "count": kb.count}
