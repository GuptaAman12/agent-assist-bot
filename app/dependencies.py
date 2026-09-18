import json
import threading
import time
from datetime import datetime, timezone

from fastapi import HTTPException, Request

from . import config
from .logging import get_request_id

# Server-side admin sessions: browser holds an opaque session id; restarting
# the app clears this dict, which logs every admin out (no session survives a restart).
ADMIN_SESSIONS: dict[str, str] = {}


def _has_admin_access(request: Request) -> bool:
    if not config.ADMIN_TOKEN:
        return True
    if request.headers.get("X-Admin-Token") == config.ADMIN_TOKEN:
        return True
    session_id = request.cookies.get(config.ADMIN_COOKIE_NAME)
    return session_id in ADMIN_SESSIONS


def require_admin(request: Request) -> None:
    if not _has_admin_access(request):
        raise HTTPException(status_code=401, detail="Missing or invalid admin token")


def get_client_ip(request: Request) -> str:
    if config.TRUST_PROXY_HEADERS:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                return first
    return request.client.host if request.client else "unknown"


def _audit_log(request: Request, action: str, entry_id: str | None = None, extra: dict | None = None) -> None:
    try:
        rid = get_request_id() or request.headers.get("X-Request-ID", "")
        # Admin identity: don't log raw token, just presence
        admin_via = "header" if request.headers.get("X-Admin-Token") == config.ADMIN_TOKEN else ("cookie" if request.cookies.get(config.ADMIN_COOKIE_NAME) in ADMIN_SESSIONS else "open" if not config.ADMIN_TOKEN else "unknown")
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "request_id": rid,
            "admin_via": admin_via,
            "action": action,
            "entry_id": entry_id,
            "ip": get_client_ip(request),
        }
        if extra:
            record.update(extra)
        with open(config.AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass  # audit must never break the request


# ---- Rate limiting (per-IP sliding window) ----

_rate_buckets: dict[str, list[float]] = {}
_rate_lock = threading.Lock()


def check_rate_limit(request: Request) -> None:
    window = config.RATE_LIMIT_WINDOW_SEC
    # Stricter limit for the more expensive transcribe endpoint
    max_req = config.RATE_LIMIT_MAX_TRANSCRIBE if request.url.path.startswith("/transcribe") else config.RATE_LIMIT_MAX_REQUESTS
    if max_req <= 0:
        return
    ip = get_client_ip(request)
    now = time.monotonic()
    cutoff = now - window
    with _rate_lock:
        bucket = _rate_buckets.get(ip)
        if bucket is None:
            bucket = []
            _rate_buckets[ip] = bucket
        # prune
        bucket[:] = [t for t in bucket if t > cutoff]
        if len(bucket) >= max_req:
            retry_after = max(1, int(window - (now - bucket[0])) + 1)
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        bucket.append(now)


def _clear_rate_limit_state() -> None:
    with _rate_lock:
        _rate_buckets.clear()
