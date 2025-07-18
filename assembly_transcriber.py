import requests
import time
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("ASSEMBLYAI_API_KEY")

transcription_endpoint = "https://api.assemblyai.com/v2/transcript"
upload_endpoint = "https://api.assemblyai.com/v2/upload"
headers = {'authorization': API_KEY}

def read_file(filename, chunk_size=5242880):
    with open(filename, 'rb') as f:
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            yield data

def upload_audio(file_path):
    print("Uploading audio...")
    response = requests.post(upload_endpoint,
                             headers=headers,
                             data=read_file(file_path))
    audio_url = response.json()['upload_url']
    print(f"Audio uploaded: {audio_url}")
    return audio_url

def transcribe(audio_url):
    json = { "audio_url": audio_url }
    response = requests.post(transcription_endpoint, json=json, headers=headers)
    transcript_id = response.json()['id']
    polling_endpoint = transcription_endpoint + "/" + transcript_id

    print("Transcribing...")
    while True:
        poll_response = requests.get(polling_endpoint, headers=headers)
        status = poll_response.json()['status']
        if status == 'completed':
            return poll_response.json()['text']
        elif status == 'error':
            raise Exception("Transcription failed:", poll_response.json()['error'])
        time.sleep(3)

if __name__ == "__main__":
    file_path = "sample_audio.wav"
    audio_url = upload_audio(file_path)
    transcript = transcribe(audio_url)
    print("\nFinal Transcript:\n", transcript)
