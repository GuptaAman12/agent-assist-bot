from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from .. import config
from ..services.rag import KnowledgeBase

router = APIRouter()


@router.get("/")
def root():
    return RedirectResponse(url="/static/index.html")


@router.get("/health")
def health(request: Request):
    kb: KnowledgeBase | None = getattr(request.app.state, "knowledge_base", None)
    kb_count = kb.count if kb else 0
    services = {
        "api": {
            "name": "API Server",
            "status": "online",
            "description": "FastAPI core service",
        },
        "rag": {
            "name": "Knowledge Base (RAG)",
            "status": "online" if kb_count > 0 else "offline",
            "description": f"{kb_count} entries indexed",
        },
        "transcription": {
            "name": "Speech Transcription",
            "status": "online" if bool(config.ASSEMBLYAI_API_KEY) else "offline",
            "description": "AssemblyAI engine",
        },
        "llm": {
            "name": "LLM Inference",
            "status": "online" if bool(config.GROQ_API_KEY) else "offline",
            "description": f"Groq ({config.GROQ_MODEL})",
        },
        "tts": {
            "name": "Voice Synthesis (TTS)",
            "status": "online",
            "description": f"Groq Orpheus ({config.GROQ_TTS_VOICE}) + gTTS",
        },
        "handoff": {
            "name": "Human Handoff",
            "status": "online" if bool(config.HANDOFF_WEBHOOK_URL or config.HANDOFF_EMAIL_TO) else "offline",
            "description": (
                "Webhook dispatch active" if config.HANDOFF_WEBHOOK_URL
                else (f"SMTP email active ({config.HANDOFF_EMAIL_TO})" if config.HANDOFF_EMAIL_TO
                else "Offline (no webhook or email configured)")
            ),
        },
    }
    return {"status": "ok", "services": services}
