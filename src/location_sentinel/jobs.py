from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Literal

JobStatus = Literal["pending", "running", "ready", "failed"]


class Job:
    def __init__(self, job_id: str, location_key: str | None = None):
        self.job_id = job_id
        self.status: JobStatus = "pending"
        self.location_key = location_key
        self.report_url: str | None = None
        self.name: str | None = None
        self.error: str | None = None
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        job = cls(d["job_id"], d.get("location_key"))
        job.status = d.get("status", "pending")
        job.report_url = d.get("report_url")
        job.name = d.get("name")
        job.error = d.get("error")
        return job

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
    """
    Job store backed by PostgreSQL so all uvicorn workers share state.
    The in-memory dict is a per-process write-through cache; reads fall
    back to DB for jobs created on other worker processes.
    """

    def __init__(self):
        self._jobs: dict[str, Job] = {}

    def _store(self):
        # Lazy import avoids circular dependency at module load time.
        from .storage.postgres_store import store
        return store

    def create(self, location_key: str) -> Job:
        job_id = secrets.token_hex(8)
        job = Job(job_id, location_key)
        self._jobs[job_id] = job
        self._store().create_job(job_id, location_key)
        return job

    def find_active(self, location_key: str) -> Job | None:
        # Fast path: check this worker's memory first.
        for job in self._jobs.values():
            if job.location_key == location_key and job.status in ("pending", "running"):
                return job
        # Cross-worker fallback: check DB.
        row = self._store().find_active_job(location_key)
        if row:
            job = Job.from_dict(row)
            self._jobs[job.job_id] = job
            return job
        return None

    def get(self, job_id: str) -> Job | None:
        # Fast path: check this worker's memory first.
        job = self._jobs.get(job_id)
        if job:
            return job
        # Cross-worker fallback: check DB.
        row = self._store().get_job(job_id)
        if row:
            job = Job.from_dict(row)
            self._jobs[job_id] = job
            return job
        return None

    def update(self, job_id: str, **kwargs) -> None:
        job = self._jobs.get(job_id)
        if job:
            for k, v in kwargs.items():
                setattr(job, k, v)
            job.updated_at = datetime.now(timezone.utc)
        self._store().update_job(job_id, **kwargs)


job_store = JobStore()
