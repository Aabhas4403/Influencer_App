"""Pydantic schemas for request/response validation."""

from __future__ import annotations
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, EmailStr


# ---------- Auth ----------
class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    plan: str
    credits: int
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- ClipVersion ----------
class ClipVersionOut(BaseModel):
    id: str
    version_num: int
    video_path: Optional[str]
    caption_instagram: Optional[str]
    caption_linkedin: Optional[str]
    caption_twitter: Optional[str]
    caption_youtube: Optional[str]
    custom_prompt: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Clip ----------
class ClipOut(BaseModel):
    id: str
    clip_index: int = 0
    start_time: float
    end_time: float
    score: float
    title: Optional[str]
    transcript_text: Optional[str]
    video_path: Optional[str]
    caption_instagram: Optional[str]
    caption_linkedin: Optional[str]
    caption_twitter: Optional[str]
    caption_youtube: Optional[str]
    active_version: int = 1
    versions: List[ClipVersionOut] = []
    created_at: datetime

    class Config:
        from_attributes = True


class ClipCustomizeRequest(BaseModel):
    custom_prompt: str  # user's special instructions for this clip


# ---------- Project ----------
class ProjectCreate(BaseModel):
    video_url: Optional[str] = None


class ProjectOut(BaseModel):
    id: str
    title: str
    video_url: Optional[str]
    duration: Optional[float]
    status: str
    progress_pct: int = 0
    progress_stage: Optional[str] = ""
    progress_detail: Optional[str] = ""
    eta_seconds: Optional[int] = None
    language: Optional[str] = None
    # Filename only (e.g. "abc.mp4") so the frontend can play /uploads/<source_filename>
    source_filename: Optional[str] = None
    manual_selections: Optional[str] = None
    created_at: datetime
    clips: List[ClipOut] = []

    class Config:
        from_attributes = True


class SelectionRange(BaseModel):
    start: float
    end: float


class SelectionsRequest(BaseModel):
    ranges: List[SelectionRange]


# Fix forward references
ProjectOut.model_rebuild()
