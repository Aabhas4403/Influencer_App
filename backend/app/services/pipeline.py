"""Background pipeline — orchestrates the full video processing workflow.

Features:
  - Progress tracking with ETA
  - Caching: skip work for duplicate URLs
  - Proper language detection (Hindi/English/Hinglish)
  - Professional editing: zoom, color grade, captions, background music
  - NO aggressive silence removal (preserves audio-video sync)
  - Clip versioning
"""

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import CLIPS_DIR
from app.database import async_session
from app.models import Project, Clip, ClipVersion
from app.services.transcription_service import transcribe, generate_srt, flatten_words
from app.services.clip_detection import detect_clips
from app.services.video_processor import process_clip, get_video_duration
from app.services.content_generator import generate_all_captions

logger = logging.getLogger(__name__)


async def _update_progress(db, project, pct: int, stage: str, detail: str = "", eta: int | None = None):
    """Update project progress fields and commit."""
    project.progress_pct = pct
    project.progress_stage = stage
    project.progress_detail = detail
    project.eta_seconds = eta
    await db.commit()


def _compute_hash(video_url: str | None, video_path: str | None) -> str:
    """Compute a cache key for a video (URL hash or file hash)."""
    if video_url:
        return hashlib.sha256(video_url.encode()).hexdigest()
    if video_path and Path(video_path).exists():
        h = hashlib.sha256()
        with open(video_path, "rb") as f:
            data = f.read(10 * 1024 * 1024)
            h.update(data)
        return h.hexdigest()
    return ""


async def _check_cache(db, project) -> Project | None:
    """Check if another project with the same video already has results."""
    if not project.video_hash:
        return None
    result = await db.execute(
        select(Project)
        .where(
            Project.video_hash == project.video_hash,
            Project.id != project.id,
            Project.status == "done",
        )
        .options(selectinload(Project.clips).selectinload(Clip.versions))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _copy_from_cache(db, project, cached: Project):
    """Copy clips from a cached project."""
    logger.info(f"[{project.id}] Cache hit! Copying from {cached.id}")
    project.transcript = cached.transcript
    project.duration = cached.duration
    project.language = cached.language

    for clip in cached.clips:
        new_clip = Clip(
            project_id=project.id,
            clip_index=clip.clip_index,
            start_time=clip.start_time,
            end_time=clip.end_time,
            score=clip.score,
            score_features=clip.score_features,
            hook_variants=clip.hook_variants,
            title=clip.title,
            transcript_text=clip.transcript_text,
            video_path=clip.video_path,
            srt_path=clip.srt_path,
            caption_instagram=clip.caption_instagram,
            caption_linkedin=clip.caption_linkedin,
            caption_twitter=clip.caption_twitter,
            caption_youtube=clip.caption_youtube,
            active_version=1,
        )
        db.add(new_clip)
        await db.flush()
        if clip.versions:
            v = clip.versions[0]
            db.add(ClipVersion(
                clip_id=new_clip.id, version_num=1,
                video_path=v.video_path, srt_path=v.srt_path,
                caption_instagram=v.caption_instagram,
                caption_linkedin=v.caption_linkedin,
                caption_twitter=v.caption_twitter,
                caption_youtube=v.caption_youtube,
            ))

    project.status = "done"
    project.progress_pct = 100
    project.progress_stage = "Complete (cached)"
    await db.commit()


async def run_pipeline(project_id: str):
    """Run the full processing pipeline for a project."""
    async with async_session() as db:
        try:
            result = await db.execute(
                select(Project).where(Project.id == project_id)
            )
            project = result.scalar_one_or_none()
            if not project:
                logger.error(f"Project {project_id} not found")
                return

            video_path = project.video_path
            if not video_path or not Path(video_path).exists():
                project.status = "failed"
                project.progress_stage = "Video file not found"
                await db.commit()
                return

            # Compute video hash for caching
            project.video_hash = _compute_hash(project.video_url, video_path)
            await db.commit()

            # Check cache
            cached = await _check_cache(db, project)
            if cached:
                await _copy_from_cache(db, project, cached)
                logger.info(f"[{project_id}] Pipeline done (from cache)")
                return

            pipeline_start = time.time()

            # ── Step 1: Transcription (2-50%) ──
            # NOTE: We transcribe the ORIGINAL video — no silence removal.
            # Silence removal caused audio-video desync; pauses are natural and
            # provide context for the viewer.
            chunks_file = Path(video_path).with_suffix(".chunks.json")
            if project.transcript and chunks_file.exists():
                logger.info(f"[{project_id}] Transcript cached, skipping")
                await _update_progress(db, project, 50, "Transcription", "Using cached transcript")
                with open(chunks_file) as f:
                    chunks = json.load(f)
                language = project.language or "english"
            else:
                project.status = "transcribing"
                video_dur = get_video_duration(video_path)
                await _update_progress(db, project, 2, "Transcribing video",
                                       "Detecting language & transcribing (Hindi/English/Hinglish)...",
                                       eta=int(video_dur * 0.25))

                transcript_result = await asyncio.to_thread(transcribe, video_path)
                project.transcript = transcript_result["full_text"]
                project.duration = video_dur
                language = transcript_result.get("language", "english")
                project.language = language
                chunks = transcript_result["chunks"]

                with open(chunks_file, "w") as f:
                    json.dump(chunks, f, ensure_ascii=False)
                await db.commit()

                await _update_progress(db, project, 50, "Transcription complete",
                                       f"Language: {language}, {len(chunks)} segments")

            if not chunks:
                project.status = "failed"
                project.progress_stage = "No transcript produced"
                await db.commit()
                return

            # ── Step 2: Clip detection (55%) ──
            project.status = "detecting"
            await _update_progress(db, project, 55, "Detecting viral moments",
                                   f"Scoring {len(chunks)} segments...")

            # Honor user-supplied manual selections (skip auto-detection).
            top_clips: list[dict] = []
            if project.manual_selections:
                try:
                    user_ranges = json.loads(project.manual_selections)
                except Exception:
                    user_ranges = []
                video_dur = project.duration or get_video_duration(video_path)
                for r in user_ranges:
                    s = max(0.0, float(r["start"]))
                    e = min(video_dur, float(r["end"]))
                    if e <= s:
                        continue
                    seg_chunks = [c for c in chunks if c["start"] >= s and c["end"] <= e]
                    text = " ".join(c["text"] for c in seg_chunks).strip() or ""
                    top_clips.append({
                        "start": s,
                        "end": e,
                        "text": text,
                        "score": 100.0,  # user-picked = max priority
                        "title": None,   # let content_generator pick a title
                    })
                # Optional: rewrite hooks with the LLM for the user's picks too.
                if top_clips:
                    from app.services.clip_detection import generate_hook_variants
                    for clip in top_clips:
                        if not clip["text"]:
                            continue
                        try:
                            variants = await asyncio.to_thread(
                                generate_hook_variants, clip["text"], 3
                            )
                            if variants:
                                clip["hook_variants"] = variants
                                # Replace first sentence with the chosen hook
                                import re as _re
                                sentences = _re.split(r'(?<=[.!?])\s+', clip["text"], maxsplit=1)
                                rest = sentences[1] if len(sentences) > 1 else ""
                                new_text = f"{variants[0]} {rest}".strip() if rest else variants[0]
                                if new_text != clip["text"]:
                                    clip["original_text"] = clip["text"]
                                    clip["text"] = new_text
                        except Exception:
                            pass
                    logger.info(f"[{project_id}] Using {len(top_clips)} user-picked clips")
            else:
                top_clips = await asyncio.to_thread(
                    detect_clips, chunks, 5, 20.0, 60.0, project.transcript or ""
                )
            if not top_clips:
                project.status = "failed"
                project.progress_stage = "No clips detected"
                await db.commit()
                return

            await _update_progress(db, project, 60, "Found clips",
                                   f"{len(top_clips)} viral moments detected")

            # ── Step 3: Process each clip (60-90%) ──
            project.status = "processing"
            clip_output_dir = str(CLIPS_DIR / str(project_id))
            per_clip_pct = 30 / max(len(top_clips), 1)
            clip_start_time = time.time()

            for i, clip_data in enumerate(top_clips):
                pct = int(60 + (i * per_clip_pct))
                elapsed_per = (time.time() - clip_start_time) / max(i, 1) if i > 0 else 30
                eta_secs = int(elapsed_per * (len(top_clips) - i))

                await _update_progress(db, project, pct, "Processing clips",
                                       f"Clip {i + 1} of {len(top_clips)} — editing & adding captions",
                                       eta=eta_secs)

                # Gather caption chunks for this clip (with relative timestamps)
                clip_chunks = [c for c in chunks
                               if c["start"] >= clip_data["start"] and c["end"] <= clip_data["end"]]
                adjusted = [{"start": c["start"] - clip_data["start"],
                             "end": c["end"] - clip_data["start"],
                             "text": c["text"]} for c in clip_chunks]

                # Word-level timestamps (used by word-pop captions, kept in absolute time)
                all_words = flatten_words(chunks)
                clip_words = [w for w in all_words
                              if clip_data["start"] <= w["start"] < clip_data["end"]]

                # Generate SRT file
                srt_path = str(Path(clip_output_dir) / f"clip_{i}.srt")
                Path(clip_output_dir).mkdir(parents=True, exist_ok=True)
                generate_srt(adjusted, srt_path)

                # Professional video processing (uses ORIGINAL video — no silence removal)
                final_path = None
                try:
                    final_path = await asyncio.to_thread(
                        process_clip,
                        video_path,
                        clip_data["start"],
                        clip_data["end"],
                        srt_path,
                        clip_output_dir,
                        i,
                        None,             # version
                        adjusted,         # caption_chunks
                        clip_words,       # word_timestamps
                        language,
                        True,             # professional
                        clip_data.get("title"),
                    )
                except Exception as e:
                    logger.error(f"[{project_id}] Clip {i} failed: {e}")

                captions = await asyncio.to_thread(generate_all_captions, clip_data["text"])

                clip = Clip(
                    project_id=project.id,
                    clip_index=i,
                    start_time=clip_data["start"],
                    end_time=clip_data["end"],
                    score=clip_data["score"],
                    score_features=(
                        json.dumps(clip_data["features"])
                        if clip_data.get("features") else None
                    ),
                    hook_variants=(
                        json.dumps(clip_data["hook_variants"])
                        if clip_data.get("hook_variants") else None
                    ),
                    title=clip_data.get("title", f"Clip {i + 1}"),
                    transcript_text=clip_data["text"],
                    video_path=final_path,
                    srt_path=srt_path,
                    caption_instagram=captions["instagram"],
                    caption_linkedin=captions["linkedin"],
                    caption_twitter=captions["twitter"],
                    caption_youtube=captions["youtube"],
                    active_version=1,
                )
                db.add(clip)
                await db.flush()

                db.add(ClipVersion(
                    clip_id=clip.id, version_num=1,
                    video_path=final_path, srt_path=srt_path,
                    caption_instagram=captions["instagram"],
                    caption_linkedin=captions["linkedin"],
                    caption_twitter=captions["twitter"],
                    caption_youtube=captions["youtube"],
                ))

            # ── Done ──
            project.status = "done"
            project.progress_pct = 100
            project.progress_stage = "Complete"
            project.progress_detail = f"{len(top_clips)} clips ready"
            project.eta_seconds = 0
            elapsed = time.time() - pipeline_start
            logger.info(f"[{project_id}] Pipeline complete in {elapsed:.0f}s")
            await db.commit()

        except Exception as e:
            logger.exception(f"[{project_id}] Pipeline error: {e}")
            try:
                project.status = "failed"
                project.progress_stage = f"Error: {str(e)[:200]}"
                await db.commit()
            except Exception:
                pass


async def run_clip_customize(clip_id: str, custom_prompt: str):
    """Re-generate a single clip with custom user requirements. Creates a new version."""
    async with async_session() as db:
        try:
            result = await db.execute(
                select(Clip).where(Clip.id == clip_id)
                .options(selectinload(Clip.versions))
            )
            clip = result.scalar_one_or_none()
            if not clip:
                return

            proj_result = await db.execute(select(Project).where(Project.id == clip.project_id))
            project = proj_result.scalar_one()

            max_ver = max((v.version_num for v in clip.versions), default=0)
            new_ver = max_ver + 1

            logger.info(f"[clip {clip_id}] Creating V{new_ver}: {custom_prompt[:60]}...")

            from app.services.content_generator import generate_all_captions_custom
            captions = await asyncio.to_thread(
                generate_all_captions_custom, clip.transcript_text, custom_prompt
            )

            # Re-process video if prompt mentions video changes
            clip_dir = str(CLIPS_DIR / str(clip.project_id))
            video_path = clip.video_path

            video_kws = ["crop", "zoom", "music", "speed", "slow", "transition", "effect", "edit", "professional"]
            if any(kw in custom_prompt.lower() for kw in video_kws):
                try:
                    # Reload word timestamps from cached chunks if available
                    word_timestamps = None
                    chunks_file = Path(project.video_path).with_suffix(".chunks.json")
                    if chunks_file.exists():
                        import json as _json
                        with open(chunks_file) as f:
                            cached_chunks = _json.load(f)
                        all_words = flatten_words(cached_chunks)
                        word_timestamps = [w for w in all_words
                                           if clip.start_time <= w["start"] < clip.end_time]

                    video_path = await asyncio.to_thread(
                        process_clip,
                        project.video_path,
                        clip.start_time,
                        clip.end_time,
                        clip.srt_path,
                        clip_dir,
                        clip.clip_index,
                        new_ver,
                        None,                       # caption_chunks
                        word_timestamps,
                        project.language or "english",
                        True,                       # professional
                        clip.title,
                    )
                except Exception as e:
                    logger.error(f"[clip {clip_id}] V{new_ver} video failed: {e}")

            version = ClipVersion(
                clip_id=clip.id, version_num=new_ver,
                video_path=video_path, srt_path=clip.srt_path,
                caption_instagram=captions["instagram"],
                caption_linkedin=captions["linkedin"],
                caption_twitter=captions["twitter"],
                caption_youtube=captions["youtube"],
                custom_prompt=custom_prompt,
            )
            db.add(version)

            clip.active_version = new_ver
            clip.video_path = video_path
            clip.caption_instagram = captions["instagram"]
            clip.caption_linkedin = captions["linkedin"]
            clip.caption_twitter = captions["twitter"]
            clip.caption_youtube = captions["youtube"]

            await db.commit()
            logger.info(f"[clip {clip_id}] V{new_ver} created")

        except Exception as e:
            logger.exception(f"[clip {clip_id}] Customize error: {e}")
