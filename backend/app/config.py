"""Application configuration loaded from environment variables."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ---------- Paths ----------
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
CLIPS_DIR = BASE_DIR / "clips"
UPLOAD_DIR.mkdir(exist_ok=True)
CLIPS_DIR.mkdir(exist_ok=True)

# ---------- Database ----------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite+aiosqlite:///{BASE_DIR / 'clipflow.db'}",
)

# ---------- JWT Auth ----------
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# ---------- Ollama (local LLM) ----------
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

# ---------- Whisper.cpp ----------
WHISPER_CPP_PATH = os.getenv("WHISPER_CPP_PATH", "./whisper.cpp/main")
WHISPER_MODEL_PATH = os.getenv(
    "WHISPER_MODEL_PATH", "./whisper.cpp/models/ggml-base.en.bin"
)

# ---------- FFmpeg ----------
FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")

# ---------- Cors ----------
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
