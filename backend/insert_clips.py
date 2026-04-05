"""Insert generated clips into the DB so the API can serve them."""
import asyncio
import json
from pathlib import Path

from app.database import async_session, engine
from app.models import Base, Clip, Project
from app.services.clip_detection import detect_clips
from app.services.content_generator import generate_all_captions
from sqlalchemy import select

PROJECT_ID = "76531ff5-137c-4bd2-9e87-8e3fe8531d5d"
CHUNKS_FILE = "uploads/58dcd49d-ac3f-443d-8711-facb777f460c.chunks.json"
OUT_DIR = "clips/76531ff5-137c-4bd2-9e87-8e3fe8531d5d"


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    with open(CHUNKS_FILE) as f:
        chunks = json.load(f)

    top_clips = detect_clips(chunks, top_n=5)

    async with async_session() as db:
        # Delete old clips for this project
        old = await db.execute(select(Clip).where(Clip.project_id == PROJECT_ID))
        for c in old.scalars().all():
            await db.delete(c)

        # Insert new clips
        for i, clip_data in enumerate(top_clips):
            video_path = str(Path(OUT_DIR) / f"clip_{i}.mp4")
            srt_path = str(Path(OUT_DIR) / f"clip_{i}.srt")

            # Generate captions (uses Ollama if available, else placeholder)
            captions = generate_all_captions(clip_data["text"])

            clip = Clip(
                project_id=PROJECT_ID,
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
            print(f"  Clip {i}: {clip_data['start']:.1f}s-{clip_data['end']:.1f}s score={clip_data['score']}")

        # Update project status to done
        result = await db.execute(select(Project).where(Project.id == PROJECT_ID))
        project = result.scalar_one()
        project.status = "done"

        await db.commit()
        print(f"\nInserted {len(top_clips)} clips, project status -> done")


asyncio.run(main())
