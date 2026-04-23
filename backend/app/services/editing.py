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
    t: float        # seconds (relative to clip start)
    cx: float       # face center X in source coords
    confidence: float  # 0..1


def track_speaker(
    video_path: str,
    start: float,
    duration: float,
    sample_hz: float = 2.0,
) -> List[TrackPoint]:
    """Sample the video twice per second and return a list of face-center X positions.

    Used to drive a smooth panning crop. Frames with no face inherit the
    previous valid X (no lateral jump). EMA smoothing is applied later.
    """
    points: List[TrackPoint] = []
    try:
        cap = cv2.VideoCapture(video_path)
        cap_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n_samples = max(int(duration * sample_hz), 1)
        cascade = _get_cascade()

        last_cx = None
        for i in range(n_samples):
            t_rel = i / sample_hz
            t_abs = start + t_rel
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(t_abs * cap_fps))
            ok, frame = cap.read()
            if not ok:
                if last_cx is not None:
                    points.append(TrackPoint(t_rel, last_cx, 0.0))
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(60, 60))
            if len(faces) > 0:
                largest = max(faces, key=lambda f: f[2] * f[3])
                x, _, w, _ = largest
                cx = float(x + w / 2)
                last_cx = cx
                points.append(TrackPoint(t_rel, cx, 1.0))
            elif last_cx is not None:
                points.append(TrackPoint(t_rel, last_cx, 0.0))

        cap.release()
    except Exception as e:
        logger.debug(f"Speaker tracking failed: {e}")

    return points


def smooth_track(points: List[TrackPoint], alpha: float = 0.25) -> List[TrackPoint]:
    """EMA-smooth the track and clamp jumps to avoid jarring snaps."""
    if not points:
        return points
    smoothed: List[TrackPoint] = []
    s = points[0].cx
    for p in points:
        s = alpha * p.cx + (1 - alpha) * s
        smoothed.append(TrackPoint(p.t, s, p.confidence))
    return smoothed


def build_pan_crop_filter(
    track: List[TrackPoint],
    src_w: int,
    src_h: int,
    crop_w: int,
) -> str:
    """Build an FFmpeg crop filter that pans the X position over time.

    Uses ffmpeg expressions: x as a piecewise interpolation across keyframes.
    """
    if not track:
        # Static center crop
        return f"crop={crop_w}:{src_h}:(in_w-{crop_w})/2:0"

    # Clamp center positions so crop window stays inside frame
    half = crop_w / 2
    max_cx = src_w - half

    # Build a piecewise expression: lerp between successive keyframes.
    # For simplicity & FFmpeg expr length, downsample keyframes if too many.
    if len(track) > 40:
        step = len(track) // 40
        track = track[::step]

    # Build nested if() expression: if(lt(t,t1), x0+(x1-x0)*(t-t0)/(t1-t0), if(...))
    def clamp(cx: float) -> float:
        return max(half, min(cx, max_cx)) - half  # convert to top-left X

    # Tail value: last point
    expr = f"{clamp(track[-1].cx):.1f}"
    for i in range(len(track) - 1, 0, -1):
        t0, t1 = track[i - 1].t, track[i].t
        x0, x1 = clamp(track[i - 1].cx), clamp(track[i].cx)
        if t1 <= t0:
            continue
        seg = f"({x0:.1f}+({x1 - x0:.1f})*(t-{t0:.2f})/{t1 - t0:.2f})"
        expr = f"if(lt(t,{t1:.2f}),{seg},{expr})"

    # Final wrap: clamp t into valid range
    return f"crop={crop_w}:{src_h}:'{expr}':0"


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
            color = style.highlight_color if is_active else style.primary_color
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
