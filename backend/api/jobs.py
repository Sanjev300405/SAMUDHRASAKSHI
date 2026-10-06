"""backend/api/jobs.py — a minimal in-process job registry for the two slow
pipeline stages (hindcast, simulate). Real background execution via a thread
pool, real progress via the progress_cb hooks in m4_hindcast/m6_counterfactual
— never a progress bar that merely counts up on a timer independent of what
the computation is actually doing.

Single-process, in-memory. Fine for a demo server (ARCHITECTURE.md's own
scope); a multi-worker deployment would need a real queue (out of scope).
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

_executor = ThreadPoolExecutor(max_workers=4)
_lock = threading.Lock()


@dataclass
class Job:
    job_id: str
    status: str = "running"  # running | done | error
    current: int = 0
    total: int = 1
    message: str = ""
    result: Any = None
    error: str | None = None


_JOBS: dict[str, Job] = {}


def create_job(fn: Callable[[Callable[[int, int, str], None]], Any]) -> str:
    """Runs `fn(progress_cb)` in a background thread. `fn` must call
    `progress_cb(current, total, message)` as it works and return the
    JSON-serialisable result. Returns the job_id to poll."""
    job_id = uuid.uuid4().hex
    job = Job(job_id=job_id)
    with _lock:
        _JOBS[job_id] = job

    def progress_cb(current: int, total: int, message: str) -> None:
        with _lock:
            job.current = current
            job.total = total
            job.message = message

    def run() -> None:
        try:
            result = fn(progress_cb)
            with _lock:
                job.result = result
                job.status = "done"
                job.current = job.total
        except Exception as e:  # noqa: BLE001
            with _lock:
                job.status = "error"
                job.error = str(e)

    _executor.submit(run)
    return job_id


def get_job(job_id: str) -> Job | None:
    with _lock:
        return _JOBS.get(job_id)


def job_to_dict(job: Job) -> dict:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "progress": {"current": job.current, "total": job.total, "message": job.message},
        "result": job.result if job.status == "done" else None,
        "error": job.error,
    }
