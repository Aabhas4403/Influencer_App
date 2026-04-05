"""Rebuild project + clip records from disk artifacts."""
import asyncio
import json
import os
from pathlib import Path

from sqlalchemy import select
from app.database import async_session, engine
from app.models import Base, Clip, Project, User
from app.services.clip_detection import detect_clips
from app.services.content_generator import generate_all_captions

DB_PATH = "/Users/karnawat.a/Influencer_App/backend/clipflow.db"
UPLOADS = Path("/Users/karnawat.a/Influencer_App/backend/uploads")
CLIPS = Path("/Users/karnawat.a/Influencer_App/backend/clips")


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as db:
        # Get user
        user = (await db.execute(select(User))).scalar_one_or_none()
        if not user:
            print("No user found! Log in first to create a user.")
            return

        print(f"User: {user.email} ({user.id})")

        # Find clip directories with processed clips
        for clip_dir in sorted(CLIPS.iterdir()):
            if not clip_dir.is_dir():
                continue

            project_id = clip_dir.name
            clip_files = sorted(clip_dir.glob("clip_[0-9].mp4"))
            if not clip_files:
                print(f"\n{project_id[:12]}: No clip files, skipping")
                continue

            # Find the video + chunks
            chunks_file = None
            video_file = None
            for f in UPLOADS.glob("*.chunks.json"):
                chunks_file = f
                video_file = f.with_suffix(".mp4")
                # Try to match by checking if this chunks file was used for this project
                # Just use the first one that has a matching video
                if video_file.exists():
                    break

            if not chunks_file or not chunks_file.exists():
                print(f"\n{project_id[:12]}: No chunks file found, skipping")
                continue

            # Check if project already exists
            existing = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
            if existing:
                print(f"\n{project_id[:12]}: Already exists, updating clips only")
                project = existing
            else:
                project = Project(
                    id=project_id,
                    user_id=user.id,
                    title=f"Video ({len(clip_files)} clips)",
                    video_url="",
                    video_path=str(video_file) if video_file else "",
                    status="done",
                )
                db.add(project)
                print(f"\n{project_id[:12]}: Created project")

            # Load chunks
            with open(chunks_file) as f:
                chunks = json.load(f)

            top_clips = detect_clips(chunks, top_n=5)

            # Delete old clips
            old = (await db.execute(select(Clip).where(Clip.project_id == project_id))).scalars().all()
            for c in old:
                await db.delete(c)

            # Insert clips
            for i, clip_data in enumerate(top_clips):
                vpath = str(clip_dir / f"clip_{i}.mp4")
                spath = str(clip_dir / f"clip_{i}.srt")
                if not Path(vpath).exists():
                    continue

                captions = generate_all_captions(clip_data["text"])
                clip = Clip(
                    project_id=project_id,
                    start_time=clip_data["start"],
                    end_time=clip_data["end"],
                    score=clip_data["score"],
                    title=clip_data.get("title", f"Clip {i + 1}"),
                    transcript_text=clip_data["text"],
                    video_path=vpath,
                    srt_path=spath,
                    caption_instagram=captions["instagram"],
                    caption_linkedin=captions["linkedin"],
                    caption_twitter=captions["twitter"],
                    caption_youtube=captions["youtube"],
                )
                db.add(clip)
                print(f"  Clip {i}: {clip_data['start']:.0f}s-{clip_data['end']:.0f}s score={clip_data['score']}")

            project.status = "done"

        await db.commit()
        print("\nDone!")


asyncio.run(main())
