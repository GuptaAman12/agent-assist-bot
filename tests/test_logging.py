import json
import logging
from app.logging import ConsoleFormatter, ConsoleNoiseFilter, JsonFormatter


def test_console_formatter_standard_message():
    formatter = ConsoleFormatter()
    record = logging.LogRecord(
        name="app.main",
        level=logging.INFO,
        pathname="app/main.py",
        lineno=10,
        msg="Application startup complete.",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    assert "[INFO ] app.main: Application startup complete." in formatted


def test_console_formatter_access_log():
    formatter = ConsoleFormatter()
    record = logging.LogRecord(
        name="app.access",
        level=logging.INFO,
        pathname="app/middleware.py",
        lineno=37,
        msg="request completed",
        args=(),
        exc_info=None,
    )
    record.req_method = "GET"
    record.req_path = "/assist/"
    record.req_status = 200
    record.req_duration_ms = 45.2
    record.req_id = "abc12345"

    formatted = formatter.format(record)
    assert "GET  /assist/ -> 200 (45.2ms) [req=abc12345]" in formatted


def test_console_formatter_access_log_with_handoff():
    formatter = ConsoleFormatter()
    record = logging.LogRecord(
        name="app.access",
        level=logging.INFO,
        pathname="app/middleware.py",
        lineno=37,
        msg="request completed",
        args=(),
        exc_info=None,
    )
    record.req_method = "POST"
    record.req_path = "/assist/"
    record.req_status = 200
    record.req_duration_ms = 120.0
    record.req_id = "xyz987"
    record.ticket_id = "ticket_555"
    record.reason = "speak_to_agent"

    formatted = formatter.format(record)
    assert "POST /assist/ -> 200 (120.0ms)" in formatted
    assert "req=xyz987" in formatted
    assert "ticket_id=ticket_555" in formatted
    assert "reason=speak_to_agent" in formatted


def test_console_formatter_with_exception():
    formatter = ConsoleFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="app.access",
        level=logging.ERROR,
        pathname="app/middleware.py",
        lineno=26,
        msg="request failed",
        args=(),
        exc_info=exc_info,
    )
    formatted = formatter.format(record)
    assert "[ERROR] app.access: request failed" in formatted
    assert "ValueError: boom" in formatted


def test_console_noise_filter_static_and_health(monkeypatch):
    noise_filter = ConsoleNoiseFilter()

    # Routine static file: filtered out
    rec_static = logging.LogRecord("app.access", logging.INFO, "", 1, "req", (), None)
    rec_static.req_path = "/static/style.css"
    rec_static.req_status = 200
    assert noise_filter.filter(rec_static) is False

    # Favicon: filtered out
    rec_fav = logging.LogRecord("app.access", logging.INFO, "", 1, "req", (), None)
    rec_fav.req_path = "/favicon.ico"
    rec_fav.req_status = 200
    assert noise_filter.filter(rec_fav) is False

    # Failed static file (404): kept
    rec_static_404 = logging.LogRecord("app.access", logging.WARNING, "", 1, "req", (), None)
    rec_static_404.req_path = "/static/missing.png"
    rec_static_404.req_status = 404
    assert noise_filter.filter(rec_static_404) is True

    # Routine health check (200): filtered out
    rec_health = logging.LogRecord("app.access", logging.INFO, "", 1, "req", (), None)
    rec_health.req_path = "/health"
    rec_health.req_status = 200
    assert noise_filter.filter(rec_health) is False

    # Failed health check (503): kept
    rec_health_err = logging.LogRecord("app.access", logging.ERROR, "", 1, "req", (), None)
    rec_health_err.req_path = "/health"
    rec_health_err.req_status = 503
    assert noise_filter.filter(rec_health_err) is True

    # Real API endpoint: kept
    rec_api = logging.LogRecord("app.access", logging.INFO, "", 1, "req", (), None)
    rec_api.req_path = "/assist/"
    rec_api.req_status = 200
    assert noise_filter.filter(rec_api) is True


def test_console_noise_filter_disabled(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "LOG_QUIET_STATIC", False)
    monkeypatch.setattr(config, "LOG_QUIET_HEALTH", False)

    noise_filter = ConsoleNoiseFilter()

    rec_static = logging.LogRecord("app.access", logging.INFO, "", 1, "req", (), None)
    rec_static.req_path = "/static/style.css"
    rec_static.req_status = 200
    assert noise_filter.filter(rec_static) is True

    rec_health = logging.LogRecord("app.access", logging.INFO, "", 1, "req", (), None)
    rec_health.req_path = "/health"
    rec_health.req_status = 200
    assert noise_filter.filter(rec_health) is True


def test_json_formatter_preserves_schema():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.access",
        level=logging.INFO,
        pathname="app/middleware.py",
        lineno=37,
        msg="request completed",
        args=(),
        exc_info=None,
    )
    record.req_method = "POST"
    record.req_path = "/assist/"
    record.req_status = 200
    record.req_duration_ms = 15.3
    record.req_id = "req_123"

    payload = json.loads(formatter.format(record))
    assert payload["logger"] == "app.access"
    assert payload["level"] == "INFO"
    assert payload["req_method"] == "POST"
    assert payload["req_path"] == "/assist/"
    assert payload["req_status"] == 200
    assert payload["req_duration_ms"] == 15.3
    assert payload["req_id"] == "req_123"
    assert "ts" in payload
