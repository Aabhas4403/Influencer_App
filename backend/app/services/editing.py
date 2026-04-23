"""Influencer-style editing primitives.

This module provides the building blocks that turn a raw cut into a reel that
looks like it was edited by a top creator agency:

  - **Smooth speaker tracking** (continuous face track + EMA smoothing) so the
    9:16 crop pans with the speaker instead of being a static center crop.
  - **Audio-energy punch-ins**: detect emphasis peaks in the audio and emit
    short zoom-in moments that ride the cadence.
  - **Word-pop captions** in multiple style presets (Hormozi / MrBeast /
    Minimal / Bold) — 1-3 words on screen at a time, current word highlighted,
    bounce-in animation per word.
  - **Hook intro card** at the very start with the clip title.
  - **CTA endcard** at the end.

All renderers produce transparent RGBA frame streams piped to FFmpeg.
"""

from __future__ import annotations

import logging
import math
import re
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Iterable

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.config import FFMPEG_PATH

logger = logging.getLogger(__name__)


# ─────────────────────────── Font discovery ───────────────────────────

# macOS / common font locations
_FONT_CANDIDATES = {
    "english_bold": [
        "/System/Library/Fonts/Helvetica.ttc",         # idx 1 = Bold
        "/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ],
    "english_black": [
        "/System/Library/Fonts/Helvetica.ttc",         # idx 8 = Black
        "/System/Library/Fonts/Avenir Next.ttc",       # idx 4 = Heavy
        "/Library/Fonts/Arial Black.ttf",
    ],
    "devanagari": [
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Kohinoor.ttc",
        "/System/Library/Fonts/Supplemental/DevanagariMT.ttc",
    ],
}


def _try_font(path: str, size: int, index: Optional[int] = None) -> Optional[ImageFont.FreeTypeFont]:
    if not Path(path).exists():
        return None
    try:
        return ImageFont.truetype(path, size, index=index) if index is not None else ImageFont.truetype(path, size)
    except Exception:
        return None


def get_font(size: int, language: str = "english", weight: str = "bold") -> ImageFont.FreeTypeFont:
    """Get a Pillow font that supports the language. weight: 'bold' or 'black'."""
    if language in ("hindi", "hinglish"):
        for p in _FONT_CANDIDATES["devanagari"]:
            f = _try_font(p, size)
            if f:
                return f

    if weight == "black":
        # Helvetica.ttc index 8 is Black on macOS
        f = _try_font("/System/Library/Fonts/Helvetica.ttc", size, 8)
        if f:
            return f
        for p in _FONT_CANDIDATES["english_black"]:
            f = _try_font(p, size)
            if f:
                return f

    f = _try_font("/System/Library/Fonts/Helvetica.ttc", size, 1)  # Bold
    if f:
        return f
    for p in _FONT_CANDIDATES["english_bold"]:
        f = _try_font(p, size)
        if f:
            return f

    return ImageFont.load_default()


def detect_script(text: str) -> str:
    devanagari = sum(1 for c in text if "\u0900" <= c <= "\u097F")
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    return "hindi" if devanagari > latin else "english"


# ─────────────────────────── ffprobe helpers ───────────────────────────

def get_dims(video_path: str) -> Tuple[int, int]:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", video_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        w, h = r.stdout.strip().split("x")
        return int(w), int(h)
    except Exception:
        return 0, 0


def get_fps(video_path: str) -> float:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=r_frame_rate",
           "-of", "default=noprint_wrappers=1:nokey=1", video_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        num, den = r.stdout.strip().split("/")
        return float(num) / float(den)
    except Exception:
        return 30.0


def get_duration(video_path: str) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", video_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


# ─────────────────────────── Silence trimming ───────────────────────────

def detect_silences(
    input_path: str,
    threshold_db: float = -30.0,
    min_duration: float = 0.5,
) -> List[Tuple[float, float]]:
    """Run FFmpeg `silencedetect` and return list of (start, end) silent ranges (seconds)."""
    cmd = [
        FFMPEG_PATH, "-hide_banner", "-nostats", "-i", input_path,
        "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration}",
        "-f", "null", "-",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    silences: List[Tuple[float, float]] = []
    cur_start: Optional[float] = None
    for line in r.stderr.splitlines():
        if "silence_start:" in line:
            try:
                cur_start = float(line.split("silence_start:")[1].strip().split()[0])
            except Exception:
                cur_start = None
        elif "silence_end:" in line and cur_start is not None:
            try:
                tok = line.split("silence_end:")[1].strip().split()[0].rstrip(",")
                silences.append((cur_start, float(tok)))
            except Exception:
                pass
            cur_start = None
    return silences


def trim_silences(
    input_path: str,
    output_path: str,
    threshold_db: float = -30.0,
    min_duration: float = 0.5,
    padding: float = 0.1,
) -> bool:
    """Remove silent ranges from a video, keeping `padding` seconds around speech.

    Re-encodes audio+video together using FFmpeg `select`/`aselect` filters so
    A/V stays in sync. Returns True if any silence was removed.
    """
    duration = get_duration(input_path)
    if duration <= 0:
        return False
    silences = detect_silences(input_path, threshold_db, min_duration)
    if not silences:
        return False

    # Build keep ranges (inverse of silence ranges, expanded by padding).
    keep: List[Tuple[float, float]] = []
    cursor = 0.0
    for s, e in silences:
        keep_end = min(duration, s + padding)
        if keep_end > cursor:
            keep.append((cursor, keep_end))
        cursor = max(cursor, e - padding)
    if cursor < duration:
        keep.append((cursor, duration))

    # Drop sub-frame ranges
    keep = [(s, e) for s, e in keep if e - s > 0.05]
    if not keep:
        return False

    # Bail if there's nothing meaningful to remove (<5% reduction)
    kept_dur = sum(e - s for s, e in keep)
    if kept_dur >= duration * 0.95:
        return False

    expr = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in keep)
    vf = f"select='{expr}',setpts=N/FRAME_RATE/TB"
    af = f"aselect='{expr}',asetpts=N/SR/TB"

    cmd = [
        FFMPEG_PATH, "-y", "-i", input_path,
        "-vf", vf, "-af", af,
        "-c:v", "libx264", "-preset", "fast", "-crf", "21",
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        logger.warning(f"trim_silences failed: {r.stderr[-300:]}")
        return False
    logger.info(
        f"trim_silences: {duration:.2f}s → {kept_dur:.2f}s "
        f"({len(silences)} silent gaps removed)"
    )
    return True


# ─────────────────────────── Filler-word jump cuts ───────────────────────────

# Single-token fillers (English + Hindi/Hinglish/common). Matched after stripping
# punctuation and lowercasing. Multi-word phrases are handled separately.
FILLER_WORDS_SINGLE = {
    # English
    "um", "umm", "uh", "uhh", "uhm", "er", "err", "ah", "ahh", "eh", "hmm", "hm",
    "like", "literally", "basically", "actually", "honestly",
    # Hindi / Hinglish discourse fillers
    "matlab", "yaani", "yani", "haan", "han", "haa", "achha", "achchha",
    "toh", "to", "bhai", "yaar", "arre", "are", "arrey",
    # Devanagari spellings
    "मतलब", "यानी", "हाँ", "हां", "अच्छा", "तो", "भाई", "यार", "अरे",
}

# Multi-word filler phrases (lowercase, space-separated). Matched against
# windows of consecutive words.
FILLER_PHRASES = [
    ("you", "know"),
    ("i", "mean"),
    ("sort", "of"),
    ("kind", "of"),
    ("aap", "jaante", "hain"),
    ("samajh", "rahe", "ho"),
]


def _normalize_word(w: str) -> str:
    """Lowercase + strip surrounding punctuation (keeps Devanagari intact)."""
    return re.sub(r"^[\W_]+|[\W_]+$", "", w.lower(), flags=re.UNICODE)


def find_filler_ranges(words: List[Dict], pad_ms: int = 40) -> List[Tuple[float, float]]:
    """Return (start, end) ranges (seconds, relative to the words' own time base)
    that should be cut as filler. Adjacent ranges are merged."""
    if not words:
        return []
    pad = pad_ms / 1000.0
    norm = [_normalize_word(w["word"]) for w in words]
    raw: List[Tuple[float, float]] = []
    n = len(words)
    i = 0
    while i < n:
        # Try multi-word phrase first
        matched = False
        for phrase in FILLER_PHRASES:
            L = len(phrase)
            if i + L <= n and tuple(norm[i:i + L]) == phrase:
                start = max(0.0, words[i]["start"] - pad)
                end = words[i + L - 1]["end"] + pad
                raw.append((start, end))
                i += L
                matched = True
                break
        if matched:
            continue
        if norm[i] in FILLER_WORDS_SINGLE:
            start = max(0.0, words[i]["start"] - pad)
            end = words[i]["end"] + pad
            raw.append((start, end))
        i += 1

    if not raw:
        return []

    # Merge overlapping / touching ranges
    raw.sort()
    merged: List[Tuple[float, float]] = [raw[0]]
    for s, e in raw[1:]:
        ls, le = merged[-1]
        if s <= le + 0.05:
            merged[-1] = (ls, max(le, e))
        else:
            merged.append((s, e))
    return merged


def trim_ranges(input_path: str, output_path: str, drop_ranges: List[Tuple[float, float]]) -> bool:
    """Drop arbitrary (start, end) ranges from a video, re-encoding to keep A/V in sync."""
    duration = get_duration(input_path)
    if duration <= 0 or not drop_ranges:
        return False

    # Build keep ranges (inverse of drop, clipped to duration)
    drop_clipped = [(max(0.0, s), min(duration, e)) for s, e in drop_ranges if e > s]
    drop_clipped.sort()
    keep: List[Tuple[float, float]] = []
    cursor = 0.0
    for s, e in drop_clipped:
        if s > cursor:
            keep.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < duration:
        keep.append((cursor, duration))
    keep = [(s, e) for s, e in keep if e - s > 0.05]
    if not keep:
        return False

    kept_dur = sum(e - s for s, e in keep)
    if kept_dur >= duration * 0.99:  # less than 1% trimmed → not worth re-encoding
        return False

    expr = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in keep)
    vf = f"select='{expr}',setpts=N/FRAME_RATE/TB"
    af = f"aselect='{expr}',asetpts=N/SR/TB"

    cmd = [
        FFMPEG_PATH, "-y", "-i", input_path,
        "-vf", vf, "-af", af,
        "-c:v", "libx264", "-preset", "fast", "-crf", "21",
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        logger.warning(f"trim_ranges failed: {r.stderr[-300:]}")
        return False
    logger.info(
        f"trim_ranges: {duration:.2f}s → {kept_dur:.2f}s "
        f"({len(drop_clipped)} ranges removed)"
    )
    return True


# ─────────────────────────── Speaker tracking ───────────────────────────

_face_cascade = None


def _get_cascade():
    global _face_cascade
    if _face_cascade is None:
        _face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
    return _face_cascade


@dataclass
class TrackPoint:
    t: float           # seconds (relative to clip start)
    cx: float          # speaker / group center X in source coords
    cw: float          # desired crop width in source pixels (widens for multi-speakers)
    confidence: float  # 0..1


def track_speaker_grid(
    video_path: str,
    start: float,
    duration: float,
    src_w: int,
    src_h: int,
    base_crop_w: int,
    grid_cols: int = 3,
    grid_rows: int = 3,
    sample_hz: float = 2.0,
) -> List[TrackPoint]:
    """Grid-based active-speaker tracking.

    The frame is divided into a `grid_rows x grid_cols` grid (default 3x3).
    At every tick we score *every* cell continuously by:
        score = motion_in_cell × face_boost
    where motion is the mean abs pixel diff between two frames sampled
    ~120 ms apart, and face_boost is 2.5× if a detected face center lies
    inside the cell (1.0× otherwise).

    The winning cell drives the crop center. When several cells score
    near-equally (≥ 60 % of the best), we widen the crop to enclose them —
    producing the dynamic "zoom out to show both speakers" behavior.

    This is more robust than face-only tracking because it still picks up
    speakers whose faces fail Haar detection (profile views, side angles,
    partial occlusion), since their gestures and mouth motion still register
    as motion in their cell.
    """
    points: List[TrackPoint] = []
    try:
        cap = cv2.VideoCapture(video_path)
        cap_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n_samples = max(int(duration * sample_hz), 1)
        cascade = _get_cascade()

        cell_w = src_w / grid_cols
        cell_h = src_h / grid_rows
        # Pre-compute the column-center X for each grid column.
        col_cx = [(c + 0.5) * cell_w for c in range(grid_cols)]

        last_cx: Optional[float] = None
        last_cw: float = float(base_crop_w)
        last_col: Optional[int] = None
        lip_dt = 0.12

        MIN_SCORE = 0.8     # noise floor for "something is happening"
        HOT_RATIO = 0.60    # cells ≥ this fraction of best are co-active
        FACE_BOOST = 2.5
        MOMENTUM_BOOST = 1.20  # bias toward staying on the previously winning column

        for i in range(n_samples):
            t_rel = i / sample_hz
            t_abs = start + t_rel

            cap.set(cv2.CAP_PROP_POS_FRAMES, int(t_abs * cap_fps))
            ok_a, frame_a = cap.read()
            cap.set(cv2.CAP_PROP_POS_FRAMES, int((t_abs + lip_dt) * cap_fps))
            ok_b, frame_b = cap.read()

            if not ok_a or not ok_b:
                if last_cx is not None:
                    points.append(TrackPoint(t_rel, last_cx, last_cw, 0.0))
                continue

            gray_a = cv2.cvtColor(frame_a, cv2.COLOR_BGR2GRAY)
            gray_b = cv2.cvtColor(frame_b, cv2.COLOR_BGR2GRAY)
            if gray_a.shape != gray_b.shape:
                if last_cx is not None:
                    points.append(TrackPoint(t_rel, last_cx, last_cw, 0.0))
                continue

            diff = np.abs(gray_a.astype(np.int16) - gray_b.astype(np.int16))

            # Detect faces ONCE on frame_a; tag which (row, col) each falls in.
            faces = cascade.detectMultiScale(
                gray_a, scaleFactor=1.1, minNeighbors=4, minSize=(60, 60)
            )
            face_cells = set()
            for (fx, fy, fw, fh) in faces:
                fcx = fx + fw / 2; fcy = fy + fh / 2
                cc = min(grid_cols - 1, max(0, int(fcx // cell_w)))
                rr = min(grid_rows - 1, max(0, int(fcy // cell_h)))
                face_cells.add((rr, cc))

            # Score every cell.
            scores = np.zeros((grid_rows, grid_cols), dtype=np.float32)
            for r in range(grid_rows):
                y0 = int(r * cell_h); y1 = int((r + 1) * cell_h)
                for c in range(grid_cols):
                    x0 = int(c * cell_w); x1 = int((c + 1) * cell_w)
                    cell = diff[y0:y1, x0:x1]
                    if cell.size == 0:
                        continue
                    s = float(cell.mean())
                    if (r, c) in face_cells:
                        s *= FACE_BOOST
                    if last_col is not None and c == last_col:
                        s *= MOMENTUM_BOOST
                    scores[r, c] = s

            best = float(scores.max())
            if best < MIN_SCORE:
                # Static frame — hold last position, ease back to base width.
                cx = last_cx if last_cx is not None else src_w / 2.0
                cw = float(base_crop_w)
                last_cx, last_cw = cx, cw
                points.append(TrackPoint(t_rel, cx, cw, 0.0))
                continue

            # Find all "hot" cells (co-active with the winner).
            hot_mask = scores >= (HOT_RATIO * best)
            hot_cols = sorted({c for r in range(grid_rows) for c in range(grid_cols) if hot_mask[r, c]})

            if len(hot_cols) >= 2:
                # WIDE: enclose all hot columns.
                left_x = hot_cols[0] * cell_w
                right_x = (hot_cols[-1] + 1) * cell_w
                group_cx = (left_x + right_x) / 2.0
                group_span = right_x - left_x
                desired_w = group_span * 1.20  # small padding
                cw = max(float(base_crop_w), min(desired_w, float(src_w)))
                # Pick the dominant column among hot ones to remember.
                col_scores = scores.max(axis=0)
                last_col = int(np.argmax(col_scores))
                last_cx, last_cw = group_cx, cw
                points.append(TrackPoint(t_rel, group_cx, cw, 1.0))
            else:
                # TIGHT: snap to the winning column's center.
                # (Use sub-cell precision: weight by face center if available.)
                best_r, best_c = np.unravel_index(int(np.argmax(scores)), scores.shape)
                cx = col_cx[best_c]
                # If a face exists in the winning cell, refine cx to that face's center.
                for (fx, fy, fw, fh) in faces:
                    fcx = fx + fw / 2; fcy = fy + fh / 2
                    cc = min(grid_cols - 1, max(0, int(fcx // cell_w)))
                    rr = min(grid_rows - 1, max(0, int(fcy // cell_h)))
                    if rr == best_r and cc == best_c:
                        cx = float(fcx)
                        break
                last_col = int(best_c)
                last_cx, last_cw = float(cx), float(base_crop_w)
                points.append(TrackPoint(t_rel, last_cx, last_cw, 1.0))

        cap.release()
    except Exception as e:
        logger.debug(f"Grid speaker tracking failed: {e}")

    return points


def track_speaker(
    video_path: str,
    start: float,
    duration: float,
    src_w: int,
    src_h: int,
    base_crop_w: int,
    sample_hz: float = 2.0,
) -> List[TrackPoint]:
    """Sample the video ~twice per second and return per-tick framing decisions.

    For each sample point we grab two frames ~120ms apart and detect faces in
    both. For every face we measure the absolute pixel difference in its mouth
    region (lower 45 % × inner 70 % of the bbox); that becomes a per-face
    "speaking score".

    Framing logic per tick:
      - 0 faces  → hold last position (or center) at base width.
      - 1 face   → tight crop centered on that face.
      - 2+ faces, only one speaking → tight crop on the active speaker.
      - 2+ faces, multiple speaking (or rapid back-and-forth) → wide crop
        centered on the midpoint of the speaking group, widened to enclose
        them with padding (capped at src_w). The wider crop is what later
        produces the "zoomed-out, blurred letterbox" wide shot.
    """
    points: List[TrackPoint] = []
    try:
        cap = cv2.VideoCapture(video_path)
        cap_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n_samples = max(int(duration * sample_hz), 1)
        cascade = _get_cascade()

        last_cx: Optional[float] = None
        last_cw: float = float(base_crop_w)
        lip_dt = 0.12

        # When motion is below this absolute threshold we treat a face as
        # silent (helps avoid false multi-speaker on noisy frames).
        MIN_MOTION = 1.5
        # A face is "actively speaking" if its motion is at least this fraction
        # of the loudest mouth in the frame.
        ACTIVE_RATIO = 0.55

        for i in range(n_samples):
            t_rel = i / sample_hz
            t_abs = start + t_rel

            cap.set(cv2.CAP_PROP_POS_FRAMES, int(t_abs * cap_fps))
            ok_a, frame_a = cap.read()
            cap.set(cv2.CAP_PROP_POS_FRAMES, int((t_abs + lip_dt) * cap_fps))
            ok_b, frame_b = cap.read()

            if not ok_a:
                if last_cx is not None:
                    points.append(TrackPoint(t_rel, last_cx, last_cw, 0.0))
                continue

            gray_a = cv2.cvtColor(frame_a, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(
                gray_a, scaleFactor=1.1, minNeighbors=4, minSize=(60, 60)
            )
            if len(faces) == 0:
                if last_cx is not None:
                    points.append(TrackPoint(t_rel, last_cx, last_cw, 0.0))
                continue

            # Single face — easy.
            if len(faces) == 1 or not ok_b:
                x, _, w, _ = faces[0]
                cx = float(x + w / 2)
                last_cx, last_cw = cx, float(base_crop_w)
                points.append(TrackPoint(t_rel, cx, last_cw, 1.0))
                continue

            # Multi-face: score each by mouth motion.
            gray_b = cv2.cvtColor(frame_b, cv2.COLOR_BGR2GRAY)
            h_a, w_a = gray_a.shape
            scored: List[Tuple[float, float, int, int]] = []  # (motion, cx, fx, fx+fw)
            for (fx, fy, fw, fh) in faces:
                my0 = int(fy + fh * 0.55); my1 = int(fy + fh)
                mx0 = int(fx + fw * 0.15); mx1 = int(fx + fw * 0.85)
                my0, my1 = max(0, my0), min(h_a, my1)
                mx0, mx1 = max(0, mx0), min(w_a, mx1)
                if my1 <= my0 or mx1 <= mx0:
                    continue
                a = gray_a[my0:my1, mx0:mx1].astype(np.int16)
                b = gray_b[my0:my1, mx0:mx1].astype(np.int16)
                if a.shape != b.shape or a.size == 0:
                    continue
                motion = float(np.abs(a - b).mean())
                cx = float(fx + fw / 2)
                # Momentum bias for the currently tracked speaker.
                if last_cx is not None and abs(cx - last_cx) < 20:
                    motion *= 1.25
                scored.append((motion, cx, int(fx), int(fx + fw)))

            if not scored:
                if last_cx is not None:
                    points.append(TrackPoint(t_rel, last_cx, last_cw, 0.0))
                continue

            max_m = max(s[0] for s in scored)
            active = [s for s in scored if s[0] >= MIN_MOTION and s[0] >= ACTIVE_RATIO * max_m]

            if len(active) >= 2:
                # WIDE SHOT: enclose all active speakers.
                left = min(s[2] for s in active)
                right = max(s[3] for s in active)
                group_cx = (left + right) / 2.0
                group_span = right - left
                # Pad the group bbox by 35 % so faces aren't kissing the edges.
                desired_w = group_span * 1.35
                cw = max(float(base_crop_w), min(desired_w, float(src_w)))
                last_cx, last_cw = group_cx, cw
                points.append(TrackPoint(t_rel, group_cx, cw, 1.0))
            else:
                # TIGHT SHOT on the dominant speaker.
                _, best_cx, _, _ = max(scored, key=lambda s: s[0])
                last_cx, last_cw = best_cx, float(base_crop_w)
                points.append(TrackPoint(t_rel, best_cx, last_cw, 1.0))

        cap.release()
    except Exception as e:
        logger.debug(f"Speaker tracking failed: {e}")

    return points


def smooth_track(
    points: List[TrackPoint],
    alpha_cx: float = 0.25,
    alpha_cw: float = 0.12,
) -> List[TrackPoint]:
    """EMA-smooth both the pan (cx) and the zoom (cw) channels.

    cw is smoothed more slowly so we don't pop in/out of the wide shot — the
    camera should ease between tight and wide framing.
    """
    if not points:
        return points
    smoothed: List[TrackPoint] = []
    sx = points[0].cx
    sw = points[0].cw
    for p in points:
        sx = alpha_cx * p.cx + (1 - alpha_cx) * sx
        sw = alpha_cw * p.cw + (1 - alpha_cw) * sw
        smoothed.append(TrackPoint(p.t, sx, sw, p.confidence))
    return smoothed


def _piecewise_expr(times: List[float], values: List[float]) -> str:
    """Build an FFmpeg piecewise-linear expression in t (clip-relative)."""
    if not times:
        return "0"
    if len(times) == 1:
        return f"{values[0]:.1f}"
    expr = f"{values[-1]:.1f}"
    for i in range(len(times) - 1, 0, -1):
        t0, t1 = times[i - 1], times[i]
        v0, v1 = values[i - 1], values[i]
        if t1 <= t0:
            continue
        seg = f"({v0:.1f}+({v1 - v0:.1f})*(t-{t0:.2f})/{t1 - t0:.2f})"
        expr = f"if(lt(t,{t1:.2f}),{seg},{expr})"
    return expr


def build_pan_crop_filter(
    track: List[TrackPoint],
    src_w: int,
    src_h: int,
    crop_w: int,
) -> str:
    """Legacy fixed-width pan crop. Kept for callers that don't want the
    dynamic zoom-out behavior. New code should use build_dynamic_frame_graph.
    """
    if not track:
        return f"crop={crop_w}:{src_h}:(in_w-{crop_w})/2:0"
    if len(track) > 40:
        step = len(track) // 40
        track = track[::step]
    half = crop_w / 2
    max_cx = src_w - half
    times = [p.t for p in track]
    xs = [max(half, min(p.cx, max_cx)) - half for p in track]
    expr = _piecewise_expr(times, xs)
    return f"crop={crop_w}:{src_h}:'{expr}':0"


def build_dynamic_frame_graph(
    track: List[TrackPoint],
    src_w: int,
    src_h: int,
    base_crop_w: int,
    in_label: str = "0:v",
    out_label: str = "framed",
    out_w: int = 1080,
    out_h: int = 1920,
    blur_strength: int = 22,
) -> str:
    """Build a -filter_complex sub-graph that:
      • pans a crop window to the active speaker, AND
      • dynamically widens the crop (and shrinks crop height to keep the
        crop's aspect a bit wider than 9:16) when multiple speakers are
        active, then
      • scales the crop into the 1080×1920 output, padding above/below with
        a blurred copy of the source — so the foreground is a "zoomed-out"
        wide shot while the background fills the canvas with a soft blur.

    Returns a string ending in `[{out_label}]` and accepting `[{in_label}]`.

    The dynamic crop's width varies in t; height is held at src_h whenever
    cw ≤ base_crop_w (giving a true 9:16 tight shot that fills the canvas
    with no visible blur), and is reduced to keep the crop ≤ 9:16 when cw
    grows wider than base — at which point the scaled crop is letterboxed
    inside the blurred bg.
    """
    if not track:
        # Static center crop fallback.
        return (
            f"[{in_label}]split=2[bgsrc][fgsrc];"
            f"[bgsrc]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h},boxblur={blur_strength}:1,eq=brightness=-0.05[bg];"
            f"[fgsrc]crop={base_crop_w}:{src_h}:(in_w-{base_crop_w})/2:0,"
            f"scale={out_w}:{out_h}[fg];"
            f"[bg][fg]overlay=x=0:y=0[{out_label}]"
        )

    # Downsample keyframes to keep expression strings manageable.
    if len(track) > 40:
        step = len(track) // 40
        track = track[::step]

    times = [p.t for p in track]

    # Per-keyframe clamped values:
    #   cw_k = clamp(track.cw, base_crop_w, src_w)
    #   ch_k = min(src_h, cw_k * src_h / base_crop_w)   ← keeps aspect ≤ 9:16-ish
    #     Actually: keep cw/ch == base_crop_w/src_h (i.e. 9:16) as long as ch ≤ src_h.
    #     If cw > base_crop_w, we'd need ch = cw * src_h / base_crop_w > src_h → cap ch at src_h
    #     and let the foreground become wider than 9:16; the overlay will then
    #     show as a horizontal letterbox inside the blurred bg.
    cws: List[float] = []
    chs: List[float] = []
    xs: List[float] = []
    ys: List[float] = []
    for p in track:
        cw = max(float(base_crop_w), min(p.cw, float(src_w)))
        # Keep crop's aspect at 9:16 until ch hits src_h.
        ratio_h = cw * (src_h / float(base_crop_w))
        ch = min(float(src_h), ratio_h)
        # Center on cx, clamp inside frame.
        x = p.cx - cw / 2.0
        x = max(0.0, min(x, src_w - cw))
        y = (src_h - ch) / 2.0
        cws.append(cw); chs.append(ch); xs.append(x); ys.append(y)

    cw_expr = _piecewise_expr(times, cws)
    ch_expr = _piecewise_expr(times, chs)
    x_expr  = _piecewise_expr(times, xs)
    y_expr  = _piecewise_expr(times, ys)

    # Inside FFmpeg crop expressions, ' is the quote that wraps an expression
    # already; we use commas freely. We wrap each expr in single quotes at the
    # filter-arg level. To keep the filter-complex parse safe we escape via
    # backslash-comma is not needed here because crop accepts comma-less exprs.

    return (
        f"[{in_label}]split=2[bgsrc][fgsrc];"
        # Background: blurred, brightness-dimmed copy filling 1080x1920.
        f"[bgsrc]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h},boxblur={blur_strength}:1,eq=brightness=-0.05[bg];"
        # Foreground: dynamic crop following speaker(s), scaled to fit width.
        f"[fgsrc]crop=w='{cw_expr}':h='{ch_expr}':x='{x_expr}':y='{y_expr}',"
        f"scale={out_w}:-2[fg];"
        # Overlay centered vertically; horizontal x=0 since fg width == out_w.
        f"[bg][fg]overlay=x=0:y='(main_h-overlay_h)/2'[{out_label}]"
    )


# ─────────────────────────── Audio energy / punch-ins ───────────────────────────

def extract_audio_energy(video_path: str, start: float, duration: float, sr: int = 8000) -> Tuple[np.ndarray, int]:
    """Extract a mono PCM audio slice and return its envelope at ~50Hz."""
    try:
        proc = subprocess.run(
            [FFMPEG_PATH, "-y", "-ss", str(start), "-i", video_path,
             "-t", str(duration), "-vn",
             "-ac", "1", "-ar", str(sr), "-f", "s16le", "pipe:1"],
            capture_output=True, timeout=60,
        )
        if proc.returncode != 0:
            return np.array([]), sr
        audio = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
        # Window envelope: 20ms hops
        hop = max(int(sr * 0.02), 1)
        n = len(audio) // hop
        if n == 0:
            return np.array([]), sr
        env = np.array([np.abs(audio[i * hop:(i + 1) * hop]).mean() for i in range(n)])
        return env, sr
    except Exception as e:
        logger.debug(f"Audio energy extract failed: {e}")
        return np.array([]), sr


def find_emphasis_times(envelope: np.ndarray, hop_sec: float = 0.02,
                        min_gap: float = 2.5, top_k: int = 3) -> List[float]:
    """Return up to top_k timestamps (s) where audio energy peaks — punch-in moments."""
    if envelope.size == 0:
        return []
    # Smooth and find local maxima above 1.4*mean
    win = max(int(0.25 / hop_sec), 1)  # 250ms
    kernel = np.ones(win) / win
    smooth = np.convolve(envelope, kernel, mode="same")
    threshold = smooth.mean() + smooth.std() * 0.8
    peaks = []
    for i in range(1, len(smooth) - 1):
        if smooth[i] > threshold and smooth[i] >= smooth[i - 1] and smooth[i] >= smooth[i + 1]:
            t = i * hop_sec
            if not peaks or t - peaks[-1] >= min_gap:
                peaks.append(t)
    # Pick top-k by amplitude
    if len(peaks) > top_k:
        scored = sorted(peaks, key=lambda t: -smooth[int(t / hop_sec)])
        peaks = sorted(scored[:top_k])
    return peaks


def build_zoompan_expression(duration: float, fps: float, peaks: List[float],
                             base_zoom: float = 1.0, peak_zoom: float = 1.12) -> Optional[str]:
    """Build a zoompan z-expression that gently zooms toward each peak.

    Each peak gets a 0.6s ease-in/ease-out bump. Returns None if no peaks.
    """
    if not peaks:
        return None

    # zoompan operates per output frame. We build z=base + sum(bumps)
    # bump(t) = (peak_zoom-base)*hann_window centered on peak_t with width 0.6s
    bump_w = 0.6
    parts = [f"{base_zoom:.3f}"]
    amp = peak_zoom - base_zoom
    for pt in peaks:
        # Triangle window: max(0, 1 - 2*|t - pt|/bump_w)
        parts.append(f"{amp:.3f}*max(0,1-2*abs(on/{fps:.2f}-{pt:.2f})/{bump_w})")
    expr = "+".join(parts)
    total_frames = max(int(duration * fps), 1)
    return f"zoompan=z='{expr}':d=1:s=1080x1920:fps={fps:.2f}"


# ─────────────────────────── Word-pop caption renderer ───────────────────────────

@dataclass
class CaptionStyle:
    name: str
    primary_color: Tuple[int, int, int]      # main text
    highlight_color: Tuple[int, int, int]    # current word
    outline_color: Tuple[int, int, int]
    outline_width: int
    bg_color: Optional[Tuple[int, int, int, int]]  # RGBA or None
    font_weight: str                          # 'bold' or 'black'
    font_size: int
    upper: bool                               # uppercase the text
    bounce: bool                              # scale-bounce on word reveal
    words_per_chunk: int                      # how many words to show together


CAPTION_PRESETS: Dict[str, CaptionStyle] = {
    "hormozi": CaptionStyle(
        name="hormozi",
        primary_color=(255, 255, 255),
        highlight_color=(255, 220, 0),     # yellow pop
        outline_color=(0, 0, 0),
        outline_width=6,
        bg_color=None,
        font_weight="black",
        font_size=92,
        upper=True,
        bounce=True,
        words_per_chunk=3,
    ),
    "mrbeast": CaptionStyle(
        name="mrbeast",
        primary_color=(255, 255, 255),
        highlight_color=(0, 230, 118),     # green
        outline_color=(0, 0, 0),
        outline_width=8,
        bg_color=None,
        font_weight="black",
        font_size=100,
        upper=True,
        bounce=True,
        words_per_chunk=2,
    ),
    "minimal": CaptionStyle(
        name="minimal",
        primary_color=(255, 255, 255),
        highlight_color=(255, 255, 255),
        outline_color=(0, 0, 0),
        outline_width=4,
        bg_color=(0, 0, 0, 140),
        font_weight="bold",
        font_size=64,
        upper=False,
        bounce=False,
        words_per_chunk=5,
    ),
    "bold": CaptionStyle(
        name="bold",
        primary_color=(255, 255, 255),
        highlight_color=(255, 200, 0),
        outline_color=(0, 0, 0),
        outline_width=5,
        bg_color=(0, 0, 0, 180),
        font_weight="bold",
        font_size=72,
        upper=False,
        bounce=True,
        words_per_chunk=4,
    ),
}


def get_caption_style(name: str) -> CaptionStyle:
    return CAPTION_PRESETS.get(name.lower(), CAPTION_PRESETS["hormozi"])


# ─────────────── Important-word emphasis (v2) ──────────────────
#
# Even when not the "currently spoken" word, these words always render in the
# style's highlight colour so the eye latches on to the punch line.

IMPORTANT_WORDS = {
    # english
    "never", "always", "mistake", "secret", "truth", "wrong", "biggest",
    "worst", "best", "nobody", "everyone", "stop", "huge", "shocking",
    "crazy", "insane", "real", "honest", "honestly", "literally",
    "actually", "obviously", "guarantee", "warning", "free",
    # hindi / hinglish
    "galat", "sahi", "sabse", "asli", "zaruri", "important",
    "shocking", "kamaal", "pagal",
}


def _is_important_word(word: str) -> bool:
    """True if `word` should always be visually emphasised."""
    if not word:
        return False
    cleaned = re.sub(r"[^\w\u0900-\u097F]+", "", word).lower()
    return cleaned in IMPORTANT_WORDS


def group_words_into_chunks(words: List[Dict], words_per_chunk: int) -> List[Dict]:
    """Group flat word list into N-word chunks for caption display.

    Returns: [{"start", "end", "words": [{word, start, end}, ...]}]
    """
    chunks: List[Dict] = []
    if not words:
        return chunks
    for i in range(0, len(words), words_per_chunk):
        group = words[i:i + words_per_chunk]
        if not group:
            continue
        chunks.append({
            "start": group[0]["start"],
            "end": group[-1]["end"],
            "words": group,
        })
    return chunks


def _draw_text_with_outline(
    draw: ImageDraw.ImageDraw,
    pos: Tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: Tuple[int, int, int],
    outline: Tuple[int, int, int],
    outline_w: int,
):
    x, y = pos
    # Outline pass
    for dx in range(-outline_w, outline_w + 1):
        for dy in range(-outline_w, outline_w + 1):
            if dx * dx + dy * dy <= outline_w * outline_w:
                draw.text((x + dx, y + dy), text, font=font, fill=outline)
    # Fill pass
    draw.text((x, y), text, font=font, fill=fill)


def render_word_pop_frame(
    chunk: Dict,
    t_in_chunk: float,
    width: int,
    height: int,
    style: CaptionStyle,
    language: str,
) -> Image.Image:
    """Render one frame of word-pop captions.

    Highlights the currently spoken word, uppercases text (if style says so),
    optionally applies a scale bounce on the new word.
    """
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    words = chunk["words"]
    if not words:
        return img

    # Determine which word is "active" right now
    active_idx = 0
    chunk_start = chunk["start"]
    abs_t = chunk_start + t_in_chunk
    for i, w in enumerate(words):
        if w["start"] <= abs_t < w["end"]:
            active_idx = i
            break
        if abs_t >= w["end"]:
            active_idx = i

    # Bounce scale: 1.25 at word start, settles to 1.0 over 120ms
    bounce_scale = 1.0
    if style.bounce:
        active_word = words[active_idx]
        time_since = max(abs_t - active_word["start"], 0)
        if time_since < 0.12:
            # ease-out from 1.25 → 1.0
            p = time_since / 0.12
            bounce_scale = 1.25 - 0.25 * p

    # Format text
    def fmt(w: str) -> str:
        s = w.strip()
        return s.upper() if style.upper else s

    rendered = [fmt(w["word"]) for w in words]
    font = get_font(style.font_size, language, style.font_weight)

    # Layout: center the line. If too wide, wrap to 2 lines.
    space_w = font.getbbox(" ")[2] - font.getbbox(" ")[0]
    word_widths = [font.getbbox(w)[2] - font.getbbox(w)[0] for w in rendered]
    total_w = sum(word_widths) + space_w * (len(rendered) - 1)
    max_w = width - 80

    lines: List[List[int]] = [[]]   # list of word index lists
    line_w = 0
    for i, ww in enumerate(word_widths):
        addition = ww + (space_w if lines[-1] else 0)
        if line_w + addition > max_w and lines[-1]:
            lines.append([i])
            line_w = ww
        else:
            lines[-1].append(i)
            line_w += addition

    line_h = int(style.font_size * 1.15)
    block_h = line_h * len(lines)
    # Position: lower third
    y_top = int(height * 0.62)
    if y_top + block_h > height - 120:
        y_top = height - 120 - block_h

    # Optional background pill
    if style.bg_color:
        pad = 24
        max_line_w = max(
            sum(word_widths[i] for i in line) + space_w * (len(line) - 1)
            for line in lines
        )
        bg_left = (width - max_line_w) // 2 - pad
        bg_right = (width + max_line_w) // 2 + pad
        draw.rounded_rectangle(
            [bg_left, y_top - pad // 2, bg_right, y_top + block_h + pad // 2],
            radius=24, fill=style.bg_color,
        )

    # Draw each line
    y = y_top
    for line in lines:
        line_w_px = sum(word_widths[i] for i in line) + space_w * (len(line) - 1)
        x = (width - line_w_px) // 2
        for idx in line:
            is_active = (idx == active_idx)
            is_important = _is_important_word(words[idx]["word"])
            # Active word always wins; otherwise important words also pop.
            color = (style.highlight_color if (is_active or is_important)
                     else style.primary_color)
            text = rendered[idx]

            if is_active and style.bounce and bounce_scale != 1.0:
                # Render to small layer then scale
                bw = word_widths[idx] + style.outline_width * 2 + 8
                bh = line_h + style.outline_width * 2 + 8
                layer = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
                ldraw = ImageDraw.Draw(layer)
                _draw_text_with_outline(
                    ldraw, (style.outline_width + 4, style.outline_width + 4),
                    text, font, color, style.outline_color, style.outline_width,
                )
                new_size = (max(int(bw * bounce_scale), 1), max(int(bh * bounce_scale), 1))
                layer = layer.resize(new_size, Image.Resampling.LANCZOS)
                paste_x = x - (new_size[0] - bw) // 2
                paste_y = y - (new_size[1] - bh) // 2
                img.alpha_composite(layer, (paste_x, paste_y))
            else:
                _draw_text_with_outline(
                    draw, (x, y), text, font, color, style.outline_color, style.outline_width,
                )
            x += word_widths[idx] + space_w
        y += line_h

    return img


# ─────────────────────────── Hook & CTA cards ───────────────────────────

def render_hook_card(text: str, width: int, height: int, language: str,
                     progress: float) -> Image.Image:
    """Render the hook intro card. progress: 0..1 for fade animation."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if progress <= 0 or progress >= 1:
        alpha = 0
    else:
        # Fade in 0-0.3, hold, fade out 0.7-1.0
        if progress < 0.3:
            alpha = int(255 * (progress / 0.3))
        elif progress > 0.7:
            alpha = int(255 * (1 - (progress - 0.7) / 0.3))
        else:
            alpha = 255

    if alpha == 0:
        return img

    font = get_font(96, language, "black")
    text_up = text.upper() if detect_script(text) == "english" else text

    # Wrap text
    max_w = width - 120
    words = text_up.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if font.getbbox(test)[2] - font.getbbox(test)[0] <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)

    line_h = int(96 * 1.15)
    block_h = line_h * len(lines)
    y = (height - block_h) // 2 - 80

    # Draw with outline
    for line in lines:
        bbox = font.getbbox(line)
        line_w = bbox[2] - bbox[0]
        x = (width - line_w) // 2
        # Outline
        for dx in range(-7, 8):
            for dy in range(-7, 8):
                if dx * dx + dy * dy <= 49:
                    draw.text((x + dx, y + dy), line, font=font,
                              fill=(0, 0, 0, alpha))
        draw.text((x, y), line, font=font, fill=(255, 220, 0, alpha))
        y += line_h

    return img


def render_cta_card(text: str, width: int, height: int,
                    progress: float) -> Image.Image:
    """Render the CTA endcard (e.g. 'FOLLOW FOR MORE')."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if progress < 0.2:
        alpha = int(255 * progress / 0.2)
    elif progress > 0.85:
        alpha = int(255 * (1 - (progress - 0.85) / 0.15))
    else:
        alpha = 255

    if alpha == 0:
        return img

    # Dim the bottom area
    overlay_h = 380
    overlay = Image.new("RGBA", (width, overlay_h), (0, 0, 0, int(180 * alpha / 255)))
    img.alpha_composite(overlay, (0, height - overlay_h))

    font = get_font(80, "english", "black")
    bbox = font.getbbox(text)
    line_w = bbox[2] - bbox[0]
    x = (width - line_w) // 2
    y = height - 250

    # Outline
    for dx in range(-6, 7):
        for dy in range(-6, 7):
            if dx * dx + dy * dy <= 36:
                draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, alpha))
    draw.text((x, y), text, font=font, fill=(255, 255, 255, alpha))

    # Small arrow / sub-text
    sub_font = get_font(36, "english", "bold")
    sub = "↓ TAP THE PROFILE"
    sb = sub_font.getbbox(sub)
    sx = (width - (sb[2] - sb[0])) // 2
    draw.text((sx, y + 110), sub, font=sub_font, fill=(255, 220, 0, alpha))

    return img


# ─────────────────────────── Combined overlay renderer ───────────────────────────

def generate_overlay_video(
    chunks: List[Dict],
    output_path: str,
    duration: float,
    fps: float = 30.0,
    width: int = 1080,
    height: int = 1920,
    style: Optional[CaptionStyle] = None,
    language: str = "english",
    hook_text: Optional[str] = None,
    cta_text: Optional[str] = None,
    hook_dur: float = 1.2,
    cta_dur: float = 1.2,
) -> str:
    """Render a transparent RGBA overlay video containing:
      - Hook card (first hook_dur seconds, if hook_text given)
      - Word-pop captions (whole video)
      - CTA endcard (last cta_dur seconds, if cta_text given)
    """
    if style is None:
        style = get_caption_style("hormozi")

    total_frames = int(duration * fps)
    logger.info(
        f"Rendering overlay: {total_frames} frames @ {fps}fps, style={style.name}, "
        f"hook={'on' if hook_text else 'off'}, cta={'on' if cta_text else 'off'}"
    )

    # Cache caption frames by (chunk_idx, active_word_idx, bounce_bucket)
    transparent = bytes(width * height * 4)

    cmd = [
        FFMPEG_PATH, "-y",
        "-f", "rawvideo", "-pix_fmt", "rgba",
        "-s", f"{width}x{height}", "-r", str(fps),
        "-i", "pipe:0",
        "-c:v", "png", "-pix_fmt", "rgba",
        output_path,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    # Pre-flatten chunks for fast lookup
    chunk_idx = 0

    try:
        for f in range(total_frames):
            t = f / fps
            base: Optional[Image.Image] = None

            # Find active caption chunk
            while chunk_idx < len(chunks) and chunks[chunk_idx]["end"] <= t:
                chunk_idx += 1
            active = None
            if chunk_idx < len(chunks) and chunks[chunk_idx]["start"] <= t < chunks[chunk_idx]["end"]:
                active = chunks[chunk_idx]
            else:
                # Search a tiny window forward (chunks may have gaps)
                for c in chunks[chunk_idx:chunk_idx + 3]:
                    if c["start"] <= t < c["end"]:
                        active = c
                        break

            if active:
                t_in = t - active["start"]
                base = render_word_pop_frame(active, t_in, width, height, style, language)

            # Hook overlay
            if hook_text and t < hook_dur:
                hook_img = render_hook_card(hook_text, width, height, language, t / hook_dur)
                if base is None:
                    base = hook_img
                else:
                    base.alpha_composite(hook_img)

            # CTA overlay
            if cta_text and t > duration - cta_dur:
                cta_img = render_cta_card(cta_text, width, height,
                                          (t - (duration - cta_dur)) / cta_dur)
                if base is None:
                    base = cta_img
                else:
                    base.alpha_composite(cta_img)

            if base is None:
                proc.stdin.write(transparent)
            else:
                proc.stdin.write(base.tobytes())

        proc.stdin.close()
        proc.wait(timeout=600)
        if proc.returncode != 0:
            stderr = proc.stderr.read().decode(errors="ignore")[:500]
            raise RuntimeError(f"Overlay encode failed: {stderr}")
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        raise

    logger.info(f"Overlay rendered: {output_path}")
    return output_path
