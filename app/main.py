"""
LiveDocAI — Main Application Entry Point
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import create_tables
from app.middleware.traffic_capture import TrafficCaptureMiddleware
from app.routers import auth, dashboard, docs_router
from app.routers.logs import router as logs_router
from app.routers.endpoints import router as endpoints_router
from app.routers.github import router as github_router
from app.services.background_tasks import start_background_tasks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    await create_tables()
    logger.info("Database ready ✓")

    bg_task = asyncio.create_task(start_background_tasks())
    logger.info("Background tasks started ✓")

    yield

    bg_task.cancel()
    logger.info(f"{settings.app_name} shut down cleanly.")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─────────────────────────────────────────────────────────────
# CORS (FIXED + SAFE DEFAULT)
# ─────────────────────────────────────────────────────────────

ALLOWED_ORIGINS = set(settings.get_cors_origins() or [])

# FORCE include frontend dev origins (fix your issue)
ALLOWED_ORIGINS.update([
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "https://live-doc-ai.vercel.app"
])

logger.info(f"CORS allowed origins: {ALLOWED_ORIGINS}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# ─────────────────────────────────────────────────────────────
# Middleware
# ─────────────────────────────────────────────────────────────

app.add_middleware(TrafficCaptureMiddleware)

# ─────────────────────────────────────────────────────────────
# Routers
# ─────────────────────────────────────────────────────────────

app.include_router(auth.router)
app.include_router(logs_router)
app.include_router(endpoints_router)
app.include_router(dashboard.router)
app.include_router(docs_router.router)
app.include_router(github_router)

# ─────────────────────────────────────────────────────────────
# Health routes
# ─────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}
