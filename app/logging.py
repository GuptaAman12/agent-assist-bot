import contextvars
import json
import logging
from datetime import datetime, timezone

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")

_EXTRA_FIELDS = ("req_id", "req_method", "req_path", "req_status", "req_duration_ms")
# Domain extras actually emitted via extra={...} (handoff, analytics). Without
# listing here JsonFormatter silently drops them - ticket_id/reason were lost.
_ANALYTICS_FIELDS = ("ticket_id", "reason", "error", "event")


def get_request_id() -> str:
    return _request_id_var.get()


def set_request_id(request_id: str) -> None:
    _request_id_var.set(request_id)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _EXTRA_FIELDS + _ANALYTICS_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_configured = False


class ConsoleFormatter(logging.Formatter):
    """Clean, human-readable terminal log formatter for local development."""

    def format(self, record: logging.LogRecord) -> str:
        time_str = datetime.now().strftime("%H:%M:%S")
        level = record.levelname.ljust(5)

        method = getattr(record, "req_method", None)
        path = getattr(record, "req_path", None)

        if method and path:
            status = getattr(record, "req_status", None)
            duration = getattr(record, "req_duration_ms", None)
            req_id = getattr(record, "req_id", None)

            status_str = f"{status}" if status is not None else "---"
            dur_str = f"{duration:0.1f}ms" if isinstance(duration, (int, float)) else f"{duration}ms"

            extras = []
            if req_id:
                extras.append(f"req={req_id}")
            for field in _ANALYTICS_FIELDS:
                val = getattr(record, field, None)
                if val is not None:
                    extras.append(f"{field}={val}")

            extra_part = f" [{', '.join(extras)}]" if extras else ""
            line = f"{time_str} [{level}] {method:<4} {path} -> {status_str} ({dur_str}){extra_part}"
        else:
            msg = record.getMessage()
            line = f"{time_str} [{level}] {record.name}: {msg}"

        if record.exc_info:
            exc = self.formatException(record.exc_info)
            line = f"{line}\n{exc}"
        return line


class ConsoleNoiseFilter(logging.Filter):
    """Filters routine high-frequency noise (static assets, health checks) from console logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        from . import config

        path = getattr(record, "req_path", None)
        status = getattr(record, "req_status", None)
        if path:
            if getattr(config, "LOG_QUIET_STATIC", True) and (path.startswith("/static/") or path == "/favicon.ico"):
                if status is None or (isinstance(status, int) and status < 400):
                    return False
            if getattr(config, "LOG_QUIET_HEALTH", True) and path == "/health":
                if status is None or status == 200:
                    return False
        return True


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    from . import config

    root = logging.getLogger()
    log_level = getattr(logging, getattr(config, "LOG_LEVEL", "INFO"), logging.INFO)
    root.setLevel(log_level)

    handler = logging.StreamHandler()
    log_format = getattr(config, "LOG_FORMAT", "console").lower()
    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(ConsoleFormatter())

    if getattr(config, "LOG_QUIET_STATIC", True) or getattr(config, "LOG_QUIET_HEALTH", True):
        handler.addFilter(ConsoleNoiseFilter())

    root.addHandler(handler)

    # Disable uvicorn's raw access log since app.access handles it with duration & req_id
    logging.getLogger("uvicorn.access").disabled = True

    # Suppress verbose internal logs from third-party libraries
    for noisy in ("httpx", "httpcore", "urllib3", "sentence_transformers", "transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("tensorflow").setLevel(logging.ERROR)


def get_access_logger() -> logging.Logger:
    return logging.getLogger("app.access")
