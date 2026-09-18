import time
import uuid

from fastapi import Request
from fastapi.responses import HTMLResponse

from .dependencies import _has_admin_access
from .logging import get_access_logger, set_request_id
from .routes.admin import _login_page

access_logger = get_access_logger()


async def request_context(request: Request, call_next):
    request_id = uuid.uuid4().hex[:12]
    set_request_id(request_id)
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        if request.url.path.endswith(".html"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = request_id
    except Exception:
        access_logger.exception(
            "request failed",
            extra={
                "req_id": request_id,
                "req_method": request.method,
                "req_path": request.url.path,
            },
        )
        raise
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        access_logger.info(
            "request completed",
            extra={
                "req_id": request_id,
                "req_method": request.method,
                "req_path": request.url.path,
                "req_status": status_code,
                "req_duration_ms": duration_ms,
            },
        )
    return response


async def guard_admin_pages(request: Request, call_next):
    if request.url.path in ("/static/kb.html", "/static/analytics.html") and not _has_admin_access(request):
        return HTMLResponse(_login_page())
    return await call_next(request)
