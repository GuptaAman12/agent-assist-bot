"""Usage analytics: per-request cost markers, no-match log, in-memory counters.

Two sinks, both best-effort and PII-conscious:
- JSONL file (config.ANALYTICS_LOG_PATH): one line per billable request
  (transcribe/assist) plus every no-match query. Only no-match lines carry
  the transcript (truncated) - that text is the KB-curation signal; matched
  requests log markers only (kb_score, llm/tts/handoff use).
- In-memory counters (process-local, reset on restart): aggregates served
  at GET /stats. Flat string keys so the snapshot is trivially JSON-safe.
"""

import collections
import json
import logging
import threading
from datetime import datetime, timezone

from .. import config
from ..logging import get_request_id

logger = logging.getLogger("app.analytics")

MAX_TRANSCRIPT_CHARS = 500

_lock = threading.Lock()
_counters: collections.Counter = collections.Counter()


def record(key: str, n: int = 1) -> None:
    with _lock:
        _counters[key] += n


def snapshot() -> dict:
    with _lock:
        return dict(_counters)


def reset() -> None:
    """Tests only: clear all counters."""
    with _lock:
        _counters.clear()


def log_event(event: str, **fields) -> None:
    """Append one analytics line. Never raises - analytics must not break requests."""
    try:
        record_data = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "request_id": get_request_id(),
            "event": event,
        }
        record_data.update(fields)
        with open(config.ANALYTICS_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record_data, ensure_ascii=False) + "\n")
    except Exception:
        pass
    try:
        logger.info(
            event,
            extra={"req_id": get_request_id() or None, "event": event},
        )
    except Exception:
        pass


def log_no_match(transcript: str, intents: list, from_history: bool = False,
                 handoff_id: str | None = None) -> None:
    record("no_match")
    if handoff_id is not None:
        record("handoff:no_match")
    log_event(
        "no_match",
        transcript=(transcript or "")[:MAX_TRANSCRIPT_CHARS],
        intents=list(intents),
        from_history=from_history,
        handoff=handoff_id is not None,
        ticket_id=handoff_id,
    )


def log_feedback(transcript: str, positive: bool, assist_request_id: str | None = None) -> None:
    if positive:
        record("feedback:positive")
    else:
        record("feedback:negative")
    log_event(
        "feedback",
        positive=positive,
        transcript=(transcript or "")[:MAX_TRANSCRIPT_CHARS],
        assist_request_id=assist_request_id,
    )


def get_unmatched_queries(limit: int = 50) -> list[dict]:
    """Read and aggregate unmatched queries from the analytics log for KB curation.
    Returns entries sorted by frequency descending, then recency descending."""
    path = config.ANALYTICS_LOG_PATH
    try:
        if not path.exists():
            return []
    except Exception:
        return []

    groups: dict[str, dict] = collections.defaultdict(lambda: {
        "transcript": "",
        "count": 0,
        "last_seen": "",
        "intents": set(),
        "handoff": False,
        "ticket_id": None,
    })
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("event") != "no_match":
                    continue
                transcript = (rec.get("transcript") or "").strip()
                if not transcript:
                    continue

                g = groups[transcript.lower()]
                g["count"] += 1
                ts = rec.get("ts", "")
                if ts >= g["last_seen"]:
                    g["last_seen"] = ts
                    g["transcript"] = transcript
                    if rec.get("ticket_id"):
                        g["ticket_id"] = rec["ticket_id"]
                g["intents"].update(rec.get("intents") or [])
                g["handoff"] = g["handoff"] or bool(rec.get("handoff"))
    except Exception as exc:
        logger.warning("failed to read unmatched queries: %s", exc)
        return []

    result = [
        {
            "transcript": g["transcript"],
            "count": g["count"],
            "last_seen": g["last_seen"],
            "intents": sorted(list(g["intents"])),
            "handoff": g["handoff"],
            "ticket_id": g["ticket_id"],
        }
        for g in groups.values()
    ]
    result.sort(key=lambda x: (x["count"], x["last_seen"]), reverse=True)
    return result[:limit]


def get_analytics_summary() -> dict:
    """Read analytics log and combine with live counters to compute service usage,
    token consumption, and cost estimates."""
    path = config.ANALYTICS_LOG_PATH
    records: list[dict] = []
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except Exception:
                            continue
        except Exception as exc:
            logger.warning("failed to read analytics log for summary: %s", exc)

    llm_calls = 0
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    llm_cost = 0.0

    stt_calls = 0
    stt_bytes = 0
    stt_seconds = 0.0
    stt_cost = 0.0

    tts_groq_calls = 0
    tts_gtts_calls = 0
    tts_chars = 0
    tts_cost = 0.0

    rag_queries = 0
    rag_matches = 0
    rag_no_matches = 0
    rag_scores = []

    handoff_count = 0
    handoff_reasons: dict[str, int] = collections.defaultdict(int)
    intent_distribution: dict[str, int] = collections.defaultdict(int)

    activity_log = []

    for r in records:
        event = r.get("event")
        ts = r.get("ts", "")
        req_id = r.get("request_id", "")
        req_cost = 0.0

        if event == "assist":
            llm_calls += 1
            rag_queries += 1

            p_tok = int(r.get("prompt_tokens") or 0)
            c_tok = int(r.get("completion_tokens") or 0)
            t_tok = int(r.get("total_tokens") or (p_tok + c_tok))
            if t_tok == 0:
                p_tok = 60
                c_tok = 30
                t_tok = 90

            prompt_tokens += p_tok
            completion_tokens += c_tok
            total_tokens += t_tok

            call_llm_cost = (p_tok / 1_000_000 * config.GROQ_INPUT_COST_PER_1M) + (
                c_tok / 1_000_000 * config.GROQ_OUTPUT_COST_PER_1M
            )
            llm_cost += call_llm_cost
            req_cost += call_llm_cost

            # TTS
            engine = r.get("tts_engine")
            chars = int(r.get("chars_synthesized") or 0)
            if engine == "groq-orpheus":
                tts_groq_calls += 1
                chars = chars or 140
                tts_chars += chars
                call_tts_cost = (chars / 1_000_000) * config.GROQ_TTS_COST_PER_1M_CHARS
                tts_cost += call_tts_cost
                req_cost += call_tts_cost
            elif engine == "gtts-fallback":
                tts_gtts_calls += 1
                chars = chars or 140
                tts_chars += chars

            # RAG
            kb_score = r.get("kb_score")
            if kb_score is not None:
                rag_matches += 1
                rag_scores.append(float(kb_score))
            else:
                rag_no_matches += 1

            # Handoff
            if r.get("handoff"):
                handoff_count += 1
                for i in r.get("intents") or []:
                    if i == "speak_to_agent":
                        handoff_reasons["speak_to_agent"] += 1
                        break
                else:
                    handoff_reasons["no_match"] += 1

            for i in r.get("intents") or []:
                intent_distribution[i] += 1

            activity_log.append({
                "ts": ts,
                "request_id": req_id,
                "event": "assist",
                "details": f"LLM ({config.GROQ_MODEL})",
                "intents": r.get("intents") or [],
                "prompt_tokens": p_tok,
                "completion_tokens": c_tok,
                "total_tokens": t_tok,
                "tts_engine": engine,
                "handoff": bool(r.get("handoff")),
                "ticket_id": r.get("ticket_id"),
                "cost_usd": round(req_cost, 5),
            })

        elif event == "transcribe":
            stt_calls += 1
            f_size = int(r.get("file_size") or 64000)
            stt_bytes += f_size
            est_sec = max(2.5, round(f_size / 32000, 1))
            stt_seconds += est_sec
            call_stt_cost = (est_sec / 3600) * config.ASSEMBLYAI_COST_PER_HOUR
            stt_cost += call_stt_cost
            req_cost += call_stt_cost

            intent = r.get("intent")
            if intent:
                intent_distribution[intent] += 1

            activity_log.append({
                "ts": ts,
                "request_id": req_id,
                "event": "transcribe",
                "details": f"AssemblyAI Audio ({round(est_sec, 1)}s)",
                "intents": [intent] if intent else [],
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "tts_engine": None,
                "handoff": False,
                "ticket_id": None,
                "cost_usd": round(req_cost, 5),
            })

        elif event == "no_match":
            for i in r.get("intents") or []:
                intent_distribution[i] += 1

    activity_log.sort(key=lambda x: x["ts"], reverse=True)

    total_cost = llm_cost + stt_cost + tts_cost
    match_rate_pct = round((rag_matches / rag_queries * 100) if rag_queries > 0 else 0.0, 1)
    avg_similarity = round(sum(rag_scores) / len(rag_scores), 3) if rag_scores else 0.0
    avg_tokens_per_call = round(total_tokens / llm_calls, 1) if llm_calls > 0 else 0.0
    escalation_rate_pct = round((handoff_count / (rag_queries or 1) * 100) if rag_queries > 0 else 0.0, 1)

    return {
        "totals": {
            "total_requests": len(records),
            "total_cost_usd": round(total_cost, 5),
            "formatted_cost": f"${total_cost:.4f}",
            "live_counters": snapshot(),
        },
        "llm": {
            "model": config.GROQ_MODEL,
            "calls": llm_calls,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "avg_tokens_per_call": avg_tokens_per_call,
            "cost_usd": round(llm_cost, 5),
            "rates": {
                "input_per_1m": config.GROQ_INPUT_COST_PER_1M,
                "output_per_1m": config.GROQ_OUTPUT_COST_PER_1M,
            },
        },
        "transcription": {
            "service": "AssemblyAI",
            "calls": stt_calls,
            "total_bytes": stt_bytes,
            "est_audio_seconds": round(stt_seconds, 1),
            "cost_usd": round(stt_cost, 5),
            "rate_per_hour": config.ASSEMBLYAI_COST_PER_HOUR,
        },
        "tts": {
            "total_calls": tts_groq_calls + tts_gtts_calls,
            "groq_calls": tts_groq_calls,
            "gtts_calls": tts_gtts_calls,
            "total_chars": tts_chars,
            "cost_usd": round(tts_cost, 5),
            "rate_per_1m_chars": config.GROQ_TTS_COST_PER_1M_CHARS,
        },
        "rag": {
            "total_queries": rag_queries,
            "matched_queries": rag_matches,
            "no_match_queries": rag_no_matches,
            "match_rate_pct": match_rate_pct,
            "avg_similarity": avg_similarity,
            "threshold": config.KB_MIN_SIMILARITY,
        },
        "handoff": {
            "total_escalations": handoff_count,
            "escalation_rate_pct": escalation_rate_pct,
            "by_reason": dict(handoff_reasons),
        },
        "top_intents": sorted(
            [{"intent": k, "count": v} for k, v in intent_distribution.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:8],
        "recent_activity": activity_log[:50],
    }
