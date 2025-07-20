# 🧠 Agent Assist & Resolution Bot

A real-time customer support system that transcribes live audio, detects user intent, retrieves answers from a knowledge base (RAG), and for predefined issues, triggers an AI voice agent to take over.

---

## 🧩 Features

- 🔊 Upload `.wav` audio → get instant transcript.
- 🧠 Context-aware RAG (Retrieval-Augmented Generation) using `sentence-transformers`.
- 💬 Answer generation using **Groq’s Llama3** model.
- 🎯 AI takeover for simple intents like password resets.
- 🔊 AI voice response generated via `gTTS` and downloadable.

---

## 🛠️ Tech Stack

| Feature                | Stack / API                              |
|------------------------|-------------------------------------------|
| Transcription          | [AssemblyAI](https://www.assemblyai.com) |
| Embedding & RAG        | Sentence Transformers (`MiniLM-L6`)      |
| LLM for Response       | [Groq API](https://groq.com/) - Mixtral   |
| Voice Generation       | gTTS (Google Text-to-Speech)             |
| Backend Framework      | FastAPI                                  |
| Frontend               | HTML + CSS + JS                          |

---

## 📦 Installation

1. **Clone this repo**

git clone https://github.com/yourusername/agent-assist-bot

cd agent-assist-bot

2. **Install dependencies**

pip install -r requirements.txt

3. **Create a .env file:**

ASSEMBLYAI_API_KEY=your_assembly_ai_key

GROQ_API_KEY=your_groq_api_key

4. **Run the server**

uvicorn main:app --reload

Visit 👉 http://127.0.0.1:8000/static/index.html
