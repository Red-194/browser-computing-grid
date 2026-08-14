from uuid import uuid4, UUID

from fastapi import APIRouter

from .models.jobs import JobSubmission
from .services.splitter_loader import get_splitter

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.post("")
async def submit(job: JobSubmission):

    job_id = uuid4()
    job.job_id = job_id

    splitter = get_splitter(job.workload)
    tasks = splitter.split(job)

    return {
        "message": "Job submitted.",
        "job": job.model_dump(),
        "task_count": len(tasks),
        "tasks": tasks
    }

@router.get("")
async def list():

    return {
        "message": "List jobs."
    }


@router.get("/{job_id}")
async def get(job_id: UUID):

    return {
        "message": "Get job.",
        "job_id": job_id
    }


@router.get("/{job_id}/result")
async def result(job_id: UUID):

    return {
        "message": "Get job result.",
        "job_id": job_id
    }


@router.delete("/{job_id}")
async def cancel(job_id: UUID):

    return {
        "message": "Job cancelled.",
        "job_id": job_id
    }