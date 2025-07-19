import os
import json
import requests
from fastapi import FastAPI, File, UploadFile, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")

app = FastAPI()

# Mount frontend assets
app.mount("/static", StaticFiles(directory="frontend"), name="static")
templates = Jinja2Templates(directory="frontend")

# Load knowledge base
with open("backend/knowledge_base.json", "r") as f:
    knowledge_base = json.load(f)

# Intents eligible for AI takeover
simple_intents = ["password_reset", "check_balance"]

@app.get("/", response_class=HTMLResponse)
async def serve_ui(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

def transcribe_audio(file_path):
    headers = {'authorization': ASSEMBLYAI_API_KEY}
    upload_url = "https://api.assemblyai.com/v2/upload"

    with open(file_path, 'rb') as f:
        response = requests.post(upload_url, headers=headers, files={'file': f})
    audio_url = response.json()['upload_url']

    transcript_req = {"audio_url": audio_url}
    transcript_res = requests.post(
        "https://api.assemblyai.com/v2/transcript",
        json=transcript_req,
        headers=headers
    )
    transcript_id = transcript_res.json()['id']

    polling_url = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"
    while True:
        status_res = requests.get(polling_url, headers=headers)
        status = status_res.json()
        if status['status'] == 'completed':
            return status['text']
        elif status['status'] == 'error':
            raise Exception("Transcription failed")

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
    for entry in knowledge_base:
        if entry["intent"] == request.intent:
            return {
                "response": entry["response"],
                "ai_takeover": request.intent in simple_intents
            }
    return {"response": "Sorry, no info found", "ai_takeover": False}