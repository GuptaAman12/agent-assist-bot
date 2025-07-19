import os
import json
import requests
from fastapi import FastAPI, File, UploadFile
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")

app = FastAPI()

# Load knowledge base
with open("knowledge_base.json", "r") as f:
    knowledge_base = json.load(f)

# Simple intents for AI voice takeover
simple_intents = ["password_reset", "check_balance"]

def transcribe_audio(file_path):
    headers = {'authorization': ASSEMBLYAI_API_KEY}
    upload_url = "https://api.assemblyai.com/v2/upload"

    # Upload file
    with open(file_path, 'rb') as f:
        response = requests.post(upload_url, headers=headers, files={'file': f})
    audio_url = response.json()['upload_url']

    # Request transcription
    transcript_req = {"audio_url": audio_url}
    transcript_res = requests.post(
        "https://api.assemblyai.com/v2/transcript",
        json=transcript_req,
        headers=headers
    )
    transcript_id = transcript_res.json()['id']

    # Poll until complete
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

    # Basic intent detection
    intent = ""
    if "password" in transcript.lower():
        intent = "password_reset"
    elif "balance" in transcript.lower():
        intent = "check_balance"
    elif "address" in transcript.lower():
        intent = "update_address"
    else:
        intent = "unknown"

    return {"transcript": transcript, "intent": intent}


class TranscriptionRequest(BaseModel):
    transcript: str
    intent: str

@app.post("/assist/")
def assist_agent(request: TranscriptionRequest):
    for entry in knowledge_base:
        if entry["intent"] == request.intent:
            response = entry["response"]
            ai_takeover = request.intent in simple_intents
            return {
                "response": response,
                "ai_takeover": ai_takeover
            }
    return {"response": "Sorry, no info found", "ai_takeover": False}
