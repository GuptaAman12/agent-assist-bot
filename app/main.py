import json
import os
import secrets
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .logging import get_access_logger, set_request_id, setup_logging
from .services import handoff as handoff_service
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


def require_admin(request: Request, x_admin_token: str | None = Header(default=None)) -> None:
    if not config.ADMIN_TOKEN:
        return
    if x_admin_token == config.ADMIN_TOKEN:
        return
    session_id = request.cookies.get(config.ADMIN_COOKIE_NAME)
    if session_id in ADMIN_SESSIONS and ADMIN_SESSIONS[session_id] == config.ADMIN_TOKEN:
        return
    raise HTTPException(status_code=401, detail="Missing or invalid admin token")


def _audit_log(request: Request, action: str, entry_id: str | None = None, extra: dict | None = None) -> None:
    try:
        from .logging import get_request_id

        rid = get_request_id() or request.headers.get("X-Request-ID", "")
        # Admin identity: don't log raw token, just presence
        admin_via = "header" if request.headers.get("X-Admin-Token") == config.ADMIN_TOKEN else ("cookie" if request.cookies.get(config.ADMIN_COOKIE_NAME) in ADMIN_SESSIONS else "open" if not config.ADMIN_TOKEN else "unknown")
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "request_id": rid,
            "admin_via": admin_via,
            "action": action,
            "entry_id": entry_id,
            "ip": request.client.host if request.client else "unknown",
        }
        if extra:
            record.update(extra)
        with open(config.AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass  # audit must never break the request


# ---- Rate limiting (per-IP sliding window) ----

import threading as _rate_threading

_rate_buckets: dict[str, list[float]] = {}
_rate_lock = _rate_threading.Lock()


def check_rate_limit(request: Request) -> None:
    window = config.RATE_LIMIT_WINDOW_SEC
    # Stricter limit for the more expensive transcribe endpoint
    max_req = config.RATE_LIMIT_MAX_TRANSCRIBE if request.url.path.startswith("/transcribe") else config.RATE_LIMIT_MAX_REQUESTS
    if max_req <= 0:
        return
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    cutoff = now - window
    with _rate_lock:
        bucket = _rate_buckets.get(ip)
        if bucket is None:
            bucket = []
            _rate_buckets[ip] = bucket
        # prune
        bucket[:] = [t for t in bucket if t > cutoff]
        if len(bucket) >= max_req:
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
        bucket.append(now)


def _clear_rate_limit_state() -> None:
    with _rate_lock:
        _rate_buckets.clear()


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


@app.post("/transcribe/", dependencies=[Depends(require_admin), Depends(check_rate_limit)])
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


@app.post("/assist/", dependencies=[Depends(require_admin), Depends(check_rate_limit)])
def assist_agent(request: AssistRequest):
    kb: KnowledgeBase = app.state.knowledge_base
    matches = kb.best_matches(request.transcript)
    detected_intents = detect_intents(request.transcript)

    if not matches and not request.history:
        handoff_id = handoff_service.create_ticket(
            reason="no_match",
            transcript=request.transcript,
            intents=detected_intents,
            assistant_response=config.KB_NO_MATCH_RESPONSE,
        )
        return {
            "response": config.KB_NO_MATCH_RESPONSE,
            "ai_takeover": False,
            "source": None,
            "sources": [],
            "audio_url": None,
            "tts_engine": None,
            "kb_score": None,
            "handoff": handoff_id is not None,
            "ticket_id": handoff_id,
        }

    if matches:
        sources = [text for text, _ in matches]
        context = "\n".join(f"[{i + 1}] {text}" for i, text in enumerate(sources))
        kb_score = matches[0][1]
    else:
        # No KB match, but the user is following up on an earlier exchange -
        # answer from the recent conversation history instead of the knowledge base.
        # history is chronological (oldest->newest); keep the tail.
        sources = []
        kb_score = None
        recent = [t for t in request.history[-config.MAX_HISTORY_TURNS:] if t.get("transcript") or t.get("response")]
        context = "\n".join(
            f"The user previously said: {t.get('transcript', '')}\n"
            f"The assistant previously said: {t.get('response', '')}"
            for t in recent
        )

    try:
        response_text = llm_service.generate_response(context, request.transcript, request.history)
    except llm_service.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    ai_takeover = any(intent in config.SIMPLE_INTENTS for intent in detected_intents)

    audio_url = None
    tts_engine = None
    if ai_takeover:
        try:
            filename, tts_engine = synthesize(response_text)
            audio_url = f"/static/audio/{filename}"
        except Exception:
            # TTS (incl. gTTS fallback) must never turn a good answer into a 500.
            access_logger.warning(
                "tts failed; returning text-only response",
                extra={
                    "req_method": "POST",
                    "req_path": "/assist/",
                },
            )
            audio_url = None
            tts_engine = None

    handoff_id = None
    if "speak_to_agent" in detected_intents:
        handoff_id = handoff_service.create_ticket(
            reason="speak_to_agent",
            transcript=request.transcript,
            intents=detected_intents,
            assistant_response=response_text,
        )

    return {
        "response": response_text,
        "ai_takeover": ai_takeover,
        "source": sources[0] if sources else None,
        "sources": sources,
        "audio_url": audio_url,
        "tts_engine": tts_engine,
        "kb_score": kb_score,
        "handoff": handoff_id is not None,
        "ticket_id": handoff_id,
    }


@app.get("/health")
def health():
    return {"status": "ok"}


class KBEntryRequest(BaseModel):
    question: str = ""
    response: str


@app.get("/kb", dependencies=[Depends(require_admin)])
def kb_list(
    limit: int | None = Query(default=None, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    include_deleted: bool = False,
):
    kb: KnowledgeBase = app.state.knowledge_base
    entries = kb.snapshot(include_deleted=include_deleted)
    total = len(entries)
    if limit is not None:
        entries = entries[offset : offset + limit]
    return {"count": total, "entries": entries, "limit": limit, "offset": offset}


@app.post("/kb", dependencies=[Depends(require_admin)])
def kb_add(entry: KBEntryRequest, request: Request):
    kb: KnowledgeBase = app.state.knowledge_base
    try:
        created = kb.add_entry(entry.question, entry.response)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _audit_log(request, "kb_add", created["id"], {"question": entry.question})
    return created


@app.put("/kb/{entry_id}", dependencies=[Depends(require_admin)])
def kb_update(entry_id: str, entry: KBEntryRequest, request: Request):
    kb: KnowledgeBase = app.state.knowledge_base
    try:
        updated = kb.update_entry(entry_id, entry.question, entry.response)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Unknown entry id: {entry_id}")
    _audit_log(request, "kb_update", entry_id)
    return updated


@app.delete("/kb/{entry_id}", dependencies=[Depends(require_admin)])
def kb_delete(entry_id: str, request: Request):
    kb: KnowledgeBase = app.state.knowledge_base
    if not kb.remove_entry(entry_id):
        raise HTTPException(status_code=404, detail=f"Unknown entry id: {entry_id}")
    _audit_log(request, "kb_delete", entry_id)
    return {"deleted": entry_id, "count": kb.count, "undo_token": entry_id}


@app.post("/kb/{entry_id}/restore", dependencies=[Depends(require_admin)])
def kb_restore(entry_id: str, request: Request):
    kb: KnowledgeBase = app.state.knowledge_base
    restored = kb.restore_entry(entry_id)
    if restored is None:
        raise HTTPException(status_code=404, detail=f"Unknown or not-deleted entry id: {entry_id}")
    _audit_log(request, "kb_restore", entry_id)
    return restored


@app.post("/kb/reload", dependencies=[Depends(require_admin)])
def kb_reload(request: Request):
    kb: KnowledgeBase = app.state.knowledge_base
    kb.reload()
    _audit_log(request, "kb_reload")
    return {"reloaded": True, "count": kb.count}


@app.get("/kb/export", dependencies=[Depends(require_admin)])
def kb_export(request: Request):
    kb: KnowledgeBase = app.state.knowledge_base
    entries = kb.snapshot(include_deleted=False)
    _audit_log(request, "kb_export", extra={"count": len(entries)})
    return JSONResponse(
        content=entries,
        headers={"Content-Disposition": 'attachment; filename="knowledge_base.json"'},
    )


@app.post("/kb/import", dependencies=[Depends(require_admin)])
async def kb_import(request: Request):
    content_type = request.headers.get("content-type", "")
    entries_data = None
    if "multipart/form-data" in content_type:
        form = await request.form()
        file = form.get("file")
        if not file:
            raise HTTPException(status_code=400, detail="Missing file field 'file'")
        content = await file.read()
        try:
            data = json.loads(content.decode("utf-8"))
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid JSON file")
        entries_data = data["entries"] if isinstance(data, dict) and "entries" in data else data
    else:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid JSON body")
        entries_data = body["entries"] if isinstance(body, dict) and "entries" in body else body

    if not isinstance(entries_data, list):
        raise HTTPException(status_code=422, detail="Import payload must be a JSON array")

    kb: KnowledgeBase = app.state.knowledge_base
    try:
        count = kb.import_entries(entries_data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _audit_log(request, "kb_import", extra={"count": count})
    return {"imported": count, "count": kb.count}
