import json
import logging
import os
import random
import smtplib
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from email.mime.text import MIMEText

import requests

from .. import config
from ..logging import get_request_id

logger = logging.getLogger("app.handoff")

_queue_lock = threading.Lock()
_worker_thread: threading.Thread | None = None
_worker_stop_event = threading.Event()


def create_ticket(
    *,
    reason: str,
    transcript: str,
    intents: list[str],
    assistant_response: str,
) -> str | None:
    """Open a support ticket for a human handoff. Best-effort: never raises.
    Returns a ticket id, or None if every delivery method failed."""
    ticket_id = uuid.uuid4().hex[:8]
    payload = {
        "ticket_id": ticket_id,
        "type": "human_handoff",
        "reason": reason,
        "transcript": transcript,
        "intents": intents,
        "assistant_response": assistant_response,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    req_id = get_request_id()

    if config.HANDOFF_WEBHOOK_URL:
        for attempt in range(3):
            try:
                res = requests.post(
                    config.HANDOFF_WEBHOOK_URL,
                    json=payload,
                    timeout=config.HANDOFF_TIMEOUT_SEC,
                )
                res.raise_for_status()
                logger.info(
                    "handoff ticket sent to webhook",
                    extra={"req_id": req_id, "ticket_id": ticket_id, "reason": reason},
                )
                return ticket_id
            except Exception as exc:
                if attempt < 2:
                    delay = 0.5 * (2**attempt) + random.uniform(0, 0.5)
                    time.sleep(delay)
                    continue
                logger.warning(
                    "handoff webhook failed after retries",
                    extra={"req_id": req_id, "ticket_id": ticket_id, "error": str(exc)},
                )
                _queue_to_disk(payload)
                return None

    if config.HANDOFF_EMAIL_TO:
        try:
            _send_email(payload)
            logger.info(
                "handoff ticket emailed",
                extra={"req_id": req_id, "ticket_id": ticket_id, "reason": reason},
            )
            return ticket_id
        except Exception as exc:
            logger.warning(
                "handoff email failed",
                extra={"req_id": req_id, "ticket_id": ticket_id, "error": str(exc)},
            )
            _queue_to_disk(payload)
            return None

    # No webhook or email configured: still record the handoff locally.
    logger.info(
        "handoff ticket created (no webhook/email configured)",
        extra={"req_id": req_id, "ticket_id": ticket_id, "reason": reason},
    )
    return ticket_id


def _send_email(payload: dict) -> None:
    body = (
        f"Ticket {payload['ticket_id']} ({payload['reason']})\n\n"
        f"Transcript: {payload['transcript']}\n\n"
        f"Assistant response: {payload['assistant_response']}\n\n"
        f"Intents: {', '.join(payload['intents'])}"
    )
    msg = MIMEText(body)
    msg["Subject"] = f"[Support] Human handoff - {payload['reason']}"
    msg["From"] = config.HANDOFF_EMAIL_FROM or config.HANDOFF_EMAIL_TO
    msg["To"] = config.HANDOFF_EMAIL_TO

    if config.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT) as server:
            _maybe_login(server)
            server.send_message(msg)
    else:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.starttls()
            _maybe_login(server)
            server.send_message(msg)


def _maybe_login(server) -> None:
    if config.SMTP_USER:
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)


def _deliver_payload(payload: dict) -> bool:
    """Attempt a single delivery of a ticket payload to webhook or email."""
    if config.HANDOFF_WEBHOOK_URL:
        try:
            res = requests.post(
                config.HANDOFF_WEBHOOK_URL,
                json=payload,
                timeout=config.HANDOFF_TIMEOUT_SEC,
            )
            res.raise_for_status()
            return True
        except Exception as exc:
            logger.warning(
                "handoff webhook replay failed",
                extra={"ticket_id": payload.get("ticket_id"), "error": str(exc)},
            )
            return False

    if config.HANDOFF_EMAIL_TO:
        try:
            _send_email(payload)
            return True
        except Exception as exc:
            logger.warning(
                "handoff email replay failed",
                extra={"ticket_id": payload.get("ticket_id"), "error": str(exc)},
            )
            return False

    return False


def _read_queue_file() -> list[dict]:
    """Read all queued tickets from disk. Never raises."""
    tickets = []
    try:
        if config.HANDOFF_QUEUE_PATH.exists():
            with open(config.HANDOFF_QUEUE_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if isinstance(data, dict):
                            tickets.append(data)
                    except Exception:
                        continue
    except Exception as exc:
        logger.warning("failed to read handoff queue", extra={"error": str(exc)})
    return tickets


def _write_queue_file(tickets: list[dict]) -> None:
    """Atomically rewrite the queue file. Never raises."""
    try:
        parent = config.HANDOFF_QUEUE_PATH.parent
        parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=parent, prefix="handoff_queue_", suffix=".tmp")
        with open(fd, "w", encoding="utf-8") as f:
            for t in tickets:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
        os.replace(tmp_path, config.HANDOFF_QUEUE_PATH)
    except Exception as exc:
        logger.warning("failed to write handoff queue", extra={"error": str(exc)})


def _queue_to_disk(payload: dict) -> None:
    with _queue_lock:
        try:
            parent = config.HANDOFF_QUEUE_PATH.parent
            parent.mkdir(parents=True, exist_ok=True)
            with open(config.HANDOFF_QUEUE_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            logger.info(
                "handoff queued to disk",
                extra={"req_id": get_request_id(), "ticket_id": payload["ticket_id"]},
            )
        except Exception as exc:
            logger.warning(
                "handoff queue failed",
                extra={"req_id": get_request_id(), "ticket_id": payload["ticket_id"], "error": str(exc)},
            )


def get_queued_tickets() -> list[dict]:
    """Return all currently queued tickets, newest first."""
    with _queue_lock:
        return list(reversed(_read_queue_file()))


def replay_ticket(ticket_id: str) -> dict:
    """Attempt replay of a specific ticket by id. Removes it on success."""
    with _queue_lock:
        tickets = _read_queue_file()
        idx = next((i for i, t in enumerate(tickets) if t.get("ticket_id") == ticket_id), None)
        if idx is None:
            return {"success": False, "error": "not_found", "ticket_id": ticket_id}
        ticket = tickets[idx]
        delivered = _deliver_payload(ticket)
        if delivered:
            tickets.pop(idx)
            _write_queue_file(tickets)
            logger.info(
                "handoff ticket replayed",
                extra={"ticket_id": ticket_id, "reason": ticket.get("reason")},
            )
            return {"success": True, "ticket_id": ticket_id, "remaining": len(tickets)}
        return {"success": False, "ticket_id": ticket_id, "error": "delivery_failed", "remaining": len(tickets)}


def replay_all_queued() -> dict:
    """Attempt replay of all queued tickets. Updates disk with remaining failures."""
    with _queue_lock:
        tickets = _read_queue_file()
        if not tickets:
            return {"replayed": 0, "failed": 0, "remaining": 0}
        succeeded = []
        failed = []
        for t in tickets:
            if _deliver_payload(t):
                succeeded.append(t)
                logger.info(
                    "handoff ticket replayed",
                    extra={"ticket_id": t.get("ticket_id"), "reason": t.get("reason")},
                )
            else:
                failed.append(t)
        if succeeded:
            _write_queue_file(failed)
        return {"replayed": len(succeeded), "failed": len(failed), "remaining": len(failed)}


def dismiss_ticket(ticket_id: str) -> bool:
    """Dismiss and remove a single ticket from the queue."""
    with _queue_lock:
        tickets = _read_queue_file()
        remaining = [t for t in tickets if t.get("ticket_id") != ticket_id]
        if len(remaining) == len(tickets):
            return False
        _write_queue_file(remaining)
        logger.info("handoff ticket dismissed", extra={"ticket_id": ticket_id})
        return True


def _worker_loop() -> None:
    while not _worker_stop_event.is_set():
        interval = getattr(config, "HANDOFF_RETRY_INTERVAL_SEC", 300)
        if interval <= 0:
            break
        if _worker_stop_event.wait(timeout=interval):
            break
        try:
            if config.HANDOFF_WEBHOOK_URL or config.HANDOFF_EMAIL_TO:
                replay_all_queued()
        except Exception as exc:
            logger.warning("background handoff worker sweep failed", extra={"error": str(exc)})


def start_worker() -> None:
    """Start the periodic background replay worker if enabled."""
    global _worker_thread
    interval = getattr(config, "HANDOFF_RETRY_INTERVAL_SEC", 300)
    if interval <= 0:
        return
    if _worker_thread is not None and _worker_thread.is_alive():
        return
    _worker_stop_event.clear()
    _worker_thread = threading.Thread(target=_worker_loop, name="handoff-worker", daemon=True)
    _worker_thread.start()


def stop_worker() -> None:
    """Stop the periodic background replay worker cleanly."""
    global _worker_thread
    _worker_stop_event.set()
    if _worker_thread is not None and _worker_thread.is_alive():
        _worker_thread.join(timeout=2.0)
        _worker_thread = None
