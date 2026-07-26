from fastapi import APIRouter

from .models.jobs import JobSubmission

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.post("")
async def submit(job: JobSubmission):

    return {
        "message": "Job submitted.",
        "job": job.model_dump()
    }


@router.get("")
async def list():

    return {
        "message": "List jobs."
    }


@router.get("/{job_id}")
async def get(job_id: str):

    return {
        "message": "Get job.",
        "job_id": job_id
    }


@router.get("/{job_id}/result")
async def result(job_id: str):

    return {
        "message": "Get job result.",
        "job_id": job_id
    }


@router.delete("/{job_id}")
async def cancel(job_id: str):

    return {
        "message": "Job cancelled.",
        "job_id": job_id
    }