from typing import Any

from core.job_runner import process_story_job_step


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    return process_story_job_step(
        job_id=event["job_id"],
        theme=event["theme"],
        session_id=event["session_id"],
        depth=event.get("depth")
    ).__dict__
