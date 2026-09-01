import smtplib
import uuid
from datetime import datetime, timezone
from email.mime.text import MIMEText

import requests

from .. import config
from ..logging import get_request_id

import logging

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
            logger.warning(
                "handoff webhook failed",
                extra={"req_id": req_id, "ticket_id": ticket_id, "error": str(exc)},
            )
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
