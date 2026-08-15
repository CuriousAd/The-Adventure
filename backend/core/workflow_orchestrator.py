import json

import boto3

from core.config import settings


def start_story_workflow(job_id: str, theme: str, session_id: str, depth: int) -> None:
    if not settings.STORY_WORKFLOW_ARN:
        raise ValueError("STORY_WORKFLOW_ARN is required when JOB_EXECUTION_MODE is workflow.")

    step_functions = boto3.client("stepfunctions", region_name=settings.AWS_REGION or None)
    step_functions.start_execution(
        stateMachineArn=settings.STORY_WORKFLOW_ARN,
        name=f"story-{job_id}",
        input=json.dumps({
            "job_id": job_id,
            "theme": theme,
            "session_id": session_id,
            "depth": depth,
        }),
    )
