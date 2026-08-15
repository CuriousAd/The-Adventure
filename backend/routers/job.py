from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Cookie
from sqlalchemy.orm import Session

from core.config import settings
from db.database import get_db
from models.generation import StoryGenerationRun
from models.job import StoryJob
from schemas.job import StoryJobResponse

router = APIRouter(
    prefix="/jobs",
    tags=["jobs"]
)


def _get_session_id(session_id: str | None = Cookie(None)) -> str:
    if not session_id:
        raise HTTPException(status_code=401, detail="Session not found")
    return session_id


def _mark_stale_job_if_needed(db: Session, job: StoryJob) -> StoryJob:
    if job.status != "processing":
        return job

    run = db.query(StoryGenerationRun).filter(StoryGenerationRun.job_id == job.job_id).first()
    heartbeat_at = run.updated_at if run is not None else job.created_at
    if heartbeat_at is None:
        return job

    if heartbeat_at.tzinfo is None:
        heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)

    age_seconds = (datetime.now(timezone.utc) - heartbeat_at).total_seconds()
    if age_seconds <= settings.STALE_JOB_TIMEOUT_SECONDS:
        return job

    job.status = "failed"
    job.completed_at = datetime.now(timezone.utc)
    job.error = "Story generation timed out or was interrupted before completion."
    db.commit()
    db.refresh(job)
    return job


@router.get("/{job_id}", response_model=StoryJobResponse)
def get_job_status(
    job_id: str,
    session_id: str = Depends(_get_session_id),
    db: Session = Depends(get_db)
):
    job = db.query(StoryJob).filter(
        StoryJob.job_id == job_id,
        StoryJob.session_id == session_id
    ).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return _mark_stale_job_if_needed(db, job)
