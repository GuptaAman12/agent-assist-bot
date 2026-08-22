# 🧠 Agent Assist & Resolution Bot

A real-time customer support system that transcribes live audio, detects user intent, retrieves answers from a knowledge base (RAG), and for predefined issues, triggers an AI voice agent to take over.

---

## 🧩 Features

- 🔊 Upload `.wav` audio → get instant transcript.
- 🎯 Intent detection from the transcript.
- 🧠 Context-aware RAG (Retrieval-Augmented Generation) using `sentence-transformers` — knowledge-base embeddings are computed once at startup.
- 💬 Answer generation using **Groq** (`openai/gpt-oss-120b` by default, override with `GROQ_MODEL`).
- 🤖 AI takeover for simple intents like password resets and balance checks.
- 🔊 AI voice response generated via `gTTS` and playable in the browser.

## 🛠️ Tech Stack

| Feature                | Stack / API                                        |
|------------------------|----------------------------------------------------|
| Transcription          | [AssemblyAI](https://www.assemblyai.com)           |
| Embedding & RAG        | Sentence Transformers (`all-MiniLM-L6-v2`)         |
| LLM for Response       | [Groq API](https://groq.com/) - GPT-OSS 120B       |
| Voice Generation       | gTTS (Google Text-to-Speech)                       |
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
    └── tts.py             # gTTS wrapper
main.py                    # thin shim so `uvicorn main:app` works
static/                    # frontend + generated audio responses
knowledge_base.json        # RAG corpus
```

## 🔌 API

| Endpoint             | Body                        | Returns                                                      |
|----------------------|-----------------------------|--------------------------------------------------------------|
| `POST /transcribe/`  | multipart `.wav` upload     | `{transcript, intent}`                                       |
| `POST /assist/`      | `{transcript, intent}` JSON | `{response, ai_takeover, source, audio_url}`                 |
| `GET /health`        | –                           | `{"status": "ok"}`                                           |

Errors return a JSON `{"detail": "..."}` with an appropriate status code (502 for upstream API failures, 504 for transcription timeouts).
