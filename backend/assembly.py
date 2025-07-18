# backend/assembly.py
import requests
import time
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("ASSEMBLYAI_API_KEY")
headers = {'authorization': API_KEY}
transcription_endpoint = "https://api.assemblyai.com/v2/transcript"
upload_endpoint = "https://api.assemblyai.com/v2/upload"

def read_file(filename, chunk_size=5242880):
    with open(filename, 'rb') as f:
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            yield data

def upload_audio(file_path):
    response = requests.post(upload_endpoint, headers=headers, data=read_file(file_path))
    return response.json()['upload_url']

def get_transcript(audio_url):
    response = requests.post(transcription_endpoint, json={"audio_url": audio_url}, headers=headers)
    transcript_id = response.json()['id']
    polling_url = transcription_endpoint + "/" + transcript_id

    while True:
        poll = requests.get(polling_url, headers=headers)
        status = poll.json()['status']
        if status == 'completed':
            return poll.json()['text']
        elif status == 'error':
            raise Exception(poll.json()['error'])
        time.sleep(2)
