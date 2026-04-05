"""FastAPI application entry point."""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import CORS_ORIGINS, CLIPS_DIR, UPLOAD_DIR, BASE_DIR
from app.database import init_db
from app.routes import auth, projects, clips

# ── Logging ──
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_DIR / "clipflow.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger("clipflow")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create DB tables on startup."""
    await init_db()
    yield


app = FastAPI(title="ClipFlow API", version="0.1.0", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve processed clips and uploads as static files
app.mount("/clips", StaticFiles(directory=str(CLIPS_DIR)), name="clips")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# Routes
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(clips.router, prefix="/api/clips", tags=["clips"])


@app.get("/api/health")
async def health():
    return {"status": "ok"}
