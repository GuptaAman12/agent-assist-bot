# backend/main.py
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from assembly import upload_audio, get_transcript
from intent import detect_intent
import os

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Allow frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/transcribe/")
async def transcribe(file: UploadFile = File(...)):
    temp_path = f"temp_{file.filename}"
    with open(temp_path, "wb") as f:
        f.write(await file.read())

    audio_url = upload_audio(temp_path)
    transcript = get_transcript(audio_url)
    intent = detect_intent(transcript)

    os.remove(temp_path)
    return {"transcript": transcript, "intent": intent}
