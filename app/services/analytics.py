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
