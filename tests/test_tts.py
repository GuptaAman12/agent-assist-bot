import io
import wave

import pytest

from app.services import tts


class TestStripMarkdown:
    def test_bold_and_italic(self):
        assert tts.strip_markdown("**bold** and *italic* text") == "bold and italic text"

    def test_code_and_links(self):
        out = tts.strip_markdown("run `reset.exe` or see [help](https://x.com)")
        assert "reset.exe" in out and "help" in out
        assert "`" not in out and "](https" not in out

    def test_headings(self):
        assert tts.strip_markdown("## Heading\nbody") == "Heading\nbody"

    def test_table(self):
        text = "| A | B |\n|---|---|\n| **x** | y |"
        out = tts.strip_markdown(text)
        assert "|" not in out and "**" not in out
        assert "x" in out and "y" in out

    def test_plain_text_unchanged(self):
        assert tts.strip_markdown("Just a normal sentence.") == "Just a normal sentence."


class TestSplitChunks:
    def test_respects_limit(self):
        text = "One. Two. Three. Four. Five. Six. Seven. Eight."
        chunks = tts._split_chunks(text, 20)
        assert all(len(c) <= 20 for c in chunks)
        assert "".join(chunks).replace(" ", "") == text.replace(" ", "")

    def test_single_hard_split(self):
        chunks = tts._split_chunks("a" * 450, 200)
        assert all(len(c) <= 200 for c in chunks)
        assert sum(len(c) for c in chunks) == 450


def _streaming_wav(n_frames):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x01" * n_frames)
    raw = bytearray(buf.getvalue())
    raw[4:8] = b"\xff\xff\xff\xff"  # placeholder RIFF size like Orpheus streams
    return bytes(raw)


class TestNormalizeWav:
    def test_single_chunk_header_fixed(self):
        out = tts._normalize_wav([_streaming_wav(100)])
        with wave.open(io.BytesIO(out), "rb") as r:
            assert r.getnframes() == 100
            assert (r.getnchannels(), r.getsampwidth(), r.getframerate()) == (1, 2, 24000)

    def test_merges_multiple_chunks(self):
        out = tts._normalize_wav([_streaming_wav(100), _streaming_wav(50), _streaming_wav(25)])
        with wave.open(io.BytesIO(out), "rb") as r:
            assert r.getnframes() == 175


class TestSynthesize:
    def test_groq_path_saves_wav(self, tts_env, monkeypatch):
        monkeypatch.setattr(tts, "_groq_speech", lambda text: _streaming_wav(50))
        filename, engine = tts.synthesize("hello there")
        assert engine == "groq-orpheus"
        assert filename.endswith(".wav")
        assert (tts_env["static_dir"] / filename).exists()

    def test_gtts_fallback_on_error(self, tts_env, monkeypatch):
        def boom(text):
            raise tts.TTSError("down")

        class FakeGtts:
            def __init__(self, text):
                self.text = text

            def save(self, path):
                import pathlib

                pathlib.Path(path).write_bytes(b"fake-mp3")

        monkeypatch.setattr(tts, "_groq_speech", boom)
        monkeypatch.setattr(tts, "gTTS", FakeGtts)
        filename, engine = tts.synthesize("hello there")
        assert engine == "gtts-fallback"
        assert filename.endswith(".mp3")
        assert (tts_env["static_dir"] / filename).exists()
