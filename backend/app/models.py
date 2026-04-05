"""SQLAlchemy ORM models — Users, Projects, Clips, ClipVersions, PipelineProgress."""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, Float, Integer, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from app.database import Base


def _gen_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    plan = Column(String(20), default="free")  # free / pro / unlimited
    credits = Column(Integer, default=3)
    created_at = Column(DateTime, default=datetime.utcnow)

    projects = relationship("Project", back_populates="user", cascade="all, delete")


class Project(Base):
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    title = Column(String(255), default="Untitled")
    video_url = Column(Text, nullable=True)
    video_path = Column(Text, nullable=True)
    transcript = Column(Text, nullable=True)
    duration = Column(Float, nullable=True)
    status = Column(String(20), default="pending")
    # Progress tracking
    progress_pct = Column(Integer, default=0)          # 0-100
    progress_stage = Column(String(100), default="")   # human-readable stage
    progress_detail = Column(String(255), default="")  # e.g. "Clip 3 of 5"
    eta_seconds = Column(Integer, nullable=True)        # estimated seconds remaining
    # Caching
    video_hash = Column(String(64), nullable=True, index=True)  # SHA256 of video URL or file
    language = Column(String(20), nullable=True)        # detected language
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="projects")
    clips = relationship("Clip", back_populates="project", cascade="all, delete")


class Clip(Base):
    __tablename__ = "clips"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    clip_index = Column(Integer, default=0)            # 0-based clip number
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    score = Column(Float, default=0)
    title = Column(String(255), nullable=True)
    transcript_text = Column(Text, nullable=True)
    video_path = Column(Text, nullable=True)
    srt_path = Column(Text, nullable=True)
    caption_instagram = Column(Text, nullable=True)
    caption_linkedin = Column(Text, nullable=True)
    caption_twitter = Column(Text, nullable=True)
    caption_youtube = Column(Text, nullable=True)
    # Versioning
    active_version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="clips")
    versions = relationship("ClipVersion", back_populates="clip", cascade="all, delete",
                            order_by="ClipVersion.version_num")


class ClipVersion(Base):
    """Each re-generation of a clip creates a new version."""
    __tablename__ = "clip_versions"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    clip_id = Column(String(36), ForeignKey("clips.id"), nullable=False)
    version_num = Column(Integer, default=1)
    video_path = Column(Text, nullable=True)
    srt_path = Column(Text, nullable=True)
    caption_instagram = Column(Text, nullable=True)
    caption_linkedin = Column(Text, nullable=True)
    caption_twitter = Column(Text, nullable=True)
    caption_youtube = Column(Text, nullable=True)
    custom_prompt = Column(Text, nullable=True)  # user's custom requirements
    created_at = Column(DateTime, default=datetime.utcnow)

    clip = relationship("Clip", back_populates="versions")
