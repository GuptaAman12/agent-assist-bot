import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from .. import config
from ..logging import get_access_logger
from ..services import analytics as analytics_service
from ..services import handoff as handoff_service
from ..services import llm as llm_service
from ..services import transcription as transcription_service
from ..services.intent import detect_intent, detect_intents
from ..services.rag import KnowledgeBase
from ..services import tts as tts_service
from ..schemas import AssistRequest
from ..dependencies import check_rate_limit, require_admin

router = APIRouter()
access_logger = get_access_logger()


@router.post("/transcribe/", dependencies=[Depends(require_admin), Depends(check_rate_limit)])
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

    intent = detect_intent(transcript)
    analytics_service.record("transcribe_requests")
    analytics_service.record("transcribe_bytes", declared_size)
    analytics_service.log_event("transcribe", intent=intent, file_size=declared_size)
    return {"transcript": transcript, "intent": intent}


@router.post("/assist/", dependencies=[Depends(require_admin), Depends(check_rate_limit)])
def assist_agent(request: AssistRequest, req: Request):
    kb: KnowledgeBase = req.app.state.knowledge_base
    matches = kb.best_matches(request.transcript)
    detected_intents = detect_intents(request.transcript)

    if not matches and not request.history:
        handoff_id = handoff_service.create_ticket(
            reason="no_match",
            transcript=request.transcript,
            intents=detected_intents,
            assistant_response=config.KB_NO_MATCH_RESPONSE,
        )
        analytics_service.log_no_match(
            request.transcript, detected_intents, handoff_id=handoff_id
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
        sources = []
        kb_score = None
        analytics_service.log_no_match(
            request.transcript, detected_intents, from_history=True
        )
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
    analytics_service.record("llm_calls")

    ai_takeover = any(intent in config.SIMPLE_INTENTS for intent in detected_intents)

    audio_url = None
    tts_engine = None
    if ai_takeover:
        try:
            if request.voice:
                filename, tts_engine = tts_service.synthesize(response_text, voice=request.voice)
            else:
                filename, tts_engine = tts_service.synthesize(response_text)
            audio_url = f"/static/audio/{filename}"
        except Exception:
            access_logger.warning(
                "tts failed; returning text-only response",
                extra={
                    "req_method": "POST",
                    "req_path": "/assist/",
                },
            )
            audio_url = None
            tts_engine = None
    analytics_service.record(f"tts:{tts_engine or 'none'}")

    handoff_id = None
    if "speak_to_agent" in detected_intents:
        handoff_id = handoff_service.create_ticket(
            reason="speak_to_agent",
            transcript=request.transcript,
            intents=detected_intents,
            assistant_response=response_text,
        )
        if handoff_id is not None:
            analytics_service.record("handoff:speak_to_agent")

    prompt_tokens = getattr(response_text, "prompt_tokens", 0)
    completion_tokens = getattr(response_text, "completion_tokens", 0)
    total_tokens = getattr(response_text, "total_tokens", 0)
    if prompt_tokens == 0:
        prompt_tokens = max(1, len(context + request.transcript) // 4)
    if completion_tokens == 0:
        completion_tokens = max(1, len(response_text) // 4)
    if total_tokens == 0:
        total_tokens = prompt_tokens + completion_tokens

    analytics_service.record("tokens:prompt", prompt_tokens)
    analytics_service.record("tokens:completion", completion_tokens)
    analytics_service.record("tokens:total", total_tokens)

    analytics_service.log_event(
        "assist",
        intents=detected_intents,
        kb_score=kb_score,
        llm=True,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        model=config.GROQ_MODEL,
        tts_engine=tts_engine,
        handoff=handoff_id is not None,
        ticket_id=handoff_id,
        chars_synthesized=len(response_text) if ai_takeover else 0,
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


@router.get("/voices")
def list_voices():
    return {
        "default": config.GROQ_TTS_VOICE,
        "voices": config.ORPHEUS_VOICES,
    }
