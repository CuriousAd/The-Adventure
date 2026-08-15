import uuid
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Cookie, Response, BackgroundTasks
from sqlalchemy.orm import Session

from core.config import settings
from core.job_runner import create_option_expansion_job, run_story_job
from core.workflow_orchestrator import start_story_workflow
from db.database import get_db
from models.story import Story, StoryNode
from models.job import StoryJob
from schemas.story import (
    CompleteStoryResponse,
    CompleteStoryNodeResponse,
    CreateStoryRequest,
    ExpandOptionRequest,
    ExpandOptionResponse,
)
from schemas.job import StoryJobResponse

router = APIRouter(
    prefix="/stories",
    tags=["stories"]
)

def get_session_id(session_id: Optional[str] = Cookie(None)):
    if not session_id:
        session_id = str(uuid.uuid4())
    return session_id


def require_session_id(session_id: Optional[str] = Cookie(None)) -> str:
    if not session_id:
        raise HTTPException(status_code=401, detail="Session not found")
    return session_id


@router.post("/create", response_model=StoryJobResponse)
def create_story(
        request: CreateStoryRequest,
        background_tasks: BackgroundTasks,
        response: Response,
        session_id: str = Depends(get_session_id), #depends help to grab data
        db: Session = Depends(get_db)
):
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        samesite="lax"
    ) #verifying users based on their instance on browser

    job_id = str(uuid.uuid4())

    job = StoryJob(
        job_id=job_id,
        session_id=session_id,
        theme=request.theme,
        status="pending"
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    requested_depth = request.depth or settings.DEFAULT_STORY_DEPTH

    if settings.job_execution_mode == "workflow":
        try:
            start_story_workflow(
                job_id=job_id,
                theme=request.theme,
                session_id=session_id,
                depth=requested_depth
            )
        except Exception as e:
            job.status = "failed"
            job.completed_at = datetime.now(timezone.utc)
            job.error = f"Failed to start story workflow: {e}"
            db.commit()
            raise HTTPException(status_code=500, detail="Failed to start story generation workflow")
    else:
        background_tasks.add_task(
            generate_story_task,
            job_id=job_id,
            theme=request.theme,
            session_id=session_id,
            depth=requested_depth
        )

    return job

# add background tasks, generate story (the idea of asynchronous operations)

def generate_story_task(job_id: str, theme: str, session_id: str, depth: int | None = None):
    run_story_job(job_id=job_id, theme=theme, session_id=session_id, depth=depth)


@router.post(
    "/{story_id}/nodes/{node_id}/options/{option_index}/expand",
    response_model=ExpandOptionResponse
)
def expand_story_option(
    story_id: int,
    node_id: int,
    option_index: int,
    request: ExpandOptionRequest,
    background_tasks: BackgroundTasks,
    session_id: str = Depends(require_session_id),
    db: Session = Depends(get_db),
):
    story = db.query(Story).filter(
        Story.id == story_id,
        Story.session_id == session_id
    ).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    parent_node = db.query(StoryNode).filter(
        StoryNode.id == node_id,
        StoryNode.story_id == story.id
    ).first()
    if not parent_node:
        raise HTTPException(status_code=404, detail="Story node not found")
    if parent_node.is_ending:
        raise HTTPException(status_code=400, detail="Ending nodes cannot be expanded")

    try:
        expansion = create_option_expansion_job(
            db=db,
            story=story,
            parent_node=parent_node,
            option_index=option_index,
            session_id=session_id,
            target_depth=settings.DEFAULT_STORY_DEPTH,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if expansion.job and expansion.created:
        if settings.job_execution_mode == "workflow":
            try:
                start_story_workflow(
                    job_id=expansion.job.job_id,
                    theme=expansion.job.theme,
                    session_id=session_id,
                    depth=settings.DEFAULT_STORY_DEPTH
                )
            except Exception as e:
                expansion.job.status = "failed"
                expansion.job.completed_at = datetime.now(timezone.utc)
                expansion.job.error = f"Failed to start story workflow: {e}"
                db.commit()
                raise HTTPException(status_code=500, detail="Failed to start option expansion workflow")
        else:
            background_tasks.add_task(
                generate_story_task,
                job_id=expansion.job.job_id,
                theme=expansion.job.theme,
                session_id=session_id,
                depth=settings.DEFAULT_STORY_DEPTH
            )

    return ExpandOptionResponse(
        status=expansion.status,
        job_id=expansion.job.job_id if expansion.job else None,
        story_id=story.id,
        node_id=expansion.node_id
    )


@router.get("/{story_id}/complete", response_model=CompleteStoryResponse)
def get_complete_story(
    story_id: int,
    session_id: str = Depends(require_session_id),
    db: Session = Depends(get_db)
):
    story = db.query(Story).filter(
        Story.id == story_id,
        Story.session_id == session_id
    ).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    complete_story = build_complete_story_tree(db, story)
    return complete_story


def build_complete_story_tree(db: Session, story: Story) -> CompleteStoryResponse:
    nodes = db.query(StoryNode).filter(StoryNode.story_id == story.id).all()

    node_dict = {}
    for node in nodes:
        node_response = CompleteStoryNodeResponse(
            id=node.id,
            content=node.content,
            is_ending=node.is_ending,
            is_winning_ending=node.is_winning_ending,
            options=node.options
        )
        node_dict[node.id] = node_response

    root_node = next((node for node in nodes if node.is_root), None)
    if not root_node:
        raise HTTPException(status_code=500, detail="Story root node not found")

    return CompleteStoryResponse(
        id=story.id,
        title= story.title,
        session_id=story.session_id,
        created_at=story.created_at,
        root_node=node_dict[root_node.id],
        all_nodes=node_dict
    )

#endpoints that will be hit by the client (frontend)
