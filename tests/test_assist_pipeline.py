"""
E2E: Call assistance pipeline — transcribe → assist → response contract.

Tests the full lifecycle a human agent or customer goes through: upload audio,
get a transcript + intent, then request AI assistance with KB context, LLM
generation, voice synthesis, and handoff escalation.

Every test hits the HTTP API and verifies externally-observable behavior that
a frontend or integration consumer depends on.
"""
import json

import pytest


# ---------------------------------------------------------------------------
# Transcription upload guards — real-world abuse scenarios
# ---------------------------------------------------------------------------


class TestTranscriptionGuards:
    """Verify that the upload pipeline rejects dangerous or malformed inputs
    before any external API call is made."""

    def test_executable_disguised_as_audio_rejected(self, client):
        """An attacker renames malware.exe → call.wav.  Extension allowlist
        must reject by the *actual* extension, not content-type sniffing."""
        r = client.post(
            "/transcribe/",
            files={"file": ("payload.exe", b"\x4d\x5a" + b"\x00" * 200, "audio/wav")},
        )
        assert r.status_code == 415
        assert "Unsupported file type" in r.json()["detail"]

    def test_oversized_audio_with_lying_content_length(self, client, monkeypatch):
        """Server trusts neither declared Content-Length nor omitted headers.
        A 200-byte file with a small declared Content-Length but actual bytes
        exceeding the cap should be caught during streaming."""
        monkeypatch.setattr("app.config.MAX_UPLOAD_BYTES", 50)
        # Actual payload is 200 bytes, well over the 50-byte cap
        r = client.post(
            "/transcribe/",
            files={"file": ("call.mp3", b"x" * 200, "audio/mpeg")},
            headers={"content-length": "10"},  # lies about size
        )
        assert r.status_code == 413

    def test_transcription_service_down_maps_to_502_not_500(self, client, monkeypatch):
        """When AssemblyAI returns an upstream error, the client sees a clean
        502 with a meaningful detail message, never an unhandled 500."""
        from app.services.transcription import TranscriptionError

        monkeypatch.setattr(
            "app.services.transcription.transcribe_file",
            lambda p: (_ for _ in ()).throw(TranscriptionError("upload rejected: 403 forbidden")),
        )
        r = client.post("/transcribe/", files={"file": ("call.wav", b"RIFF" + b"\x00" * 50, "audio/wav")})
        assert r.status_code == 502
        assert "403" in r.json()["detail"]

    def test_transcription_timeout_maps_to_504(self, client, monkeypatch):
        """Polling timeout surfaces as 504, not a generic server error."""
        from app.services.transcription import TranscriptionTimeout

        monkeypatch.setattr(
            "app.services.transcription.transcribe_file",
            lambda p: (_ for _ in ()).throw(TranscriptionTimeout("polling exceeded 120s")),
        )
        r = client.post("/transcribe/", files={"file": ("call.wav", b"RIFF" + b"\x00" * 50, "audio/wav")})
        assert r.status_code == 504

    def test_successful_transcription_detects_compound_intent(self, client, monkeypatch):
        """A realistic call: customer says something that triggers intent
        detection.  Verify the response contract (transcript + intent)."""
        monkeypatch.setattr(
            "app.services.transcription.transcribe_file",
            lambda p: "My account is locked and I forgot my password",
        )
        r = client.post("/transcribe/", files={"file": ("call.wav", b"RIFF" + b"\x00" * 50, "audio/wav")})
        assert r.status_code == 200
        body = r.json()
        assert body["transcript"] == "My account is locked and I forgot my password"
        # "locked" → account_locked comes first in INTENT_KEYWORDS dict order
        # (speak_to_agent checked first, then password_reset, then ... account_locked).
        # detect_intent is first-match — depends on dict ordering, but both are
        # valid intents.  We only care that *some* intent was detected, not gibberish.
        assert body["intent"] != "unknown"


# ---------------------------------------------------------------------------
# Assist pipeline — KB match → LLM → TTS → response
# ---------------------------------------------------------------------------


class TestAssistPipeline:
    """Full /assist/ flow exercising the interaction between KB retrieval,
    LLM generation, TTS synthesis, and handoff escalation."""

    def test_matched_query_gets_llm_response_with_sources(self, client, monkeypatch):
        """When the KB matches, the LLM is called with context from multiple
        sources, and all sources are surfaced to the frontend."""
        llm_context_received = {}

        def capture_llm(context, query, history=None):
            llm_context_received["context"] = context
            llm_context_received["query"] = query
            return "Here's how to reset your password: go to Settings > Security."

        monkeypatch.setattr("app.services.llm.generate_response", capture_llm)

        r = client.post("/assist/", json={
            "transcript": "I can't remember my password and want to check my account balance",
            "intent": "unknown",
        })
        assert r.status_code == 200
        body = r.json()

        # LLM was called with actual KB context (multiple numbered sources)
        assert "[1]" in llm_context_received["context"]
        assert "[2]" in llm_context_received["context"]

        # Response shape matches frontend contract
        assert body["response"] == "Here's how to reset your password: go to Settings > Security."
        assert body["sources"] == ["context one", "context two"]
        assert body["source"] == "context one"  # first source
        assert isinstance(body["kb_score"], float) and body["kb_score"] > 0
        assert body["handoff"] is False
        assert body["ticket_id"] is None

    def test_takeover_intent_generates_audio_while_non_takeover_does_not(self, client, monkeypatch):
        """password_reset (SIMPLE_INTENT) triggers TTS; refund_request does not.
        This verifies the voice takeover decision logic end-to-end."""
        monkeypatch.setattr("app.services.llm.generate_response", lambda s, q, history=None: "done")
        monkeypatch.setattr("app.services.tts.synthesize", lambda t: ("ai_resp.wav", "groq-orpheus"))

        # Takeover case
        r1 = client.post("/assist/", json={"transcript": "reset my password", "intent": "password_reset"})
        b1 = r1.json()
        assert b1["ai_takeover"] is True
        assert b1["audio_url"] == "/static/audio/ai_resp.wav"
        assert b1["tts_engine"] == "groq-orpheus"

        # Non-takeover case — same LLM mock, same TTS mock, but refund_request
        # is NOT in SIMPLE_INTENTS, so TTS should never be called
        tts_called = {"n": 0}
        original_synth = lambda t: (tts_called.update(n=tts_called["n"] + 1), ("x.wav", "groq-orpheus"))[-1]
        monkeypatch.setattr("app.services.tts.synthesize", original_synth)

        r2 = client.post("/assist/", json={"transcript": "I want a refund", "intent": "refund_request"})
        b2 = r2.json()
        assert b2["ai_takeover"] is False
        assert b2["audio_url"] is None
        assert b2["tts_engine"] is None
        assert tts_called["n"] == 0  # TTS was never invoked

    def test_mixed_multi_topic_utterance_triggers_takeover(self, client, monkeypatch):
        """A customer call mentioning both a SIMPLE_INTENT topic (email change)
        and another SIMPLE_INTENT topic (app crashing) should trigger takeover
        because ANY detected intent is automatable."""
        monkeypatch.setattr("app.services.llm.generate_response", lambda s, q, history=None: "answer")
        monkeypatch.setattr("app.services.tts.synthesize", lambda t: ("out.wav", "groq-orpheus"))

        r = client.post("/assist/", json={
            "transcript": "How do I change my email address? Also the app keeps crashing every time I open it.",
            "intent": "update_email",
        })
        assert r.status_code == 200
        assert r.json()["ai_takeover"] is True
        assert r.json()["audio_url"] is not None

    def test_no_kb_match_triggers_handoff_and_canned_response(self, client, monkeypatch):
        """When the KB has nothing relevant and there's no conversation history,
        the system returns a canned "I'm not sure" response, never calls the LLM,
        and opens a handoff ticket for a human agent."""
        client.app.state.knowledge_base.matches_result = []
        llm_called = {"n": 0}

        def should_not_be_called(s, q, history=None):
            llm_called["n"] += 1
            return "BUG"

        monkeypatch.setattr("app.services.llm.generate_response", should_not_be_called)
        monkeypatch.setattr("app.services.handoff.create_ticket", lambda **k: "TICKET-42")

        r = client.post("/assist/", json={
            "transcript": "Can you help me with quantum entanglement?",
            "intent": "unknown",
        })
        body = r.json()
        assert r.status_code == 200
        assert llm_called["n"] == 0
        assert "not sure" in body["response"].lower()
        assert body["source"] is None
        assert body["sources"] == []
        assert body["kb_score"] is None
        assert body["handoff"] is True
        assert body["ticket_id"] == "TICKET-42"

    def test_tts_failure_degrades_gracefully_to_text_only(self, client, monkeypatch):
        """If Groq Orpheus AND gTTS both fail, the response still comes back
        with the LLM text — the user just doesn't get audio.  This is critical:
        a TTS outage must never block the assist response."""
        monkeypatch.setattr("app.services.llm.generate_response", lambda s, q, history=None: "Here is your answer.")
        monkeypatch.setattr("app.services.tts.synthesize", lambda t: (_ for _ in ()).throw(RuntimeError("GPU OOM")))

        r = client.post("/assist/", json={"transcript": "reset my password", "intent": "password_reset"})
        assert r.status_code == 200
        body = r.json()
        assert body["response"] == "Here is your answer."
        assert body["ai_takeover"] is True  # intent still triggers takeover
        assert body["audio_url"] is None  # but no audio
        assert body["tts_engine"] is None

    def test_llm_failure_returns_502_not_500(self, client, monkeypatch):
        """Groq going down should return a clean 502 that the frontend can
        show as a transient error, not an unhandled exception."""
        from app.services.llm import LLMError

        monkeypatch.setattr(
            "app.services.llm.generate_response",
            lambda s, q, history=None: (_ for _ in ()).throw(LLMError("Groq 503: overloaded")),
        )
        r = client.post("/assist/", json={"transcript": "check my balance", "intent": "check_balance"})
        assert r.status_code == 502


# ---------------------------------------------------------------------------
# Multi-turn conversation (history-aware follow-ups)
# ---------------------------------------------------------------------------


class TestMultiTurnConversation:
    """Verify conversation continuity when a follow-up question has no direct
    KB match but prior conversation context should inform the answer."""

    def test_followup_with_no_kb_match_uses_conversation_history(self, client, monkeypatch):
        """User asks 'what about the shipping?' after discussing order cancellation.
        KB has no match, but the LLM should receive the prior conversation and
        produce an answer instead of the canned 'I'm not sure' response."""
        client.app.state.knowledge_base.matches_result = []
        llm_received = {}

        def capture_llm(context, query, history=None):
            llm_received["context"] = context
            llm_received["history"] = history
            return "Your cancellation was processed. Shipping will be refunded in 3-5 days."

        monkeypatch.setattr("app.services.llm.generate_response", capture_llm)

        r = client.post("/assist/", json={
            "transcript": "what about the shipping costs?",
            "intent": "unknown",
            "history": [
                {"transcript": "I want to cancel my order #12345", "response": "Your order has been cancelled."},
                {"transcript": "will I get my money back?", "response": "Yes, a full refund has been initiated."},
            ],
        })
        assert r.status_code == 200
        body = r.json()
        # LLM should have been called (not the canned no-match response)
        assert "refunded" in body["response"].lower()
        # Context should reference prior conversation
        assert "previously said" in llm_received["context"]
        assert "order" in llm_received["context"].lower()
        # No KB match — but no handoff either (history provides context)
        assert body["handoff"] is False
        assert body["source"] is None

    def test_history_overflow_keeps_most_recent_turns(self, client, monkeypatch):
        """When history exceeds MAX_HISTORY_TURNS, only the most recent turns
        survive in the LLM context.  Oldest turns should be evicted."""
        client.app.state.knowledge_base.matches_result = []
        llm_received = {}

        def capture_llm(context, query, history=None):
            llm_received["context"] = context
            return "answer"

        monkeypatch.setattr("app.services.llm.generate_response", capture_llm)

        # 12 turns of history — MAX_HISTORY_TURNS is 5 by default
        history = [
            {"transcript": f"question_{i}", "response": f"answer_{i}"}
            for i in range(12)
        ]
        r = client.post("/assist/", json={
            "transcript": "follow-up?",
            "intent": "unknown",
            "history": history,
        })
        assert r.status_code == 200
        # Most recent turn (question_11/answer_11) must be in context
        assert "question_11" in llm_received["context"]
        assert "answer_11" in llm_received["context"]
        # Oldest turn (question_0) must have been evicted
        assert "question_0" not in llm_received["context"]

    def test_speak_to_agent_with_kb_match_still_triggers_handoff(self, client, monkeypatch):
        """Even when the KB has relevant context, if the customer explicitly
        says 'talk to a real person', the handoff should fire in addition to
        the LLM response."""
        handoff_args = {}

        def capture_handoff(**kwargs):
            handoff_args.update(kwargs)
            return "ESC-789"

        monkeypatch.setattr("app.services.llm.generate_response", lambda s, q, history=None: "I'll help you.")
        monkeypatch.setattr("app.services.handoff.create_ticket", capture_handoff)

        r = client.post("/assist/", json={
            "transcript": "I need to talk to a real person about resetting my password",
            "intent": "speak_to_agent",
        })
        body = r.json()
        assert r.status_code == 200
        assert body["response"] == "I'll help you."
        assert body["handoff"] is True
        assert body["ticket_id"] == "ESC-789"
        assert handoff_args["reason"] == "speak_to_agent"
        assert "password" in handoff_args["transcript"].lower()

    def test_custom_voice_selection_passed_to_tts(self, client, monkeypatch):
        """The frontend can request a specific Orpheus voice (e.g. 'diana').
        Verify it propagates through to the TTS service."""
        tts_received = {}

        def capture_synth(text, voice=None):
            tts_received["voice"] = voice
            return ("out.wav", "groq-orpheus")

        monkeypatch.setattr("app.services.llm.generate_response", lambda s, q, history=None: "answer")
        monkeypatch.setattr("app.services.tts.synthesize", capture_synth)

        r = client.post("/assist/", json={
            "transcript": "reset my password",
            "intent": "password_reset",
            "voice": "diana",
        })
        assert r.status_code == 200
        assert tts_received["voice"] == "diana"
        assert r.json()["tts_engine"] == "groq-orpheus"
