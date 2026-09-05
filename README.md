# 🧠 Agent Assist & Resolution Bot

A real-time customer support system that transcribes live audio, detects user intent, retrieves answers from a knowledge base (RAG), and for predefined issues, lets an AI voice agent take over and speak the resolution.

---

## 🧩 Features

- 🔊 Upload audio files (or drag & drop) → instant transcript via AssemblyAI.
- 🎙️ **Record live from the microphone** right in the dashboard (MediaRecorder) - the recording is re-encoded to MP3 in the browser and becomes the upload.
- 🎯 Intent detection from the transcript (password reset, refunds, order tracking…).
- 🧠 Context-aware RAG using `sentence-transformers` - knowledge-base embeddings are computed once at startup.
- 🎚️ **Retrieval confidence threshold** - queries that don't match the knowledge base (cosine similarity below `KB_MIN_SIMILARITY`) get an honest "I'm not sure" instead of a confidently wrong answer, and skip the LLM call entirely.
- 🧩 **Multi-topic retrieval** - mixed recordings pull the top matching KB entries (`sources` array) so every issue in a single call is answered from the knowledge base, not invented.
- 📝 **Hot-reloadable knowledge base** - add, edit, and remove entries from a dedicated manager page, or edit `knowledge_base.json` directly; changes apply without restarting (invalid edits keep serving the last good state).
- 💬 Answer generation using **Groq** (`openai/gpt-oss-20b` by default).
- 💭 **Multi-turn memory** - the dashboard sends the recent conversation with each request, so follow-ups like "what about my order from earlier?" are answered from context, not as isolated one-shot Q&A.
- 🎫 **Human handoff** - when a caller asks to speak to an agent, or the bot can't match the knowledge base, a support ticket is created (webhook with retry, else email, else disk queue), so the handoff actually happens instead of just being promised. The dashboard shows a "ticket opened" banner with the ticket ID.
- 🤖 AI takeover: automatable intents are answered aloud by a realistic neural voice (**Groq Orpheus**), with automatic gTTS fallback. If a recording mentions **any** automatable intent, the bot takes over and speaks.
- 🔒 **Rate limiting + auth** on `/transcribe/` and `/assist/` (when `ADMIN_TOKEN` is set) so the credit-burning endpoints can't be abused anonymously.
- 🖥️ Modern dashboard: light/dark mode, session history that survives page navigation (stored in `sessionStorage`), markdown-rendered responses, live API status, copy-to-clipboard.
- 📚 Knowledge base manager at `/static/kb.html`: search, inline editing, soft-delete with undo, paginated list (`?limit&offset`), import/export (bulk JSON), reload from disk.
- 📝 **Audit log** (`knowledge_base.log.jsonl`): every admin KB write is appended with timestamp, request ID, and admin identity - never blocks the request.

## 🛠️ Tech Stack

| Feature                | Stack / API                                        |
|------------------------|----------------------------------------------------|
| Transcription          | [AssemblyAI](https://www.assemblyai.com)           |
| Embedding & RAG        | Sentence Transformers (`all-MiniLM-L6-v2`)         |
| LLM for Response       | [Groq API](https://groq.com/) - GPT-OSS 20B        |
| Voice Generation       | [Groq Orpheus](https://console.groq.com/docs/text-to-speech) (`gTTS` fallback) |
| Mic recording encode   | [lamejs](https://github.com/zhuker/lamejs) (in-browser MP3) |
| Backend Framework      | FastAPI                                            |
| Frontend               | HTML + CSS + JS                                    |

> **AssemblyAI format note:** this account reliably transcodes **MP3**; it currently rejects raw WebM/Opus and PCM WAV recordings (`application/octet-stream` transcoding error). All `audio_sample/*.wav` files are actually MP3s (works for that reason), and live mic recordings are re-encoded to MP3 in the browser before upload.

## 📦 Installation

1. **Clone this repo**

   ```
   git clone https://github.com/GuptaAman12/agent-assist-bot
   cd agent-assist-bot
   ```

2. **Install dependencies**

   ```
   pip install -r requirements.txt
   ```

3. **Create a `.env` file** (copy the template):

   ```
   ASSEMBLYAI_API_KEY=your_assembly_ai_key
   GROQ_API_KEY=your_groq_api_key
   ```

   A template with all keys is committed as `.env.example` - copy it, then fill in real values:

   ```
   cp .env.example .env
   ```

   Optional overrides (also listed in `.env.example`):

   ```
   GROQ_MODEL=openai/gpt-oss-20b        # chat model
   EMBEDDING_MODEL=all-MiniLM-L6-v2      # sentence-transformers model
   KB_MIN_SIMILARITY=0.45                # below this, /assist/ answers "I'm not sure"
   MAX_UPLOAD_BYTES=104857600            # max /transcribe/ upload size (100 MB)
   ADMIN_TOKEN=change-me                 # if set, /kb/* and /transcribe/+/assist/ require auth
   RATE_LIMIT_MAX_REQUESTS=20            # per-IP per minute for /assist/
   RATE_LIMIT_MAX_TRANSCRIBE=10          # stricter for the costlier transcribe endpoint
   TRUST_PROXY_HEADERS=false             # true only behind a trusted proxy (uses X-Forwarded-For for rate limits)
   AUDIO_TTL_SEC=86400                   # prune TTS audio older than this (seconds)
   AUDIO_MAX_FILES=100                   # keep at most this many TTS audio files
   HANDOFF_WEBHOOK_URL=                  # POST ticket JSON when a human is needed
   GROQ_TTS_MODEL=canopylabs/orpheus-v1-english
   GROQ_TTS_VOICE=troy                   # autumn/diana/hannah/austin/daniel/troy
   ```

   Handoff can go to an email instead of a webhook (`HANDOFF_EMAIL_TO` + `SMTP_*`); with neither set, tickets are still recorded in the structured logs.

4. **Run the server**

   ```
   uvicorn main:app --reload
   ```

5. Open 👉 http://127.0.0.1:8000/ (redirects to the UI) - knowledge base manager at http://127.0.0.1:8000/static/kb.html

The first startup downloads the `all-MiniLM-L6-v2` embedding model from HuggingFace, so it can take a while. Interactive API docs are at `/docs`.

## 🧪 Tests

```
pip install -r requirements-dev.txt
python -m pytest -q
```

104 tests cover intent detection, KB hot-reload behavior (threshold, external edits, broken-file fail-open, ID stability, admin auth), TTS stripping/normalization/fallback, AssemblyAI/Groq error paths, upload guards, handoff retry/queue, audit log, import/export, and the full API surface - all external calls and the embedding model are mocked, so tests run offline and fast. CI runs them on every push (`.github/workflows/ci.yml`).

## 🐳 Docker

**Recommended (one command):**

```
docker compose up -d --build
```

Starts the full stack (ports, `.env` keys, model cache volume) from `docker-compose.yml` - then open http://localhost:8000/. In Docker Desktop you can start/stop the stack from the **Containers** tab without any commands.

**Manual alternative:**

```
docker build -t agent-assist-bot .
docker run -p 8000:8000 --env-file .env agent-assist-bot
```

Keys are passed at runtime via `--env-file` - never baked into the image. First container start downloads the embedding model; compose mounts a cache volume automatically so it persists across restarts:

```
docker run -p 8000:8000 --env-file .env -v hf_cache:/app/.hf_cache agent-assist-bot
```

## 📁 Project Structure

```
app/
├── config.py              # env vars, paths, model names, intent keywords
├── main.py                # FastAPI app, routes, lifespan (startup validation)
├── logging.py             # JSON structured logs + per-request ID
└── services/
    ├── transcription.py   # AssemblyAI upload + polling (with timeout)
    ├── llm.py             # Groq chat completion
    ├── rag.py             # knowledge base load + precomputed embeddings
    ├── intent.py          # keyword-based intent detection
    ├── handoff.py         # ticket delivery (webhook retry, email, disk queue)
    └── tts.py             # Groq Orpheus TTS with gTTS fallback
main.py                    # thin shim so `uvicorn main:app` works
static/                    # dashboard UI, KB manager page, vendor libs, generated audio
static/vendor/lame.all.js  # in-browser MP3 encoder for live mic recordings
knowledge_base.json        # RAG corpus
```

## 🔌 API

| Endpoint             | Body                        | Returns                                                      |
|----------------------|-----------------------------|--------------------------------------------------------------|
| `POST /transcribe/`  | multipart audio upload   | `{transcript, intent}`                                       |
| `POST /assist/`      | `{transcript, intent, history?}` JSON | `{response, ai_takeover, source, sources, audio_url, tts_engine, kb_score, handoff, ticket_id}` |
| `GET /health`        | –                           | `{"status": "ok"}`                                           |
| `GET /kb`            | `?limit&offset&include_deleted` | `{count, entries: [{id, question, response}], limit, offset}` |
| `GET /kb/export`     | –                           | JSON file download (`Content-Disposition: attachment`)       |
| `POST /kb`           | `{question?, response}`     | created entry                                                |
| `PUT /kb/{id}`       | `{question?, response}`     | updated entry (re-embedded immediately)                      |
| `DELETE /kb/{id}`    | –                           | `{deleted, count, undo_token}` (soft-delete)                 |
| `POST /kb/{id}/restore` | –                        | restored entry                                               |
| `POST /kb/reload`    | –                           | `{reloaded, count}`                                          |
| `POST /kb/import`    | `file` or JSON `[{question, response}]` | `{imported, count}` (replaces all, re-embeds) |

`audio_url` is set only when `ai_takeover` is true (the response is spoken). `handoff` is true when a support ticket was opened (check `ticket_id`). Errors return a JSON `{"detail": "..."}` with an appropriate status code (502 for upstream API failures, 504 for transcription timeouts, 429 when over the per-IP rate limit). KB entries can also be edited by modifying `knowledge_base.json` directly - the server detects the change and re-embeds on the next request.

`history` is optional: an array of prior `{transcript, response}` turns (the dashboard sends the last 5). The LLM sees them as conversation context. If the current query has no KB match but `history` is present, the bot answers from the earlier exchange instead of the canned "I'm not sure".

`POST /transcribe/` enforces upload guards before any external API call: unsupported file extensions return **415** (audio/video allowlist matching AssemblyAI's formats), and files over `MAX_UPLOAD_BYTES` (default 100 MB) return **413**.

**Admin auth:** if `ADMIN_TOKEN` is set in `.env`, the knowledge base is locked down:
- `/kb/*` API requires it (via `X-Admin-Token` header **or** the admin cookie)
- `/static/kb.html` shows a login page instead of the editor - sign in at the form (`POST /kb-admin/login` sets an `HttpOnly` cookie; `/kb-admin/logout` clears it)
- When `ADMIN_TOKEN` is empty (local dev), everything stays open.

## 📝 Logging

Logs are structured JSON lines on stdout. Every request produces a `request completed` line (and `request failed` on errors) carrying a `req_id`, and the same ID is echoed back on the response as the `X-Request-ID` header, so a bad request is traceable end to end:

```
{"ts": "...", "level": "INFO", "logger": "app.access", "message": "request completed",
 "req_id": "8d93452cdd5e", "req_method": "GET", "req_path": "/health",
 "req_status": 200, "req_duration_ms": 0.52}
```

Any code can read the current request ID via `app.logging.get_request_id()`.

### Test without a microphone

```bash
curl -X POST http://127.0.0.1:8000/assist/ \
  -H "Content-Type: application/json" \
  -d '{"transcript": "How do I reset my password?", "intent": "password_reset"}'
```

Then open the returned `audio_url`. Sample recordings for `/transcribe/` are in `audio_sample/` (note: these are MP3s with a `.wav` extension).
