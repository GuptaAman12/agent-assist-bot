import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .services import llm as llm_service
from .services import transcription as transcription_service
from .services.intent import detect_intent
from .services.rag import KnowledgeBase
from .services.tts import synthesize


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = config.missing_api_keys()
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)} (check your .env file)")
    app.state.knowledge_base = KnowledgeBase()
    yield


app = FastAPI(title="Agent Assist & Resolution Bot", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")


class AssistRequest(BaseModel):
    transcript: str
    intent: str


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
    source, score = kb.best_match(request.transcript)

    if source is None:
        return {
            "response": config.KB_NO_MATCH_RESPONSE,
            "ai_takeover": False,
            "source": None,
            "audio_url": None,
            "tts_engine": None,
            "kb_score": round(score, 4),
        }

    try:
        response_text = llm_service.generate_response(source, request.transcript)
    except llm_service.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    ai_takeover = request.intent in config.SIMPLE_INTENTS

    audio_url = None
    tts_engine = None
    if ai_takeover:
        filename, tts_engine = synthesize(response_text)
        audio_url = f"/static/{filename}"

    return {
        "response": response_text,
        "ai_takeover": ai_takeover,
        "source": source,
        "audio_url": audio_url,
        "tts_engine": tts_engine,
        "kb_score": round(score, 4),
    }


@app.get("/health")
def health():
    return {"status": "ok"}


class KBEntryRequest(BaseModel):
    question: str = ""
    response: str


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if not config.ADMIN_TOKEN:
        return
    if x_admin_token != config.ADMIN_TOKEN:
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
