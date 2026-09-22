"""
E2E: Analytics, usage counters, unmatched query curation, and feedback.

Tests that the analytics pipeline correctly logs events, aggregates counters,
tracks unmatched queries for KB curation, and accepts user feedback — all
through the HTTP API with realistic multi-step scenarios.
"""
import json

import pytest

from app.services import analytics as analytics_service


def _analytics_lines(tmp_path):
    path = tmp_path / "analytics.log.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class TestAnalyticsTracking:
    """Verify that API calls produce correct analytics side-effects."""

    def test_assist_and_transcribe_flow_produces_coherent_analytics(self, client, tmp_path, monkeypatch):
        """A realistic session: transcribe an audio file, then use /assist/.
        Both operations should produce analytics events with correct markers,
        and the /stats endpoint should reflect accumulated counters."""
        # Transcribe
        monkeypatch.setattr("app.services.transcription.transcribe_file", lambda p: "I forgot my password")
        client.post("/transcribe/", files={"file": ("call.wav", b"RIFF" + b"\x00" * 50, "audio/wav")})

        # Assist with takeover
        monkeypatch.setattr("app.services.llm.generate_response", lambda s, q, history=None: "Reset it here.")
        monkeypatch.setattr("app.services.tts.synthesize", lambda t: ("resp.wav", "groq-orpheus"))
        client.post("/assist/", json={"transcript": "I forgot my password", "intent": "password_reset"})

        # Assist without takeover
        client.post("/assist/", json={"transcript": "I want a refund", "intent": "refund_request"})

        # Check analytics log
        lines = _analytics_lines(tmp_path)
        events = [l["event"] for l in lines]
        assert "transcribe" in events
        assert events.count("assist") == 2

        # Find the takeover assist event
        takeover_event = next(l for l in lines if l["event"] == "assist" and l.get("tts_engine") == "groq-orpheus")
        assert takeover_event["llm"] is True
        assert isinstance(takeover_event["kb_score"], float)

        # Find the non-takeover assist event
        no_tts_event = next(l for l in lines if l["event"] == "assist" and l.get("tts_engine") is None)
        assert no_tts_event["llm"] is True

        # Stats endpoint should aggregate
        stats = client.get("/stats").json()
        assert stats["counters"]["transcribe_requests"] == 1
        assert stats["counters"]["llm_calls"] == 2
        assert stats["counters"]["tts:groq-orpheus"] == 1
        assert stats["counters"]["tts:none"] == 1
        assert stats["kb_count"] == 2  # FakeKB has 2 entries

    def test_no_match_events_logged_with_privacy_truncation(self, client, tmp_path, monkeypatch):
        """When a query has no KB match, the transcript is logged for curation
        but truncated to MAX_TRANSCRIPT_CHARS for privacy.  Long transcripts
        should be clipped."""
        client.app.state.knowledge_base.matches_result = []
        monkeypatch.setattr("app.services.handoff.create_ticket", lambda **k: "T-PRIV")

        # Submit a very long transcript
        long_text = "I have a really long question about " + "many things " * 200
        client.post("/assist/", json={"transcript": long_text, "intent": "unknown"})

        lines = _analytics_lines(tmp_path)
        no_match = next(l for l in lines if l["event"] == "no_match")
        assert len(no_match["transcript"]) <= analytics_service.MAX_TRANSCRIPT_CHARS
        assert no_match["handoff"] is True
        assert no_match["from_history"] is False

    def test_no_match_with_history_flagged_differently(self, client, tmp_path, monkeypatch):
        """A follow-up question with no KB match but with history should:
        1. Log a no_match event with from_history=True
        2. Log an assist event (because LLM is called)
        3. NOT create a handoff (history provides context)
        """
        client.app.state.knowledge_base.matches_result = []
        monkeypatch.setattr("app.services.llm.generate_response", lambda s, q, history=None: "Based on our earlier conversation...")

        client.post("/assist/", json={
            "transcript": "what about that other thing?",
            "intent": "unknown",
            "history": [{"transcript": "cancel my order", "response": "Done."}],
        })

        lines = _analytics_lines(tmp_path)
        no_match = next(l for l in lines if l["event"] == "no_match")
        assert no_match["from_history"] is True
        assert no_match["handoff"] is False

        assist = next(l for l in lines if l["event"] == "assist")
        assert assist["llm"] is True

        # Stats
        counters = client.get("/stats").json()["counters"]
        assert counters["no_match"] == 1
        assert counters["llm_calls"] == 1

    def test_handoff_from_speak_to_agent_counted_separately(self, client, tmp_path, monkeypatch):
        """speak_to_agent handoffs should increment handoff:speak_to_agent,
        while no_match handoffs increment handoff:no_match."""
        monkeypatch.setattr("app.services.llm.generate_response", lambda s, q, history=None: "answer")
        monkeypatch.setattr("app.services.handoff.create_ticket", lambda **k: "T-AGENT")

        client.post("/assist/", json={
            "transcript": "I want to speak to a real person immediately",
            "intent": "speak_to_agent",
        })

        counters = client.get("/stats").json()["counters"]
        assert counters.get("handoff:speak_to_agent") == 1

        # handoff:no_match should NOT be set
        assert "handoff:no_match" not in counters


class TestUnmatchedQueries:
    """Verify the KB curation pipeline for unmatched queries."""

    def test_repeated_unmatched_queries_aggregated_with_in_kb_flag(self, client, monkeypatch):
        """Multiple identical unmatched queries should be grouped by frequency.
        Queries that match an existing KB question should be flagged in_kb=True."""
        client.app.state.knowledge_base.matches_result = []
        monkeypatch.setattr("app.services.handoff.create_ticket", lambda **k: "T-AGG")

        # Submit the same unmatched query 3 times
        for _ in range(3):
            client.post("/assist/", json={"transcript": "How do I enable dark mode?", "intent": "unknown"})

        # Submit a query that happens to match an existing KB question
        client.post("/assist/", json={"transcript": "reset password", "intent": "unknown"})

        r = client.get("/kb/unmatched")
        assert r.status_code == 200
        data = r.json()

        # "How do I enable dark mode?" should be aggregated with count=3
        dark_mode = next(q for q in data["unmatched"] if "dark mode" in q["transcript"].lower())
        assert dark_mode["count"] == 3
        assert dark_mode["in_kb"] is False
        assert dark_mode["handoff"] is True

        # "reset password" matches existing KB question
        reset = next(q for q in data["unmatched"] if q["transcript"] == "reset password")
        assert reset["count"] == 1
        assert reset["in_kb"] is True

    def test_unmatched_queries_require_admin_when_token_set(self, client, monkeypatch):
        monkeypatch.setattr("app.config.ADMIN_TOKEN", "s3cret")
        assert client.get("/kb/unmatched").status_code == 401
        r = client.get("/kb/unmatched", headers={"X-Admin-Token": "s3cret"})
        assert r.status_code == 200


class TestFeedback:
    """User feedback endpoint."""

    def test_positive_and_negative_feedback_accepted(self, client):
        """Both thumbs-up and thumbs-down should be accepted."""
        r1 = client.post("/analytics/feedback", json={
            "transcript": "reset my password",
            "positive": True,
        })
        assert r1.status_code == 200
        assert r1.json()["status"] == "ok"

        r2 = client.post("/analytics/feedback", json={
            "transcript": "check my balance",
            "positive": False,
            "assist_request_id": "req-123",
        })
        assert r2.status_code == 200


class TestAnalyticsSummary:
    """Aggregated analytics endpoint."""

    def test_summary_includes_cost_estimates_after_usage(self, client, tmp_path, monkeypatch):
        """After some LLM and transcription usage, the analytics summary
        should include token counts and cost estimates."""
        log_file = tmp_path / "analytics.log.jsonl"
        monkeypatch.setattr(analytics_service.config, "ANALYTICS_LOG_PATH", log_file)

        # Simulate realistic usage by writing analytics events
        analytics_service.log_event(
            "assist", intents=["password_reset"],
            kb_score=0.82, prompt_tokens=150, completion_tokens=60,
            total_tokens=210, tts_engine="groq-orpheus", chars_synthesized=180,
        )
        analytics_service.log_event(
            "transcribe", intent="check_balance", file_size=48000,
        )
        analytics_service.log_event(
            "assist", intents=["refund_request"],
            kb_score=0.71, prompt_tokens=200, completion_tokens=80,
            total_tokens=280, tts_engine=None, chars_synthesized=0,
        )

        r = client.get("/analytics/summary")
        assert r.status_code == 200
        summary = r.json()

        assert summary["totals"]["total_requests"] == 3
        assert summary["llm"]["calls"] >= 2
        assert summary["llm"]["prompt_tokens"] >= 350
        assert summary["llm"]["total_tokens"] >= 490
        assert summary["llm"]["cost_usd"] > 0
        assert summary["transcription"]["calls"] == 1
        assert summary["tts"]["groq_calls"] >= 1
        assert len(summary["recent_activity"]) == 3


class TestStatsEndpoint:
    """The /stats process-local counters."""

    def test_stats_starts_empty_and_requires_admin(self, client, monkeypatch):
        """Fresh app starts with empty counters.  Admin-gated when configured."""
        body = client.get("/stats").json()
        assert body["counters"] == {}
        assert body["kb_count"] == 2

        monkeypatch.setattr("app.config.ADMIN_TOKEN", "s3cret")
        assert client.get("/stats").status_code == 401
