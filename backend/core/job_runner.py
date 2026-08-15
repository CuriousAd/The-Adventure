import json
from datetime import datetime, timezone

import boto3
from sqlalchemy.orm import Session

from core.config import settings
from core.story_generator import StoryGenerator
from db.database import SessionLocal
from models.job import StoryJob


def enqueue_story_job(job_id: str, theme: str, session_id: str) -> None:
    if not settings.STORY_JOB_QUEUE_URL:
        raise ValueError("STORY_JOB_QUEUE_URL is required when JOB_EXECUTION_MODE is queue.")

    sqs = boto3.client("sqs", region_name=settings.AWS_REGION or None)
    sqs.send_message(
        QueueUrl=settings.STORY_JOB_QUEUE_URL,
        MessageBody=json.dumps({
            "job_id": job_id,
            "theme": theme,
            "session_id": session_id,
        }),
    )


def run_story_job(job_id: str, theme: str, session_id: str) -> None:
    db = SessionLocal()
    try:
        _run_story_job_with_db(db, job_id=job_id, theme=theme, session_id=session_id)
    finally:
        db.close()


def _run_story_job_with_db(db: Session, job_id: str, theme: str, session_id: str) -> None:
    job = db.query(StoryJob).filter(
        StoryJob.job_id == job_id,
        StoryJob.session_id == session_id
    ).first()

    if not job:
        return

    if job.status == "completed" and job.story_id:
        return

    job.status = "processing"
    job.error = None
    db.commit()

    last_error = None
    for _attempt in range(1, settings.STORY_GENERATION_RETRIES + 2):
        try:
            story = StoryGenerator.generate_story(db, session_id, theme)
            job.story_id = story.id
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            job.error = None
            db.commit()
            return
        except Exception as e:
            db.rollback()
            last_error = str(e)

    job = db.query(StoryJob).filter(
        StoryJob.job_id == job_id,
        StoryJob.session_id == session_id
    ).first()
    if job:
        job.status = "failed"
        job.completed_at = datetime.now(timezone.utc)
        job.error = f"Generation failed after {settings.STORY_GENERATION_RETRIES + 1} attempt(s): {last_error}"
        db.commit()
