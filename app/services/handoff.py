import json
import logging
import random
import smtplib
import time
import uuid
from datetime import datetime, timezone
from email.mime.text import MIMEText

import requests

from .. import config
from ..logging import get_request_id

logger = logging.getLogger("app.handoff")


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


def _queue_to_disk(payload: dict) -> None:
    try:
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
