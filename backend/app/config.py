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
# Default to llama3.1:8b — meaningfully better than llama3 for clip detection / hooks.
# Override with OLLAMA_MODEL=qwen2.5:14b for even higher quality if you have RAM.
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

# ---------- Whisper / Transcription ----------
# Engine: "auto" (prefer faster-whisper, fallback openai-whisper),
#         "faster-whisper", or "openai-whisper".
# NOTE: faster-whisper downloads weights from huggingface.co — if that's
# blocked by your network proxy, set WHISPER_ENGINE=openai-whisper.
WHISPER_ENGINE = os.getenv("WHISPER_ENGINE", "auto")
# Model size: tiny / base / small / medium / large-v3 / distil-large-v3
# medium = good Hindi/Hinglish balance on CPU
# small = faster, already cached on most setups, decent quality
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "medium")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")  # "cpu" / "cuda" / "auto"
# int8 = fastest on CPU; float16 on CUDA
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

# Legacy whisper.cpp config (kept for backward compat — unused by current engine)
WHISPER_CPP_PATH = os.getenv("WHISPER_CPP_PATH", "./whisper.cpp/main")
WHISPER_MODEL_PATH = os.getenv("WHISPER_MODEL_PATH", "./whisper.cpp/models/ggml-base.en.bin")

# ---------- FFmpeg ----------
FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")

# ---------- Editing style ----------
# Caption style preset: "hormozi" (big yellow word-pop), "mrbeast" (white pop + outline),
# "minimal" (clean white with shadow), "bold" (full-line current-word highlight)
CAPTION_STYLE = os.getenv("CAPTION_STYLE", "hormozi")
# Show 1-3 word "pop" captions (influencer-style) instead of full-line subtitles
WORD_POP_CAPTIONS = os.getenv("WORD_POP_CAPTIONS", "true").lower() == "true"
# Add audio-driven punch-in zooms on emphasis words
PUNCH_ZOOMS = os.getenv("PUNCH_ZOOMS", "true").lower() == "true"
# Add hook intro overlay (clip title for first ~1.2s)
HOOK_INTRO = os.getenv("HOOK_INTRO", "true").lower() == "true"
# Add CTA endcard ("Follow for more", last ~1.2s)
CTA_ENDCARD = os.getenv("CTA_ENDCARD", "true").lower() == "true"
CTA_TEXT = os.getenv("CTA_TEXT", "FOLLOW FOR MORE")
# Smooth speaker tracking (per-second face track w/ EMA) instead of one-shot crop
SMOOTH_SPEAKER_TRACK = os.getenv("SMOOTH_SPEAKER_TRACK", "true").lower() == "true"
# Trim long silent gaps from each clip (tightens pacing, influencer-style)
TRIM_SILENCES = os.getenv("TRIM_SILENCES", "false").lower() == "true"
SILENCE_THRESHOLD_DB = float(os.getenv("SILENCE_THRESHOLD_DB", "-30"))
SILENCE_MIN_DURATION = float(os.getenv("SILENCE_MIN_DURATION", "0.5"))
SILENCE_PADDING = float(os.getenv("SILENCE_PADDING", "0.1"))
# Trim filler words ("um", "uh", "matlab", "you know"...) using word-level timestamps
TRIM_FILLER_WORDS = os.getenv("TRIM_FILLER_WORDS", "true").lower() == "true"
FILLER_PAD_MS = int(os.getenv("FILLER_PAD_MS", "40"))  # tighten cuts a touch around each filler

# ---------- Cors ----------
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
