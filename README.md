# 🧠 Agent Assist & Resolution Bot

A real-time customer support system that transcribes live audio, detects user intent, retrieves answers from a knowledge base (RAG), and for predefined issues, lets an AI voice agent take over and speak the resolution.

---

## 🧩 Features

- 🔊 Upload `.wav` audio (or drag & drop) → instant transcript via AssemblyAI.
- 🎯 Intent detection from the transcript (password reset, refunds, order tracking…).
- 🧠 Context-aware RAG using `sentence-transformers` - knowledge-base embeddings are computed once at startup.
- 🎚️ **Retrieval confidence threshold** - queries that don't match the knowledge base (cosine similarity below `KB_MIN_SIMILARITY`) get an honest "I'm not sure" instead of a confidently wrong answer, and skip the LLM call entirely.
- 🧩 **Multi-topic retrieval** - mixed recordings pull the top matching KB entries (`sources` array) so every issue in a single call is answered from the knowledge base, not invented.
- 📝 **Hot-reloadable knowledge base** - add, edit, and remove entries from a dedicated manager page, or edit `knowledge_base.json` directly; changes apply without restarting (invalid edits keep serving the last good state).
- 💬 Answer generation using **Groq** (`openai/gpt-oss-120b` by default).
- 🤖 AI takeover: simple intents are answered aloud by a realistic neural voice (**Groq Orpheus**), with automatic gTTS fallback.
- 🖥️ Modern dashboard: light/dark mode, session history, markdown-rendered responses, live API status, copy-to-clipboard.
- 📚 Knowledge base manager at `/static/kb.html`: search, inline editing, add/delete, reload from disk.

## 🛠️ Tech Stack

| Feature                | Stack / API                                        |
|------------------------|----------------------------------------------------|
| Transcription          | [AssemblyAI](https://www.assemblyai.com)           |
| Embedding & RAG        | Sentence Transformers (`all-MiniLM-L6-v2`)         |
| LLM for Response       | [Groq API](https://groq.com/) - GPT-OSS 120B       |
| Voice Generation       | [Groq Orpheus](https://console.groq.com/docs/text-to-speech) (`gTTS` fallback) |
| Backend Framework      | FastAPI                                            |
| Frontend               | HTML + CSS + JS                                    |

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
   GROQ_MODEL=openai/gpt-oss-120b        # chat model
   EMBEDDING_MODEL=all-MiniLM-L6-v2      # sentence-transformers model
   KB_MIN_SIMILARITY=0.45                # below this, /assist/ answers "I'm not sure"
   MAX_UPLOAD_BYTES=104857600            # max /transcribe/ upload size (100 MB)
   ADMIN_TOKEN=change-me                 # if set, /kb/* requires this as X-Admin-Token
   GROQ_TTS_MODEL=canopylabs/orpheus-v1-english
   GROQ_TTS_VOICE=troy                   # autumn/diana/hannah/austin/daniel/troy
   ```

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

59 tests cover intent detection, KB hot-reload behavior (threshold, external edits, broken-file fail-open, ID stability), TTS stripping/normalization/fallback, AssemblyAI/Groq error paths, and the full API surface - all external calls and the embedding model are mocked, so tests run offline and fast. CI runs them on every push (`.github/workflows/ci.yml`).

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
└── services/
    ├── transcription.py   # AssemblyAI upload + polling (with timeout)
    ├── llm.py             # Groq chat completion
    ├── rag.py             # knowledge base load + precomputed embeddings
    ├── intent.py          # keyword-based intent detection
    └── tts.py             # Groq Orpheus TTS with gTTS fallback
main.py                    # thin shim so `uvicorn main:app` works
static/                    # dashboard UI, KB manager page, generated audio
knowledge_base.json        # RAG corpus
```

## 🔌 API

| Endpoint             | Body                        | Returns                                                      |
|----------------------|-----------------------------|--------------------------------------------------------------|
| `POST /transcribe/`  | multipart `.wav` upload     | `{transcript, intent}`                                       |
| `POST /assist/`      | `{transcript, intent}` JSON | `{response, ai_takeover, source, sources, audio_url, tts_engine, kb_score}` |
| `GET /health`        | –                           | `{"status": "ok"}`                                           |
| `GET /kb`            | –                           | `{count, entries: [{id, question, response}]}`               |
| `POST /kb`           | `{question?, response}`     | created entry                                                |
| `PUT /kb/{id}`       | `{question?, response}`     | updated entry (re-embedded immediately)                      |
| `DELETE /kb/{id}`    | –                           | `{deleted, count}`                                           |
| `POST /kb/reload`    | –                           | `{reloaded, count}`                                          |

`audio_url` is set only when `ai_takeover` is true (the response is spoken). Errors return a JSON `{"detail": "..."}` with an appropriate status code (502 for upstream API failures, 504 for transcription timeouts). KB entries can also be edited by modifying `knowledge_base.json` directly - the server detects the change and re-embeds on the next request.

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

Then open the returned `audio_url`. Sample recordings for `/transcribe/` are in `audio_sample/`.
