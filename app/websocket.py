import math
import logging
import time
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .events import notify_dashboards
from .models.protocol import HeartbeatMessage, PongMessage, RegisterAckMessage, RegisterMessage
from .models.worker import Worker, WorkerMetadata, WorkerStates
from .registry import workers, worker_pcbs
from .models.pcb import WorkerPCB

router = APIRouter()
logger = logging.getLogger("grid.websocket")

async def send_task(worker, task, attempt: int | None = None):
    if worker.websocket is None:
        return False

    try:
        payload = {
            "type": "task",
            "task": task.model_dump(mode="json")
        }
        if attempt is not None:
            payload["task"]["attempt"] = attempt
        await worker.websocket.send_json(payload)

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

                worker_pcb = worker_pcbs.get(worker.uuid)
                if worker_pcb is None:
                    worker_pcb = WorkerPCB(worker.uuid, capacity=max(1, worker.cores))
                    worker_pcbs[worker.uuid] = worker_pcb
                else:
                    worker_pcb.mark_online()
                worker_pcb.touch()
                from .jobs import sync_worker_state
                sync_worker_state(worker.uuid)
                
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
                worker_pcb.touch()
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
                worker_pcbs[worker.uuid].touch()

                logger.debug("Latency %s: %s ms", worker.uuid, worker.latency)

                await notify_dashboards()

            elif msg_type == "task_result":

                job_id = raw["job_id"]
                task_id = raw["task_id"]

                result = raw["result"]
                # Aggregators that need idempotence (such as SAT) can use the
                # task id without changing the worker-to-controller protocol.
                if isinstance(result, dict):
                    result = {
                        **result,
                        "_task_id": task_id,
                        "_execution_time_ms": raw.get("execution_time_ms"),
                    }
                logger.debug(
                    "Task result received: job=%s task=%s execution_time=%s ms",
                    job_id,
                    task_id,
                    raw.get("execution_time_ms"),
                )

                from .jobs import handle_task_result
                await handle_task_result(
                    worker_uuid,
                    UUID(str(job_id)),
                    task_id,
                    result,
                    raw.get("attempt"),
                    raw.get("execution_time_ms"),
                )



    except WebSocketDisconnect:

        if worker_uuid is not None:

            worker = workers.get(worker_uuid)

            if worker is not None:
                from .jobs import handle_worker_failure
                await handle_worker_failure(worker.uuid, "worker disconnected")
                worker.websocket = None
                worker.latency = 0

                logger.info("Worker disconnected: %s", worker.uuid)
                await notify_dashboards()

        else:
            logger.warning("Unknown worker disconnected")
    except Exception:
        logger.error("WebSocket failure for worker %s", worker_uuid, exc_info=True)
        raise
