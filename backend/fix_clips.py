"""Re-insert clips for all projects with proper fallback captions."""
import asyncio
import json
from pathlib import Path

from sqlalchemy import select
from app.database import async_session, engine
from app.models import Base, Clip, Project
from app.services.clip_detection import detect_clips
from app.services.content_generator import generate_all_captions


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as db:
        projects = (await db.execute(select(Project))).scalars().all()
        print(f"Found {len(projects)} projects")

        for project in projects:
            print(f"\n--- {project.title} ({project.id[:12]}) ---")

            # Check for cached chunks
            if not project.video_path:
                print("  No video path, skipping")
                continue

            chunks_file = Path(project.video_path).with_suffix(".chunks.json")
            if not chunks_file.exists():
                print(f"  No chunks file at {chunks_file}, skipping")
                continue

            # Check for clip video files
            clip_dir = Path("clips") / project.id
            if not clip_dir.exists():
                print(f"  No clip dir at {clip_dir}, skipping")
                continue

            # Load chunks and detect clips
            with open(chunks_file) as f:
                chunks = json.load(f)

            top_clips = detect_clips(chunks, top_n=5)
            print(f"  Detected {len(top_clips)} clips")

            # Delete old clips
            old = (await db.execute(select(Clip).where(Clip.project_id == project.id))).scalars().all()
            for c in old:
                await db.delete(c)

            # Insert new clips
            for i, clip_data in enumerate(top_clips):
                video_path = str(clip_dir / f"clip_{i}.mp4")
                srt_path = str(clip_dir / f"clip_{i}.srt")

                if not Path(video_path).exists():
                    print(f"  Clip {i}: video not found, skipping")
                    continue

                captions = generate_all_captions(clip_data["text"])

                clip = Clip(
                    project_id=project.id,
                    start_time=clip_data["start"],
                    end_time=clip_data["end"],
                    score=clip_data["score"],
                    title=clip_data.get("title", f"Clip {i + 1}"),
                    transcript_text=clip_data["text"],
                    video_path=video_path,
                    srt_path=srt_path,
                    caption_instagram=captions["instagram"],
                    caption_linkedin=captions["linkedin"],
                    caption_twitter=captions["twitter"],
                    caption_youtube=captions["youtube"],
                )
                db.add(clip)
                print(f"  Clip {i}: OK")

            project.status = "done"

        await db.commit()
        print("\nDone!")


asyncio.run(main())
