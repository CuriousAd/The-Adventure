import json
from typing import Any

from core.job_runner import run_story_job


def handler(event: dict[str, Any], _context: Any) -> dict[str, list[dict[str, str]]]:
    batch_item_failures: list[dict[str, str]] = []

    for record in event.get("Records", []):
        message_id = record["messageId"]
        try:
            payload = json.loads(record["body"])
            run_story_job(
                job_id=payload["job_id"],
                theme=payload["theme"],
                session_id=payload["session_id"],
            )
        except Exception:
            batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}
