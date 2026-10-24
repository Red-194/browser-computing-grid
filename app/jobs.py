from uuid import uuid4, UUID
import time

import base64

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import ValidationError

from .models.jobs import MAX_SYNTHETIC_BYTES, JobSubmission
from .services.loader import get_splitter, get_aggregator
from .services.scheduler.round_robin import RoundRobinScheduler
from .services.scheduler.random import RandomScheduler
from .registry import workers, aggregators, task_counts, completed_jobs, job_start_times
from .websocket import send_task

router = APIRouter(prefix="/jobs", tags=["Jobs"])

# Current scheduler mode
scheduler = RandomScheduler()

@router.post("")
async def submit(job: JobSubmission):
    return await submit_job(job)


@router.post("/compression/upload")
async def submit_compression_upload(
    file: UploadFile = File(...),
    variants: str = Form("lz4,zstd-fastest"),
    chunk_size: int = Form(256 * 1024),
):
    """Compress a real uploaded file (multipart form) instead of made-up data."""
    data = await file.read(MAX_SYNTHETIC_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="uploaded file is empty")
    if len(data) > MAX_SYNTHETIC_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"file is larger than {MAX_SYNTHETIC_BYTES // (1024 * 1024)} MiB",
        )

    try:
        job = JobSubmission(
            workload="compression",
            config={
                "variants": [v.strip() for v in variants.split(",") if v.strip()],
                "chunk_size": chunk_size,
                "data_base64": base64.b64encode(data).decode("ascii"),
            },
        )
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors(include_url=False, include_context=False))

    response = await submit_job(job)
    response["job"]["config"]["data_base64"] = f"<{len(data)} bytes from {file.filename}>"
    response["filename"] = file.filename
    return response


async def submit_job(job: JobSubmission):

    job_id = uuid4()
    job.job_id = job_id
    job_start_times[str(job_id)] = time.perf_counter()

    splitter = get_splitter(job.workload)
    tasks = splitter.split(job)

    aggregator = get_aggregator(job.workload, job.config)
    aggregators[str(job.job_id)] = aggregator
    task_counts[str(job.job_id)] = len(tasks)

    assignments = scheduler.schedule(
        tasks,
        list(workers.values())
    )

    for task, worker in assignments:
        await send_task(worker, task)

    return {
        "message": "Job submitted.",
        "job": job.model_dump(),
        "task_count": len(tasks),
        "assignments": [
            {
                "task_id": task.task_id,
                "worker": worker.uuid
            }
            for task, worker in assignments
        ]
    }

@router.get("")
async def list_jobs():

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

    job_id_str = str(job_id)

    if job_id_str not in aggregators:
        return {
            "message": "Job not found.",
            "job_id": job_id
        }

    if job_id_str not in completed_jobs:
        return {
            "message": "Job is still processing.",
            "job_id": job_id
        }

    aggregator = aggregators[job_id_str]

    return Response(
        content=aggregator.get_result(),
        media_type=aggregator.result_type
    )

@router.delete("/{job_id}")
async def cancel(job_id: UUID):

    return {
        "message": "Job cancelled.",
        "job_id": job_id
    }