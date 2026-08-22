import time

import requests

from .. import config


class TranscriptionError(Exception):
    pass


class TranscriptionTimeout(TranscriptionError):
    pass


def _check(response: requests.Response, stage: str) -> dict:
    if response.status_code >= 400:
        raise TranscriptionError(
            f"AssemblyAI {stage} failed with status {response.status_code}: {response.text[:300]}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise TranscriptionError(f"AssemblyAI {stage} returned invalid JSON") from exc


def transcribe_file(path: str) -> str:
    headers = {"authorization": config.ASSEMBLYAI_API_KEY}

    with open(path, "rb") as f:
        upload_data = _check(
            requests.post(
                config.ASSEMBLYAI_UPLOAD_URL,
                headers=headers,
                files={"file": f},
                timeout=config.REQUEST_TIMEOUT_SEC * 2,
            ),
            "upload",
        )
    audio_url = upload_data.get("upload_url")
    if not audio_url:
        raise TranscriptionError("AssemblyAI upload response missing 'upload_url'")

    transcript_data = _check(
        requests.post(
            config.ASSEMBLYAI_TRANSCRIPT_URL,
            json={"audio_url": audio_url},
            headers=headers,
            timeout=config.REQUEST_TIMEOUT_SEC,
        ),
        "transcript creation",
    )
    transcript_id = transcript_data.get("id")
    if not transcript_id:
        raise TranscriptionError("AssemblyAI transcript creation response missing 'id'")

    polling_url = f"{config.ASSEMBLYAI_TRANSCRIPT_URL}/{transcript_id}"
    deadline = time.monotonic() + config.TRANSCRIPTION_TIMEOUT_SEC
    while True:
        status_data = _check(requests.get(polling_url, headers=headers, timeout=config.REQUEST_TIMEOUT_SEC), "polling")
        status = status_data.get("status")
        if status == "completed":
            return status_data["text"]
        if status == "error":
            raise TranscriptionError(f"Transcription failed: {status_data.get('error', 'unknown error')}")
        if time.monotonic() > deadline:
            raise TranscriptionTimeout(f"Transcription timed out after {config.TRANSCRIPTION_TIMEOUT_SEC}s (last status: {status})")
        time.sleep(config.TRANSCRIPTION_POLL_INTERVAL_SEC)
