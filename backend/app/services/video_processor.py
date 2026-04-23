"""Video Processing Pipeline — influencer-style reel/short editor.

Per clip:
  1. Cut from source (precise seek).
  2. **Smooth speaker-tracking 9:16 crop** (continuous face track + EMA pan).
  3. **Audio-energy punch-in zooms** on emphasis peaks.
  4. Color grade (contrast / saturation lift).
  5. Fade in/out.
  6. Burn **word-pop captions** (Hormozi / MrBeast / Minimal / Bold preset)
     with optional **hook intro card** and **CTA endcard**.
  7. Mix subtle background music (or generated ambience).
  8. Loudness-normalize the speech track.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import List, Dict, Optional

from app.config import (
    FFMPEG_PATH, BASE_DIR,
    CAPTION_STYLE, WORD_POP_CAPTIONS, PUNCH_ZOOMS,
    HOOK_INTRO, CTA_ENDCARD, CTA_TEXT, SMOOTH_SPEAKER_TRACK,
    GRID_SPEAKER_TRACK, GRID_TRACK_COLS, GRID_TRACK_ROWS,
    TRIM_SILENCES, SILENCE_THRESHOLD_DB, SILENCE_MIN_DURATION, SILENCE_PADDING,
    TRIM_FILLER_WORDS, FILLER_PAD_MS,
)
from app.services import editing
from app.services.editing import (
    get_dims, get_fps, get_duration,
    track_speaker, track_speaker_grid, smooth_track, build_pan_crop_filter,
    build_dynamic_frame_graph,
    extract_audio_energy, find_emphasis_times, build_zoompan_expression,
    get_caption_style, group_words_into_chunks, generate_overlay_video,
    trim_silences,
    find_filler_ranges,
    trim_ranges,
)

logger = logging.getLogger(__name__)

ASSETS_DIR = BASE_DIR / "assets"
ASSETS_DIR.mkdir(exist_ok=True)
MUSIC_DIR = ASSETS_DIR / "music"
MUSIC_DIR.mkdir(exist_ok=True)


# ─────────────────────────── Public exports for back-compat ───────────────────────────

def get_video_duration(p: str) -> float:
    return get_duration(p)


# ─────────────────────────── Background music ───────────────────────────

def _generate_ambient_music(output_path: str, duration: float) -> str:
    """Generate a subtle ambient sine-wave bed (used when no music files exist)."""
    cmd = [
        FFMPEG_PATH, "-y",
        "-f", "lavfi", "-i", f"sine=frequency=220:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=330:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-filter_complex",
        "[0:a]volume=0.03[a0];"
        "[1:a]volume=0.02[a1];"
        "[2:a]volume=0.01[a2];"
        "[a0][a1][a2]amix=inputs=3:duration=first[mixed];"
        f"[mixed]lowpass=f=800,afade=t=in:st=0:d=2,afade=t=out:st={max(duration - 2, 0)}:d=2[out]",
        "-map", "[out]", "-c:a", "aac", "-b:a", "64k",
        output_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return output_path if r.returncode == 0 else ""


def _find_bg_music(duration: float) -> Optional[str]:
    for ext in ("mp3", "aac", "m4a", "wav"):
        cands = list(MUSIC_DIR.glob(f"*.{ext}"))
        if cands:
            return str(cands[0])
    ambient = str(ASSETS_DIR / "ambient_bg.aac")
    if not Path(ambient).exists() or get_duration(ambient) < duration:
        out = _generate_ambient_music(ambient, duration + 5)
        return out or None
    return ambient


# ─────────────────────────── Main per-clip processor ───────────────────────────

def process_clip(
    source_video: str,
    start: float,
    end: float,
    srt_path: Optional[str],
    output_dir: str,
    clip_index: int,
    version: Optional[int] = None,
    caption_chunks: Optional[List[Dict]] = None,
    word_timestamps: Optional[List[Dict]] = None,
    language: str = "english",
    professional: bool = True,
    hook_text: Optional[str] = None,
) -> str:
    """Render one influencer-style reel.

    Args:
        caption_chunks: legacy chunk-level captions (used if word_timestamps missing).
        word_timestamps: flat list of {"word", "start", "end"} relative to source.
                         When provided + WORD_POP_CAPTIONS=true, used for word-pop captions.
        hook_text: text for the intro hook card (e.g. clip title).
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    suffix = f"_v{version}" if version and version > 1 else ""
    final_clip = str(out / f"clip_{clip_index}{suffix}.mp4")
    base_clip = str(out / f"_base_{clip_index}{suffix}.mp4")
    duration = end - start

    sw, sh = get_dims(source_video)
    fps = get_fps(source_video)

    # ── Build video filter chain (Step 1: cut + crop + grade + fades + zoom) ──
    filters: List[str] = []
    aspect = sw / sh if sh > 0 else 1.0

    # Will be set in landscape branch when we use a filter_complex graph for
    # dynamic speaker-following + blurred-letterbox wide shots.
    complex_prefix: Optional[str] = None
    chain_in_label: Optional[str] = None  # label feeding the linear `filters` chain

    if aspect <= 0.5625 + 0.05:
        # Already vertical-ish — pad/scale
        filters.append("scale=1080:1920:force_original_aspect_ratio=decrease")
        filters.append("pad=1080:1920:(ow-iw)/2:(oh-ih)/2")
    else:
        # Landscape → smooth speaker-tracked vertical crop
        crop_w = int(sh * 9 / 16)
        if SMOOTH_SPEAKER_TRACK:
            if GRID_SPEAKER_TRACK:
                track = track_speaker_grid(
                    source_video, start, duration,
                    src_w=sw, src_h=sh, base_crop_w=crop_w,
                    grid_cols=GRID_TRACK_COLS, grid_rows=GRID_TRACK_ROWS,
                    sample_hz=2.0,
                )
                tracker_name = f"grid({GRID_TRACK_ROWS}x{GRID_TRACK_COLS})"
            else:
                track = track_speaker(
                    source_video, start, duration,
                    src_w=sw, src_h=sh, base_crop_w=crop_w,
                    sample_hz=2.0,
                )
                tracker_name = "face/mouth"
            track = smooth_track(track, alpha_cx=0.25, alpha_cw=0.12)
            n_wide = sum(1 for p in track if p.cw > crop_w * 1.05)
            complex_prefix = build_dynamic_frame_graph(
                track, src_w=sw, src_h=sh, base_crop_w=crop_w,
                in_label="0:v", out_label="framed",
                out_w=1080, out_h=1920,
            )
            chain_in_label = "framed"
            logger.info(
                f"Clip {clip_index}: {tracker_name} tracker → {len(track)} keyframes "
                f"({n_wide} wide-shot frames)"
            )
        else:
            # Static center crop fallback.
            filters.append(f"crop={crop_w}:{sh}:(in_w-{crop_w})/2:0")
            filters.append("scale=1080:1920")

    if professional:
        # Color grade
        filters.append("eq=contrast=1.05:brightness=0.02:saturation=1.15")

        # Punch-in zooms tied to audio peaks
        if PUNCH_ZOOMS:
            env, _ = extract_audio_energy(source_video, start, duration)
            peaks = find_emphasis_times(env, hop_sec=0.02, min_gap=2.5, top_k=3)
            zp = build_zoompan_expression(duration, fps, peaks,
                                           base_zoom=1.0, peak_zoom=1.10)
            if zp:
                filters.append(zp)
                logger.info(f"Clip {clip_index}: punch-in zooms at {peaks}")

        # Fades
        filters.append(
            f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(duration - 0.4, 0)}:d=0.4"
        )

    vf = ",".join(filters)

    # Audio: fades + loudness normalization
    af_parts = [f"afade=t=in:st=0:d=0.3,afade=t=out:st={max(duration - 0.3, 0)}:d=0.3"]
    if professional:
        af_parts.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    af = ",".join(af_parts)

    if complex_prefix and chain_in_label:
        # Compose: <complex_prefix>;[chain_in_label]<linear filters>[vout]
        if vf:
            graph = f"{complex_prefix};[{chain_in_label}]{vf}[vout]"
        else:
            graph = f"{complex_prefix.replace(f'[{chain_in_label}]', '[vout]', 1)}"
            # Fallback: if we had no extra filters, just rename the last label.
            if "[vout]" not in graph:
                graph = f"{complex_prefix};[{chain_in_label}]copy[vout]"
        cmd = [
            FFMPEG_PATH, "-y",
            "-ss", str(start), "-i", source_video, "-t", str(duration),
            "-filter_complex", graph,
            "-map", "[vout]", "-map", "0:a?",
            "-af", af,
            "-c:v", "libx264", "-preset", "fast", "-crf", "21",
            "-c:a", "aac", "-b:a", "128k",
            "-r", str(fps),
            base_clip,
        ]
    else:
        cmd = [
            FFMPEG_PATH, "-y",
            "-ss", str(start), "-i", source_video, "-t", str(duration),
            "-vf", vf, "-af", af,
            "-c:v", "libx264", "-preset", "fast", "-crf", "21",
            "-c:a", "aac", "-b:a", "128k",
            "-r", str(fps),
            base_clip,
        ]
    logger.info(f"Clip {clip_index}: base render ({start:.1f}-{end:.1f}s, professional={professional})")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        logger.error(f"FFmpeg base render failed: {r.stderr[-500:]}")
        # Fallback: simple center crop
        simple = ["scale=1080:1920:force_original_aspect_ratio=decrease",
                  "pad=1080:1920:(ow-iw)/2:(oh-ih)/2"] if aspect <= 0.5625 + 0.05 else \
                 [f"crop=ih*9/16:ih", "scale=1080:1920"]
        r2 = subprocess.run([
            FFMPEG_PATH, "-y", "-ss", str(start), "-i", source_video, "-t", str(duration),
            "-vf", ",".join(simple),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", base_clip,
        ], capture_output=True, text=True)
        if r2.returncode != 0:
            raise subprocess.CalledProcessError(r2.returncode, "ffmpeg")

    actual_dur = get_duration(base_clip)
    actual_fps = get_fps(base_clip) or fps

    # ── Step 2: Caption overlay (word-pop, hook, CTA) ──
    style = get_caption_style(CAPTION_STYLE)

    # Build word-pop chunks: use word-level timestamps if available
    pop_chunks: List[Dict] = []
    if word_timestamps and WORD_POP_CAPTIONS:
        # Re-base timestamps to be relative to clip start
        rel_words = [
            {"word": w["word"],
             "start": max(0, w["start"] - start),
             "end": max(0, w["end"] - start)}
            for w in word_timestamps
            if start <= w["start"] < end
        ]
        pop_chunks = group_words_into_chunks(rel_words, style.words_per_chunk)
    elif caption_chunks:
        # Fallback: synthesize word timings from chunk-level captions
        synth: List[Dict] = []
        for c in caption_chunks:
            toks = c["text"].split()
            if not toks:
                continue
            dur = max(c["end"] - c["start"], 0.001)
            per = dur / len(toks)
            for i, w in enumerate(toks):
                synth.append({
                    "word": w,
                    "start": c["start"] + i * per,
                    "end": c["start"] + (i + 1) * per,
                })
        pop_chunks = group_words_into_chunks(synth, style.words_per_chunk)

    if pop_chunks or (HOOK_INTRO and hook_text) or CTA_ENDCARD:
        overlay_path = str(out / f"_overlay_{clip_index}{suffix}.mov")
        try:
            generate_overlay_video(
                chunks=pop_chunks,
                output_path=overlay_path,
                duration=actual_dur,
                fps=actual_fps,
                width=1080,
                height=1920,
                style=style,
                language=language,
                hook_text=hook_text if HOOK_INTRO else None,
                cta_text=CTA_TEXT if CTA_ENDCARD else None,
                hook_dur=1.2,
                cta_dur=1.2,
            )

            with_overlay = str(out / f"_overlaid_{clip_index}{suffix}.mp4")
            ov = subprocess.run([
                FFMPEG_PATH, "-y",
                "-i", base_clip, "-i", overlay_path,
                "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto[v]",
                "-map", "[v]", "-map", "0:a",
                "-c:v", "libx264", "-preset", "fast", "-crf", "21",
                "-c:a", "copy",
                with_overlay,
            ], capture_output=True, text=True)
            if ov.returncode == 0:
                os.replace(with_overlay, base_clip)
                logger.info(f"Clip {clip_index}: overlay applied ({len(pop_chunks)} caption chunks)")
            else:
                logger.warning(f"Overlay apply failed: {ov.stderr[-300:]}")
            Path(overlay_path).unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Overlay generation failed: {e}")

    # ── Step 3: Background music ──
    if professional:
        bg = _find_bg_music(actual_dur)
        if bg and Path(bg).exists():
            with_music = str(out / f"_music_{clip_index}{suffix}.mp4")
            mr = subprocess.run([
                FFMPEG_PATH, "-y",
                "-i", base_clip, "-i", bg,
                "-filter_complex",
                f"[1:a]atrim=0:{actual_dur},volume=0.07,"
                f"afade=t=in:d=1,afade=t=out:st={max(actual_dur - 1, 0)}:d=1[bg];"
                "[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[a]",
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                with_music,
            ], capture_output=True, text=True)
            if mr.returncode == 0:
                os.replace(with_music, base_clip)
                logger.info(f"Clip {clip_index}: background music mixed")
            else:
                logger.warning(f"Music mix failed: {mr.stderr[-300:]}")

    os.replace(base_clip, final_clip)

    # ── Step 4a: Trim filler words ("um", "uh", "matlab"...) using word timestamps ──
    if TRIM_FILLER_WORDS and word_timestamps:
        # Re-base words to clip-relative time and find filler ranges.
        rel_words = [
            {"word": w["word"],
             "start": max(0.0, w["start"] - start),
             "end": max(0.0, w["end"] - start)}
            for w in word_timestamps
            if start <= w["start"] < end
        ]
        filler_ranges = find_filler_ranges(rel_words, pad_ms=FILLER_PAD_MS)
        if filler_ranges:
            cut_path = str(out / f"_filler_{clip_index}{suffix}.mp4")
            try:
                if trim_ranges(final_clip, cut_path, filler_ranges):
                    os.replace(cut_path, final_clip)
                    logger.info(
                        f"Clip {clip_index}: filler-word jump cuts ({len(filler_ranges)} ranges removed)"
                    )
                else:
                    Path(cut_path).unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Clip {clip_index}: filler-word trim skipped ({e})")
                Path(cut_path).unlink(missing_ok=True)

    # ── Step 4b: Trim long silent gaps (optional, tightens pacing) ──
    if TRIM_SILENCES:
        trimmed = str(out / f"_trimmed_{clip_index}{suffix}.mp4")
        try:
            if trim_silences(
                final_clip, trimmed,
                threshold_db=SILENCE_THRESHOLD_DB,
                min_duration=SILENCE_MIN_DURATION,
                padding=SILENCE_PADDING,
            ):
                os.replace(trimmed, final_clip)
            else:
                Path(trimmed).unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Clip {clip_index}: silence trim skipped ({e})")
            Path(trimmed).unlink(missing_ok=True)

    # Cleanup leftovers
    for pat in [f"_base_{clip_index}*", f"_overlay_{clip_index}*",
                f"_overlaid_{clip_index}*", f"_music_{clip_index}*",
                f"_trimmed_{clip_index}*", f"_filler_{clip_index}*"]:
        for f in out.glob(pat):
            f.unlink(missing_ok=True)

    logger.info(f"Clip {clip_index} done: {final_clip}")
    return final_clip
