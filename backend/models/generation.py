from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from db.database import Base


class StoryGenerationRun(Base):
    __tablename__ = "story_generation_runs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, ForeignKey("story_jobs.job_id"), unique=True, index=True, nullable=False)
    story_id = Column(Integer, ForeignKey("stories.id"), index=True, nullable=False)
    session_id = Column(String, index=True, nullable=False)
    theme = Column(String, nullable=False)
    requested_depth = Column(Integer, nullable=False)
    branching_factor = Column(Integer, nullable=False)
    status = Column(String, index=True, nullable=False, default="pending")
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    story = relationship("Story")
    tasks = relationship("StoryGenerationTask", back_populates="run")


class StoryGenerationTask(Base):
    __tablename__ = "story_generation_tasks"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("story_generation_runs.id"), index=True, nullable=False)
    parent_task_id = Column(Integer, ForeignKey("story_generation_tasks.id"), index=True, nullable=True)
    parent_node_id = Column(Integer, ForeignKey("story_nodes.id"), index=True, nullable=True)
    generated_node_id = Column(Integer, ForeignKey("story_nodes.id"), index=True, nullable=True)
    incoming_option_text = Column(String, nullable=True)
    option_position = Column(Integer, nullable=True)
    depth = Column(Integer, nullable=False)
    status = Column(String, index=True, nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    repair_attempts = Column(Integer, nullable=False, default=0)
    raw_response = Column(Text, nullable=True)
    repaired_response = Column(Text, nullable=True)
    parsed_response = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    run = relationship("StoryGenerationRun", back_populates="tasks")
    parent_task = relationship("StoryGenerationTask", remote_side=[id], uselist=False)
