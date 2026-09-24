# Configuration Reference

All settings in Agent Assist & Resolution Bot are managed via environment variables (typically defined in a root `.env` file). A complete starting template is provided in [`.env.example`](../.env.example).

---

## Required Settings

The application will fail fast on startup if these keys are missing:

| Variable | Description |
|---|---|
| `ASSEMBLYAI_API_KEY` | AssemblyAI API key used for audio upload and asynchronous transcription. |
| `GROQ_API_KEY` | Groq API key used for fast LLM response generation and neural voice synthesis (Orpheus). |

---

## Optional Settings

### Authentication & Admin

| Variable | Default | Description |
|---|---|---|
| `ADMIN_TOKEN` | *(empty)* | Shared secret token. When set, all `/kb/*`, `/stats`, and `/analytics/summary` endpoints require authentication via `X-Admin-Token` header or session cookie. When empty, authentication is disabled (ideal for local testing). |

### Models & RAG Engine

| Variable | Default | Description |
|---|---|---|
| `GROQ_MODEL` | `openai/gpt-oss-20b` | LLM model identifier for Groq Chat Completion. |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | HuggingFace SentenceTransformer model used for embedding knowledge base entries and query matching. |
| `KB_MIN_SIMILARITY` | `0.45` | Minimum cosine similarity score (0.0 to 1.0) required to consider a KB match valid. Queries below this threshold trigger polite fallback responses rather than hallucinations. |
| `MAX_HISTORY_TURNS` | `5` | Maximum number of conversational dialogue turns passed as context to the LLM during multi-turn exchanges. |

### Voice Synthesis (TTS)

| Variable | Default | Description |
|---|---|---|
| `GROQ_TTS_MODEL` | `canopylabs/orpheus-v1-english` | Groq Orpheus neural text-to-speech model. |
| `GROQ_TTS_VOICE` | `troy` | Default neural voice choice (`autumn`, `diana`, `hannah`, `austin`, `daniel`, `troy`). |
| `AUDIO_TTL_SEC` | `86400` | Lifetime in seconds (default 24h) before generated TTS audio files in `static/audio/` are automatically evicted. Set to `<= 0` to disable age eviction. |
| `AUDIO_MAX_FILES` | `100` | Maximum number of generated audio files to keep on disk. Oldest files are pruned when this limit is exceeded. |

### Network & Rate Limiting

| Variable | Default | Description |
|---|---|---|
| `RATE_LIMIT_MAX_REQUESTS` | `20` | Maximum requests allowed per IP address per minute for the `/assist/` endpoint. |
| `RATE_LIMIT_MAX_TRANSCRIBE`| `10` | Maximum audio transcription requests allowed per IP address per minute. |
| `TRUST_PROXY_HEADERS` | `false` | When `true`, respects `X-Forwarded-For` headers to determine the client IP address. Only enable if running behind a trusted reverse proxy (NGINX, Cloudflare, Traefik). |
| `MAX_UPLOAD_BYTES` | `104857600` | Maximum allowed audio upload payload size (100 MB). Evaluated before processing to prevent memory exhaustion. |

### Human Escalation & Handoff

| Variable | Default | Description |
|---|---|---|
| `HANDOFF_WEBHOOK_URL` | *(empty)* | HTTPS endpoint to dispatch JSON tickets to when an escalation or human handoff is requested. Automatically retries 3 times with exponential backoff. |
| `HANDOFF_EMAIL_TO` | *(empty)* | Email address for ticket delivery fallback if no webhook is configured. Uses SMTP settings below. |
| `SMTP_HOST` | *(empty)* | SMTP server hostname for email delivery. |
| `SMTP_PORT` | `587` | SMTP server port. |
| `SMTP_USER` | *(empty)* | SMTP username. |
| `SMTP_PASSWORD` | *(empty)* | SMTP password. |
| `SMTP_FROM` | *(empty)* | Sender email address. |

### Logging & Diagnostics

| Variable | Default | Description |
|---|---|---|
| `LOG_FORMAT` | `console` | `console` for colorized, human-readable terminal output; `json` for structured JSONL logs suitable for production log collectors. |
| `LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `LOG_QUIET_STATIC` | `true` | Suppresses routine 2xx static file access logs in console mode to prevent noise. |
| `LOG_QUIET_HEALTH` | `true` | Suppresses repetitive 200 responses from `/health` uptime pollers in console mode. |
