import io
import re
import time
import uuid
import wave
from datetime import datetime

import requests
from gtts import gTTS

from .. import config


class TTSError(Exception):
    pass


_MARKDOWN_PATTERNS = [
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),
    (re.compile(r"^\s*\|[\s:\-|]*\|\s*$", re.MULTILINE), ""),
    (re.compile(r"^\s*:?-{3,}:?\s*$", re.MULTILINE), ""),
    (re.compile(r"^\s*\|(.+)\|\s*$", re.MULTILINE), r"\1"),
    (re.compile(r"\s*\|\s*"), ", "),
    (re.compile(r"\|"), ","),
    (re.compile(r"(\*\*\*|___)(.+?)\1"), r"\2"),
    (re.compile(r"(\*\*|__)(.+?)\1"), r"\2"),
    (re.compile(r"(\*|_)([^*_\s][^*_]*)\1"), r"\2"),
    (re.compile(r"`+([^`]*)`+"), r"\1"),
    (re.compile(r"^#{1,6}\s+", re.MULTILINE), ""),
]


def strip_markdown(text: str) -> str:
    for pattern, replacement in _MARKDOWN_PATTERNS:
        text = pattern.sub(replacement, text)
    return text.strip()


def _split_chunks(text: str, limit: int) -> list[str]:
    pieces = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        while len(piece) > limit:
            cut = piece.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if current:
                chunks.append(current)
                current = ""
            chunks.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        if not piece:
            continue
        candidate = f"{current} {piece}".strip() if current else piece
        if len(candidate) <= limit:
            current = candidate
        else:
            chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return [c for c in chunks if c] or [text[:limit]]


def _groq_speech(text: str) -> bytes:
    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.GROQ_TTS_MODEL,
        "input": text,
        "voice": config.GROQ_TTS_VOICE,
        "response_format": "wav",
    }
    try:
        res = requests.post(
            config.GROQ_SPEECH_URL,
            headers=headers,
            json=payload,
            timeout=config.REQUEST_TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        raise TTSError(f"Could not reach Groq speech API: {exc}") from exc
    if res.status_code >= 400:
        raise TTSError(f"Groq TTS error {res.status_code}: {res.text[:300]}")
    if not res.content:
        raise TTSError("Groq TTS returned empty audio")
    return res.content


def _normalize_wav(parts: list[bytes]) -> bytes:
    fmt = None
    frames = []
    for part in parts:
        with wave.open(io.BytesIO(part), "rb") as reader:
            this_fmt = (reader.getnchannels(), reader.getsampwidth(), reader.getframerate())
            if fmt is None:
                fmt = this_fmt
            elif this_fmt != fmt:
                raise TTSError(f"Inconsistent WAV formats across chunks: {this_fmt} vs {fmt}")
            frames.append(reader.readframes(reader.getnframes()))
    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setnchannels(fmt[0])
        writer.setsampwidth(fmt[1])
        writer.setframerate(fmt[2])
        for frame in frames:
            writer.writeframes(frame)
    return out.getvalue()


def synthesize(text: str) -> tuple[str, str]:
    clean = strip_markdown(text)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    config.AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    try:
        parts = [_groq_speech(chunk) for chunk in _split_chunks(clean, config.TTS_MAX_INPUT_CHARS)]
        audio = _normalize_wav(parts)
        filename = f"ai_response_{stamp}_{uuid.uuid4().hex[:8]}.wav"
        (config.AUDIO_DIR / filename).write_bytes(audio)
        result = (filename, "groq-orpheus")
    except TTSError:
        filename = f"ai_response_{stamp}_{uuid.uuid4().hex[:8]}.mp3"
        gTTS(clean).save(str(config.AUDIO_DIR / filename))
        result = (filename, "gtts-fallback")
    try:
        prune_old_audio()
    except Exception:
        pass  # pruning is best-effort; never break a good response
    return result


def prune_old_audio() -> int:
    """Delete expired/excess TTS files. Best-effort, never raises.

    Removes `ai_response_*` files older than `AUDIO_TTL_SEC`, then trims to
    `AUDIO_MAX_FILES` newest. Non-positive config values disable that check.
    Returns the number of files removed.
    """
    try:
        audio_dir = config.AUDIO_DIR
        if not audio_dir.exists():
            return 0
        try:
            files = sorted(
                (p for p in audio_dir.glob("ai_response_*.*") if p.is_file()),
                key=lambda p: p.stat().st_mtime,
            )
        except OSError:
            return 0
        removed = 0
        if config.AUDIO_TTL_SEC > 0:
            now = time.time()
            kept = []
            for p in files:
                try:
                    if now - p.stat().st_mtime > config.AUDIO_TTL_SEC:
                        p.unlink(missing_ok=True)
                        removed += 1
                    else:
                        kept.append(p)
                except OSError:
                    kept.append(p)
            files = kept
        if config.AUDIO_MAX_FILES > 0:
            overflow = len(files) - config.AUDIO_MAX_FILES
            for p in files[: max(0, overflow)]:
                try:
                    p.unlink(missing_ok=True)
                    removed += 1
                except OSError:
                    continue
        return removed
    except Exception:
        return 0
