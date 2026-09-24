# Agent Assist & Resolution Bot

An intelligent, real-time customer support platform that transcribes live audio, classifies caller intent, retrieves context-aware answers from a semantic knowledge base (RAG), and autonomously resolves routine issues through a neural voice agent - escalating complex cases to human operators with full context.

[![CI](https://github.com/GuptaAman12/agent-assist-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/GuptaAman12/agent-assist-bot/actions/workflows/ci.yml)
![Python 3.10](https://img.shields.io/badge/python-3.10-blue)
![FastAPI](https://img.shields.io/badge/framework-FastAPI-009688)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Overview

Agent Assist & Resolution Bot bridges the gap between automated voice bots and traditional support ticketing. When a customer speaks or uploads an audio query:

1. **Transcription** - Audio is transcribed in real-time via AssemblyAI (or browser-encoded MP3).
2. **Intent Classification** - Regex classifiers determine customer intent (password reset, order tracking, refund, etc.).
3. **Semantic Retrieval (RAG)** - Queries are matched against vector embeddings (`all-MiniLM-L6-v2`). Matches below confidence thresholds trigger polite fallback rather than hallucinations.
4. **Conversational Synthesis** - Context-grounded responses are generated via Groq LLM (`openai/gpt-oss-20b`).
5. **Neural Voice Takeover** - Automatable inquiries are spoken directly to the caller via Groq Orpheus TTS.
6. **Human Escalation** - Complex or sensitive cases dispatch structured tickets with transcripts via webhook or SMTP.

The platform provides three integrated web portals:
- **Agent Dashboard:** Live call handling, dual card/stream views, draft-and-edit, sentiment pills, and audio visualizer.
- **Knowledge Base Manager:** Visual CRUD, live similarity sandbox, unmatched query curation, and instant hot-reload.
- **Analytics Dashboard:** Real-time usage counters, cost estimates, and caller feedback tracking.

---

## Architecture Overview

```
[Audio / Mic] ──► [Transcribe (AssemblyAI)] ──► [Intent Classifier]
                                                        │
┌───────────────────────────────────────────────────────┘
▼
[RAG Similarity Search]
  ├── Score >= KB_MIN_SIMILARITY ──► [LLM Answer Synthesis] ──► [Takeover Voice (TTS)]
  └── Score < KB_MIN_SIMILARITY  ──► [Polite Fallback]       ──► [Human Escalation Ticket]
```

> 📖 **Deep Dive:** For detailed system diagrams, incremental caching details, and lifecycle mechanics, see the [Architecture Documentation](docs/architecture.md).

---

## Quick Start

### Prerequisites

- Python 3.10+
- [AssemblyAI API key](https://www.assemblyai.com/dashboard/signup)
- [Groq API key](https://console.groq.com/keys)

### Local Setup

```bash
# 1. Clone repository
git clone https://github.com/GuptaAman12/agent-assist-bot.git
cd agent-assist-bot

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure API keys
cp .env.example .env
# Edit .env and supply ASSEMBLYAI_API_KEY and GROQ_API_KEY

# 4. Start application
uvicorn main:app --reload
```

Open **http://127.0.0.1:8000/** in your browser. *(Note: Initial startup downloads the ~90 MB embedding model to cache).*

### Web Interfaces

| Interface | URL | Description |
|---|---|---|
| **Agent Dashboard** | `http://127.0.0.1:8000/` | Main operator workspace (root redirects here) |
| **KB Manager** | `http://127.0.0.1:8000/static/kb.html` | Knowledge base search, test sandbox, and editor |
| **Analytics** | `http://127.0.0.1:8000/static/analytics.html` | Usage metrics, cost estimates, and feedback |
| **Interactive API Docs** | `http://127.0.0.1:8000/docs` | Swagger UI with live endpoint testing |

### Quick API Test

```bash
# Test assist resolution directly
curl -X POST http://127.0.0.1:8000/assist/ \
  -H "Content-Type: application/json" \
  -d '{"transcript": "How do I reset my password?", "intent": "password_reset"}'
```

---

## Docker Deployment

Run the complete stack with persistent model caching in a single command:

```bash
docker compose up -d --build
```

Access the dashboard at **http://localhost:8000/**. API keys in `.env` are injected safely at runtime, and the container runs under a non-root `appuser`.

---

## Documentation

Full documentation is organized into focused reference guides:

| Guide | Description |
|---|---|
| 📡 **[API Reference](docs/api.md)** | Endpoints (`/transcribe/`, `/assist/`, `/kb/*`), schemas, and error codes. |
| ⚙️ **[Configuration Reference](docs/configuration.md)** | All environment variables, rate limits, proxy settings, and audio pruning rules. |
| 🏗️ **[Architecture & Design](docs/architecture.md)** | End-to-end pipeline, RAG caching, hot reload mechanics, and full project structure. |

---

## Testing

The test suite runs **100% offline** with mocked external services:

```bash
# Install test dependencies
pip install -r requirements-dev.txt

# Run pytest
python -m pytest -q
```

Automated CI runs on every commit via [GitHub Actions](https://github.com/GuptaAman12/agent-assist-bot/actions).

---

## High-Level Repository Layout

```
agent-assist-bot/
├── app/               # FastAPI application, routers, pipeline services, and middleware
├── docs/              # Detailed API, configuration, and architecture documentation
├── static/            # Frontend dashboards (HTML/CSS/JS) and browser MP3 encoder
├── tests/             # Offline unit and integration test suite (160+ tests)
├── audio_sample/      # Sample audio files for manual testing
├── knowledge_base.json# Semantic RAG knowledge base dataset
├── Dockerfile         # Production container definition
└── docker-compose.yml # Docker Compose specification with HF cache volume
```

*(See [docs/architecture.md](docs/architecture.md#complete-project-structure) for the complete file-by-file tree).*

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make changes and verify test pass (`python -m pytest -q`)
4. Submit a Pull Request

---

Built by [Aman Gupta](https://github.com/GuptaAman12)
