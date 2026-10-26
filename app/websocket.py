
import math
import time
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .events import notify_dashboards
from .models.protocol import (
    HeartbeatMessage,
    PongMessage,
    RegisterAckMessage,
    RegisterMessage,
)
from .models.worker import Worker, WorkerMetadata, WorkerStates
from .registry import (
    workers,
    aggregators,
    task_counts,
    completed_jobs,
    job_start_times,
    task_assignments,
)

router = APIRouter()


async def send_task(worker, task):
    if worker.websocket is None:
        return False

    try:
        await worker.websocket.send_json({
            "type": "task",
            "task": task.model_dump(mode="json"),
        })

        return True

    except Exception as e:
        print(
            f"Failed to send task {task.task_id} "
            f"to worker {worker.uuid}: {e}"
        )
        return False


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("Worker connected.")

    worker_uuid = None

    try:
        while True:
            raw = await websocket.receive_json()
            msg_type = raw["type"]

            if msg_type == "register":
                message = RegisterMessage.model_validate(raw)
                worker = workers.get(message.uuid)

                if worker is not None:
                    worker.websocket = websocket
                    worker.ip = websocket.client.host
                    worker.cores = message.cores
                    worker.memory = message.memory
                    worker.last_heartbeat = datetime.now()
                    worker.metadata = WorkerMetadata(
                        browser=message.browser,
                        os=message.os,
                    )
                    worker.state = WorkerStates.IDLE

                else:
                    worker = Worker(
                        uuid=message.uuid,
                        websocket=websocket,
                        ip=websocket.client.host,
                        cores=message.cores,
                        memory=message.memory,
                        last_heartbeat=datetime.now(),
                        metadata=WorkerMetadata(
                            browser=message.browser,
                            os=message.os,
                        ),
                        state=WorkerStates.IDLE,
                    )

                    workers[worker.uuid] = worker

                worker_uuid = worker.uuid

                print(f"Registered worker: {worker.uuid}")
                print(f"Worker metadata: {worker.metadata}")

                await notify_dashboards()

                ack = RegisterAckMessage(
                    type="register_ack",
                    uuid=worker.uuid,
                    state=worker.state,
                )

                await websocket.send_json(ack.model_dump())

            elif msg_type == "heartbeat":
                message = HeartbeatMessage.model_validate(raw)
                worker = workers.get(worker_uuid)

                if worker is None:
                    continue

                worker.last_heartbeat = datetime.now()

                print(
                    f"Heartbeat received from {worker.uuid} "
                    f"at {worker.last_heartbeat}"
                )

            elif msg_type == "pong":
                message = PongMessage.model_validate(raw)
                worker = workers.get(worker_uuid)

                if worker is None:
                    continue

                latency = (
                    time.perf_counter() - message.timestamp
                ) * 1000

                worker.latency = math.ceil(latency)

                print(
                    f"Latency {worker.uuid}: "
                    f"{worker.latency} ms"
                )

                await notify_dashboards()

            elif msg_type == "task_result":
                job_id = str(raw["job_id"])
                task_id = raw["task_id"]

                aggregator = aggregators.get(job_id)

                if aggregator is None:
                    print(f"No aggregator found for job {job_id}")
                    continue

                # Update the task status when its result arrives.
                job_tasks = task_assignments.get(job_id, {})

                try:
                    task_key = int(task_id)
                except (TypeError, ValueError):
                    task_key = task_id

                if task_key in job_tasks:
                    job_tasks[task_key]["status"] = "Completed"

                    if worker_uuid is not None:
                        job_tasks[task_key]["worker_id"] = worker_uuid

                result = raw["result"]

                # Preserve task information for aggregators that need
                # task IDs or execution-time information.
                if isinstance(result, dict):
                    result = {
                        **result,
                        "_task_id": task_id,
                        "_execution_time_ms": raw.get(
                            "execution_time_ms"
                        ),
                    }

                aggregator.add_result(result)

                total_tasks = task_counts.get(job_id)

                print(
                    f"Task result received: "
                    f"job={job_id} "
                    f"task={task_id} "
                    f"execution_time="
                    f"{raw.get('execution_time_ms')} ms"
                )

                if aggregator.is_complete(total_tasks):
                    elapsed = (
                        time.perf_counter()
                        - job_start_times[job_id]
                    )

                    completed_jobs.add(job_id)

                    print(f"Job {job_id} aggregation complete.")
                    print(
                        f"Total execution time: "
                        f"{elapsed:.3f} seconds"
                    )

    except WebSocketDisconnect:
        if worker_uuid is not None:
            worker = workers.get(worker_uuid)

            if worker is not None:
                worker.websocket = None
                worker.latency = 0
                worker.state = WorkerStates.OFFLINE

                print(f"Worker disconnected: {worker.uuid}")
                await notify_dashboards()

        else:
            print("Unknown worker disconnected.")
