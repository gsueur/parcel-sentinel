from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..jobs import job_store

router = APIRouter()


@router.get("/jobs")
async def list_jobs():
    """List all jobs, most recent first."""
    jobs = sorted(job_store._jobs.values(), key=lambda j: j.created_at, reverse=True)
    return {
        "count": len(jobs),
        "jobs": [j.to_dict() for j in jobs],
    }


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """Poll the status of an async location computation job."""
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()
