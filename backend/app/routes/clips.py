"""Clip routes — get clips, regenerate captions, customize, version management."""

from pathlib import Path
from typing import List
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.config import BASE_DIR
from app.database import get_db
from app.models import User, Clip, ClipVersion, Project
from app.schemas import ClipOut, ClipCustomizeRequest
from app.services.content_generator import generate_all_captions
from app.services.pipeline import run_clip_customize

router = APIRouter()


@router.get("/{project_id}", response_model=List[ClipOut])
async def get_clips(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get all clips for a project."""
    proj = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    if not proj.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    result = await db.execute(
        select(Clip)
        .where(Clip.project_id == project_id)
        .options(selectinload(Clip.versions))
        .order_by(Clip.score.desc())
    )
    return result.scalars().all()


@router.get("/{clip_id}/download")
async def download_clip(
    clip_id: str,
    version: int | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Download a processed clip video file. Optionally specify a version."""
    result = await db.execute(
        select(Clip).where(Clip.id == clip_id).options(selectinload(Clip.versions))
    )
    clip = result.scalar_one_or_none()
    if not clip or not clip.video_path:
        raise HTTPException(status_code=404, detail="Clip not found")

    # Verify ownership
    proj = await db.execute(
        select(Project).where(Project.id == clip.project_id, Project.user_id == user.id)
    )
    if not proj.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Forbidden")

    # Determine video path — use version-specific path if requested
    video_file_str = clip.video_path
    if version:
        ver = next((v for v in clip.versions if v.version_num == version), None)
        if ver and ver.video_path:
            video_file_str = ver.video_path

    video_file = Path(video_file_str)
    if not video_file.is_absolute():
        video_file = BASE_DIR / video_file
    if not video_file.exists():
        raise HTTPException(status_code=404, detail="Video file not found")

    ver_suffix = f"_v{version}" if version else ""
    return FileResponse(
        str(video_file),
        media_type="video/mp4",
        filename=f"{clip.title or 'clip'}{ver_suffix}.mp4",
    )


@router.post("/{clip_id}/regenerate", response_model=ClipOut)
async def regenerate_captions(
    clip_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Regenerate all captions for a clip using the LLM."""
    result = await db.execute(
        select(Clip).where(Clip.id == clip_id).options(selectinload(Clip.versions))
    )
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    proj = await db.execute(
        select(Project).where(Project.id == clip.project_id, Project.user_id == user.id)
    )
    if not proj.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Forbidden")

    captions = generate_all_captions(clip.transcript_text)
    clip.caption_instagram = captions["instagram"]
    clip.caption_linkedin = captions["linkedin"]
    clip.caption_twitter = captions["twitter"]
    clip.caption_youtube = captions["youtube"]
    await db.commit()
    await db.refresh(clip)
    return clip


@router.post("/{clip_id}/customize", response_model=ClipOut)
async def customize_clip(
    clip_id: str,
    body: ClipCustomizeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new version of a clip with custom requirements."""
    result = await db.execute(
        select(Clip).where(Clip.id == clip_id).options(selectinload(Clip.versions))
    )
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    proj = await db.execute(
        select(Project).where(Project.id == clip.project_id, Project.user_id == user.id)
    )
    if not proj.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Forbidden")

    # Run customization in background
    background_tasks.add_task(run_clip_customize, str(clip.id), body.custom_prompt)
    return clip


@router.post("/{clip_id}/switch-version", response_model=ClipOut)
async def switch_version(
    clip_id: str,
    version: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Switch the active version for a clip."""
    result = await db.execute(
        select(Clip).where(Clip.id == clip_id).options(selectinload(Clip.versions))
    )
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    proj = await db.execute(
        select(Project).where(Project.id == clip.project_id, Project.user_id == user.id)
    )
    if not proj.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Forbidden")

    ver = next((v for v in clip.versions if v.version_num == version), None)
    if not ver:
        raise HTTPException(status_code=404, detail=f"Version {version} not found")

    clip.active_version = version
    clip.video_path = ver.video_path
    clip.caption_instagram = ver.caption_instagram
    clip.caption_linkedin = ver.caption_linkedin
    clip.caption_twitter = ver.caption_twitter
    clip.caption_youtube = ver.caption_youtube
    await db.commit()
    await db.refresh(clip)
    return clip
