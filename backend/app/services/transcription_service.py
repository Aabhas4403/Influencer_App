"""Transcription service.

Primary engine: **faster-whisper** (CTranslate2-backed Whisper).
  - 4-10x faster than openai-whisper on CPU
  - Better accuracy at the same model size
  - Built-in Silero VAD filtering removes silences for tighter word timestamps
  - Native word-level timestamps

Fallback: **openai-whisper** (so existing installs keep working).

Designed for Hindi / English / Hinglish creator content.
"""

import logging
from pathlib import Path
from typing import List, Dict, Optional

from app.config import (
    WHISPER_ENGINE,
    WHISPER_MODEL_SIZE,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DEVICE,
)

logger = logging.getLogger(__name__)

# Lazy model cache
_fw_model = None
_ow_model = None


# ─────────────────────────── Engine loaders ───────────────────────────

def _load_faster_whisper():
    """Load a faster-whisper model (CTranslate2)."""
    global _fw_model
    if _fw_model is not None:
        return _fw_model
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        logger.warning(f"faster-whisper not installed ({e}); falling back to openai-whisper")
        return None

    logger.info(
        f"Loading faster-whisper model='{WHISPER_MODEL_SIZE}' "
        f"device='{WHISPER_DEVICE}' compute='{WHISPER_COMPUTE_TYPE}' "
        f"(first run downloads weights)..."
    )
    try:
        _fw_model = WhisperModel(
            WHISPER_MODEL_SIZE,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
        logger.info("faster-whisper loaded.")
        return _fw_model
    except Exception as e:
        # Common case: HuggingFace is blocked by a corporate proxy (Zscaler etc.)
        logger.warning(
            f"faster-whisper unavailable ({type(e).__name__}: {e}); "
            "falling back to openai-whisper. To use faster-whisper, ensure "
            "huggingface.co is reachable or pre-download weights to "
            "~/.cache/huggingface/hub/models--Systran--faster-whisper-<size>/."
        )
        return None


def _load_openai_whisper():
    """Load openai-whisper as fallback."""
    global _ow_model
    if _ow_model is not None:
        return _ow_model
    try:
        import whisper
    except ImportError as e:
        raise RuntimeError(
            "Neither faster-whisper nor openai-whisper is installed. "
            "Run: pip install faster-whisper"
        ) from e

    name = WHISPER_MODEL_SIZE
    if name == "distil-large-v3":
        name = "medium"  # closest fallback
    logger.info(f"Loading openai-whisper '{name}' (fallback)...")
    _ow_model = whisper.load_model(name)
    logger.info("openai-whisper loaded.")
    return _ow_model


# ─────────────────────────── Language helpers ───────────────────────────

def _detect_language_detail(text: str, whisper_lang: str) -> str:
    """Classify language as english / hindi / hinglish."""
    devanagari = sum(1 for c in text if "\u0900" <= c <= "\u097F")
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    total = devanagari + latin
    if total == 0:
        return whisper_lang or "english"

    deva_ratio = devanagari / total
    latin_ratio = latin / total

    if deva_ratio > 0.15 and latin_ratio > 0.15:
        return "hinglish"
    if deva_ratio > 0.5:
        return "hindi"
    if whisper_lang == "hi" and latin_ratio > 0.8:
        return "hinglish"
    if whisper_lang == "hi":
        return "hindi"
    return "english"


def _seconds_to_timestamp(seconds: float) -> str:
    """SRT timestamp HH:MM:SS,mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ─────────────────────────── Faster-whisper path ───────────────────────────

def _transcribe_faster_whisper(video_path: str, language_hint: Optional[str], model) -> dict:
    segments_iter, info = model.transcribe(
        str(video_path),
        language=language_hint,
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=True,
    )

    chunks: List[Dict] = []
    full_parts: List[str] = []

    for seg in segments_iter:
        text = (seg.text or "").strip()
        if not text:
            continue
        chunk = {"start": float(seg.start), "end": float(seg.end), "text": text}
        if seg.words:
            chunk["words"] = [
                {
                    "word": (w.word or "").strip(),
                    "start": float(w.start) if w.start is not None else float(seg.start),
                    "end": float(w.end) if w.end is not None else float(seg.end),
                    "probability": float(getattr(w, "probability", 1.0) or 1.0),
                }
                for w in seg.words
                if (w.word or "").strip()
            ]
        chunks.append(chunk)
        full_parts.append(text)

    full_text = " ".join(full_parts).strip()
    whisper_lang = info.language or "unknown"
    language = _detect_language_detail(full_text, whisper_lang)

    logger.info(
        f"faster-whisper: {len(chunks)} segments, {len(full_text)} chars, "
        f"detected_lang={whisper_lang} (refined={language}), "
        f"prob={info.language_probability:.2f}"
    )
    return {
        "full_text": full_text,
        "chunks": chunks,
        "language": language,
        "whisper_lang": whisper_lang,
        "engine": "faster-whisper",
    }


# ─────────────────────────── openai-whisper fallback ───────────────────────────

def _transcribe_openai_whisper(video_path: str, language_hint: Optional[str], model) -> dict:
    options = {"verbose": False, "word_timestamps": True}
    if language_hint:
        options["language"] = language_hint
    result = model.transcribe(str(video_path), **options)
    whisper_lang = result.get("language", "unknown")

    chunks: List[Dict] = []
    for seg in result.get("segments", []):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        chunk = {"start": seg["start"], "end": seg["end"], "text": text}
        if "words" in seg:
            chunk["words"] = [
                {
                    "word": (w.get("word", w.get("text", "")) or "").strip(),
                    "start": w["start"],
                    "end": w["end"],
                    "probability": float(w.get("probability", 1.0)),
                }
                for w in seg["words"]
                if (w.get("word", w.get("text", "")) or "").strip()
            ]
        chunks.append(chunk)

    full_text = (result.get("text") or "").strip()
    language = _detect_language_detail(full_text, whisper_lang)

    logger.info(
        f"openai-whisper: {len(chunks)} segments, {len(full_text)} chars, "
        f"detected_lang={whisper_lang} (refined={language})"
    )
    return {
        "full_text": full_text,
        "chunks": chunks,
        "language": language,
        "whisper_lang": whisper_lang,
        "engine": "openai-whisper",
    }


# ─────────────────────────── Public API ───────────────────────────

def transcribe(video_path: str, language_hint: Optional[str] = None) -> dict:
    """Transcribe a video / audio file.

    Returns:
        {
            "full_text": str,
            "chunks": [{"start", "end", "text", "words"}],
            "language": "hindi" | "english" | "hinglish",
            "whisper_lang": str,
            "engine": str
        }
    """
    logger.info(
        f"Transcribing: {video_path} (engine_pref={WHISPER_ENGINE}, hint={language_hint})"
    )

    if WHISPER_ENGINE in ("auto", "faster-whisper"):
        model = _load_faster_whisper()
        if model is not None:
            return _transcribe_faster_whisper(video_path, language_hint, model)

    model = _load_openai_whisper()
    return _transcribe_openai_whisper(video_path, language_hint, model)


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
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    return output_path


def flatten_words(chunks: List[Dict]) -> List[Dict]:
    """Flatten word-level timestamps from chunks into a single list.

    Returns: [{"word", "start", "end", "probability"}, ...]
    If word-level data is missing, fake even-spaced timings.
    """
    words: List[Dict] = []
    for chunk in chunks:
        if chunk.get("words"):
            words.extend(chunk["words"])
            continue
        toks = chunk["text"].split()
        if not toks:
            continue
        dur = max(chunk["end"] - chunk["start"], 0.001)
        per = dur / len(toks)
        for i, w in enumerate(toks):
            words.append({
                "word": w,
                "start": chunk["start"] + i * per,
                "end": chunk["start"] + (i + 1) * per,
                "probability": 1.0,
            })
    return words
