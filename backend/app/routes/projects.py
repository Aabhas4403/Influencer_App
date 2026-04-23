"""Project routes — upload video, start processing, get results."""

import shutil
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.config import UPLOAD_DIR
from app.database import get_db
from app.models import User, Project, Clip
from app.schemas import ProjectOut, SelectionsRequest
from app.services.pipeline import run_pipeline

router = APIRouter()


@router.post("/upload", response_model=ProjectOut, status_code=201)
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(None),
    video_url: str = Form(None),
    manual_select: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Upload a video file or provide a YouTube URL, then start the pipeline.

    If `manual_select=true`, the project is left in `pending_selection` status
    after the source video is ready. The user must then POST clip ranges to
    `/projects/{id}/selections` to kick off the rest of the pipeline.
    """
    if not file and not video_url:
        raise HTTPException(status_code=400, detail="Provide a file or video_url")

    project = Project(user_id=user.id, title="New Project")

    if file:
        # Save uploaded file
        ext = Path(file.filename).suffix or ".mp4"
        filename = f"{uuid.uuid4()}{ext}"
        dest = UPLOAD_DIR / filename
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)
        project.video_path = str(dest)
        project.title = file.filename or "Uploaded Video"

    elif video_url:
        # Download YouTube video using yt-dlp
        project.video_url = video_url
        project.title = "YouTube Video"
        filename = f"{uuid.uuid4()}.mp4"
        dest = UPLOAD_DIR / filename
        try:
            import subprocess, sys
            yt_dlp_bin = str(Path(sys.executable).parent / "yt-dlp")
            result = subprocess.run(
                [yt_dlp_bin, "--no-check-certificates", "-f", "best[height<=720]", "-o", str(dest), video_url],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                raise HTTPException(status_code=400, detail=f"yt-dlp error: {result.stderr[:200]}")
        except FileNotFoundError:
            raise HTTPException(status_code=500, detail="yt-dlp not installed. Run: pip install yt-dlp")
        project.video_path = str(dest)

    project.status = "pending_selection" if manual_select else "pending"
    db.add(project)
    await db.commit()

    # Re-fetch with clips eagerly loaded to avoid MissingGreenlet
    result = await db.execute(
        select(Project)
        .where(Project.id == project.id)
        .options(selectinload(Project.clips).selectinload(Clip.versions))
    )
    project = result.scalar_one()

    # Start background processing only if the user is not selecting clips manually
    if not manual_select:
        background_tasks.add_task(run_pipeline, str(project.id))

    return project


@router.get("", response_model=List[ProjectOut])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all projects for the current user."""
    result = await db.execute(
        select(Project)
        .where(Project.user_id == user.id)
        .options(selectinload(Project.clips).selectinload(Clip.versions))
        .order_by(Project.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a single project with its clips."""
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id, Project.user_id == user.id)
        .options(selectinload(Project.clips).selectinload(Clip.versions))
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a project and its clips."""
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await db.delete(project)
    await db.commit()


@router.post("/{project_id}/reprocess")
async def reprocess_project(
    project_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Re-run the pipeline on an existing project."""
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Delete existing clips
    from app.models import Clip
    existing = await db.execute(select(Clip).where(Clip.project_id == project_id))
    for clip in existing.scalars().all():
        await db.delete(clip)

    project.status = "pending"
    await db.commit()

    background_tasks.add_task(run_pipeline, str(project.id))
    return {"status": "reprocessing"}


@router.post("/{project_id}/selections", response_model=ProjectOut)
async def submit_selections(
    project_id: str,
    payload: SelectionsRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Persist the user-picked clip ranges and kick off the pipeline.

    Validates ranges (start < end, non-empty, no duplicates) and stores them as
    JSON on the project. The pipeline will then bypass auto-detection and use
    these ranges directly.
    """
    import json
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not payload.ranges:
        raise HTTPException(status_code=400, detail="At least one selection is required")

    cleaned: list[dict] = []
    for r in payload.ranges:
        if r.end <= r.start:
            raise HTTPException(status_code=400, detail=f"Invalid range: end must be greater than start (got {r.start}-{r.end})")
        if r.end - r.start < 2:
            raise HTTPException(status_code=400, detail=f"Selection too short ({r.end - r.start:.1f}s); minimum 2s")
        cleaned.append({"start": float(r.start), "end": float(r.end)})

    cleaned.sort(key=lambda x: x["start"])
    project.manual_selections = json.dumps(cleaned)
    project.status = "pending"
    await db.commit()

    background_tasks.add_task(run_pipeline, str(project.id))

    # Re-fetch with clips eagerly loaded
    result = await db.execute(
        select(Project)
        .where(Project.id == project.id)
        .options(selectinload(Project.clips).selectinload(Clip.versions))
    )
    return result.scalar_one()
