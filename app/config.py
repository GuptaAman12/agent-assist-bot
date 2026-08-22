import json
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

KNOWLEDGE_BASE_PATH = BASE_DIR / "knowledge_base.json"
STATIC_DIR = BASE_DIR / "static"

ASSEMBLYAI_UPLOAD_URL = "https://api.assemblyai.com/v2/upload"
ASSEMBLYAI_TRANSCRIPT_URL = "https://api.assemblyai.com/v2/transcript"
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_SPEECH_URL = "https://api.groq.com/openai/v1/audio/speech"

GROQ_TTS_MODEL = os.getenv("GROQ_TTS_MODEL", "canopylabs/orpheus-v1-english")
GROQ_TTS_VOICE = os.getenv("GROQ_TTS_VOICE", "troy")
TTS_MAX_INPUT_CHARS = 200

TRANSCRIPTION_POLL_INTERVAL_SEC = 2
TRANSCRIPTION_TIMEOUT_SEC = 120
REQUEST_TIMEOUT_SEC = 60

INTENT_KEYWORDS = {
    "speak_to_agent": ("human", "representative", "real person", "live agent"),
    "password_reset": ("password",),
    "check_balance": ("balance",),
    "update_email": ("change my email", "update my email", "email address"),
    "update_address": ("address",),
    "refund_request": ("refund", "money back"),
    "cancel_order": ("cancel",),
    "track_order": ("track", "order status"),
    "update_payment_method": ("payment method", "card on file", "credit card"),
    "account_locked": ("locked", "lock out"),
    "recover_username": ("username",),
    "change_subscription": ("upgrade", "downgrade", "subscription"),
    "get_invoice": ("invoice", "receipt"),
    "technical_issue": ("not working", "crash", "error message", "won't load"),
}
SIMPLE_INTENTS = {"password_reset", "check_balance", "update_address", "track_order", "get_invoice"}
UNKNOWN_INTENT = "unknown"


def missing_api_keys() -> list[str]:
    required = {
        "ASSEMBLYAI_API_KEY": ASSEMBLYAI_API_KEY,
        "GROQ_API_KEY": GROQ_API_KEY,
    }
    return sorted(name for name, value in required.items() if not value)


def load_knowledge_base() -> list[dict]:
    with open(KNOWLEDGE_BASE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        raise ValueError(f"{KNOWLEDGE_BASE_PATH} must be a non-empty JSON array")
    for i, entry in enumerate(data):
        if not isinstance(entry, dict) or "response" not in entry:
            raise ValueError(f"Knowledge base entry {i} must be an object with a 'response' field")
    return data
