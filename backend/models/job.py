from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func

from db.database import Base


class StoryJob(Base):
    __tablename__ = "story_jobs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, index=True, unique=True)
    session_id = Column(String, index=True)
    theme = Column(String)
    status = Column(String)
    story_id = Column(Integer, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    #job represents the intent to make the story, generating a story takes time. (It records progress), once status finish job is completed i.e., story is complete

#frontend-> job (submits)
#backend-> job  (returns)

#frontend asks if job is done? 
#backend checks job status
#if status = true, i.e., job is complete
#backend-> send the story to frontend to display
