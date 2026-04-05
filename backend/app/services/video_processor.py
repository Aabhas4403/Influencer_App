"""Video Processing Pipeline — FFmpeg + Pillow + OpenCV for professional clip editing.

Operations:
  1. Cut clip from source video using timestamps (no silence removal — preserves sync)
  2. Face-centered vertical crop (9:16) using OpenCV face detection
  3. Burn animated word-by-word captions using Pillow → overlay
  4. Color grade for professional look
  5. Subtle zoom animation for engagement
  6. Mix in subtle background music
  7. Add intro/outro fade
"""

import logging
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.config import FFMPEG_PATH, BASE_DIR

logger = logging.getLogger(__name__)

# ── Paths ──
ASSETS_DIR = BASE_DIR / "assets"
ASSETS_DIR.mkdir(exist_ok=True)
MUSIC_DIR = ASSETS_DIR / "music"
MUSIC_DIR.mkdir(exist_ok=True)

# ── Font paths (macOS) ──
# Arial Unicode MS covers BOTH Devanagari and Latin perfectly — no boxes.
# Use it as the PRIMARY font for all Hindi/Hinglish content.
_ARIAL_UNICODE = "/Library/Fonts/Arial Unicode.ttf"
_ARIAL_UNICODE_SYS = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
_KOHINOOR = "/System/Library/Fonts/Kohinoor.ttc"
_DEVANAGARI_MT = "/System/Library/Fonts/Supplemental/DevanagariMT.ttc"
_HELVETICA = "/System/Library/Fonts/Helvetica.ttc"

# Check once at import time whether this ffmpeg has the subtitles filter
_HAS_SUBTITLES_FILTER: bool | None = None


def _check_subtitles_filter() -> bool:
    global _HAS_SUBTITLES_FILTER
    if _HAS_SUBTITLES_FILTER is None:
        try:
            r = subprocess.run(
                [FFMPEG_PATH, "-filters"],
                capture_output=True, text=True, timeout=5,
            )
            _HAS_SUBTITLES_FILTER = "subtitles" in r.stdout
        except Exception:
            _HAS_SUBTITLES_FILTER = False
        if not _HAS_SUBTITLES_FILTER:
            logger.info("subtitles filter unavailable — will use Pillow overlay for captions")
    return _HAS_SUBTITLES_FILTER


def _has_filter(name: str) -> bool:
    """Check if a specific FFmpeg filter is available."""
    try:
        r = subprocess.run([FFMPEG_PATH, "-filters"], capture_output=True, text=True, timeout=5)
        return name in r.stdout
    except Exception:
        return False


def get_video_duration(video_path: str) -> float:
    """Get video duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def _get_video_dimensions(video_path: str) -> tuple[int, int]:
    """Get video width and height."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        w, h = result.stdout.strip().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 0, 0


def _get_fps(video_path: str) -> float:
    """Get video FPS."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        num, den = result.stdout.strip().split("/")
        return float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        return 30.0


# ──────────────────────────────────────────────
# Face-centered cropping (OpenCV)
# ──────────────────────────────────────────────

# Load cascade once
_face_cascade = None


def _get_face_cascade():
    global _face_cascade
    if _face_cascade is None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _face_cascade = cv2.CascadeClassifier(cascade_path)
    return _face_cascade


def detect_face_center_x(video_path: str, start: float, duration: float) -> int | None:
    """Sample a few frames from the clip and detect the average face center X position.

    Returns the X coordinate to center the 9:16 crop around, or None if no face found.
    Samples 5 frames evenly spaced through the clip for stability.
    """
    try:
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(duration * fps)

        # Sample 5 evenly-spaced frames
        sample_indices = [
            int(start * fps + i * total_frames / 5) for i in range(5)
        ]

        cascade = _get_face_cascade()
        face_centers = []

        for frame_idx in sample_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(50, 50))

            if len(faces) > 0:
                # Pick the largest face
                largest = max(faces, key=lambda f: f[2] * f[3])
                x, y, w, h = largest
                face_centers.append(x + w // 2)

        cap.release()

        if face_centers:
            avg_center = int(np.mean(face_centers))
            logger.debug(f"Face detected at avg X={avg_center} from {len(face_centers)} frames")
            return avg_center

    except Exception as e:
        logger.debug(f"Face detection failed: {e}")

    return None


# ──────────────────────────────────────────────
# Pillow caption renderer
# ──────────────────────────────────────────────

def _detect_script(text: str) -> str:
    """Detect if text is primarily Devanagari (Hindi) or Latin (English)."""
    devanagari_count = sum(1 for c in text if '\u0900' <= c <= '\u097F')
    latin_count = sum(1 for c in text if 'A' <= c <= 'Z' or 'a' <= c <= 'z')
    return "hindi" if devanagari_count > latin_count else "english"


def _get_font(size: int, language: str = "english", bold: bool = True) -> ImageFont.FreeTypeFont:
    """Get a font that supports the detected language.

    For Hindi/Hinglish: Arial Unicode MS (covers both Devanagari + Latin).
    For English-only: Helvetica Bold (cleaner look).
    """
    if language in ("hindi", "hinglish"):
        # Priority: Arial Unicode (both scripts), then Kohinoor Bold, then DevanagariMT
        for path in [_ARIAL_UNICODE, _ARIAL_UNICODE_SYS]:
            if Path(path).exists():
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue
        # Kohinoor idx=3 is Bold
        try:
            return ImageFont.truetype(_KOHINOOR, size, index=3 if bold else 0)
        except Exception:
            pass
        try:
            return ImageFont.truetype(_DEVANAGARI_MT, size, index=1 if bold else 0)
        except Exception:
            pass
    else:
        # English: Helvetica Bold looks best
        idx = 1 if bold else 0
        try:
            return ImageFont.truetype(_HELVETICA, size, index=idx)
        except Exception:
            pass

    # Final fallback for any language
    for path in [_ARIAL_UNICODE, _ARIAL_UNICODE_SYS]:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = font.getbbox(test)
        if bbox[2] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


def render_caption_frame(
    text: str,
    width: int = 1080,
    height: int = 1920,
    language: str = "english",
    highlight_word: str | None = None,
) -> Image.Image:
    """Render a single caption frame as a transparent PNG.

    - Text at bottom third with rounded-rect background
    - Optionally highlights one word in a different color (karaoke style)
    """
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_size = 52
    font = _get_font(font_size, language, bold=True)

    max_text_width = width - 120  # 60px padding each side
    lines = _wrap_text(text, font, max_text_width)

    # Calculate text block dimensions
    line_height = font_size + 12
    block_height = len(lines) * line_height + 30
    block_top = height - block_height - 180  # above bottom nav area

    # Draw semi-transparent rounded background
    bg_left = 40
    bg_right = width - 40
    bg_top = block_top - 15
    bg_bottom = block_top + block_height + 5
    draw.rounded_rectangle(
        [bg_left, bg_top, bg_right, bg_bottom],
        radius=20,
        fill=(0, 0, 0, 160),
    )

    # Draw text line by line
    y = block_top
    for line in lines:
        # Center horizontally
        bbox = font.getbbox(line)
        text_w = bbox[2] - bbox[0]
        x = (width - text_w) // 2

        if highlight_word and highlight_word.lower() in line.lower():
            # Draw word-by-word, highlighting the target word
            cx = x
            for word in line.split():
                word_bbox = font.getbbox(word + " ")
                word_w = word_bbox[2] - word_bbox[0]
                if word.lower().strip(",.!?") == highlight_word.lower().strip(",.!?"):
                    # Highlight: yellow with glow
                    draw.text((cx + 2, y + 2), word, fill=(0, 0, 0, 200), font=font)
                    draw.text((cx, y), word, fill=(255, 230, 0, 255), font=font)
                else:
                    # Normal: white with shadow
                    draw.text((cx + 2, y + 2), word, fill=(0, 0, 0, 200), font=font)
                    draw.text((cx, y), word, fill=(255, 255, 255, 255), font=font)
                cx += word_w
        else:
            # All white with shadow
            draw.text((x + 2, y + 2), line, fill=(0, 0, 0, 200), font=font)
            draw.text((x, y), line, fill=(255, 255, 255, 255), font=font)

        y += line_height

    return img


def generate_caption_video(
    chunks: List[Dict],
    output_path: str,
    duration: float,
    fps: float = 30.0,
    width: int = 1080,
    height: int = 1920,
    language: str = "english",
) -> str:
    """Generate a transparent video of animated captions from transcript chunks.

    Uses Pillow to render frames -> pipes raw RGBA to FFmpeg.
    Chunks: [{"start": 0.0, "end": 3.0, "text": "Hello world"}, ...]
    """
    total_frames = int(duration * fps)
    logger.info(f"Generating caption overlay: {total_frames} frames, {len(chunks)} chunks")

    # Pre-render unique caption frames (cache by text+highlight combo)
    frame_cache: dict[str, bytes] = {}

    cmd = [
        FFMPEG_PATH, "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgba",
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "pipe:0",
        "-c:v", "png",          # lossless with alpha
        "-pix_fmt", "rgba",
        output_path,
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    transparent_frame = bytes(width * height * 4)  # all zeros = transparent

    for frame_num in range(total_frames):
        t = frame_num / fps

        # Find the chunk active at this time
        active_chunk = None
        for chunk in chunks:
            if chunk["start"] <= t < chunk["end"]:
                active_chunk = chunk
                break

        if not active_chunk:
            proc.stdin.write(transparent_frame)
            continue

        text = active_chunk["text"]

        # Determine which word to highlight (karaoke effect)
        words = text.split()
        chunk_duration = active_chunk["end"] - active_chunk["start"]
        elapsed = t - active_chunk["start"]
        word_idx = min(int(elapsed / max(chunk_duration, 0.1) * len(words)), len(words) - 1)
        highlight = words[word_idx] if words else None

        cache_key = f"{text}|{highlight}"
        if cache_key not in frame_cache:
            img = render_caption_frame(text, width, height, language, highlight)
            frame_cache[cache_key] = img.tobytes()

        proc.stdin.write(frame_cache[cache_key])

    proc.stdin.close()
    proc.wait()

    if proc.returncode != 0:
        stderr = proc.stderr.read().decode()[:500]
        logger.error(f"Caption video generation failed: {stderr}")
        raise RuntimeError(f"Caption overlay failed: {stderr}")

    logger.info(f"Caption overlay generated: {output_path}")
    return output_path


# ──────────────────────────────────────────────
# Background music
# ──────────────────────────────────────────────

def _generate_ambient_music(output_path: str, duration: float) -> str:
    """Generate a subtle ambient tone using FFmpeg's sine source.
    
    Creates a soft layered sine wave mix as background ambience.
    Not as good as real music but provides a professional feel.
    """
    cmd = [
        FFMPEG_PATH, "-y",
        "-f", "lavfi",
        "-i", f"sine=frequency=220:duration={duration}",
        "-f", "lavfi",
        "-i", f"sine=frequency=330:duration={duration}",
        "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={duration}",
        "-filter_complex",
        "[0:a]volume=0.03[a0];"
        "[1:a]volume=0.02[a1];"
        "[2:a]volume=0.01[a2];"
        "[a0][a1][a2]amix=inputs=3:duration=first[mixed];"
        "[mixed]lowpass=f=800,afade=t=in:st=0:d=2,afade=t=out:st=" + f"{max(duration - 2, 0)}:d=2[out]",
        "-map", "[out]",
        "-c:a", "aac", "-b:a", "64k",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning(f"Ambient music generation failed: {result.stderr[:200]}")
        return ""
    return output_path


def _find_bg_music(duration: float) -> str | None:
    """Find a background music file from assets, or generate ambient tones."""
    # Check for user-provided music files
    for ext in ("mp3", "aac", "m4a", "wav"):
        candidates = list(MUSIC_DIR.glob(f"*.{ext}"))
        if candidates:
            return str(candidates[0])

    # Generate ambient tones as fallback
    ambient_path = str(ASSETS_DIR / "ambient_bg.aac")
    if not Path(ambient_path).exists() or get_video_duration(ambient_path) < duration:
        result = _generate_ambient_music(ambient_path, duration + 5)
        return result if result else None

    return ambient_path


# ──────────────────────────────────────────────
# Main processing
# ──────────────────────────────────────────────

def remove_silence(
    input_path: str,
    output_path: str,
    noise_db: str = "-30dB",
    min_silence_duration: float = 0.5,
) -> str:
    """Remove silent sections — note: can cause audio/video desync.
    Kept for backward compat but NOT used by default pipeline anymore.
    """
    af = (
        f"silenceremove=stop_periods=-1:stop_duration={min_silence_duration}"
        f":stop_threshold={noise_db}"
    )
    cmd = [
        FFMPEG_PATH, "-y",
        "-i", input_path,
        "-af", af,
        "-c:v", "copy",
        output_path,
    ]
    logger.info(f"Removing silence (threshold={noise_db}, min_dur={min_silence_duration}s)")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning(f"Silence removal failed: {result.stderr[:300]}")
        raise RuntimeError(f"Silence removal failed: {result.stderr[:200]}")
    return output_path


def process_clip(
    source_video: str,
    start: float,
    end: float,
    srt_path: str | None,
    output_dir: str,
    clip_index: int,
    version: int | None = None,
    caption_chunks: List[Dict] | None = None,
    language: str = "english",
    professional: bool = True,
) -> str:
    """Full professional pipeline for a single clip:

    1. Cut & scale to vertical 9:16
    2. Color grade (slight contrast/saturation boost)
    3. Subtle zoom animation
    4. Fade in/out
    5. Burn animated captions (Pillow overlay if no drawtext)
    6. Mix background music at low volume
    7. Normalize audio loudness

    Returns path to the final processed clip.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    suffix = f"_v{version}" if version and version > 1 else ""
    final_clip = str(out / f"clip_{clip_index}{suffix}.mp4")
    clip_duration = end - start

    # Detect source dimensions
    w, h = _get_video_dimensions(source_video)
    aspect = w / h if h > 0 else 1.0
    fps = _get_fps(source_video)

    # ── Step 1: Base clip — cut + face-centered vertical + color grade + zoom ──
    base_clip = str(out / f"_base_{clip_index}{suffix}.mp4")

    filters = []
    # Crop/scale to vertical with face-centered cropping
    if aspect <= 0.5625 + 0.05:  # already vertical
        filters.append("scale=1080:1920:force_original_aspect_ratio=decrease")
        filters.append("pad=1080:1920:(ow-iw)/2:(oh-ih)/2")
    else:
        # Try to detect face and center crop around it
        crop_width = int(h * 9 / 16)  # width for 9:16 from full height
        face_cx = detect_face_center_x(source_video, start, clip_duration)

        if face_cx is not None and w > crop_width:
            # Center the crop around the face
            crop_x = max(0, min(face_cx - crop_width // 2, w - crop_width))
            filters.append(f"crop={crop_width}:{h}:{crop_x}:0")
            logger.info(f"Clip {clip_index}: face-centered crop at x={crop_x}")
        else:
            # Fallback: center crop
            filters.append("crop=ih*9/16:ih")

        filters.append("scale=1080:1920")

    if professional:
        # Color grade: slight contrast boost + warm tones
        filters.append("eq=contrast=1.05:brightness=0.02:saturation=1.15")
        # Subtle slow zoom (1.0 → 1.04 over the clip) for engagement
        # Using zoompan: zoom from 1.0 to 1.04
        total_frames = int(clip_duration * fps)
        if total_frames > 0:
            filters.append(
                f"zoompan=z='1+0.04*on/{total_frames}':d=1:s=1080x1920:fps={fps}"
            )
        # Fade in first 0.5s, fade out last 0.5s
        filters.append(f"fade=t=in:st=0:d=0.5,fade=t=out:st={max(clip_duration - 0.5, 0)}:d=0.5")

    # Add subtitles if available via FFmpeg filter (preferred path)
    has_srt_filter = srt_path and Path(srt_path).exists() and _check_subtitles_filter()
    if has_srt_filter:
        safe_srt = srt_path.replace("\\", "/").replace(":", "\\\\:")
        style = (
            "FontSize=24,FontName=Helvetica,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,BorderStyle=3,Outline=2,MarginV=200"
        )
        filters.append(f"subtitles={safe_srt}:force_style='{style}'")

    vf = ",".join(filters)

    # Audio: normalize loudness + fade
    af_parts = []
    af_parts.append(f"afade=t=in:st=0:d=0.3,afade=t=out:st={max(clip_duration - 0.3, 0)}:d=0.3")
    if professional:
        af_parts.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    af = ",".join(af_parts)

    cmd = [
        FFMPEG_PATH, "-y",
        "-ss", str(start),
        "-i", source_video,
        "-t", str(clip_duration),
        "-vf", vf,
        "-af", af,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        "-r", str(fps),
        base_clip,
    ]

    logger.info(f"Processing clip {clip_index}: {start:.1f}s-{end:.1f}s (professional={professional})")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"FFmpeg base clip error: {result.stderr[:500]}")
        # Fallback: simpler filter chain without zoompan/color grade
        filters_simple = []
        if aspect <= 0.5625 + 0.05:
            filters_simple.append("scale=1080:1920:force_original_aspect_ratio=decrease")
            filters_simple.append("pad=1080:1920:(ow-iw)/2:(oh-ih)/2")
        else:
            filters_simple.append("crop=ih*9/16:ih")
            filters_simple.append("scale=1080:1920")
        vf_simple = ",".join(filters_simple)
        cmd_simple = [
            FFMPEG_PATH, "-y",
            "-ss", str(start), "-i", source_video, "-t", str(clip_duration),
            "-vf", vf_simple,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            base_clip,
        ]
        result2 = subprocess.run(cmd_simple, capture_output=True, text=True)
        if result2.returncode != 0:
            logger.error(f"FFmpeg simple fallback also failed: {result2.stderr[:500]}")
            raise subprocess.CalledProcessError(result2.returncode, cmd_simple)

    # ── Step 2: Caption overlay (Pillow-rendered) ──
    # Only if we didn't already burn subtitles via FFmpeg's subtitles filter
    if caption_chunks and not has_srt_filter:
        caption_overlay = str(out / f"_captions_{clip_index}{suffix}.mov")
        try:
            actual_dur = get_video_duration(base_clip)
            actual_fps = _get_fps(base_clip)
            generate_caption_video(
                caption_chunks, caption_overlay,
                actual_dur, actual_fps,
                1080, 1920, language,
            )

            # Overlay captions onto base clip
            with_captions = str(out / f"_captioned_{clip_index}{suffix}.mp4")
            overlay_cmd = [
                FFMPEG_PATH, "-y",
                "-i", base_clip,
                "-i", caption_overlay,
                "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto[v]",
                "-map", "[v]", "-map", "0:a",
                "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                "-c:a", "copy",
                with_captions,
            ]
            ov_result = subprocess.run(overlay_cmd, capture_output=True, text=True)
            if ov_result.returncode == 0:
                os.replace(with_captions, base_clip)
                logger.info(f"Clip {clip_index}: captions overlaid")
            else:
                logger.warning(f"Caption overlay failed, using base: {ov_result.stderr[:200]}")
            # Cleanup
            Path(caption_overlay).unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Caption generation failed for clip {clip_index}: {e}")

    # ── Step 3: Mix background music ──
    if professional:
        bg_music = _find_bg_music(clip_duration)
        if bg_music and Path(bg_music).exists():
            with_music = str(out / f"_music_{clip_index}{suffix}.mp4")
            music_cmd = [
                FFMPEG_PATH, "-y",
                "-i", base_clip,
                "-i", bg_music,
                "-filter_complex",
                f"[1:a]atrim=0:{clip_duration},volume=0.08,afade=t=in:d=1,afade=t=out:st={max(clip_duration - 1, 0)}:d=1[bg];"
                "[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[a]",
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                with_music,
            ]
            music_result = subprocess.run(music_cmd, capture_output=True, text=True)
            if music_result.returncode == 0:
                os.replace(with_music, base_clip)
                logger.info(f"Clip {clip_index}: background music mixed")
            else:
                logger.warning(f"Music mix failed: {music_result.stderr[:200]}")

    # Move base to final
    os.replace(base_clip, final_clip)

    # Cleanup temp files
    for pattern in [f"_base_{clip_index}*", f"_captions_{clip_index}*", f"_captioned_{clip_index}*", f"_music_{clip_index}*"]:
        for f in out.glob(pattern):
            f.unlink(missing_ok=True)

    logger.info(f"Clip {clip_index} done: {final_clip}")
    return final_clip
