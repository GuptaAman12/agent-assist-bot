# AGENTS.md

## What this is

Real-time support bot: FastAPI backend in `app/` (routes + services), vanilla JS frontend in `static/`, RAG corpus in `knowledge_base.json`. No tests, no lint config, no CI.

## Run

```
pip install -r requirements.txt
uvicorn main:app --reload
```

- Root `/` redirects to the UI (`/static/index.html`); API docs at `/docs`.
- Requires `.env` with `ASSEMBLYAI_API_KEY` and `GROQ_API_KEY` — startup fails fast with a clear error if missing.
- First startup downloads the `all-MiniLM-L6-v2` model from HuggingFace (slow, needs network).
- Optional env overrides: `GROQ_MODEL`, `EMBEDDING_MODEL`.

## Layout

- `app/main.py` — routes, lifespan startup, HTTP error mapping. Keep endpoints thin.
- `app/config.py` — ALL constants: env vars, paths (anchored to repo root, CWD-independent), intent keywords (`INTENT_KEYWORDS`), takeover list (`SIMPLE_INTENTS`).
- `app/services/` — one module per external concern: `transcription.py` (AssemblyAI), `llm.py` (Groq), `rag.py`, `intent.py`, `tts.py`.

## Manual verification (no test suite exists)

Exercise the two endpoints with files from `audio_sample/`:
- `POST /transcribe/` — multipart wav upload; returns `{transcript, intent}`.
- `POST /assist/` — JSON `{transcript, intent}`; returns LLM response, `ai_takeover` flag, optional audio URL.

Both call external APIs (AssemblyAI, Groq) and fail without valid keys. `GET /health` works offline for a quick liveness check. Frontend contract: script.js expects exactly `{transcript, intent}` and `{response, ai_takeover, audio_url}` — changing response shapes breaks the UI.

## Gotchas

- Adding an intent requires touching two places: `INTENT_KEYWORDS` in `app/config.py` (order matters — first match wins) and a matching entry in `knowledge_base.json`. Add the intent to `SIMPLE_INTENTS` if it should trigger AI takeover/TTS.
- `knowledge_base.json` is loaded and embedded once at startup — restart the server after editing it.
- Upstream failures raise typed errors (`TranscriptionError`, `LLMError`) that routers map to 502; polling timeout → 504. Don't let raw exceptions leak out of services.
- Endpoints are sync `def` on purpose so FastAPI runs them in a threadpool — the external API calls block. Don't convert to `async def` without wrapping the blocking calls.
- Runtime artifacts are gitignored: generated TTS lands in `static/ai_response_*.mp3`; uploads go through OS temp files (cleaned up per request). Never commit them.
- HTTP calls use raw `requests`, not SDKs. Groq model defaults to `openai/gpt-oss-120b` via `GROQ_MODEL` env var (no Llama models exist on this Groq account — verify with `GET /openai/v1/models` before changing).
- LLM responses are rendered as markdown in the UI and spoken via gTTS — keep the system prompt in `app/services/llm.py` discouraging tables/headings, and keep `strip_markdown` in `tts.py` in sync with whatever renderer `static/script.js` supports.
- TTS: primary engine is Groq Orpheus (`canopylabs/orpheus-v1-english`, voices: autumn/diana/hannah/austin/daniel/troy) with automatic gTTS fallback on any failure. Orpheus caps input at 200 chars (tts.py chunks + merges) and streams WAVs with placeholder headers (`nframes=2147483647`) — `_normalize_wav` rewrites them; never save raw Orpheus output or copy reader params into a writer.
- `claude-setup.ps1` contains an exposed API key; gitignored but present locally — never commit or copy its contents anywhere.
- Static assets in `static/index.html` are loaded with `?v=N` cache-busting params — bump `N` whenever you change `style.css`/`script.js`, or browsers serve stale copies and the UI appears broken/unstyled.
