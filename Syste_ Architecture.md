🧱 1. SYSTEM ARCHITECTURE (simple but scalable)
Frontend (Next.js)
    ↓
Backend API (FastAPI / Node)
    ↓
Services:
  - Transcription (Whisper)
  - Clip Detection (Python logic)
  - Video Processing (FFmpeg)
  - Content Generation (OpenAI)
    ↓
Storage:
  - S3 (videos)
  - DB (Supabase/Postgres)