"""Background job queue (Redis + RQ). One queue per stage, named after it.

PIPELINE_SYNC=true runs stages inline instead (used by API tests).
"""
from __future__ import annotations

import os
from functools import lru_cache

from redis import Redis
from rq import Queue, Retry

from app.config import get_settings
from app.contracts import Stage

# Long jobs: OCR of a 1,000-page scan, or extraction with many LLM calls.
JOB_TIMEOUT = {Stage.PARSE: 4 * 3600, Stage.EXTRACT: 4 * 3600, Stage.VALIDATE: 1800, Stage.INDEX: 1800}


@lru_cache
def redis_conn() -> Redis:
    return Redis.from_url(get_settings().redis_url)


def queue(stage: Stage | str) -> Queue:
    return Queue(Stage(stage).value, connection=redis_conn())


def sync_mode() -> bool:
    return os.getenv("PIPELINE_SYNC", "").lower() in ("1", "true", "yes")


def enqueue_stage(document_id: str, stage: Stage | str) -> None:
    from app.pipeline import run_stage

    stage = Stage(stage)
    if sync_mode():
        run_stage(str(document_id), stage.value)
        return
    queue(stage).enqueue(
        run_stage, str(document_id), stage.value,
        job_timeout=JOB_TIMEOUT[stage],
        # Transient errors (DB hiccup, LLM 5xx) are retried with backoff.
        # Coded PipelineErrors are caught inside run_stage and never retried.
        retry=Retry(max=3, interval=[10, 30, 90]),
        failure_ttl=7 * 24 * 3600,
    )
