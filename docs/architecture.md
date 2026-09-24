# Architecture & Implementation

This document covers the internal design, request pipeline, knowledge base engine, and complete directory structure of the Agent Assist & Resolution Bot.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Client (Browser)                               │
│  ┌───────────────┐  ┌───────────────┐  ┌────────────────────────────┐   │
│  │   Dashboard   │  │  KB Manager   │  │    Analytics Dashboard     │   │
│  │  index.html   │  │    kb.html    │  │       analytics.html       │   │
│  └───────┬───────┘  └───────┬───────┘  └─────────────┬──────────────┘   │
└──────────┼──────────────────┼────────────────────────┼──────────────────┘
           │                  │                        │
           ▼                  ▼                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        FastAPI Application                              │
│                                                                         │
│  Routes:  /transcribe/   /assist/   /kb/*   /handoff/*   /analytics/*   │
│                                                                         │
│  Middleware: request_context (X-Request-ID, access logs)                │
│              guard_admin_pages (auth gate on KB/analytics)              │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                         Services Layer                           │   │
│  │  ┌───────────────┐  ┌──────────┐  ┌────────┐  ┌───────────────┐  │   │
│  │  │ Transcription │  │  Intent  │  │  RAG   │  │      LLM      │  │   │
│  │  │ (AssemblyAI)  │  │  Detect  │  │  (ST)  │  │  (Groq Chat)  │  │   │
│  │  └───────────────┘  └──────────┘  └────────┘  └───────────────┘  │   │
│  │  ┌───────────────┐  ┌───────────────┐  ┌──────────────────────┐  │   │
│  │  │      TTS      │  │    Handoff    │  │      Analytics       │  │   │
│  │  │(Orpheus/gTTS) │  │(Webhook/SMTP) │  │  (Counters + JSONL)  │  │   │
│  │  └───────────────┘  └───────────────┘  └──────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  Data:  knowledge_base.json (RAG corpus, hot-reloadable)                │
│         *.log.jsonl (audit, analytics, handoff queue)                   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Processing Pipeline

When a customer or agent provides an audio sample or text input:

```
[Audio / Mic] ──► [Transcribe (AssemblyAI)] ──► [Intent Classifier]
                                                        │
┌───────────────────────────────────────────────────────┘
▼
[RAG Similarity Search]
  ├── Score >= KB_MIN_SIMILARITY ──► [LLM Answer Synthesis] ──► [Takeover Voice (TTS)]
  └── Score < KB_MIN_SIMILARITY  ──► [Polite Fallback]       ──► [Human Escalation Ticket]
```

1. **Transcription (`app/services/transcription.py`)**:
   - Files uploaded to `/transcribe/` are sent to AssemblyAI.
   - Live microphone audio is encoded client-side to MP3 via `lamejs` before upload to optimize transfer speed and ensure codec compatibility.
2. **Intent Classification (`app/services/intent.py`)**:
   - Uses precompiled regular expressions with left-hand word boundaries (`\bkeyword`).
   - Tolerates common verb and plural variations (e.g. "crashing", "cancelled", "passwords") while avoiding false positives ("unlocked" won't trigger `account_locked`).
3. **Retrieval-Augmented Generation (`app/services/rag.py`)**:
   - The transcript is embedded using `sentence-transformers` (`all-MiniLM-L6-v2`) and compared against the knowledge base via cosine similarity.
   - If one or more entries meet or exceed `KB_MIN_SIMILARITY` (default `0.45`), they are provided as numbered sources to the LLM.
4. **Response Generation (`app/services/llm.py`)**:
   - Groq API generates a conversational response anchored strictly in the retrieved knowledge base entries.
   - Text is cleaned with automated mojibake normalization to eliminate character encoding defects.
5. **AI Voice Takeover (`app/services/tts.py`)**:
   - If the detected intent is in `SIMPLE_INTENTS` (automatable requests like password reset or balance checks), Groq Orpheus synthesizes a spoken audio response.
   - Responses are sentence-chunked, normalized (correcting Orpheus WAV headers), and made available via the dashboard waveform visualizer. If Groq TTS fails, the system automatically falls back to `gTTS`.
6. **Human Handoff (`app/services/handoff.py`)**:
   - If the user explicitly asks for an agent or no knowledge base matches are found without context, an escalation ticket is generated.
   - Dispatched via webhook (with 3x exponential backoff retry), fallback SMTP email, or persisted to `handoff_queue.jsonl`.

---

## Knowledge Base Mechanics

The knowledge base (`knowledge_base.json`) uses several resilience and performance optimizations:

* **Joint Question + Answer Embedding:** Rather than embedding only questions or only answers, entries are embedded as `"{question}\n{response}"`. This significantly boosts recall accuracy on conversational user queries.
* **Incremental Re-encoding:** During reload, only new or updated entries are encoded through the PyTorch model. Unmodified entries reuse their existing vectors in memory.
* **Hot Reloading:** The server inspects the file modification timestamp (`mtime`) on every search query. If an external edit occurs, the knowledge base updates instantly without requiring a server reboot.
* **Fail-Safe Persistence:** If an external edit introduces malformed JSON, the server logs a warning and continues serving the last valid in-memory state.
* **Stable IDs & Soft Deletes:** Every entry is assigned an 8-character hexadecimal identifier. Deleted entries are soft-deleted via a `deleted_at` timestamp to enable instant undo operations.

---

## Logging & Observability

### Console Logging (Default)
Optimized for local terminal readability. Routine static asset transfers (`GET /static/*`) and health checks (`GET /health`) are filtered out to keep terminal logs clean:

```
17:45:12 [INFO ] POST /transcribe/ -> 200 (340.5ms) [req=4b2c3d12]
17:45:13 [INFO ] POST /assist/     -> 200 (112.8ms) [req=5c3d4e34]
17:45:14 [INFO ] POST /assist/     -> 200 (105.2ms) [req=6d4e5f56, ticket_id=tkt_123]
```

### JSON Logging (Production)
Set `LOG_FORMAT=json` in `.env` to emit one JSON object per line with ISO timestamps, logger names, request IDs, and timing metrics:

```json
{"ts": "2026-09-21T17:45:12.123+00:00", "level": "INFO", "logger": "app.access", "message": "request completed", "req_id": "4b2c3d12", "req_method": "POST", "req_path": "/transcribe/", "req_status": 200, "req_duration_ms": 340.5}
```

### Request Tracing
Every incoming HTTP request receives an `X-Request-ID` header and context variable, making it simple to trace logs across transcription, RAG retrieval, LLM synthesis, and handoff dispatch.

---

## Complete Project Structure

```
agent-assist-bot/
├── app/
│   ├── main.py                 # FastAPI application, lifespan, middleware & router setup
│   ├── config.py               # Environment variables, file paths, constants, intent keywords
│   ├── dependencies.py         # Authentication, IP sliding-window rate limiting, audit logger
│   ├── middleware.py           # Request ID injection, structured access logging, admin auth guards
│   ├── schemas.py              # Pydantic models (AssistRequest, KBEntryRequest, FeedbackRequest)
│   ├── logging.py              # ConsoleFormatter, JsonFormatter, console noise filters
│   ├── routes/
│   │   ├── assist.py           # POST /transcribe/, POST /assist/, GET /voices
│   │   ├── kb.py               # /kb/* CRUD, similarity sandbox, import/export, reload
│   │   ├── handoff.py          # /handoff/queue - inspection, replay, deletion
│   │   ├── analytics.py        # /stats, /analytics/summary, /kb/unmatched, feedback
│   │   ├── admin.py            # /kb-admin/login, /kb-admin/logout
│   │   └── health.py           # GET /health, root redirection
│   └── services/
│       ├── transcription.py    # AssemblyAI upload and polling service
│       ├── intent.py           # Regex-based intent classification
│       ├── rag.py              # Vector KB with SentenceTransformers & incremental cache
│       ├── llm.py              # Groq chat client with text normalization
│       ├── tts.py              # Groq Orpheus TTS, gTTS fallback, and audio pruning
│       ├── handoff.py          # Ticket dispatcher with retry backoff and queue
│       └── analytics.py        # In-memory counters, JSONL event logs, cost estimation
├── docs/
│   ├── api.md                  # Comprehensive REST API reference and payload schemas
│   ├── configuration.md        # Environment variables and configuration options
│   └── architecture.md         # Architecture, RAG internals, and project design (this file)
├── static/
│   ├── index.html              # Agent dashboard (cards & chat view, waveform, draft-edit)
│   ├── script.js               # Dashboard controller, microphone capture, MP3 encoding
│   ├── kb.html                 # Knowledge base curation manager and testing sandbox
│   ├── kb.js                   # KB management interface logic
│   ├── analytics.html          # Operational metrics and cost breakdown dashboard
│   ├── analytics.js            # Analytics graphs and data polling
│   ├── style.css               # Shared application styling and themes
│   ├── theme.js                # Theme switcher (dark / light mode persistence)
│   └── vendor/lame.all.js      # Client-side MP3 encoder library
├── tests/                      # 160+ offline unit and integration tests
├── audio_sample/               # Pre-recorded WAV/MP3 samples for local testing
├── knowledge_base.json         # Default knowledge base dataset
├── main.py                     # Entry point shim (`uvicorn main:app`)
├── Dockerfile                  # Production container definition (Python 3.10-slim)
├── docker-compose.yml          # Container configuration with volume caching
├── requirements.txt            # Pinned runtime dependencies
└── requirements-dev.txt        # Test dependencies (pytest, httpx)
```
