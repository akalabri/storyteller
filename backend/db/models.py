"""
SQLAlchemy models for the storyteller database.

Tables
------
sessions, conversations, stories, scenes, characters, props,
subscenes, pipeline_steps, edit_history, errors, page_views
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def _utcnow():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------

class Session(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True)
    status = Column(String, default="idle")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow)

    # relationships
    conversation = relationship("Conversation", back_populates="session", uselist=False)
    story = relationship("Story", back_populates="session", uselist=False)
    scenes = relationship("Scene", back_populates="session", order_by="Scene.scene_index")
    characters = relationship("Character", back_populates="session")
    props = relationship("Prop", back_populates="session")
    pipeline_steps = relationship("PipelineStep", back_populates="session", order_by="PipelineStep.id")
    edits = relationship("EditHistory", back_populates="session", order_by="EditHistory.id")
    errors = relationship("Error", back_populates="session", order_by="Error.id")
    page_views = relationship("PageView", back_populates="session", order_by="PageView.id")


# ---------------------------------------------------------------------------
# conversations
# ---------------------------------------------------------------------------

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), unique=True, nullable=False)
    transcript = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("Session", back_populates="conversation")


# ---------------------------------------------------------------------------
# stories
# ---------------------------------------------------------------------------

class Story(Base):
    __tablename__ = "stories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), unique=True, nullable=False)
    special_instructions = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("Session", back_populates="story")


# ---------------------------------------------------------------------------
# scenes
# ---------------------------------------------------------------------------

class Scene(Base):
    __tablename__ = "scenes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    scene_index = Column(Integer, nullable=False)       # 1-based
    text = Column(Text, nullable=False)
    summary = Column(String, default="")
    narration_minio_key = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("Session", back_populates="scenes")
    subscenes = relationship("SubScene", back_populates="scene", order_by="SubScene.sub_index")


# ---------------------------------------------------------------------------
# characters
# ---------------------------------------------------------------------------

class Character(Base):
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    image_minio_key = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("Session", back_populates="characters")


# ---------------------------------------------------------------------------
# props
# ---------------------------------------------------------------------------

class Prop(Base):
    __tablename__ = "props"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("Session", back_populates="props")


# ---------------------------------------------------------------------------
# subscenes
# ---------------------------------------------------------------------------

class SubScene(Base):
    __tablename__ = "subscenes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scene_id = Column(Integer, ForeignKey("scenes.id"), nullable=False)
    sub_index = Column(Integer, nullable=False)          # 1-based
    image_prompt = Column(Text, default="")
    video_prompt = Column(Text, default="")
    image_minio_key = Column(String, nullable=True)
    video_minio_key = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    scene = relationship("Scene", back_populates="subscenes")


# ---------------------------------------------------------------------------
# pipeline_steps
# ---------------------------------------------------------------------------

class PipelineStep(Base):
    __tablename__ = "pipeline_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    step = Column(String, nullable=False)
    status = Column(String, nullable=False)
    message = Column(Text, default="")
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    session = relationship("Session", back_populates="pipeline_steps")


# ---------------------------------------------------------------------------
# edit_history
# ---------------------------------------------------------------------------

class EditHistory(Base):
    __tablename__ = "edit_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    user_message = Column(Text, default="")
    reasoning = Column(Text, default="")
    dirty_keys = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("Session", back_populates="edits")


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------

class Error(Base):
    __tablename__ = "errors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    step = Column(String, nullable=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("Session", back_populates="errors")


# ---------------------------------------------------------------------------
# page_views (user stage tracking)
# ---------------------------------------------------------------------------

class PageView(Base):
    __tablename__ = "page_views"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=True)  # null for landing
    page = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("Session", back_populates="page_views")

