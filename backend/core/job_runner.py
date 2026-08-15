from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from core.config import settings
from core.gemini_key_pool import GeminiQuotaExhaustedError
from core.story_generator import StoryGenerator, StructuredGenerationError
from db.database import SessionLocal
from models.generation import StoryGenerationRun, StoryGenerationTask
from models.job import StoryJob
from models.story import Story, StoryNode


OPTION_PENDING = "pending"
OPTION_PROCESSING = "processing"
OPTION_COMPLETED = "completed"
OPTION_FAILED = "failed"


@dataclass
class WorkflowStepResult:
    job_id: str
    status: str
    has_more_work: bool
    story_id: int | None = None
    pending_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    last_error: str | None = None
    retry_after_seconds: float | None = None


@dataclass
class ExpansionJobResult:
    status: str
    job: StoryJob | None = None
    node_id: int | None = None
    created: bool = False


def run_story_job(job_id: str, theme: str, session_id: str, depth: int | None = None) -> None:
    while True:
        result = process_story_job_step(job_id=job_id, theme=theme, session_id=session_id, depth=depth)
        if result.status in {"completed", "failed"}:
            return
        if not result.has_more_work:
            return
        if result.retry_after_seconds:
            time.sleep(min(result.retry_after_seconds, 30.0))


def process_story_job_step(job_id: str, theme: str, session_id: str, depth: int | None = None) -> WorkflowStepResult:
    db = SessionLocal()
    try:
        return _process_story_job_step_with_db(
            db=db,
            job_id=job_id,
            theme=theme,
            session_id=session_id,
            depth=depth
        )
    finally:
        db.close()


def _process_story_job_step_with_db(
    db: Session,
    job_id: str,
    theme: str,
    session_id: str,
    depth: int | None = None
) -> WorkflowStepResult:
    job = db.query(StoryJob).filter(
        StoryJob.job_id == job_id,
        StoryJob.session_id == session_id
    ).first()

    if not job:
        return WorkflowStepResult(job_id=job_id, status="failed", has_more_work=False, last_error="Job not found.")

    target_depth = depth or settings.DEFAULT_STORY_DEPTH
    branching_factor = settings.DEFAULT_BRANCHING_FACTOR

    run = db.query(StoryGenerationRun).filter(StoryGenerationRun.job_id == job_id).first()
    if run is None:
        run = _initialize_generation_run(
            db=db,
            job=job,
            theme=theme,
            session_id=session_id,
            target_depth=target_depth,
            branching_factor=branching_factor
        )

    if run.status == "completed":
        return _sync_completed_result(db, job, run)

    if run.status == "failed":
        return _sync_failed_result(db, job, run.last_error or "Story generation failed.")

    next_task = _get_next_generation_task(db, run.id)
    if next_task is None:
        return _finalize_generation_run(db, job, run)

    return _process_generation_task(db, job, run, next_task)


def _initialize_generation_run(
    db: Session,
    job: StoryJob,
    theme: str,
    session_id: str,
    target_depth: int,
    branching_factor: int
) -> StoryGenerationRun:
    story = Story(title="Generating Adventure", session_id=session_id)
    db.add(story)
    db.flush()

    run = StoryGenerationRun(
        job_id=job.job_id,
        story_id=story.id,
        session_id=session_id,
        theme=theme,
        requested_depth=target_depth,
        branching_factor=branching_factor,
        status="processing"
    )
    db.add(run)
    db.flush()

    root_task = StoryGenerationTask(
        run_id=run.id,
        depth=1,
        status="pending"
    )
    db.add(root_task)
    job.status = "processing"
    job.error = None
    db.commit()
    db.refresh(run)
    return run


def _get_next_generation_task(db: Session, run_id: int) -> StoryGenerationTask | None:
    return db.query(StoryGenerationTask).filter(
        StoryGenerationTask.run_id == run_id,
        StoryGenerationTask.status.in_(["pending", "failed"]),
        StoryGenerationTask.attempts < settings.STORY_TASK_MAX_ATTEMPTS
    ).order_by(StoryGenerationTask.depth.asc(), StoryGenerationTask.id.asc()).first()


def _process_generation_task(
    db: Session,
    job: StoryJob,
    run: StoryGenerationRun,
    task: StoryGenerationTask
) -> WorkflowStepResult:
    job.status = "processing"
    job.error = None
    task.status = "processing"
    task.attempts += 1
    task.error = None
    run.updated_at = datetime.now(timezone.utc)
    db.commit()

    try:
        if task.parent_task_id is None:
            result = StoryGenerator.generate_root(
                theme=run.theme,
                target_depth=run.requested_depth,
                branching_factor=run.branching_factor
            )
            created_node = _persist_root_node(db, run, task, result)
            _schedule_child_tasks(db, run, task, created_node, result.parsed.rootNode.options)
        else:
            path_context = _build_path_context(db, task)
            result = StoryGenerator.generate_branch(
                theme=run.theme,
                path_context=path_context,
                option_text=task.incoming_option_text or "",
                depth=task.depth,
                target_depth=run.requested_depth,
                branching_factor=run.branching_factor
            )
            created_node = _persist_branch_node(db, task, result)
            _schedule_child_tasks(db, run, task, created_node, result.parsed.options)

        run.last_error = None
        run.updated_at = datetime.now(timezone.utc)
        db.commit()
        remaining_task = _get_next_generation_task(db, run.id)
        if remaining_task is None:
            return _finalize_generation_run(db, job, run)
        return _build_progress_result(db, run, "processing", True)
    except StructuredGenerationError as e:
        task.status = "failed"
        task.error = str(e)
        task.raw_response = e.raw_response
        task.repaired_response = e.repaired_response
        run.last_error = str(e)
        run.updated_at = datetime.now(timezone.utc)
        db.commit()
        return _build_progress_result(db, run, "processing", True, str(e))
    except GeminiQuotaExhaustedError as e:
        task.status = "pending"
        task.attempts = max(task.attempts - 1, 0)
        task.error = str(e)
        run.last_error = str(e)
        run.updated_at = datetime.now(timezone.utc)
        db.commit()
        return _build_progress_result(
            db,
            run,
            "processing",
            True,
            str(e),
            retry_after_seconds=e.retry_after_seconds
        )
    except Exception as e:
        task.status = "failed"
        task.error = str(e)
        run.last_error = str(e)
        run.updated_at = datetime.now(timezone.utc)
        db.commit()
        return _build_progress_result(db, run, "processing", True, str(e))


def create_option_expansion_job(
    db: Session,
    story: Story,
    parent_node: StoryNode,
    option_index: int,
    session_id: str,
    target_depth: int | None = None,
) -> ExpansionJobResult:
    parent_options = list(parent_node.options or [])
    if option_index < 0 or option_index >= len(parent_options):
        raise ValueError("Option index is out of range.")

    option = dict(parent_options[option_index] or {})
    option_text = option.get("text")
    if not option_text:
        raise ValueError("Selected option is missing text.")

    if option.get("node_id"):
        return ExpansionJobResult(status="completed", node_id=option["node_id"])

    existing_task = _find_existing_option_task(db, parent_node.id, option_index)
    if existing_task is not None:
        if existing_task.generated_node_id:
            _set_option_metadata(
                parent_node,
                option_index,
                generation_status=OPTION_COMPLETED,
                node_id=existing_task.generated_node_id,
                expansion_job_id=None,
            )
            db.commit()
            return ExpansionJobResult(status="completed", node_id=existing_task.generated_node_id)

        existing_job = db.query(StoryJob).filter(StoryJob.job_id == existing_task.run.job_id).first()
        if existing_job and existing_task.attempts < settings.STORY_TASK_MAX_ATTEMPTS:
            _set_option_metadata(
                parent_node,
                option_index,
                generation_status=OPTION_PROCESSING,
                expansion_job_id=existing_job.job_id,
            )
            db.commit()
            return ExpansionJobResult(status=existing_job.status or OPTION_PROCESSING, job=existing_job)

    parent_task = db.query(StoryGenerationTask).filter(
        StoryGenerationTask.generated_node_id == parent_node.id,
        StoryGenerationTask.status == "completed",
    ).order_by(StoryGenerationTask.id.desc()).first()

    if parent_task is None:
        raise ValueError("Parent node is not linked to a completed generation task.")

    source_run = parent_task.run
    job_id = str(uuid.uuid4())
    job = StoryJob(
        job_id=job_id,
        session_id=session_id,
        theme=source_run.theme,
        status="pending",
        story_id=story.id,
    )
    db.add(job)
    db.flush()

    run = StoryGenerationRun(
        job_id=job_id,
        story_id=story.id,
        session_id=session_id,
        theme=source_run.theme,
        requested_depth=target_depth or source_run.requested_depth,
        branching_factor=source_run.branching_factor,
        status="processing",
    )
    db.add(run)
    db.flush()

    task = StoryGenerationTask(
        run_id=run.id,
        parent_task_id=parent_task.id,
        parent_node_id=parent_node.id,
        incoming_option_text=option_text,
        option_position=option_index,
        depth=parent_task.depth + 1,
        status="pending",
    )
    db.add(task)

    _set_option_metadata(
        parent_node,
        option_index,
        generation_status=OPTION_PROCESSING,
        expansion_job_id=job_id,
    )
    db.commit()
    db.refresh(job)
    return ExpansionJobResult(status=job.status, job=job, created=True)


def _find_existing_option_task(db: Session, parent_node_id: int, option_index: int) -> StoryGenerationTask | None:
    tasks = db.query(StoryGenerationTask).filter(
        StoryGenerationTask.parent_node_id == parent_node_id,
        StoryGenerationTask.option_position == option_index,
    ).order_by(StoryGenerationTask.id.desc()).all()

    for task in tasks:
        if task.status in {"pending", "processing"}:
            return task
        if task.status == "completed" and task.generated_node_id:
            return task
        if task.status == "failed" and task.attempts < settings.STORY_TASK_MAX_ATTEMPTS:
            return task

    return None


def _set_option_metadata(
    node: StoryNode,
    option_index: int,
    generation_status: str,
    node_id: int | None = None,
    expansion_job_id: str | None = None,
) -> None:
    options = list(node.options or [])
    option = dict(options[option_index] or {})
    option["generation_status"] = generation_status
    option["expansion_job_id"] = expansion_job_id
    if node_id is not None:
        option["node_id"] = node_id
    elif "node_id" not in option:
        option["node_id"] = None
    options[option_index] = option
    node.options = options


def _persist_root_node(db: Session, run: StoryGenerationRun, task: StoryGenerationTask, result) -> StoryNode:
    run.story.title = result.parsed.title
    root_data = result.parsed.rootNode

    node = StoryNode(
        story_id=run.story_id,
        content=root_data.content,
        is_root=True,
        is_ending=root_data.isEnding,
        is_winning_ending=root_data.isWinningEnding,
        options=_option_seeds_to_pending_options(root_data.options)
    )
    db.add(node)
    db.flush()

    task.generated_node_id = node.id
    task.status = "completed"
    task.completed_at = datetime.now(timezone.utc)
    task.raw_response = result.raw_response
    task.repaired_response = result.repaired_response
    task.repair_attempts = result.repair_attempts
    task.parsed_response = result.parsed.model_dump(mode="json")
    return node


def _persist_branch_node(db: Session, task: StoryGenerationTask, result) -> StoryNode:
    parent_node = db.query(StoryNode).filter(StoryNode.id == task.parent_node_id).one()
    node_data = result.parsed

    node = StoryNode(
        story_id=parent_node.story_id,
        content=node_data.content,
        is_root=False,
        is_ending=node_data.isEnding,
        is_winning_ending=node_data.isWinningEnding,
        options=_option_seeds_to_pending_options(node_data.options)
    )
    db.add(node)
    db.flush()

    _mark_parent_option_completed(parent_node, task, node.id)

    task.generated_node_id = node.id
    task.status = "completed"
    task.completed_at = datetime.now(timezone.utc)
    task.raw_response = result.raw_response
    task.repaired_response = result.repaired_response
    task.repair_attempts = result.repair_attempts
    task.parsed_response = result.parsed.model_dump(mode="json")
    return node


def _option_seeds_to_pending_options(options) -> list[dict]:
    if not options:
        return []
    return [
        {
            "text": option.text,
            "node_id": None,
            "generation_status": OPTION_PENDING,
            "expansion_job_id": None,
        }
        for option in options
    ]


def _mark_parent_option_completed(parent_node: StoryNode, task: StoryGenerationTask, generated_node_id: int) -> None:
    parent_options = list(parent_node.options or [])
    entry = {
        "text": task.incoming_option_text,
        "node_id": generated_node_id,
        "generation_status": OPTION_COMPLETED,
        "expansion_job_id": None,
    }

    if task.option_position is not None and 0 <= task.option_position < len(parent_options):
        existing = dict(parent_options[task.option_position] or {})
        existing.update(entry)
        parent_options[task.option_position] = existing
    else:
        existing_index = next(
            (index for index, option in enumerate(parent_options) if option.get("text") == task.incoming_option_text),
            None
        )
        if existing_index is not None:
            existing = dict(parent_options[existing_index] or {})
            existing.update(entry)
            parent_options[existing_index] = existing
        elif task.option_position is not None and task.option_position <= len(parent_options):
            parent_options.insert(task.option_position, entry)
        else:
            parent_options.append(entry)

    parent_node.options = parent_options


def _schedule_child_tasks(
    db: Session,
    run: StoryGenerationRun,
    task: StoryGenerationTask,
    node: StoryNode,
    options
) -> None:
    if node.is_ending or not options:
        return
    if task.depth >= settings.LAZY_INITIAL_DEPTH:
        return

    for index, option in enumerate(options):
        child_task = StoryGenerationTask(
            run_id=run.id,
            parent_task_id=task.id,
            parent_node_id=node.id,
            incoming_option_text=option.text,
            option_position=index,
            depth=task.depth + 1,
            status="pending"
        )
        db.add(child_task)


def _build_path_context(db: Session, task: StoryGenerationTask) -> str:
    chain: list[StoryGenerationTask] = []
    current = task
    while current.parent_task_id is not None:
        parent = db.query(StoryGenerationTask).filter(StoryGenerationTask.id == current.parent_task_id).one()
        chain.append(parent)
        current = parent
    chain.reverse()

    lines: list[str] = []
    for index, ancestor in enumerate(chain):
        node = db.query(StoryNode).filter(StoryNode.id == ancestor.generated_node_id).first()
        if node is None:
            continue
        if index == 0:
            lines.append(f"Root node: {node.content}")
        else:
            lines.append(f"Then the story reached: {node.content}")

        chosen_task = chain[index + 1] if index + 1 < len(chain) else task
        if chosen_task.incoming_option_text:
            lines.append(f"Chosen option: {chosen_task.incoming_option_text}")

    return "\n".join(lines) if lines else "The story is just beginning."


def _finalize_generation_run(db: Session, job: StoryJob, run: StoryGenerationRun) -> WorkflowStepResult:
    failed_tasks = db.query(StoryGenerationTask).filter(
        StoryGenerationTask.run_id == run.id,
        StoryGenerationTask.status != "completed"
    ).count()

    if failed_tasks > 0:
        run.status = "failed"
        run.completed_at = datetime.now(timezone.utc)
        run.last_error = run.last_error or "One or more story branches failed permanently."
        run.updated_at = datetime.now(timezone.utc)
        db.commit()
        return _sync_failed_result(db, job, run.last_error)

    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    run.updated_at = datetime.now(timezone.utc)
    job.story_id = run.story_id
    job.status = "completed"
    job.completed_at = datetime.now(timezone.utc)
    job.error = None
    db.commit()
    return _sync_completed_result(db, job, run)


def _sync_completed_result(db: Session, job: StoryJob, run: StoryGenerationRun) -> WorkflowStepResult:
    job.story_id = run.story_id
    job.status = "completed"
    if job.completed_at is None:
        job.completed_at = datetime.now(timezone.utc)
    job.error = None
    db.commit()
    return _build_progress_result(db, run, "completed", False, story_id=run.story_id)


def _sync_failed_result(db: Session, job: StoryJob, error: str) -> WorkflowStepResult:
    run = db.query(StoryGenerationRun).filter(StoryGenerationRun.job_id == job.job_id).first()
    if run is not None:
        _mark_run_options_failed(db, run)
    job.status = "failed"
    job.completed_at = datetime.now(timezone.utc)
    job.error = error
    db.commit()
    return WorkflowStepResult(job_id=job.job_id, status="failed", has_more_work=False, last_error=error)


def _mark_run_options_failed(db: Session, run: StoryGenerationRun) -> None:
    failed_tasks = db.query(StoryGenerationTask).filter(
        StoryGenerationTask.run_id == run.id,
        StoryGenerationTask.status == "failed",
        StoryGenerationTask.parent_node_id.isnot(None),
        StoryGenerationTask.option_position.isnot(None),
        StoryGenerationTask.generated_node_id.is_(None),
        StoryGenerationTask.attempts >= settings.STORY_TASK_MAX_ATTEMPTS,
    ).all()

    for task in failed_tasks:
        parent_node = db.query(StoryNode).filter(StoryNode.id == task.parent_node_id).first()
        if parent_node is None:
            continue
        options = list(parent_node.options or [])
        if task.option_position is None or task.option_position >= len(options):
            continue
        option = dict(options[task.option_position] or {})
        option["generation_status"] = OPTION_FAILED
        option["expansion_job_id"] = run.job_id
        option["error"] = task.error or run.last_error or "This branch failed to generate."
        options[task.option_position] = option
        parent_node.options = options


def _build_progress_result(
    db: Session,
    run: StoryGenerationRun,
    status: str,
    has_more_work: bool,
    last_error: str | None = None,
    story_id: int | None = None,
    retry_after_seconds: float | None = None
) -> WorkflowStepResult:
    pending_count = db.query(StoryGenerationTask).filter(
        StoryGenerationTask.run_id == run.id,
        StoryGenerationTask.status.in_(["pending", "failed", "processing"])
    ).count()
    completed_count = db.query(StoryGenerationTask).filter(
        StoryGenerationTask.run_id == run.id,
        StoryGenerationTask.status == "completed"
    ).count()
    failed_count = db.query(StoryGenerationTask).filter(
        StoryGenerationTask.run_id == run.id,
        StoryGenerationTask.status == "failed",
        StoryGenerationTask.attempts >= settings.STORY_TASK_MAX_ATTEMPTS
    ).count()

    return WorkflowStepResult(
        job_id=run.job_id,
        status=status,
        has_more_work=has_more_work and pending_count > 0,
        story_id=story_id,
        pending_tasks=pending_count,
        completed_tasks=completed_count,
        failed_tasks=failed_count,
        last_error=last_error or run.last_error,
        retry_after_seconds=retry_after_seconds
    )
