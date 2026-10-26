import base64
import logging
import time
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import ValidationError

from .models.jobs import MAX_SYNTHETIC_BYTES, JobSubmission
from .models.pcb import CompletionOutcome, JobPCB, JobStatus, WorkerPCB
from .models.worker import WorkerStates
from .registry import (
    aggregators,
    completed_jobs,
    job_pcbs,
    job_start_times,
    job_tasks,
    task_counts,
    worker_pcbs,
    workers,
)
from .services.loader import get_aggregator, get_splitter
from .services.scheduler.random import RandomScheduler
from .websocket import send_task

router = APIRouter(prefix="/jobs", tags=["Jobs"])
scheduler = RandomScheduler()
logger = logging.getLogger("grid.jobs")


def sync_worker_state(worker_uuid: str) -> None:
    """Mirror the execution PCB state onto the network-facing worker record."""
    worker = workers.get(worker_uuid)
    worker_pcb = worker_pcbs.get(worker_uuid)
    if worker is None or worker_pcb is None:
        return
    if worker_pcb.state == WorkerStates.OFFLINE:
        worker.state = WorkerStates.OFFLINE
    elif worker_pcb.running:
        worker.state = WorkerStates.BUSY
    else:
        worker.state = WorkerStates.IDLE


@router.post("")
async def submit(job: JobSubmission):
    return await submit_job(job)


@router.post("/compression/upload")
async def submit_compression_upload(
    file: UploadFile = File(...),
    variants: str = Form("lz4,zstd-fastest"),
    chunk_size: int = Form(256 * 1024),
):
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
        raise HTTPException(
            status_code=422,
            detail=error.errors(include_url=False, include_context=False),
        )
    response = await submit_job(job)
    response["job"]["config"]["data_base64"] = f"<{len(data)} bytes from {file.filename}>"
    response["filename"] = file.filename
    return response


async def submit_job(job: JobSubmission):
    job_id = uuid4()
    job.job_id = job_id
    job_start_times[str(job_id)] = time.perf_counter()
    logger.debug("Job %s splitter started (%s)", job_id, job.workload)
    split_started = time.perf_counter()
    tasks = get_splitter(job.workload).split(job)
    logger.debug(
        "Job %s splitter finished: %d tasks in %.3f s",
        job_id,
        len(tasks),
        time.perf_counter() - split_started,
    )
    job_pcbs[str(job_id)] = JobPCB.create(
        job_id, job.workload, [task.task_id for task in tasks]
    )
    job_tasks[str(job_id)] = {task.task_id: task for task in tasks}
    aggregators[str(job_id)] = get_aggregator(job.workload, job.config)
    task_counts[str(job_id)] = len(tasks)
    logger.info("Job %s submitted for workload %s", job_id, job.workload)
    logger.info("Job %s splitting complete: %d tasks", job_id, len(tasks))
    assignments = await dispatch_pending(job_id)
    return {
        "message": "Job submitted.",
        "job": job.model_dump(),
        "task_count": len(tasks),
        "assignments": assignments,
    }


async def dispatch_pending(job_id: UUID | None = None) -> list[dict]:
    dispatched = []
    selected = (
        [job_pcbs[str(job_id)]]
        if job_id is not None and str(job_id) in job_pcbs
        else list(job_pcbs.values())
    )
    for job_pcb in selected:
        if job_pcb.status != JobStatus.RUNNING:
            continue
        for worker in workers.values():
            if worker.uuid not in worker_pcbs:
                worker_pcbs[worker.uuid] = WorkerPCB(
                    worker.uuid,
                    capacity=max(
                        1,
                        getattr(worker, "cores", len(job_pcb.tasks)),
                    ),
                )
        assignments = scheduler.schedule(
            job_pcb.waiting(), list(workers.values()), worker_pcbs
        )
        retry_dispatch = False
        for task_pcb, worker in assignments:
            attempt = task_pcb.assign(worker.uuid)
            worker_pcb = worker_pcbs[worker.uuid]
            worker_pcb.assign(task_pcb.key, attempt)
            sync_worker_state(worker.uuid)
            task = job_tasks[str(job_pcb.job_id)][task_pcb.task_id]
            sent = await send_task(worker, task, attempt=attempt)
            if sent is not False:
                dispatched.append(
                    {"task_id": task.task_id, "worker": worker.uuid, "attempt": attempt}
                )
            else:
                retry_dispatch = True
                worker_pcb.release(task_pcb.key, completed=False)
                task_pcb.requeue("task send failed", attempt=attempt)
                sync_worker_state(worker.uuid)
        if retry_dispatch and job_pcb.status == JobStatus.RUNNING and job_pcb.waiting():
            dispatched.extend(await dispatch_pending(job_pcb.job_id))
    return dispatched


async def handle_task_result(
    worker_uuid: str,
    job_id: UUID,
    task_id: int,
    result: object,
    attempt: int | None,
    execution_time_ms: float | None,
) -> CompletionOutcome | None:
    job_pcb = job_pcbs.get(str(job_id))
    worker_pcb = worker_pcbs.get(worker_uuid)
    if job_pcb is None or worker_pcb is None or task_id not in job_pcb.tasks:
        return None
    task_pcb = job_pcb.task(task_id)
    outcome = task_pcb.complete(
        task_pcb.attempt if attempt is None else attempt,
        worker_uuid=worker_uuid,
    )
    if outcome == CompletionOutcome.STALE:
        return outcome
    worker_pcb.release(task_pcb.key)
    sync_worker_state(worker_uuid)
    if isinstance(result, dict):
        result = {
            **result,
            "_task_id": task_id,
            "_execution_time_ms": execution_time_ms,
        }
    aggregators[str(job_id)].add_result(result)
    if job_pcb.status == JobStatus.DONE:
        completed_jobs.add(str(job_id))
    await dispatch_pending()
    return outcome


async def handle_worker_failure(worker_uuid: str, reason: str) -> None:
    worker_pcb = worker_pcbs.get(worker_uuid)
    if worker_pcb is None:
        return
    lost = worker_pcb.mark_offline()
    sync_worker_state(worker_uuid)
    for (job_id, task_id), attempt in lost:
        job_pcb = job_pcbs.get(str(job_id))
        if job_pcb is not None:
            job_pcb.task(task_id).requeue(reason, attempt=attempt)
    await dispatch_pending()


@router.get("")
async def list_jobs():
    return {"message": "List jobs."}


@router.get("/{job_id}")
async def get(job_id: UUID):
    job_pcb = job_pcbs.get(str(job_id))
    if job_pcb is None:
        return {"message": "Job not found.", "job_id": job_id}
    return {
        "message": "Get job.",
        "job_id": job_id,
        "workload": job_pcb.workload,
        "status": job_pcb.status.value,
        "progress": job_pcb.progress(),
    }


@router.get("/{job_id}/result")
async def result(job_id: UUID):
    job_id_str = str(job_id)
    if job_id_str not in aggregators:
        return {"message": "Job not found.", "job_id": job_id}
    job_pcb = job_pcbs[job_id_str]
    if job_pcb.status == JobStatus.FAILED:
        return {
            "message": "Job failed.",
            "job_id": job_id,
            "status": JobStatus.FAILED.value,
            "failed_tasks": [
                {
                    "task_id": task.task_id,
                    "retries": task.retries,
                    "error": task.last_error,
                }
                for task in job_pcb.failed_tasks()[:10]  # keep the reply small
            ],
        }
    if job_pcb.status != JobStatus.DONE:
        return {"message": "Job is still processing.", "job_id": job_id}
    return Response(
        content=aggregators[job_id_str].get_result(),
        media_type=aggregators[job_id_str].result_type,
    )


@router.delete("/{job_id}")
async def cancel(job_id: UUID):
    return {"message": "Job cancelled.", "job_id": job_id}
