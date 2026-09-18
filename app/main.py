from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config
from .logging import setup_logging
from .middleware import guard_admin_pages, request_context
from .routes import admin, analytics, assist, handoff, health, kb
from .services.rag import KnowledgeBase
from .services.tts import prune_old_audio

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = config.missing_api_keys()
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)} (check your .env file)")
    app.state.knowledge_base = KnowledgeBase()
    try:
        prune_old_audio()
    except Exception:
        pass  # audio pruning is best-effort; never block startup
    yield


app = FastAPI(title="Agent Assist & Resolution Bot", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")

app.middleware("http")(guard_admin_pages)
app.middleware("http")(request_context)

app.include_router(health.router)
app.include_router(admin.router)
app.include_router(assist.router)
app.include_router(kb.router)
app.include_router(handoff.router)
app.include_router(analytics.router)
