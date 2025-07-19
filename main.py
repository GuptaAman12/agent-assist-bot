# File: main.py
import os
import json
import requests
import time
from fastapi import FastAPI, File, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer, util
from gtts import gTTS
from datetime import datetime

load_dotenv()

ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

with open("knowledge_base.json", "r") as f:
    knowledge_base = json.load(f)

model = SentenceTransformer("all-MiniLM-L6-v2")
simple_intents = ["password_reset", "check_balance"]


def transcribe_audio(file_path):
    headers = {'authorization': ASSEMBLYAI_API_KEY}
    with open(file_path, 'rb') as f:
        upload_res = requests.post("https://api.assemblyai.com/v2/upload", headers=headers, files={'file': f})
    audio_url = upload_res.json()['upload_url']

    transcript_res = requests.post("https://api.assemblyai.com/v2/transcript",
                                   json={"audio_url": audio_url}, headers=headers)
    transcript_id = transcript_res.json()['id']
    polling_url = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"

    while True:
        status_res = requests.get(polling_url, headers=headers).json()
        if status_res['status'] == 'completed':
            return status_res['text']
        elif status_res['status'] == 'error':
            raise Exception("Transcription failed")
        time.sleep(2)


@app.post("/transcribe/")
async def transcribe(file: UploadFile = File(...)):
    contents = await file.read()
    temp_path = "temp.wav"
    with open(temp_path, "wb") as f:
        f.write(contents)

    transcript = transcribe_audio(temp_path)

    intent = "unknown"
    if "password" in transcript.lower():
        intent = "password_reset"
    elif "balance" in transcript.lower():
        intent = "check_balance"
    elif "address" in transcript.lower():
        intent = "update_address"

    return {"transcript": transcript, "intent": intent}


class TranscriptionRequest(BaseModel):
    transcript: str
    intent: str


@app.post("/assist/")
def assist_agent(request: TranscriptionRequest):
    query = request.transcript
    query_embedding = model.encode(query, convert_to_tensor=True)
    kb_texts = [entry["response"] for entry in knowledge_base]
    kb_embeddings = model.encode(kb_texts, convert_to_tensor=True)

    scores = util.pytorch_cos_sim(query_embedding, kb_embeddings)[0]
    top_idx = scores.argmax().item()
    top_entry = knowledge_base[top_idx]
    context = top_entry["response"]

    generated_response = generate_with_groq(context, query)
    ai_takeover = request.intent in simple_intents

    audio_path = None
    if ai_takeover:
        audio_path = text_to_speech(generated_response)

    return {
        "response": generated_response,
        "ai_takeover": ai_takeover,
        "source": context,
        "audio_url": f"/static/{audio_path}" if audio_path else None
    }


def generate_with_groq(context, query):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama3-70b-8192",  # ✅ most stable and powerful
        "messages": [
            {"role": "system", "content": "You are a helpful support assistant."},
            {"role": "user", "content": f"Context: {context}\n\nQuery: {query}"}
        ]
    }
    res = requests.post(url, headers=headers, json=payload)
    return res.json()['choices'][0]['message']['content'].strip()


def text_to_speech(text):
    tts = gTTS(text)
    filename = f"ai_response_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
    path = os.path.join("static", filename)
    tts.save(path)
    return filename
