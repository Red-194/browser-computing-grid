import math
import logging
import time
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .events import notify_dashboards
from .models.protocol import HeartbeatMessage, PongMessage, RegisterAckMessage, RegisterMessage
from .models.worker import Worker, WorkerMetadata, WorkerStates
from .registry import workers, aggregators, task_counts, completed_jobs, job_start_times

router = APIRouter()
logger = logging.getLogger("grid.websocket")

async def send_task(worker, task):
    if worker.websocket is None:
        return False

    try:
        await worker.websocket.send_json({
            "type": "task",
            "task": task.model_dump(mode="json")
        })

        return True

    except Exception as e:
        logger.error(
            "Failed to send task %s to worker %s: %s",
            task.task_id,
            worker.uuid,
            e,
        )

        return False

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):

    await websocket.accept()
    logger.info("Worker connected")
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
                        os=message.os
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
                            os=message.os
                        ),
                        state=WorkerStates.IDLE
                    )

                    workers[worker.uuid] = worker
                
                worker_uuid = worker.uuid

                logger.info("Registered worker: %s", worker.uuid)
                logger.debug("Worker metadata for %s: %s", worker.uuid, worker.metadata)

                await notify_dashboards()

                ack = RegisterAckMessage(
                    type="register_ack",
                    uuid=worker.uuid,
                    state=worker.state
                )

                await websocket.send_json(ack.model_dump())

            elif msg_type == "heartbeat":

                message = HeartbeatMessage.model_validate(raw)
                worker = workers.get(worker_uuid)

                if worker is None:
                    continue

                worker.last_heartbeat = datetime.now()
                logger.debug(
                    "Heartbeat received from %s at %s",
                    worker.uuid,
                    worker.last_heartbeat,
                )

            elif msg_type == "pong":

                message = PongMessage.model_validate(raw)
                worker = workers.get(worker_uuid)

                if worker is None:
                    continue

                latency = (time.perf_counter() - message.timestamp) * 1000
                worker.latency = math.ceil(latency)

                logger.debug("Latency %s: %s ms", worker.uuid, worker.latency)

                await notify_dashboards()

            elif msg_type == "task_result":

                job_id = raw["job_id"]
                task_id = raw["task_id"]

                aggregator = aggregators.get(str(job_id))

                if aggregator is None:
                    logger.error("No aggregator found for job %s", job_id)
                    continue

                result = raw["result"]
                # Aggregators that need idempotence (such as SAT) can use the
                # task id without changing the worker-to-controller protocol.
                if isinstance(result, dict):
                    result = {
                        **result,
                        "_task_id": task_id,
                        "_execution_time_ms": raw.get("execution_time_ms"),
                    }
                try:
                    aggregator.add_result(result)
                except Exception:
                    logger.error(
                        "Failed to aggregate result for job %s task %s",
                        job_id,
                        task_id,
                        exc_info=True,
                    )
                    raise
                total_tasks = task_counts.get(str(job_id))

                logger.debug(
                    "Task result received: job=%s task=%s execution_time=%s ms",
                    job_id,
                    task_id,
                    raw["execution_time_ms"],
                )

                if aggregator.is_complete(total_tasks):

                    elapsed = (
                        time.perf_counter()
                        - job_start_times[str(job_id)]
                    )
                    completed_jobs.add(str(job_id))
                    logger.info("Job %s aggregation complete", job_id)
                    logger.info("Job %s total execution time: %.3f seconds", job_id, elapsed)



    except WebSocketDisconnect:

        if worker_uuid is not None:

            worker = workers.get(worker_uuid)

            if worker is not None:
                worker.websocket = None
                worker.latency = 0
                worker.state = WorkerStates.OFFLINE

                logger.info("Worker disconnected: %s", worker.uuid)
                await notify_dashboards()

        else:
            logger.warning("Unknown worker disconnected")
    except Exception:
        logger.error("WebSocket failure for worker %s", worker_uuid, exc_info=True)
        raise
