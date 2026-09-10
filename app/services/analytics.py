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


def get_unmatched_queries(limit: int = 50) -> list[dict]:
    """Read and aggregate unmatched queries from the analytics log for KB curation.
    Returns entries sorted by frequency descending, then recency descending."""
    path = config.ANALYTICS_LOG_PATH
    try:
        if not path.exists():
            return []
    except Exception:
        return []

    groups: dict[str, dict] = {}
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

                norm = transcript.lower()
                ts = rec.get("ts", "")
                intents = rec.get("intents") or []
                handoff = bool(rec.get("handoff"))
                ticket_id = rec.get("ticket_id")

                if norm not in groups:
                    groups[norm] = {
                        "transcript": transcript,
                        "count": 1,
                        "last_seen": ts,
                        "intents": set(intents),
                        "handoff": handoff,
                        "ticket_id": ticket_id,
                    }
                else:
                    g = groups[norm]
                    g["count"] += 1
                    if ts and ts >= g["last_seen"]:
                        g["last_seen"] = ts
                        g["transcript"] = transcript
                        if ticket_id:
                            g["ticket_id"] = ticket_id
                    g["intents"].update(intents)
                    g["handoff"] = g["handoff"] or handoff
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
