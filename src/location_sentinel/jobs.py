from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Literal

JobStatus = Literal["pending", "running", "ready", "failed"]


class Job:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.status: JobStatus = "pending"
        self.location_key: str | None = None
        self.report_url: str | None = None
        self.name: str | None = None
        self.error: str | None = None
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "location_key": self.location_key,
            "report_url": self.report_url,
            "name": self.name,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class JobStore:
    def __init__(self):
        self._jobs: dict[str, Job] = {}

    def create(self) -> Job:
        job_id = secrets.token_hex(8)
        job = Job(job_id)
        self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def update(self, job_id: str, **kwargs) -> None:
        job = self._jobs.get(job_id)
        if job:
            for k, v in kwargs.items():
                setattr(job, k, v)
            job.updated_at = datetime.now(timezone.utc)


job_store = JobStore()
