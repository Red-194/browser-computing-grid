from uuid import uuid4, UUID
import time

from fastapi import APIRouter, Response

from .models.jobs import JobSubmission
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