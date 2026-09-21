# Agent Assist & Resolution Bot

An intelligent, real-time customer support platform that transcribes live audio, classifies caller intent, retrieves context-aware answers from a semantic knowledge base (RAG), and autonomously resolves routine issues through a neural voice agent — escalating complex cases to human operators with full handoff context.

[![CI](https://github.com/GuptaAman12/agent-assist-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/GuptaAman12/agent-assist-bot/actions/workflows/ci.yml)
![Python 3.10](https://img.shields.io/badge/python-3.10-blue)
![FastAPI](https://img.shields.io/badge/framework-FastAPI-009688)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [Docker Deployment](#docker-deployment)
- [Configuration Reference](#configuration-reference)
- [API Reference](#api-reference)
- [Knowledge Base Management](#knowledge-base-management)
- [Logging & Observability](#logging--observability)
- [Testing](#testing)
- [Project Structure](#project-structure)
- [Contributing](#contributing)

---

## Overview

Agent Assist & Resolution Bot bridges the gap between fully automated voice bots and traditional ticket-based support. When a customer calls in or uploads a recording:

1. **Transcription** — Audio is transcribed in real time via AssemblyAI.
2. **Intent Classification** — Regex-based classifiers detect what the caller needs (password reset, refund, order tracking, etc.).
3. **Semantic Retrieval (RAG)** — The transcript is matched against a vector-embedded knowledge base using cosine similarity. Only results above a confidence threshold are used — the system never fabricates answers.
4. **LLM Response Generation** — Matched context is sent to a Groq-hosted LLM for natural, conversational response synthesis.
5. **AI Voice Takeover** — For automatable intents, a neural voice (Groq Orpheus) speaks the resolution directly to the caller.
6. **Human Handoff** — When the bot can't help or the caller asks for a person, a support ticket is created and dispatched via webhook, email, or disk queue.

The platform ships with three integrated web interfaces: an **agent dashboard** for live call handling, a **knowledge base manager** for content curation, and an **analytics dashboard** for usage and cost monitoring.

---

## Key Features

### Core Pipeline

| Capability | Description |
|---|---|
| **Audio Transcription** | Upload files (drag & drop, 17 formats) or record live from the microphone — recordings are MP3-encoded in-browser via lamejs |
| **Intent Detection** | Keyword-based classifier with left-boundary regex matching for natural language tolerance (handles plurals, verb forms) |
| **Semantic RAG** | `sentence-transformers` (`all-MiniLM-L6-v2`) with question+response joint embeddings, incremental re-encoding on changes |
| **Confidence Threshold** | Queries below `KB_MIN_SIMILARITY` (default 0.45) return an honest fallback instead of hallucinated answers |
| **Multi-topic Retrieval** | Mixed recordings pull top-k matching KB entries — every issue in a single call gets addressed from the knowledge base |
| **Multi-turn Memory** | The dashboard sends conversation history (up to 5 turns) so follow-up questions are answered from context |
| **LLM Generation** | Groq API (`openai/gpt-oss-20b`) with mojibake repair and spoken-output constraints |
| **Neural Voice Synthesis** | Groq Orpheus TTS with 6 voices, sentence-boundary chunking, WAV header normalization, and automatic gTTS fallback |
| **Human Handoff** | Webhook (3x retry with backoff), SMTP email, or disk queue — the dashboard shows ticket ID banners |

### Agent Dashboard

- **Dual View Modes** — Cards view (inspector cards with confidence, sources, audio) and Chat Stream view (conversational timeline with timestamps)
- **Voice Waveform Visualizer** — Real-time frequency animation on canvas during AI voice playback
- **Draft & Edit Mode** — Human-in-the-loop: agents can revise AI drafts in-place before sending
- **Sentiment Detection** — Automatic emotion classification (Satisfied 🟢, Neutral ⚪, Frustrated 🟠, Urgent 🔴)
- **Feedback Loop** — Thumbs up/down ratings logged to analytics for continuous improvement
- **Session Export** — One-click Markdown export of complete call transcripts
- **Autoplay & Mute** — Granular audio controls persisted in `localStorage`

### Knowledge Base Manager

- Full CRUD with inline editing, soft-delete with undo, and pagination
- **Live Similarity Sandbox** — Test queries against the KB in real time (`GET /kb/search`)
- **Unmatched Query Feed** — Surface below-threshold queries with one-click "Add to KB"
- Bulk JSON import/export, manual reload from disk
- Live system status indicator

### Analytics & Observability

- **Cost Dashboard** — Real-time estimates across LLM tokens, transcription hours, and TTS character volume
- **Audit Log** — Every admin KB write recorded with timestamp, request ID, and admin identity (`knowledge_base.log.jsonl`)
- **Usage Counters** — Process-local metrics served via `GET /stats` and `GET /analytics/summary`

### Security & Operations

- **Admin Auth** — Token-based authentication via header or HttpOnly session cookie
- **Rate Limiting** — Per-IP sliding window with `Retry-After` headers; proxy-aware via `X-Forwarded-For`
- **Upload Guards** — Extension allowlist (415) and size cap (413) enforced before any API call
- **TTS Pruning** — Automatic eviction of generated audio files by age and count
- **Hot-Reload KB** — Edit `knowledge_base.json` directly; changes apply on the next query without restart

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Client (Browser)                               │
│  ┌──────────────┐  ┌───────────────┐  ┌────────────────────────────┐   │
│  │  Dashboard    │  │  KB Manager   │  │  Analytics Dashboard       │   │
│  │  index.html   │  │  kb.html      │  │  analytics.html            │   │
│  └──────┬───────┘  └──────┬────────┘  └───────────┬────────────────┘   │
└─────────┼──────────────────┼──────────────────────┼────────────────────┘
          │                  │                      │
          ▼                  ▼                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        FastAPI Application                              │
│                                                                         │
│  Routes:  /transcribe/  /assist/  /kb/*  /handoff/*  /analytics/*      │
│                                                                         │
│  Middleware: request_context (X-Request-ID, access logs)                │
│              guard_admin_pages (auth gate on KB/analytics)              │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                         Services Layer                           │   │
│  │  ┌──────────────┐ ┌─────────┐ ┌─────────┐ ┌──────────────────┐ │   │
│  │  │ Transcription │ │  Intent │ │   RAG   │ │       LLM        │ │   │
│  │  │ (AssemblyAI)  │ │ Detect  │ │  (ST)   │ │   (Groq Chat)    │ │   │
│  │  └──────────────┘ └─────────┘ └─────────┘ └──────────────────┘ │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌────────────────────────┐  │   │
│  │  │     TTS      │ │   Handoff    │ │      Analytics         │  │   │
│  │  │(Orpheus/gTTS)│ │(Webhook/SMTP)│ │  (Counters + JSONL)    │  │   │
│  │  └──────────────┘ └──────────────┘ └────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  Data:  knowledge_base.json (RAG corpus, hot-reloadable)               │
│         *.log.jsonl (audit, analytics, handoff queue)                   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Component | Technology |
|---|---|
| **Backend** | [FastAPI](https://fastapi.tiangolo.com/) (Python 3.10) |
| **Transcription** | [AssemblyAI](https://www.assemblyai.com/) |
| **Embeddings & RAG** | [Sentence Transformers](https://www.sbert.net/) (`all-MiniLM-L6-v2`) + PyTorch |
| **LLM** | [Groq API](https://groq.com/) — `openai/gpt-oss-20b` |
| **Voice Synthesis** | [Groq Orpheus](https://console.groq.com/docs/text-to-speech) (`canopylabs/orpheus-v1-english`) with [gTTS](https://gtts.readthedocs.io/) fallback |
| **Audio Encoding** | [lamejs](https://github.com/zhuker/lamejs) (in-browser MP3 for mic recordings) |
| **Frontend** | Vanilla HTML/CSS/JS — no build step required |
| **CI/CD** | GitHub Actions (`.github/workflows/ci.yml`) |
| **Containerization** | Docker + Docker Compose |

---

## Getting Started

### Prerequisites

- Python 3.10+
- [AssemblyAI API key](https://www.assemblyai.com/dashboard/signup)
- [Groq API key](https://console.groq.com/keys)

### Installation

```bash
# Clone the repository
git clone https://github.com/GuptaAman12/agent-assist-bot.git
cd agent-assist-bot

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your API keys:
#   ASSEMBLYAI_API_KEY=your_key_here
#   GROQ_API_KEY=your_key_here

# Start the server
uvicorn main:app --reload
```

Open **http://127.0.0.1:8000/** to access the dashboard. The first startup downloads the `all-MiniLM-L6-v2` embedding model from HuggingFace (~90 MB), which may take a moment.

| Interface | URL |
|---|---|
| Agent Dashboard | http://127.0.0.1:8000/static/index.html |
| Knowledge Base Manager | http://127.0.0.1:8000/static/kb.html |
| Analytics Dashboard | http://127.0.0.1:8000/static/analytics.html |
| Interactive API Docs | http://127.0.0.1:8000/docs |

### Quick Test (No Microphone Required)

```bash
# Test the assist endpoint directly
curl -X POST http://127.0.0.1:8000/assist/ \
  -H "Content-Type: application/json" \
  -d '{"transcript": "How do I reset my password?", "intent": "password_reset"}'

# Test with a sample audio file
curl -X POST http://127.0.0.1:8000/transcribe/ \
  -F "file=@audio_sample/password_reset.wav"
```

Pre-recorded audio samples are included in `audio_sample/` for testing transcription and intent classification.

---

## Docker Deployment

### Docker Compose (Recommended)

```bash
docker compose up -d --build
```

This starts the application on port 8000 with `.env` keys injected at runtime and a persistent volume for the HuggingFace model cache. Open **http://localhost:8000/**.

### Manual Docker Build

```bash
docker build -t agent-assist-bot .
docker run -p 8000:8000 --env-file .env -v hf_cache:/app/.hf_cache agent-assist-bot
```

> **Security:** API keys are passed at runtime via `--env-file` and are never baked into the image. The container runs as a non-root `appuser` and includes a built-in healthcheck.

---

## Configuration Reference

All configuration is managed through environment variables (set in `.env`). A complete template is provided in `.env.example`.

### Required

| Variable | Description |
|---|---|
| `ASSEMBLYAI_API_KEY` | AssemblyAI API key for audio transcription |
| `GROQ_API_KEY` | Groq API key for LLM inference and TTS |

### Optional

| Variable | Default | Description |
|---|---|---|
| `ADMIN_TOKEN` | *(empty)* | When set, gates `/kb/*`, `/transcribe/`, and `/assist/` behind auth |
| `GROQ_MODEL` | `openai/gpt-oss-20b` | Chat completion model |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence Transformers model for RAG embeddings |
| `KB_MIN_SIMILARITY` | `0.45` | Cosine similarity threshold — below this, the bot declines to answer |
| `MAX_HISTORY_TURNS` | `5` | Number of conversation turns sent as LLM context |
| `GROQ_TTS_MODEL` | `canopylabs/orpheus-v1-english` | TTS model |
| `GROQ_TTS_VOICE` | `troy` | Default voice (`autumn`, `diana`, `hannah`, `austin`, `daniel`, `troy`) |
| `RATE_LIMIT_MAX_REQUESTS` | `20` | Max requests per IP per minute for `/assist/` |
| `RATE_LIMIT_MAX_TRANSCRIBE` | `10` | Max requests per IP per minute for `/transcribe/` |
| `TRUST_PROXY_HEADERS` | `false` | Honor `X-Forwarded-For` for rate limiting (enable only behind a trusted proxy) |
| `MAX_UPLOAD_BYTES` | `104857600` | Maximum upload size for `/transcribe/` (100 MB) |
| `AUDIO_TTL_SEC` | `86400` | Prune TTS audio files older than this (seconds) |
| `AUDIO_MAX_FILES` | `100` | Maximum TTS audio files to retain |
| `HANDOFF_WEBHOOK_URL` | *(empty)* | POST ticket JSON when a human agent is needed |
| `HANDOFF_EMAIL_TO` | *(empty)* | Fallback: send ticket via SMTP email |
| `LOG_FORMAT` | `console` | `console` for human-readable output, `json` for structured JSON |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `LOG_QUIET_STATIC` | `true` | Suppress successful static asset logs in console mode |
| `LOG_QUIET_HEALTH` | `true` | Suppress routine `/health` poll logs in console mode |

---

## API Reference

### Core Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/transcribe/` | Upload audio → returns `{transcript, intent}` |
| `POST` | `/assist/` | Submit transcript → returns `{response, ai_takeover, sources, audio_url, kb_score, handoff, ticket_id}` |
| `GET` | `/voices` | List available TTS voices |
| `GET` | `/health` | System health with per-service status |

### Knowledge Base

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/kb` | Paginated list (`?limit&offset&include_deleted`) |
| `GET` | `/kb/search?q=...` | Similarity test sandbox (bypasses threshold) |
| `POST` | `/kb` | Create entry `{question?, response}` |
| `PUT` | `/kb/{id}` | Update entry (re-embedded immediately) |
| `DELETE` | `/kb/{id}` | Soft-delete (returns `undo_token`) |
| `POST` | `/kb/{id}/restore` | Restore soft-deleted entry |
| `POST` | `/kb/reload` | Force re-read from `knowledge_base.json` |
| `GET` | `/kb/export` | Download KB as JSON file |
| `POST` | `/kb/import` | Replace all entries from JSON upload |

### Analytics & Handoff

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/stats` | Process-local usage counters |
| `GET` | `/analytics/summary` | Usage totals with cost estimates |
| `POST` | `/analytics/feedback` | Log thumbs-up/down rating |
| `GET` | `/kb/unmatched` | Below-threshold queries for KB curation |
| `GET` | `/handoff/queue` | Queued escalation tickets |
| `POST` | `/handoff/queue/replay` | Retry failed ticket delivery |
| `DELETE` | `/handoff/queue/{id}` | Dismiss a queued ticket |

### Admin

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/kb-admin/login` | Authenticate with `ADMIN_TOKEN`, sets HttpOnly cookie |
| `POST` | `/kb-admin/logout` | Clear admin session |

> **Error Responses:** All errors return `{"detail": "..."}` with appropriate HTTP status codes — `413` (upload too large), `415` (unsupported format), `429` (rate limited, includes `Retry-After` header), `502` (upstream API failure), `504` (transcription timeout).

### Request/Response Examples

**Assist Request:**
```json
{
  "transcript": "I need to reset my password and check my balance",
  "intent": "password_reset",
  "history": [
    {"transcript": "Hello, I need help", "response": "Of course! How can I assist you today?"}
  ]
}
```

**Assist Response:**
```json
{
  "response": "To reset your password, go to the login page and click 'Forgot Password'...",
  "ai_takeover": true,
  "source": "To reset your password...",
  "sources": [
    {"text": "To reset your password...", "score": 0.87},
    {"text": "Log into your account dashboard...", "score": 0.72}
  ],
  "audio_url": "/static/audio/ai_response_20260921_174512_a1b2c3d4.wav",
  "tts_engine": "orpheus",
  "kb_score": 0.87,
  "handoff": false,
  "ticket_id": null
}
```

---

## Knowledge Base Management

The knowledge base is stored in `knowledge_base.json` as a JSON array. Each entry contains:

```json
{
  "id": "e4d8d1bc",
  "question": "How do I reset my password?",
  "response": "To reset your password, go to the login page, click 'Forgot Password'..."
}
```

### How It Works

- **Embeddings** are computed as `question + "\n" + response` using `all-MiniLM-L6-v2`, so both the user's phrasing and the answer contribute to matching accuracy.
- **Incremental updates** — only new or modified entries are re-encoded; unchanged rows reuse cached vectors.
- **Hot reload** — the server checks file mtime on every query. External edits to `knowledge_base.json` take effect immediately.
- **Fail-safe** — invalid edits (malformed JSON, empty array) keep serving the last good state without crashing.
- **Stable IDs** — assigned once and persisted back to the file atomically via `tempfile` + `os.replace`.
- **Soft deletes** — entries are marked with `deleted_at` timestamps and can be restored via the API.

### Admin Authentication

When `ADMIN_TOKEN` is set in `.env`:

- All `/kb/*` API endpoints require the token via `X-Admin-Token` header or admin session cookie.
- `/static/kb.html` and `/static/analytics.html` display a login page for unauthenticated visitors.
- Sign in via the form (`POST /kb-admin/login` sets an HttpOnly cookie).
- When `ADMIN_TOKEN` is empty (local development), authentication is disabled.

---

## Logging & Observability

### Console Mode (Default)

Clean, human-readable one-line logs optimized for local development. Routine static asset requests and `/health` polls are filtered out automatically:

```
17:45:12 [INFO ] POST /transcribe/ -> 200 (340.5ms) [req=4b2c3d12]
17:45:13 [INFO ] POST /assist/     -> 200 (112.8ms) [req=5c3d4e34]
17:45:14 [INFO ] POST /assist/     -> 200 (105.2ms) [req=6d4e5f56, ticket_id=tkt_123]
```

### JSON Mode (Production)

Set `LOG_FORMAT=json` to emit structured JSON lines for log aggregators (Datadog, Loki, CloudWatch):

```json
{"ts": "2026-09-21T17:45:12.123+00:00", "level": "INFO", "logger": "app.access", "message": "request completed", "req_id": "4b2c3d12", "req_method": "POST", "req_path": "/transcribe/", "req_status": 200, "req_duration_ms": 340.5}
```

### Request Tracing

Every request is assigned a unique `req_id` and returned as the `X-Request-ID` HTTP header for end-to-end tracing. Access the current ID programmatically via `app.logging.get_request_id()`.

---

## Testing

```bash
# Install test dependencies
pip install -r requirements-dev.txt

# Run the full suite
python -m pytest -q
```

**163 tests** run fully offline — all external APIs (AssemblyAI, Groq) and the embedding model are mocked. The suite covers:

- Intent detection with word-boundary edge cases
- RAG retrieval: threshold behavior, incremental reload, question+response re-embedding, fail-open on broken files, ID stability
- TTS: Markdown stripping, WAV normalization, Orpheus/gTTS fallback, audio pruning
- API surface: upload guards (413/415), rate limiting with `Retry-After`, proxy header handling, admin auth
- Handoff: webhook retry, email fallback, disk queue
- Analytics: event logging, counters, feedback tracking
- Logging: ConsoleFormatter, JsonFormatter, noise filtering
- KB operations: CRUD, soft-delete/restore, import/export, audit log

CI runs the suite automatically on every push to `main` and on pull requests via [GitHub Actions](https://github.com/GuptaAman12/agent-assist-bot/actions).

---

## Project Structure

```
agent-assist-bot/
├── app/
│   ├── main.py                 # FastAPI app, lifespan, middleware, router registration
│   ├── config.py               # All env vars, paths, constants, intent keywords
│   ├── dependencies.py         # Auth, rate limiting, audit logging, admin sessions
│   ├── middleware.py            # Request context (X-Request-ID), access logs, admin page guard
│   ├── schemas.py              # Pydantic models (AssistRequest, KBEntryRequest, FeedbackRequest)
│   ├── logging.py              # ConsoleFormatter, JsonFormatter, noise filter, request ID contextvar
│   ├── routes/
│   │   ├── assist.py           # POST /transcribe/, POST /assist/, GET /voices
│   │   ├── kb.py               # /kb/* CRUD, search sandbox, import/export, reload
│   │   ├── handoff.py          # /handoff/queue — inspect, replay, delete
│   │   ├── analytics.py        # /stats, /analytics/summary, /kb/unmatched, feedback
│   │   ├── admin.py            # /kb-admin/login, /kb-admin/logout, session management
│   │   └── health.py           # GET /health, root redirect
│   └── services/
│       ├── transcription.py    # AssemblyAI upload + polling (sync)
│       ├── intent.py           # Regex-based intent classifier
│       ├── rag.py              # Hot-reloadable vector KB (SentenceTransformers + PyTorch)
│       ├── llm.py              # Groq chat client with mojibake repair
│       ├── tts.py              # Groq Orpheus TTS + gTTS fallback + WAV normalizer
│       ├── handoff.py          # Webhook/SMTP escalation with retry and disk queue
│       └── analytics.py        # In-memory counters, JSONL event logging, cost estimates
├── static/
│   ├── index.html              # Agent dashboard (dual view, waveform, sentiment, draft-edit)
│   ├── script.js               # Dashboard logic, mic recording, MP3 encoding, chat timeline
│   ├── kb.html                 # Knowledge base manager (search, test, import/export)
│   ├── kb.js                   # KB manager logic, pagination, unmatched feed
│   ├── analytics.html          # Usage & cost analytics dashboard
│   ├── analytics.js            # Analytics charts and data fetching
│   ├── style.css               # Shared styles, dark/light themes, responsive layout
│   ├── theme.js                # Theme persistence (localStorage + system preference)
│   └── vendor/lame.all.js      # In-browser MP3 encoder for mic recordings
├── tests/                      # 163 offline tests (mocked APIs, fake embedding model)
├── audio_sample/               # Pre-recorded test audio files
├── knowledge_base.json         # RAG corpus (17 entries, hot-reloadable)
├── main.py                     # Thin shim: `from app.main import app`
├── Dockerfile                  # Python 3.10-slim, CPU-only PyTorch, non-root user
├── docker-compose.yml          # One-command deployment with HF cache volume
├── .github/workflows/ci.yml   # GitHub Actions CI (pytest on every push)
├── requirements.txt            # Runtime dependencies (pinned)
└── requirements-dev.txt        # Test dependencies (pytest + httpx)
```

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes and ensure tests pass (`python -m pytest -q`)
4. Commit and push (`git push origin feature/my-feature`)
5. Open a Pull Request

Please ensure all existing tests continue to pass and add tests for new functionality.

---

Built with ❤️ by [Aman Gupta](https://github.com/GuptaAman12)
