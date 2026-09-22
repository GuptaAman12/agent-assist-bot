"""
E2E: Service resilience — TTS fallback chains, handoff retry/queue mechanics,
audio retention, and transcription error handling.

These tests verify the fault-tolerance behaviors that keep the system running
when external dependencies fail: TTS fallback from Orpheus to gTTS, webhook
retry with disk queueing, audio garbage collection, and graceful error mapping.
"""
import io
import os
import time
import wave

import pytest
import requests

from app.services import handoff, tts
from app.services.transcription import TranscriptionError, TranscriptionTimeout


# ---------------------------------------------------------------------------
# TTS fallback and audio management
# ---------------------------------------------------------------------------


def _streaming_wav(n_frames):
    """Build a WAV with placeholder RIFF headers like Orpheus streams."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x01" * n_frames)
    raw = bytearray(buf.getvalue())
    raw[4:8] = b"\xff\xff\xff\xff"  # placeholder RIFF size like Orpheus
    return bytes(raw)


class TestTTSResilience:
    """TTS synthesis, fallback, and WAV normalization."""

    def test_orpheus_streaming_wav_headers_normalized(self, tts_env, monkeypatch):
        """Orpheus streams WAVs with placeholder headers (RIFF size 0xFFFFFFFF,
        nframes=2147483647).  The normalization step should produce a valid WAV
        with correct frame counts."""
        monkeypatch.setattr(tts, "_groq_speech", lambda text: _streaming_wav(100))

        filename, engine = tts.synthesize("Your password has been reset successfully.")
        assert engine == "groq-orpheus"

        # Verify the output is a valid WAV with correct metadata
        output_path = tts_env["static_dir"] / "audio" / filename
        assert output_path.exists()
        with wave.open(str(output_path), "rb") as r:
            assert r.getnframes() == 100
            assert r.getsampwidth() == 2
            assert r.getframerate() == 24000

    def test_multi_chunk_merging(self, tts_env, monkeypatch):
        """Long responses are split at sentence boundaries and each chunk
        produces a separate WAV.  _normalize_wav should merge them into one."""
        chunks = [_streaming_wav(100), _streaming_wav(75), _streaming_wav(50)]
        merged = tts._normalize_wav(chunks)

        with wave.open(io.BytesIO(merged), "rb") as r:
            assert r.getnframes() == 225

    def test_groq_failure_falls_back_to_gtts(self, tts_env, monkeypatch):
        """When Orpheus fails with TTSError, gTTS should take over and
        produce an MP3 file."""
        def boom(text):
            raise tts.TTSError("GPU quota exceeded")

        class FakeGtts:
            def __init__(self, text):
                self.text = text

            def save(self, path):
                import pathlib
                pathlib.Path(path).write_bytes(b"fake-mp3-data")

        monkeypatch.setattr(tts, "_groq_speech", boom)
        monkeypatch.setattr(tts, "gTTS", FakeGtts)

        filename, engine = tts.synthesize("Your password has been reset.")
        assert engine == "gtts-fallback"
        assert filename.endswith(".mp3")
        assert (tts_env["static_dir"] / "audio" / filename).exists()


class TestAudioRetention:
    """Audio file pruning to prevent disk exhaustion."""

    def _make_audio(self, path, age_sec=0):
        path.write_bytes(b"fake-audio-data")
        if age_sec:
            old = time.time() - age_sec
            os.utime(path, (old, old))
        return path

    def test_ttl_based_pruning_keeps_fresh_files(self, tts_env, monkeypatch):
        """Files older than AUDIO_TTL_SEC are pruned; fresh files and
        non-audio files are kept."""
        monkeypatch.setattr("app.services.tts.config.AUDIO_TTL_SEC", 3600)
        monkeypatch.setattr("app.services.tts.config.AUDIO_MAX_FILES", 100)
        audio_dir = tts_env["static_dir"] / "audio"
        audio_dir.mkdir(exist_ok=True)

        old = self._make_audio(audio_dir / "ai_response_old.wav", age_sec=7200)
        fresh = self._make_audio(audio_dir / "ai_response_fresh.wav")
        unmanaged = self._make_audio(audio_dir / "notes.txt", age_sec=7200)

        pruned = tts.prune_old_audio()
        assert pruned == 1
        assert not old.exists()
        assert fresh.exists()
        assert unmanaged.exists()  # only ai_response_* is managed

    def test_max_files_cap_keeps_newest(self, tts_env, monkeypatch):
        """When there are more files than AUDIO_MAX_FILES, the oldest are
        pruned to keep only the newest N."""
        monkeypatch.setattr("app.services.tts.config.AUDIO_TTL_SEC", 0)  # TTL off
        monkeypatch.setattr("app.services.tts.config.AUDIO_MAX_FILES", 2)
        audio_dir = tts_env["static_dir"] / "audio"
        audio_dir.mkdir(exist_ok=True)

        now = time.time()
        files = []
        for i in range(4):
            p = audio_dir / f"ai_response_2025010{i}_000000_0000000{i}.wav"
            p.write_bytes(b"x")
            os.utime(p, (now - (40 - i * 10), now - (40 - i * 10)))
            files.append(p)

        pruned = tts.prune_old_audio()
        assert pruned == 2
        assert not files[0].exists() and not files[1].exists()
        assert files[2].exists() and files[3].exists()

    def test_synthesize_auto_prunes(self, tts_env, monkeypatch):
        """Every synthesize() call should trigger pruning after saving."""
        monkeypatch.setattr(tts, "_groq_speech", lambda text: _streaming_wav(50))
        monkeypatch.setattr("app.services.tts.config.AUDIO_TTL_SEC", 0)
        monkeypatch.setattr("app.services.tts.config.AUDIO_MAX_FILES", 2)

        audio_dir = tts_env["static_dir"] / "audio"
        audio_dir.mkdir(exist_ok=True)
        self._make_audio(audio_dir / "ai_response_20200101_000000_aaaaaaaa.wav", age_sec=9999)
        self._make_audio(audio_dir / "ai_response_20200102_000000_bbbbbbbb.wav", age_sec=9999)

        filename, _ = tts.synthesize("hello there")
        remaining = sorted(p.name for p in audio_dir.glob("ai_response_*.*"))
        assert len(remaining) == 2  # max_files cap
        assert filename in remaining


# ---------------------------------------------------------------------------
# Handoff service — webhook retry, disk queueing, replay
# ---------------------------------------------------------------------------


class TestHandoffRetryAndQueue:
    """Verify the fault-tolerant handoff delivery pipeline."""

    def test_webhook_retries_then_succeeds(self, monkeypatch, tmp_path):
        """Transient failures should be retried up to 3 times.  If the third
        attempt succeeds, a ticket_id is returned."""
        monkeypatch.setattr(handoff.config, "HANDOFF_WEBHOOK_URL", "https://hooks.example.com/t")
        monkeypatch.setattr(handoff.config, "HANDOFF_EMAIL_TO", "")
        monkeypatch.setattr(handoff.config, "HANDOFF_QUEUE_PATH", tmp_path / "queue.jsonl")
        monkeypatch.setattr(handoff.time, "sleep", lambda s: None)
        monkeypatch.setattr(handoff.random, "uniform", lambda a, b: 0)

        call_count = {"n": 0}

        class FakeResp:
            def raise_for_status(self):
                pass

        def flaky_post(*a, **k):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise RuntimeError("transient network error")
            return FakeResp()

        monkeypatch.setattr(handoff.requests, "post", flaky_post)

        ticket_id = handoff.create_ticket(
            reason="speak_to_agent",
            transcript="I need help",
            intents=["speak_to_agent"],
            assistant_response="Transferring you.",
        )
        assert ticket_id is not None
        assert call_count["n"] == 3

    def test_all_retries_fail_queues_to_disk(self, monkeypatch, tmp_path):
        """When all 3 retry attempts fail, the ticket is queued to disk
        for later replay, and create_ticket returns None."""
        monkeypatch.setattr(handoff.config, "HANDOFF_WEBHOOK_URL", "https://hooks.example.com/t")
        monkeypatch.setattr(handoff.config, "HANDOFF_EMAIL_TO", "")
        queue_path = tmp_path / "queue.jsonl"
        monkeypatch.setattr(handoff.config, "HANDOFF_QUEUE_PATH", queue_path)
        monkeypatch.setattr(handoff.time, "sleep", lambda s: None)
        monkeypatch.setattr(handoff.random, "uniform", lambda a, b: 0)

        monkeypatch.setattr(handoff.requests, "post", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("persistent failure")))

        ticket_id = handoff.create_ticket(
            reason="no_match", transcript="help", intents=[], assistant_response="Sorry",
        )
        assert ticket_id is None

        # Verify queued to disk
        assert queue_path.exists()
        import json
        data = json.loads(queue_path.read_text(encoding="utf-8").strip().splitlines()[0])
        assert data["reason"] == "no_match"

    def test_corrupt_queue_file_handled_gracefully(self, monkeypatch, tmp_path):
        """If the queue JSONL file has corrupt lines (e.g. partial writes from
        a crash), they should be silently skipped."""
        queue_path = tmp_path / "queue.jsonl"
        monkeypatch.setattr(handoff.config, "HANDOFF_QUEUE_PATH", queue_path)

        queue_path.write_text(
            'not valid json\n{"ticket_id": "T-OK", "reason": "no_match"}\n\n{broken\n',
            encoding="utf-8",
        )
        tickets = handoff.get_queued_tickets()
        assert len(tickets) == 1
        assert tickets[0]["ticket_id"] == "T-OK"

    def test_email_fallback_when_no_webhook(self, monkeypatch):
        """When webhook URL is empty but email is configured, delivery
        should go through the email path."""
        monkeypatch.setattr(handoff.config, "HANDOFF_WEBHOOK_URL", "")
        monkeypatch.setattr(handoff.config, "HANDOFF_EMAIL_TO", "support@example.com")
        monkeypatch.setattr(handoff.config, "HANDOFF_EMAIL_FROM", "bot@example.com")
        monkeypatch.setattr(handoff.config, "SMTP_HOST", "smtp.example.com")
        monkeypatch.setattr(handoff.config, "SMTP_PORT", 587)
        monkeypatch.setattr(handoff.config, "SMTP_USER", "")

        email_sent = {}

        def capture_email(payload):
            email_sent.update(payload)

        monkeypatch.setattr(handoff, "_send_email", capture_email)

        ticket_id = handoff.create_ticket(
            reason="no_match", transcript="q", intents=[], assistant_response="r",
        )
        assert ticket_id is not None
        assert email_sent["reason"] == "no_match"

    def test_no_delivery_configured_still_returns_ticket_id(self, monkeypatch):
        """With neither webhook nor email configured, create_ticket should
        still return a ticket_id (logged locally) and never raise."""
        monkeypatch.setattr(handoff.config, "HANDOFF_WEBHOOK_URL", "")
        monkeypatch.setattr(handoff.config, "HANDOFF_EMAIL_TO", "")

        ticket_id = handoff.create_ticket(
            reason="no_match", transcript="q", intents=[], assistant_response="r",
        )
        assert ticket_id is not None


# ---------------------------------------------------------------------------
# Markdown stripping for TTS (spoken output must be plain text)
# ---------------------------------------------------------------------------


class TestMarkdownStripping:
    """TTS output goes through strip_markdown.  Verify it handles the markdown
    patterns that the LLM system prompt is supposed to avoid but occasionally
    produces anyway."""

    def test_complex_markdown_stripped_to_speakable_text(self):
        """Bold, italic, code, links, headings, and tables — all of which
        should be cleaned for speech synthesis."""
        md = (
            "## Password Reset\n"
            "Go to **Settings** > *Security* and click `Reset Password`.\n"
            "See [help center](https://help.example.com) for details.\n"
            "| Step | Action |\n|---|---|\n| 1 | Click **Reset** |\n| 2 | Enter email |"
        )
        plain = tts.strip_markdown(md)
        # No markdown artifacts remain
        assert "**" not in plain
        assert "*" not in plain or plain.count("*") == 0
        assert "`" not in plain
        assert "](http" not in plain
        assert "|" not in plain
        assert "##" not in plain
        # Content preserved
        assert "Settings" in plain
        assert "Security" in plain
        assert "Reset Password" in plain or "Reset" in plain
        assert "help center" in plain

    def test_plain_text_passes_through_unchanged(self):
        assert tts.strip_markdown("Just a normal sentence.") == "Just a normal sentence."
