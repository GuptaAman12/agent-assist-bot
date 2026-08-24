# AGENTS.md

## What this is

Real-time support bot: single-file FastAPI backend (`main.py` holds all backend logic), vanilla JS frontend in `static/`, RAG corpus in `knowledge_base.json`. No test suite, no lint config, no CI.

## Run

```
pip install -r requirements.txt
uvicorn main:app --reload
```

- Root `/` redirects to the UI (`/static/index.html`); API docs at `/docs`.
- Requires `.env` with `ASSEMBLYAI_API_KEY` and `GROQ_API_KEY` — startup fails fast with a clear error if missing.
- First startup downloads the `all-MiniLM-L6-v2` model from HuggingFace (slow, needs network).
- Optional env overrides: `GROQ_MODEL`, `EMBEDDING_MODEL`, `GROQ_TTS_MODEL`, `GROQ_TTS_VOICE`.

## Layout

- `app/main.py` — routes, lifespan startup, HTTP error mapping. Keep endpoints thin.
- `app/config.py` — ALL constants: env vars, paths (anchored to repo root, CWD-independent), intent keywords (`INTENT_KEYWORDS`), takeover list (`SIMPLE_INTENTS`).
- `app/services/` — one module per external concern: `transcription.py` (AssemblyAI), `llm.py` (Groq), `rag.py`, `intent.py`, `tts.py`.
- `app/services/tts.py` — `synthesize(text)` returns `(filename, engine)`. Primary engine is Groq Orpheus (`canopylabs/orpheus-v1-english`, voices: `autumn/diana/hannah/austin/daniel/troy`); automatic gTTS fallback on any failure. **Orpheus streams WAVs with placeholder headers (`nframes=2147483647`, RIFF size `0xFFFFFFFF`) — `_normalize_wav` rewrites them with correct sizes before serving.**
- `app/services/rag.py` — `KnowledgeBase` loaded **once** at startup; `best_response(query)` uses precomputed `corpus_embeddings` (one encode, not per-request).
- `app/services/transcription.py` — `TranscriptionError` / `TranscriptionTimeout` raise typed errors; routers map to **502** (upstream failure) / **504** (polling timeout). Polling timeout **120s** (was infinite loop).
- `app/services/llm.py` — `LLMError`; status checks + request timeout; Groq model overridable via `GROQ_MODEL` env var.
- `app/config.py` — `missing_api_keys()` raises `RuntimeError` at import if keys absent.
- `main.py` — `GET /` redirect to `/static/index.html`; `GET /health` returns `{"status":"ok"}` (works without external keys).
- `static/` — frontend + generated `.wav`/`.mp3` audio files.
- `knowledge_base.json` — RAG corpus; every new intent needs a matching entry **plus** a keyword in `INTENT_KEYWORDS` (first‑match‑wins) and optionally membership in `SIMPLE_INTENTS` (triggers AI‑voice takeover).
- `.gitignore` covers runtime artifacts (`temp.wav`, `static/ai_response_*.mp3`, `static/ai_response_*.wav`) and `claude-setup.ps1` (embedded secret — never commit).

## Gotchas

- **Add an intent** — touch two places: `INTENT_KEYWORDS` in `app/config.py` (order matters — first match wins) **and** a matching entry in `knowledge_base.json`. Add the intent to `SIMPLE_INTENTS` if it should trigger AI‑voice/TTS.
- **`knowledge_base.json`** is loaded and embedded **once** at startup — restart the server after editing it.
- Endpoints are sync `def` on purpose so FastAPI runs them in a threadpool — the external API calls block. Don't convert to `async def` without wrapping the blocking calls.
- Upstream failures raise typed errors (`TranscriptionError`, `LLMError`) that routers map to **502**; polling timeout → **504**. Don't let raw exceptions leak out of services.
- Runtime artifacts are gitignored: generated TTS lands in `static/ai_response_*.wav`/`.mp3`; uploads go through OS temp files (cleaned up per request). Never commit them.
- HTTP calls use raw `requests`, not SDKs. Groq model defaults to `canopylabs/orpheus-v1-english` via `GROQ_TTS_MODEL` env var (voices: `autumn/diana/hannah/austin/daniel/troy`).
- `claude-setup.ps1` contains an exposed API key; gitignored but present locally — never commit or copy its contents anywhere.
- LLM responses are rendered as markdown in the UI and spoken via gTTS — keep the system prompt in `app/services/llm.py` discouraging tables/headings, and keep `strip_markdown` in `tts.py` in sync with whatever renderer `static/script.js` supports.

## Manual verification (no test suite exists)

Exercise the two endpoints with files from `audio_sample/`:
- `POST /transcribe/` — multipart wav upload; returns `{transcript, intent}`.
- `POST /assist/` — JSON `{transcript, intent}`; returns LLM response, `ai_takeover` flag, optional audio URL, and `tts_engine`.

Both call external APIs (AssemblyAI, Groq) and fail without valid keys.

`GET /health` works offline for a quick liveness check. Frontend contract: `script.js` expects exactly `{transcript, intent}` and `{response, ai_takeover, audio_url, tts_engine}` — changing response shapes breaks the UI.

## Gotchas (continued)

- **`/transcribe/` with a bad file type** (e.g. `requirements.txt`) → AssemblyAI returns a 400 with a descriptive error message; our router maps it to **502** JSON with detail.
- **Groq Orpheus 200‑char limit** — we chunk long responses at sentence boundaries (`re.split(r"(?<=[.!?])\s+", text)`) and merge the resulting WAVs via `_normalize_wav` (which rewrites the placeholder headers). If any chunk fails, the whole fallback to gTTS is triggered.
- **Dark‑mode / light‑mode** — toggle via the moon/sun icon in the top‑right; preference saved to `localStorage`; first visit respects `prefers-color-scheme`; `[data-theme="dark"]` CSS overrides variables and `color-scheme` so native controls (scrollbars, audio player) follow the theme.
- **Hover tooltips** — native `title` attributes on all interactive buttons (submit, clear file, copy, clear history, history items, dropzone, theme toggle) so they appear on hover without extra JavaScript.
- **History items** are `<button>` elements; without an explicit `color` they would inherit the UA default (black) and become invisible on the dark surface — we set `color: var(--text)` and add `button { font: inherit; cursor: pointer; color: inherit }` as a guard.
- **`/health`** endpoint works without external keys; it only checks that the FastAPI process is alive.

## Test without a microphone

```bash
curl -X POST http://127.0.0.1:8000/assist/ \
  -H "Content-Type: application/json" \
  -d '{"transcript":"How do I reset my password?","intent":"password_reset"}'
```

Then open the returned `audio_url`. You can also use the interactive form at `/docs`.

## Limits & caveats

- **AssemblyAI** caps local uploads at **2.2 GB** and audio duration at **10 hours** (min 160 ms). Our app has no intrinsic size limit, but a large upload will spike RAM (we buffer the whole file in memory before writing the temp file).
- **Groq Orpheus** caps each request at **200 characters**; our `_split_chunks` routine chops longer responses and merges the resulting WAVs.
- **Groq** models are overridable via `GROQ_MODEL`; the TTS model is `canopylabs/orpheus-v1-english` with voices `autumn/diana/hannah/austin/daniel/troy`.
- **File types** AssemblyAI accepts most audio/video (`wav, mp3, m4a, flac, ogg, opus, aac, wma, amr, ape, 3gp, mkv, mov, mpeg, webm`). Our UI only filters `.wav` in the file picker, but drag‑drop or pasting a URL bypasses the picker — any format AssemblyAI accepts will be submitted.

## Adding a new intent

1. Add a keyword tuple in `app/config.py`'s `INTENT_KEYWORDS` (first match wins).
2. Add a matching entry in `knowledge_base.json`.
3. Add to `SIMPLE_INTENTS` if the intent should trigger AI‑voice takeover.
4. Restart the server so the KB and embeddings are re‑loaded.

## TTS engine choice

- **Groq Orpheus** (recommended): same Groq key, no new account needed; voices sound natural; automatic gTTS fallback if terms‑not‑accepted or any request fails.
- **OpenAI TTS** would require adding `OPENAI_API_KEY` to `.env` and switching `GROQ_TTS_MODEL` to `openai/tts-1` / `openai/tts-1-hd`.
- **ElevenLabs** would require `ELEVENLABS_API_KEY` and is the most realistic voice, but comes with a separate account and free‑tier quota (~10 min/month).

## Dark‑mode caveat

The CSS rule `[data-theme="dark"] { color-scheme: dark }` tells the browser to use the system’s dark‑mode palette for native controls (scrollbars, audio player, system fonts). Without it, those controls stay white and look out of place on a dark surface.

## File‑type caveat

Our UI’s `accept=".wav"` only filters the native file‑picker. The `/transcribe/` endpoint accepts **any** format that AssemblyAI supports; uploading a non‑`.wav` file will succeed upload but AssemblyAI may reject it with a 400/502 (e.g. `text/plain` → *"Transcoding failed. File type text/plain..."*). An explicit allowlist check can be added if you want to lock uploads to `.wav` only.