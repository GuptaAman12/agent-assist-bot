# API Reference

Agent Assist & Resolution Bot provides REST endpoints for real-time transcription, AI resolution, knowledge base management, analytics, and admin tasks.

Interactive documentation with live testing is available locally when the application is running:
- **Swagger UI:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc:** [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

---

## Authentication

When `ADMIN_TOKEN` is configured in `.env`, sensitive endpoints (`/kb/*`, `/kb-admin/*`, `/stats`, `/analytics/summary`, etc.) require authentication.

Authentication is accepted via either:
1. **Header:** `X-Admin-Token: <your_token>`
2. **Session Cookie:** `admin_token=<session_id>` (obtained via `POST /kb-admin/login`)

When `ADMIN_TOKEN` is left empty (local development), authentication is disabled and endpoints are accessible.

---

## Error Responses

All error responses return a JSON body with a standard `detail` field:

```json
{
  "detail": "Descriptive error message"
}
```

| HTTP Status | Reason | Notes |
|---|---|---|
| `400 Bad Request` | Invalid payload or missing parameters | Check payload structure |
| `401 Unauthorized` | Missing or invalid admin token | Set `X-Admin-Token` or log in |
| `404 Not Found` | Resource / KB entry not found | Verify ID or query |
| `413 Payload Too Large` | Uploaded audio file exceeds limit | Configured via `MAX_UPLOAD_BYTES` (default 100 MB) |
| `415 Unsupported Media Type` | File extension not allowed | Supported: 17 formats (mp3, wav, m4a, ogg, etc.) |
| `429 Too Many Requests` | IP rate limit exceeded | Response includes `Retry-After` header with wait seconds |
| `502 Bad Gateway` | Upstream service failure | AssemblyAI or Groq API connection issue |
| `504 Gateway Timeout` | Upstream transcription timeout | Audio processing exceeded timeout limit |

---

## Core Endpoints

### 1. Audio Transcription

Upload an audio file or microphone recording for transcription and intent classification.

- **URL:** `POST /transcribe/`
- **Content-Type:** `multipart/form-data`
- **Body:** `file` (Binary audio file)
- **Response:** `200 OK`

```json
{
  "transcript": "I forgot my password and cannot sign in.",
  "intent": "password_reset"
}
```

### 2. Resolution Assist

Submit transcript text (and optional conversation history) for RAG matching, LLM response synthesis, and optional voice audio generation.

- **URL:** `POST /assist/`
- **Content-Type:** `application/json`
- **Body:**
```json
{
  "transcript": "I need to reset my password and check my balance",
  "intent": "password_reset",
  "history": [
    {
      "transcript": "Hello, I need help with my account",
      "response": "Of course! How can I assist you today?"
    }
  ]
}
```
- **Response:** `200 OK`
```json
{
  "response": "To reset your password, visit the login page and click 'Forgot Password'. Follow the email verification link sent to your registered address.",
  "ai_takeover": true,
  "source": "To reset your password, visit the login page...",
  "sources": [
    {
      "text": "To reset your password, visit the login page...",
      "score": 0.87
    },
    {
      "text": "Log into your account dashboard to view balance...",
      "score": 0.72
    }
  ],
  "audio_url": "/static/audio/ai_response_20260921_174512_a1b2c3d4.wav",
  "tts_engine": "orpheus",
  "kb_score": 0.87,
  "handoff": false,
  "ticket_id": null
}
```

*Note:* If `handoff` is `true`, `ticket_id` will contain the generated handoff ticket reference.

### 3. TTS Voices

List available neural voices for text-to-speech.

- **URL:** `GET /voices`
- **Response:** `200 OK`
```json
{
  "voices": ["autumn", "diana", "hannah", "austin", "daniel", "troy"],
  "default": "troy"
}
```

### 4. System Health

Check service health and operational statuses.

- **URL:** `GET /health`
- **Response:** `200 OK`
```json
{
  "status": "healthy",
  "kb_entries": 17,
  "models": {
    "embedding": "loaded",
    "llm": "configured",
    "transcription": "configured"
  }
}
```

---

## Knowledge Base Endpoints

Manage semantic knowledge base entries. Requires admin authentication if `ADMIN_TOKEN` is set.

| Method | Endpoint | Description | Query / Body |
|---|---|---|---|
| `GET` | `/kb` | List knowledge base entries | `?limit=50&offset=0&include_deleted=false` |
| `GET` | `/kb/search` | Similarity test sandbox (bypasses threshold) | `?q=how+to+cancel+order` |
| `POST` | `/kb` | Add new KB entry | `{"question": "...", "response": "..."}` |
| `PUT` | `/kb/{id}` | Update existing entry (triggers re-encode) | `{"question": "...", "response": "..."}` |
| `DELETE` | `/kb/{id}` | Soft-delete entry (returns undo token) | None |
| `POST` | `/kb/{id}/restore` | Restore soft-deleted entry | None |
| `POST` | `/kb/reload` | Force reload from disk `knowledge_base.json` | None |
| `GET` | `/kb/export` | Download complete KB as JSON file | None |
| `POST` | `/kb/import` | Replace entire KB via JSON array upload | Multipart `file` or raw JSON |

### Example: Search Sandbox (`GET /kb/search?q=reset+password`)

Returns the top matches and cosine similarity scores even if they fall below the active confidence threshold:

```json
{
  "query": "reset password",
  "matches": [
    {
      "id": "e4d8d1bc",
      "question": "How do I reset my password?",
      "response": "To reset your password...",
      "score": 0.892,
      "above_threshold": true
    }
  ]
}
```

---

## Analytics & Handoff Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/stats` | Process-local real-time counters (admin gated) |
| `GET` | `/analytics/summary` | Aggregated usage totals with estimated costs (admin gated) |
| `POST` | `/analytics/feedback` | Record user feedback (`{"rating": "up" \| "down", "transcript": "...", "response": "..."}`) |
| `GET` | `/kb/unmatched` | Below-threshold queries for KB curation and training |
| `GET` | `/handoff/queue` | Inspect queued human handoff tickets |
| `POST` | `/handoff/queue/replay` | Retry delivery of queued handoff tickets |
| `DELETE` | `/handoff/queue/{id}` | Dismiss or archive a queued ticket |

---

## Admin Session Endpoints

| Method | Endpoint | Description | Payload |
|---|---|---|---|
| `POST` | `/kb-admin/login` | Authenticate and obtain HttpOnly session cookie | `{"token": "your_admin_token"}` |
| `POST` | `/kb-admin/logout` | Invalidate session cookie | None |
