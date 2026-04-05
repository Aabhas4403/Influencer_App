"""Quick script to regenerate clips using cached transcription data."""
import json
import os
from pathlib import Path

from app.services.clip_detection import detect_clips
from app.services.video_processor import process_clip
from app.services.transcription_service import generate_srt

# Load cached chunks (skips 7-min transcription)
CHUNKS_FILE = "uploads/58dcd49d-ac3f-443d-8711-facb777f460c.chunks.json"
VIDEO = "uploads/58dcd49d-ac3f-443d-8711-facb777f460c.mp4"
OUT_DIR = "clips/76531ff5-137c-4bd2-9e87-8e3fe8531d5d"

with open(CHUNKS_FILE) as f:
    chunks = json.load(f)

print(f"Loaded {len(chunks)} cached chunks")

# Detect clips
top_clips = detect_clips(chunks, top_n=5)
print(f"\nDetected {len(top_clips)} clips:")
for i, c in enumerate(top_clips):
    print(f"  Clip {i}: {c['start']:.1f}s - {c['end']:.1f}s  score={c['score']}")

# Process each clip
for i, clip_data in enumerate(top_clips):
    print(f"\n--- Processing clip {i} ---")

    # Generate SRT for this clip
    clip_chunks = [
        ch for ch in chunks
        if ch["start"] >= clip_data["start"] and ch["end"] <= clip_data["end"]
    ]
    adjusted = [
        {
            "start": ch["start"] - clip_data["start"],
            "end": ch["end"] - clip_data["start"],
            "text": ch["text"],
        }
        for ch in clip_chunks
    ]
    srt_path = str(Path(OUT_DIR) / f"clip_{i}.srt")
    Path(OUT_DIR).mkdir(parents=True, exist_ok=True)
    generate_srt(adjusted, srt_path)

    # Run FFmpeg
    try:
        result = process_clip(VIDEO, clip_data["start"], clip_data["end"], srt_path, OUT_DIR, i)
        size_mb = os.path.getsize(result) / 1024 / 1024
        print(f"  OK: {result} ({size_mb:.1f}MB)")
    except Exception as e:
        print(f"  FAILED: {e}")

# Summary
print("\n=== Final output files ===")
for f in sorted(Path(OUT_DIR).glob("clip_[0-9].mp4")):
    size_mb = os.path.getsize(f) / 1024 / 1024
    print(f"  {f.name}: {size_mb:.1f}MB")
