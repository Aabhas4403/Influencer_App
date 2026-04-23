# ClipFlow 🎬

**AI-powered Auto-Repurposing Engine** — drop in one long video (file or YouTube link) and get back 5 vertical, captioned, speaker-tracked, music-mixed reels along with platform-tailored copy for Instagram, LinkedIn, X/Twitter, and YouTube Shorts.

The whole pipeline runs locally: faster-whisper for transcription, Ollama (llama3.1) for clip selection + caption generation, FFmpeg for cutting/cropping/grading, OpenCV for face tracking, and Pillow for animated word-pop captions.

---

## Table of Contents

- [Features](#features)
- [System Architecture](#system-architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Pipeline Walkthrough](#pipeline-walkthrough)
- [Data Model](#data-model)
- [API Reference](#api-reference)
- [Frontend](#frontend)
- [Configuration](#configuration)
- [Local Setup](#local-setup)
- [Docker Setup](#docker-setup)
- [Operational Notes](#operational-notes)
- [Roadmap](#roadmap)

---

## Features

### Core
- **Video ingest**: file upload or YouTube URL (downloaded via `yt-dlp`).
- **Transcription**: `faster-whisper` (CTranslate2) primary, `openai-whisper` fallback. Handles English, Hindi, and Hinglish with word-level timestamps.
- **3-layer smart clip detection** (LLM + heuristic):
  1. LLM video summarization for context.
  2. LLM topic-based segmentation (not blind time-chunks).
  3. Hybrid scoring (rule-based hook keywords + LLM scoring) picks the top 5 viral moments.
- **Hook rewriting**: LLM rewrites the opening line of each clip into a scroll-stopper.
- **Multi-platform caption generation** via Ollama (`llama3.1:8b`):
  - Instagram Reel caption (hook + value + CTA + 5 hashtags)
  - LinkedIn post (story-format, no emojis)
  - Twitter/X thread (4-6 tweets)
  - YouTube Shorts title + description

### Editing (per clip)
- **Smooth speaker-tracking 9:16 crop** — OpenCV face cascade samples 2 Hz, EMA smoothing, FFmpeg pan-crop expression.
- **Audio-energy punch-in zooms** on emphasis peaks (1.0× → 1.10×).
- **Color grade** (contrast / brightness / saturation lift).
- **Word-pop captions** in four style presets:
  - `hormozi` — big yellow word-pop
  - `mrbeast` — white pop with outline
  - `minimal` — clean white with shadow
  - `bold` — full-line, current-word highlight
- **Hook intro card** for the first ~1.2 s (clip title).
- **CTA endcard** for the last ~1.2 s (configurable text).
- **Background music** mixed at -23 dB with fade in/out (or generated ambient pad if no music asset is available).
- **Loudness normalization** on the speech track (`loudnorm=I=-16:TP=-1.5:LRA=11`).
- **Silence trimming** (optional) — `ffmpeg silencedetect` finds gaps, `select`/`aselect` filters rebuild a tighter cut while preserving caption sync. Inspired by `auto-influencer`.
- **Fades** in/out on both video and audio.

### Platform
- JWT authentication (FastAPI + python-jose + bcrypt).
- Async SQLAlchemy 2.0 (works with PostgreSQL or SQLite).
- Background pipeline orchestrator with progress tracking + ETA.
- Project + clip versioning (`Clip.versions`) — each regeneration creates a new `ClipVersion` row.
- SHA-256 video cache — duplicate uploads/URLs reuse prior results.
- Static file mounts for `/clips` and `/uploads`.

---

## System Architecture

```
┌─────────────────────┐         ┌──────────────────────────────────────┐
│  Frontend (Next.js) │         │              Backend (FastAPI)        │
│                     │  HTTP   │                                       │
│  - Auth (JWT)       │ ──────▶ │  /api/auth   /api/projects   /api/clips
│  - Upload form      │ ◀────── │                  │                    │
│  - Dashboard        │   JSON  │                  ▼                    │
│  - Project view     │         │   ┌──────────────────────────────┐   │
│  - Polling progress │         │   │   Background Pipeline         │   │
└─────────────────────┘         │   │   (services/pipeline.py)      │   │
                                │   └────┬───────┬────────┬─────────┘   │
                                │        │       │        │             │
                                │        ▼       ▼        ▼             │
                                │   ┌────────┐ ┌──────┐ ┌──────────┐    │
                                │   │transcr.│ │clip  │ │video_proc│    │
                                │   │service │ │detect│ │ + editing│    │
                                │   └───┬────┘ └──┬───┘ └─────┬────┘    │
                                │       │         │           │         │
                                │       ▼         ▼           ▼         │
                                │  faster-whisper Ollama   FFmpeg +     │
                                │  (CTranslate2) (llama3)  OpenCV +     │
                                │                          Pillow       │
                                │                                       │
                                │   ┌──────────────────────────────┐    │
                                │   │  Async SQLAlchemy / Postgres │    │
                                │   └──────────────────────────────┘    │
                                └───────────────────────────────────────┘
```

### Request flow

1. User uploads a video (or pastes a YouTube URL) from the dashboard.
2. `POST /api/projects/upload` saves the file (or runs `yt-dlp`), creates a `Project` row in `pending`, schedules `run_pipeline(project_id)` as a FastAPI background task, and returns the project.
3. Frontend polls `GET /api/projects/{id}` every few seconds and renders the progress bar (`progress_pct`, `progress_stage`, `progress_detail`, `eta_seconds`).
4. The pipeline writes finished clip files to `backend/clips/<project_id>/clip_<i>.mp4`, persists `Clip` and `ClipVersion` rows, and flips `status` to `done`.
5. The project view page lists each clip with download links, an inline `<video>` player (served from `/clips/...`), and tabs for the four caption variants.

---

## Tech Stack

| Layer | Tech |
|---|---|
| Frontend | Next.js 14 (App Router), TypeScript, TailwindCSS |
| Backend  | FastAPI 0.115, Python 3.12, async SQLAlchemy 2.0 |
| Auth     | JWT (python-jose), bcrypt |
| DB       | PostgreSQL 16 (Docker) or SQLite (local default) |
| Transcription | faster-whisper (primary), openai-whisper (fallback) |
| LLM      | Ollama running `llama3.1:8b` |
| Video    | FFmpeg, OpenCV (face tracking), Pillow (caption rendering) |
| YouTube  | yt-dlp |
| Container | Docker / docker-compose |

---

## Project Structure

```
Influencer_App/
├── backend/
│   ├── app/
│   │   ├── main.py                     # FastAPI entry, CORS, static mounts
│   │   ├── config.py                   # All env-driven settings
│   │   ├── database.py                 # Async engine, session, Base
│   │   ├── models.py                   # User, Project, Clip, ClipVersion
│   │   ├── schemas.py                  # Pydantic request/response models
│   │   ├── auth.py                     # JWT + password hashing
│   │   ├── routes/
│   │   │   ├── auth.py                 # /api/auth/{register,login,me}
│   │   │   ├── projects.py             # upload, list, get, delete, reprocess
│   │   │   └── clips.py                # get, download, regenerate, customize
│   │   └── services/
│   │       ├── transcription_service.py  # faster-whisper / openai-whisper
│   │       ├── clip_detection.py         # 3-layer LLM + heuristic scoring
│   │       ├── editing.py                # primitives: face track, captions,
│   │       │                             # word-pop overlay, silence trim
│   │       ├── video_processor.py        # per-clip orchestrator (FFmpeg)
│   │       ├── content_generator.py      # IG/LinkedIn/Twitter/YT prompts
│   │       └── pipeline.py               # background task orchestrator
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── uploads/                        # raw videos (gitignored)
│   ├── clips/                          # rendered output (gitignored)
│   └── assets/music/                   # optional bg music drop-in
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx                # auth (login/register)
│   │   │   ├── dashboard/page.tsx      # projects + upload
│   │   │   └── project/[id]/page.tsx   # clip results + progress
│   │   ├── components/
│   │   │   ├── Navbar.tsx
│   │   │   ├── UploadForm.tsx
│   │   │   ├── ProjectCard.tsx
│   │   │   ├── ClipCard.tsx
│   │   │   ├── CaptionBlock.tsx
│   │   │   └── ProcessingStatus.tsx
│   │   └── lib/
│   │       ├── api.ts                  # fetch wrappers
│   │       └── auth.tsx                # auth context provider
│   ├── next.config.js                  # /api proxy to backend
│   ├── tailwind.config.js
│   └── Dockerfile
├── docker-compose.yml
├── README.md  ← (this file)
└── docs/                               # design references
    ├── AI_Prompts.md
    ├── Backend_API_Structure.md
    ├── Clip_Detection_Logic.md
    ├── Database_Schema.md
    ├── FFMPED_Commands.md
    ├── Frontend.md
    ├── Subtitle_Generation.md
    └── Syste_ Architecture.md
```

---

## Pipeline Walkthrough

`backend/app/services/pipeline.py::run_pipeline(project_id)` — runs the following steps on the asyncio event loop, blocking work pushed to `asyncio.to_thread`:

| # | Stage | % | What happens |
|---|---|---|---|
| 0 | Cache check | — | SHA-256 of the URL (or first 10 MB of the file). If a prior `done` project matches, clone its clips and exit. |
| 1 | Transcription | 2 → 50 | `transcription_service.transcribe()` runs faster-whisper with VAD filtering. Returns word-level chunks + detected language (english / hindi / hinglish). Cached as `<video>.chunks.json`. |
| 2 | Clip detection | 50 → 60 | `clip_detection.detect_clips()` summarizes via LLM, segments into 5-10 topic-based windows, scores them, optionally rewrites hooks, and returns the top 5. |
| 3 | Per-clip editing | 60 → 90 | For each clip: SRT generation, then `video_processor.process_clip()` runs the FFmpeg + overlay + music chain. |
| 4 | Caption gen | inline | `content_generator.generate_all_captions()` calls Ollama 4× per clip (IG, LinkedIn, X, YT). |
| 5 | Persist | 90 → 100 | One `Clip` + one `ClipVersion` row per output; project marked `done`. |

### Per-clip editing chain (`video_processor.process_clip`)

1. **Cut + crop**: precise seek (`-ss`), 9:16 vertical via either pad (already vertical) or smooth pan-crop (landscape, OpenCV face track + EMA).
2. **Color grade** + **punch-in zooms** (audio-energy peaks via the envelope of a downsampled WAV) + **fades**.
3. **Loudness normalization** (`loudnorm=I=-16:TP=-1.5:LRA=11`).
4. **Caption overlay**: pre-renders an RGBA `.mov` of word-pop chunks + hook intro + CTA endcard via Pillow, then a single `overlay=0:0` pass burns it onto the base clip.
5. **Background music**: mix at -23 dB if a track exists in `backend/assets/music/`, else generate ambient pad; fade in/out.
6. **Silence trim** (when `TRIM_SILENCES=true`): `silencedetect` → `select`/`aselect` rebuilds a tighter cut.

The rendered file lands at `backend/clips/<project_id>/clip_<i>.mp4`.

---

## Data Model

```
User
 ├── id (uuid)
 ├── email (unique)
 ├── hashed_password
 ├── plan          (free | pro | unlimited)
 ├── credits
 └── projects → [Project]

Project
 ├── id (uuid)
 ├── user_id → User
 ├── title
 ├── video_url           (nullable)
 ├── video_path          (filesystem path)
 ├── video_hash          (sha256, used for caching)
 ├── transcript          (full text)
 ├── duration            (seconds)
 ├── language            (english | hindi | hinglish)
 ├── status              (pending | transcribing | detecting | processing | done | failed)
 ├── progress_pct        (0..100)
 ├── progress_stage      (human-readable)
 ├── progress_detail     ("Clip 3 of 5 …")
 ├── eta_seconds
 └── clips → [Clip]

Clip
 ├── id (uuid)
 ├── project_id → Project
 ├── clip_index, start_time, end_time, score
 ├── title, transcript_text
 ├── video_path, srt_path
 ├── caption_{instagram,linkedin,twitter,youtube}
 ├── active_version
 └── versions → [ClipVersion]

ClipVersion
 ├── id, clip_id, version_num
 ├── video_path, srt_path
 ├── caption_*
 └── custom_prompt   (user-supplied tweak that produced this version)
```

---

## API Reference

All `/api/*` routes (except `/api/health`, `/api/auth/register`, `/api/auth/login`) require `Authorization: Bearer <jwt>`.

### Auth

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/auth/register` | `{email, password}` | `User` |
| POST | `/api/auth/login`    | `{email, password}` | `{access_token}` |
| GET  | `/api/auth/me`       | — | `User` |

### Projects

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/projects/upload` | multipart: `file` **or** `video_url` | `Project` (status=pending, pipeline scheduled) |
| GET  | `/api/projects` | — | `Project[]` (with eager-loaded clips) |
| GET  | `/api/projects/{id}` | — | `Project` |
| DELETE | `/api/projects/{id}` | — | 204 |
| POST | `/api/projects/{id}/reprocess` | — | re-runs the pipeline, keeps the project row |

### Clips

| Method | Path | Notes |
|---|---|---|
| GET  | `/api/clips/{project_id}` | list clips for a project (own clips only) |
| GET  | `/api/clips/{clip_id}/download?version=N` | streams `video/mp4` |
| POST | `/api/clips/{clip_id}/regenerate` | re-runs the LLM caption generators |
| POST | `/api/clips/{clip_id}/customize` | regenerate with a `custom_prompt`; spawns a new `ClipVersion` |

### Static

- `GET /clips/<project_id>/clip_<i>.mp4` — direct file mount (used by the `<video>` tag on the project page).
- `GET /uploads/<file>` — raw uploads.
- `GET /api/health` — `{"status":"ok"}`.

---

## Frontend

Next.js 14 with the App Router, TailwindCSS, and a small custom auth context.

| Route | File | Purpose |
|---|---|---|
| `/` | [page.tsx](frontend/src/app/page.tsx) | Login + register tabs |
| `/dashboard` | [dashboard/page.tsx](frontend/src/app/dashboard/page.tsx) | Upload form + list of past projects |
| `/project/[id]` | [project/[id]/page.tsx](frontend/src/app/project/[id]/page.tsx) | Live progress + finished clips + caption tabs |

Key components: `UploadForm`, `ProjectCard`, `ClipCard`, `CaptionBlock`, `ProcessingStatus`. `lib/api.ts` is a thin fetch wrapper; `lib/auth.tsx` exposes `useAuth()`.

`next.config.js` proxies `/api/*` to `http://backend:8000` (Docker) or `http://localhost:8000` (dev).

---

## Configuration

All settings live in `backend/app/config.py` and read from env (`.env` is supported via `python-dotenv`).

### Core

| Var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///backend/clipflow.db` | DB connection (use `postgresql+asyncpg://...` in Docker) |
| `SECRET_KEY` | `change-me-in-production` | JWT signing |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins |

### Ollama

| Var | Default |
|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` |
| `OLLAMA_MODEL`    | `llama3.1:8b` |

### Whisper

| Var | Default | Notes |
|---|---|---|
| `WHISPER_ENGINE`       | `auto` | `auto` / `faster-whisper` / `openai-whisper` |
| `WHISPER_MODEL_SIZE`   | `medium` | `tiny`/`base`/`small`/`medium`/`large-v3`/`distil-large-v3` |
| `WHISPER_DEVICE`       | `cpu` | `cpu` / `cuda` / `auto` |
| `WHISPER_COMPUTE_TYPE` | `int8` | `int8` on CPU, `float16` on CUDA |

> If your network blocks HuggingFace, faster-whisper can't fetch weights — set `WHISPER_ENGINE=openai-whisper`.

### Editing style

| Var | Default | Effect |
|---|---|---|
| `CAPTION_STYLE` | `hormozi` | `hormozi` / `mrbeast` / `minimal` / `bold` |
| `WORD_POP_CAPTIONS` | `true` | 1-3 word pop captions instead of full-line subs |
| `PUNCH_ZOOMS` | `true` | audio-emphasis-driven zoom-ins |
| `HOOK_INTRO` | `true` | clip-title intro card (~1.2 s) |
| `CTA_ENDCARD` | `true` | endcard (~1.2 s) |
| `CTA_TEXT` | `FOLLOW FOR MORE` | endcard text |
| `SMOOTH_SPEAKER_TRACK` | `true` | OpenCV face track + EMA pan-crop |
| `TRIM_SILENCES` | `false` | post-process: drop silent gaps |
| `SILENCE_THRESHOLD_DB` | `-30` | dB floor for "silent" |
| `SILENCE_MIN_DURATION` | `0.5` | seconds; minimum silence to cut |
| `SILENCE_PADDING` | `0.1` | seconds of padding kept around speech |

### FFmpeg

| Var | Default |
|---|---|
| `FFMPEG_PATH` | `ffmpeg` (must be on `PATH`) |

---

## Local Setup

### Prerequisites

- macOS or Linux (tested on macOS Apple Silicon)
- Python 3.12 (≥ 3.10 should work; **3.14 is currently incompatible** with the pinned pydantic)
- Node.js 18+
- FFmpeg — `brew install ffmpeg`
- [Ollama](https://ollama.com) — `ollama pull llama3.1:8b && ollama serve`
- (Optional) PostgreSQL 16 — otherwise SQLite is used

### 1. Clone + venv

```bash
git clone https://github.com/Aabhas4403/Influencer_App.git
cd Influencer_App

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

### 2. Backend

```bash
cd backend
# Optional: copy env template if you have one
# cp .env.example .env

uvicorn app.main:app --reload --port 8000
```

Hit http://localhost:8000/api/health → `{"status":"ok"}`.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000, register, paste a YouTube URL, and watch the progress bar.

---

## Docker Setup

```bash
# Make sure Ollama is reachable from containers
ollama serve

docker compose up --build
```

`docker-compose.yml` brings up:

- **db** — `postgres:16-alpine` on `5432`
- **backend** — built from `backend/Dockerfile`, exposes `8000`, mounts `uploads/` and `clips/`, talks to Ollama via `host.docker.internal:11434`
- **frontend** — built from `frontend/Dockerfile`, exposes `3000`

---

## Operational Notes

### Performance tips

- Whisper `medium` on CPU is the bottleneck for an 8-minute Hindi clip (~minutes). Drop to `small` for fast iteration: `WHISPER_MODEL_SIZE=small`.
- Disable speaker tracking on long inputs if CPU is tight: `SMOOTH_SPEAKER_TRACK=false`.
- Caption rendering pre-bakes an RGBA `.mov`, which is the second-biggest cost. Set `WORD_POP_CAPTIONS=false` to fall back to FFmpeg's `subtitles=` filter (faster, plain look).

### Caching

- `Project.video_hash` is set on every upload. If the same URL or file (first 10 MB SHA-256) was already processed and is `done`, the new project simply clones the prior clips — no recompute.
- Transcripts persist to `<video>.chunks.json` next to the upload, so reprocessing a project skips Step 1.

### Debugging

- Backend logs to stdout **and** `backend/logs/clipflow.log`.
- The progress bar fields (`progress_stage`, `progress_detail`, `eta_seconds`) come from `_update_progress()` calls inside `pipeline.py` — useful breadcrumbs when something stalls.
- Stale `ffmpeg` subprocesses can wedge the pipeline; `ps -A | grep ffmpeg` and `kill -9 <pid>` if needed.

### Security

- JWT secret defaults to `change-me-in-production` — override `SECRET_KEY` for any non-local deployment.
- CORS is locked to `http://localhost:3000` by default.
- Auth endpoints rate-limiting is **not** implemented; add a reverse proxy (nginx, Cloudflare) in production.

---

## Roadmap

- [ ] Direct posting to Instagram / YouTube Shorts via Graph / YouTube Data API
- [ ] Per-user style presets (saved fonts, brand colors, intro/outro stings)
- [ ] B-roll suggestion (LLM picks moments needing visual support)
- [ ] Hosted billing tier (Stripe + credit metering against `User.credits`)
- [ ] Performance feedback loop ("this style worked best for you")
- [ ] GPU-accelerated path (CUDA faster-whisper + NVENC FFmpeg encoder)

---

## Credits

- Inspired by the 7-day repurposing engine spec in `docs/`.
- Silence-trim primitive borrowed from [`allanspadini/auto-influencer`](https://github.com/allanspadini/auto-influencer) (rewritten as a single-pass FFmpeg filter chain).
- Whisper / faster-whisper / Ollama / FFmpeg / OpenCV — open source ecosystem this project would not exist without.

## License

MIT.
