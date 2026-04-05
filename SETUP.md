# ClipFlow 🎬

**Auto Content Repurposing Engine** — Turn 1 long video into viral clips + captions in minutes.

Upload a video (or paste a YouTube link) → Get transcription → Detect top viral moments → Generate vertical clips with subtitles → Get platform-specific captions (Instagram, LinkedIn, Twitter, YouTube).

---

## Architecture

```
Frontend (Next.js)  →  Backend (FastAPI)
                            ├── Transcription (whisper.cpp)
                            ├── Clip Detection (Python scoring)
                            ├── Video Processing (FFmpeg)
                            └── Content Generation (Ollama / llama3)
                            ↓
                        PostgreSQL
```

## Project Structure

```
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry point
│   │   ├── config.py            # Environment config
│   │   ├── database.py          # Async SQLAlchemy setup
│   │   ├── models.py            # User, Project, Clip tables
│   │   ├── schemas.py           # Pydantic request/response
│   │   ├── auth.py              # JWT + password hashing
│   │   ├── routes/
│   │   │   ├── auth.py          # Register, login, me
│   │   │   ├── projects.py      # Upload, list, get, delete
│   │   │   └── clips.py         # Get clips, download, regenerate
│   │   └── services/
│   │       ├── transcription_service.py  # whisper.cpp wrapper
│   │       ├── clip_detection.py         # Viral moment scoring
│   │       ├── video_processor.py        # FFmpeg pipeline
│   │       ├── content_generator.py      # Ollama prompts
│   │       └── pipeline.py               # Background orchestrator
│   ├── requirements.txt
│   ├── .env.example
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx       # Root layout
│   │   │   ├── page.tsx         # Auth page (login/register)
│   │   │   ├── dashboard/page.tsx    # Projects list + upload
│   │   │   └── project/[id]/page.tsx # Clip results view
│   │   ├── components/
│   │   │   ├── Navbar.tsx
│   │   │   ├── UploadForm.tsx
│   │   │   ├── ProjectCard.tsx
│   │   │   ├── ClipCard.tsx
│   │   │   ├── CaptionBlock.tsx
│   │   │   └── ProcessingStatus.tsx
│   │   └── lib/
│   │       ├── api.ts           # API client
│   │       └── auth.tsx         # Auth context
│   ├── package.json
│   ├── next.config.js           # API proxy to backend
│   ├── tailwind.config.js
│   └── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## Prerequisites

- **PostgreSQL** (or use Docker)
- **FFmpeg** — `brew install ffmpeg` (macOS) / `apt install ffmpeg` (Linux)
- **Ollama** — https://ollama.com → `ollama pull llama3`
- **whisper.cpp** — https://github.com/ggerganov/whisper.cpp (for local transcription)
- **yt-dlp** (for YouTube downloads) — `pip install yt-dlp`
- **Node.js** 18+ and **Python** 3.11+

---

## Setup — Local Development

### 1. Start PostgreSQL

Using Docker (easiest):
```bash
docker run -d --name clipflow-db \
  -e POSTGRES_USER=clipflow \
  -e POSTGRES_PASSWORD=clipflow \
  -e POSTGRES_DB=clipflow \
  -p 5432:5432 \
  postgres:16-alpine
```

### 2. Start Ollama

```bash
# Install: https://ollama.com
ollama pull llama3
ollama serve  # runs on port 11434
```

### 3. Setup whisper.cpp

```bash
git clone https://github.com/ggerganov/whisper.cpp.git
cd whisper.cpp
make
bash ./models/download-ggml-model.sh base.en
cd ..
```

### 4. Backend

```bash
cd backend

# Create virtualenv
python -m venv venv
source venv/bin/activate

# Install deps
pip install -r requirements.txt

# Copy env config
cp .env.example .env
# Edit .env — set WHISPER_CPP_PATH and WHISPER_MODEL_PATH to your whisper.cpp paths

# Run server
uvicorn app.main:app --reload --port 8000
```

### 5. Frontend

```bash
cd frontend

npm install
npm run dev
# → http://localhost:3000
```

---

## Setup — Docker (All-in-One)

```bash
# Make sure Ollama is running on your host machine first
ollama serve

# Then:
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- Health check: http://localhost:8000/api/health

---

## Environment Variables

| Variable            | Default                                       | Description                    |
|---------------------|-----------------------------------------------|--------------------------------|
| `DATABASE_URL`      | `postgresql+asyncpg://clipflow:clipflow@localhost:5432/clipflow` | PostgreSQL connection |
| `SECRET_KEY`        | `change-me-in-production`                     | JWT signing secret             |
| `OLLAMA_BASE_URL`   | `http://localhost:11434`                      | Ollama API endpoint            |
| `OLLAMA_MODEL`      | `llama3`                                      | LLM model for captions         |
| `WHISPER_CPP_PATH`  | `./whisper.cpp/main`                          | Path to whisper.cpp binary     |
| `WHISPER_MODEL_PATH`| `./whisper.cpp/models/ggml-base.en.bin`       | Path to whisper model          |
| `FFMPEG_PATH`       | `ffmpeg`                                      | FFmpeg binary                  |
| `CORS_ORIGINS`      | `http://localhost:3000`                       | Comma-separated allowed origins|

---

## API Endpoints

| Method | Endpoint                     | Description                    |
|--------|------------------------------|--------------------------------|
| POST   | `/api/auth/register`         | Create account                 |
| POST   | `/api/auth/login`            | Get JWT token                  |
| GET    | `/api/auth/me`               | Current user info              |
| POST   | `/api/projects/upload`       | Upload video + start pipeline  |
| GET    | `/api/projects/`             | List user's projects           |
| GET    | `/api/projects/{id}`         | Get project with clips         |
| DELETE | `/api/projects/{id}`         | Delete project                 |
| GET    | `/api/clips/{project_id}`    | Get clips for a project        |
| GET    | `/api/clips/{clip_id}/download` | Download clip video         |
| POST   | `/api/clips/{clip_id}/regenerate` | Re-generate captions      |

---

## How It Works

1. **Upload** — File upload or YouTube URL (downloaded via yt-dlp)
2. **Transcribe** — Video → WAV → whisper.cpp → timestamped transcript
3. **Detect** — Transcript chunks scored on hook keywords, emotional indicators, length → top 5 clips picked
4. **Process** — FFmpeg cuts clips, converts to 9:16 vertical, burns in SRT subtitles
5. **Generate** — Ollama (llama3) creates platform-specific captions with tailored prompts
6. **Display** — Dashboard shows clips with scores, previews, and copy-able captions

---

## V2 Improvements (Roadmap)

- **Auto-posting** — Direct publish to Instagram, LinkedIn, Twitter via APIs
- **Face detection** — Auto center-crop on speaker's face
- **ML clip scoring** — Train on engagement data instead of keyword heuristics
- **Hook generator** — "Stop scrolling..." style opening lines
- **A/B testing** — Generate multiple caption variants, track performance
- **Brand presets** — Consistent tone/style across all content
- **Batch processing** — Queue multiple videos
- **Webhook notifications** — Notify when processing completes
- **S3 storage** — Move from local to cloud for production

## Known Bottlenecks

- **Transcription** — whisper.cpp on CPU can be slow for long videos (consider GPU or Whisper API)
- **Video processing** — FFmpeg re-encoding for vertical + subtitles is CPU-intensive
- **LLM generation** — Sequential Ollama calls for 4 platforms × 5 clips = 20 calls per video
- **No queue** — Background tasks via FastAPI are in-process; use Celery/Redis for production scale
