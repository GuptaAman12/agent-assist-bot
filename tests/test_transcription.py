import time

import pytest
import requests

from app.services import transcription
from app.services.transcription import TranscriptionError, TranscriptionTimeout


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text or str(payload)

    def json(self):
        return self._payload


def _ok_response(payload):
    return FakeResponse(200, payload)


def test_success_flow(monkeypatch, tmp_path):
    path = tmp_path / "a.wav"
    path.write_bytes(b"RIFF")

    responses = iter([
        _ok_response({"upload_url": "https://x/audio"}),
        _ok_response({"id": "t1"}),
        _ok_response({"status": "completed", "text": "hello world"}),
    ])

    def fake_post(*args, **kwargs):
        return next(responses)

    def fake_get(*args, **kwargs):
        return next(responses)

    monkeypatch.setattr(transcription.requests, "post", fake_post)
    monkeypatch.setattr(transcription.requests, "get", fake_get)
    assert transcription.transcribe_file(str(path)) == "hello world"


def test_upload_network_error(monkeypatch, tmp_path):
    path = tmp_path / "a.wav"
    path.write_bytes(b"RIFF")

    def fake_post(*args, **kwargs):
        raise requests.ConnectionError("no route")

    monkeypatch.setattr(transcription.requests, "post", fake_post)
    with pytest.raises(TranscriptionError):
        transcription.transcribe_file(str(path))


def test_upload_http_error(monkeypatch, tmp_path):
    path = tmp_path / "a.wav"
    path.write_bytes(b"RIFF")

    monkeypatch.setattr(transcription.requests, "post",
                        lambda *a, **k: FakeResponse(401, text="unauthorized"))
    with pytest.raises(TranscriptionError):
        transcription.transcribe_file(str(path))


def test_polling_network_error(monkeypatch, tmp_path):
    path = tmp_path / "a.wav"
    path.write_bytes(b"RIFF")
    monkeypatch.setattr(transcription.requests, "post",
                        lambda *a, **k: _ok_response({"upload_url": "u"}))
    responses = iter([
        _ok_response({"id": "t1"}),
        requests.ConnectionError("drop"),
    ])

    def fake_get(*args, **kwargs):
        r = next(responses)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(transcription.requests, "get", fake_get)
    with pytest.raises(TranscriptionError):
        transcription.transcribe_file(str(path))


def _post_sequence(*responses):
    """requests.post is called twice (upload, then transcript creation)."""
    seq = list(responses)

    def fake_post(*args, **kwargs):
        return seq.pop(0)

    return fake_post


def test_transcription_status_error(monkeypatch, tmp_path):
    path = tmp_path / "a.wav"
    path.write_bytes(b"RIFF")
    monkeypatch.setattr(
        transcription.requests,
        "post",
        _post_sequence(
            _ok_response({"upload_url": "u"}),
            _ok_response({"id": "t1"}),
        ),
    )
    monkeypatch.setattr(transcription.requests, "get",
                        lambda *a, **k: _ok_response({"status": "error", "error": "bad audio"}))
    with pytest.raises(TranscriptionError, match="bad audio"):
        transcription.transcribe_file(str(path))


def test_timeout(monkeypatch, tmp_path):
    path = tmp_path / "a.wav"
    path.write_bytes(b"RIFF")
    monkeypatch.setattr(
        transcription.requests,
        "post",
        _post_sequence(
            _ok_response({"upload_url": "u"}),
            _ok_response({"id": "t1"}),
        ),
    )

    def fake_get(*args, **kwargs):
        monkeypatch.setattr(transcription.time, "monotonic", lambda: float("inf"))
        return _ok_response({"status": "queued"})

    monkeypatch.setattr(transcription.requests, "get", fake_get)
    monkeypatch.setattr(transcription.time, "sleep", lambda s: None)
    with pytest.raises(TranscriptionTimeout):
        transcription.transcribe_file(str(path))
