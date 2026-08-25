# 🧠 Agent Assist & Resolution Bot

A real-time customer support system that transcribes live audio, detects user intent, retrieves answers from a knowledge base (RAG), and for predefined issues, lets an AI voice agent take over and speak the resolution.

---

## 🧩 Features

- 🔊 Upload `.wav` audio (or drag & drop) → instant transcript via AssemblyAI.
- 🎯 Intent detection from the transcript (password reset, refunds, order tracking…).
- 🧠 Context-aware RAG using `sentence-transformers` - knowledge-base embeddings are computed once at startup.
- 📝 **Hot-reloadable knowledge base** - add/remove entries from the dashboard or edit `knowledge_base.json` directly; changes apply without restarting (invalid edits keep serving the last good state).
- 💬 Answer generation using **Groq** (`openai/gpt-oss-120b` by default).
- 🤖 AI takeover: simple intents are answered aloud by a realistic neural voice (**Groq Orpheus**), with automatic gTTS fallback.
- 🖥️ Modern dashboard: light/dark mode, session history, markdown-rendered responses, live API status, copy-to-clipboard.

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

3. **Create a `.env` file:**

   ```
   ASSEMBLYAI_API_KEY=your_assembly_ai_key
   GROQ_API_KEY=your_groq_api_key
   ```

   Optional overrides:

   ```
   GROQ_MODEL=openai/gpt-oss-120b        # chat model
   EMBEDDING_MODEL=all-MiniLM-L6-v2      # sentence-transformers model
   GROQ_TTS_MODEL=canopylabs/orpheus-v1-english
   GROQ_TTS_VOICE=troy                   # autumn/diana/hannah/austin/daniel/troy
   ```

4. **Run the server**

   ```
   uvicorn main:app --reload
   ```

5. Open 👉 http://127.0.0.1:8000/ (redirects to the UI)

The first startup downloads the `all-MiniLM-L6-v2` embedding model from HuggingFace, so it can take a while. Interactive API docs are at `/docs`.

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
static/                    # frontend + generated audio responses
knowledge_base.json        # RAG corpus
```

## 🔌 API

| Endpoint             | Body                        | Returns                                                      |
|----------------------|-----------------------------|--------------------------------------------------------------|
| `POST /transcribe/`  | multipart `.wav` upload     | `{transcript, intent}`                                       |
| `POST /assist/`      | `{transcript, intent}` JSON | `{response, ai_takeover, source, audio_url, tts_engine}`     |
| `GET /health`        | –                           | `{"status": "ok"}`                                           |
| `GET /kb`            | –                           | `{count, entries: [{id, question, response}]}`               |
| `POST /kb`           | `{question?, response}`     | created entry                                                |
| `DELETE /kb/{id}`    | –                           | `{deleted, count}`                                           |
| `POST /kb/reload`    | –                           | `{reloaded, count}`                                          |

`audio_url` is set only when `ai_takeover` is true (the response is spoken). Errors return a JSON `{"detail": "..."}` with an appropriate status code (502 for upstream API failures, 504 for transcription timeouts). KB entries can also be edited by modifying `knowledge_base.json` directly — the server detects the change and re-embeds on the next request.

### Test without a microphone

```bash
curl -X POST http://127.0.0.1:8000/assist/ \
  -H "Content-Type: application/json" \
  -d '{"transcript": "How do I reset my password?", "intent": "password_reset"}'
```

Then open the returned `audio_url`. Sample recordings for `/transcribe/` are in `audio_sample/`.
