"""Transcription service — uses OpenAI Whisper Python package (runs locally, no API key).

Produces a list of timestamped transcript chunks.
Properly handles Hindi, English, and Hinglish (mixed Hindi+English) content.
"""

import logging
import re
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)

# Load whisper model lazily
_model = None


def _get_model():
    global _model
    if _model is None:
        import whisper
        # Use 'small' model for much better Hindi/multilingual accuracy
        # (base model struggles with Hindi script and Hinglish)
        model_name = "small"
        logger.info(f"Loading Whisper '{model_name}' model (first time may download ~461MB)...")
        _model = whisper.load_model(model_name)
        logger.info("Whisper model loaded.")
    return _model


def _detect_language_detail(text: str, whisper_lang: str) -> str:
    """Classify detected language more precisely: english, hindi, or hinglish.

    Whisper just says 'hi' or 'en', but Hinglish (mixed) is common in Indian
    influencer content. We detect it by checking for both Devanagari and Latin.
    """
    devanagari_chars = sum(1 for c in text if '\u0900' <= c <= '\u097F')
    latin_chars = sum(1 for c in text if 'A' <= c <= 'Z' or 'a' <= c <= 'z')
    total = devanagari_chars + latin_chars

    if total == 0:
        return whisper_lang

    deva_ratio = devanagari_chars / total
    latin_ratio = latin_chars / total

    # If both scripts are significantly present (>15% each), it's Hinglish
    if deva_ratio > 0.15 and latin_ratio > 0.15:
        return "hinglish"
    elif deva_ratio > 0.5:
        return "hindi"
    elif whisper_lang == "hi" and latin_ratio > 0.8:
        # Whisper says Hindi but text is mostly Latin = romanized Hindi (also Hinglish)
        return "hinglish"
    elif whisper_lang == "hi":
        return "hindi"
    else:
        return "english"


def _seconds_to_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS,mmm format for SRT."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def transcribe(video_path: str, language_hint: str | None = None) -> dict:
    """Transcribe a video file using OpenAI Whisper (local).

    Args:
        video_path: Path to the video/audio file.
        language_hint: Optional language hint ('hi', 'en'). If None, auto-detect.

    Returns:
        {
            "full_text": "...",
            "chunks": [{"start": 0.0, "end": 3.04, "text": "..."}, ...],
            "language": "hindi" | "english" | "hinglish",
            "whisper_lang": "hi" | "en" | ...  (raw whisper code)
        }
    """
    logger.info(f"Transcribing: {video_path} (hint={language_hint})")
    model = _get_model()

    # Whisper options for better Hindi/multilingual handling
    options = {
        "verbose": False,
        "word_timestamps": True,  # needed for word-level captions
    }
    if language_hint:
        options["language"] = language_hint

    result = model.transcribe(str(video_path), **options)

    whisper_lang = result.get("language", "unknown")

    # Build chunks from segments
    chunks: List[Dict] = []
    for segment in result.get("segments", []):
        text = segment["text"].strip()
        if not text:
            continue

        chunk = {
            "start": segment["start"],
            "end": segment["end"],
            "text": text,
        }

        # Include word-level timestamps if available
        if "words" in segment:
            chunk["words"] = [
                {
                    "word": w.get("word", w.get("text", "")).strip(),
                    "start": w["start"],
                    "end": w["end"],
                }
                for w in segment["words"]
                if w.get("word", w.get("text", "")).strip()
            ]

        chunks.append(chunk)

    full_text = result.get("text", "").strip()
    language = _detect_language_detail(full_text, whisper_lang)

    logger.info(
        f"Transcription done: {len(chunks)} segments, {len(full_text)} chars, "
        f"whisper_lang={whisper_lang}, detected={language}"
    )
    return {
        "full_text": full_text,
        "chunks": chunks,
        "language": language,
        "whisper_lang": whisper_lang,
    }


def generate_srt(chunks: List[Dict], output_path: str) -> str:
    """Generate an SRT subtitle file from transcript chunks."""
    lines = []
    for i, chunk in enumerate(chunks, 1):
        start = _seconds_to_timestamp(chunk["start"])
        end = _seconds_to_timestamp(chunk["end"])
        lines.append(f"{i}")
        lines.append(f"{start} --> {end}")
        lines.append(chunk["text"])
        lines.append("")

    srt_content = "\n".join(lines)
    Path(output_path).write_text(srt_content, encoding="utf-8")
    return output_path
