import asyncio
import math
import logging
import time
import weakref
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .events import notify_dashboards
from .models.protocol import HeartbeatMessage, PongMessage, RegisterAckMessage, RegisterMessage
from .models.worker import Worker, WorkerMetadata, WorkerStates
from .registry import workers, worker_pcbs
from .models.pcb import WorkerPCB
from .services.scheduler.stats import tracker as speed_tracker

router = APIRouter()
logger = logging.getLogger("grid.websocket")

# One lock per connection. Two coroutines writing to the same websocket at once
# (a dispatch sending tasks while another dispatch or a ping also sends) can make
# the library raise AssertionError when large messages fill the write buffer, so
# every send goes through send_json below.
_send_locks: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


async def send_json(websocket, payload) -> None:
    lock = _send_locks.get(websocket)
    if lock is None:
        lock = _send_locks[websocket] = asyncio.Lock()
    async with lock:
        await websocket.send_json(payload)


async def send_tasks(worker, items):
    """Send several tasks to a worker in one message.

    items: list of (task, attempt). Returns False if the connection is unusable.
    The tab handles each task exactly as if it had arrived on its own.
    """
    if worker.websocket is None:
        return False

    try:
        tasks = []
        for task, attempt in items:
            payload = task.model_dump(mode="json")
            if attempt is not None:
                payload["attempt"] = attempt
            tasks.append(payload)
        await send_json(worker.websocket, {"type": "tasks", "tasks": tasks})
        return True

    except Exception as e:
        logger.error(
            "Failed to send %d tasks to worker %s: %s %r",
            len(items),
            worker.uuid,
            type(e).__name__,
            e,
        )
        return False


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
        await send_json(worker.websocket, payload)

        return True

    except Exception as e:
        logger.error(
            "Failed to send task %s to worker %s: %s %r",
            task.task_id,
            worker.uuid,
            type(e).__name__,
            e,
        )

        return False

async def attach_worker_pcb(worker):
    """Create or revive the worker's control block when it registers.

    If the worker already had one with tasks on it, those tasks belonged to its
    old session (the tab reloaded or reconnected) and are gone, so they are
    requeued before the worker is marked online again.
    """
    from .jobs import handle_worker_failure, sync_worker_state

    worker_pcb = worker_pcbs.get(worker.uuid)
    if worker_pcb is None:
        worker_pcb = WorkerPCB(worker.uuid, capacity=max(1, worker.cores))
        worker_pcbs[worker.uuid] = worker_pcb
    else:
        if worker_pcb.running:
            await handle_worker_failure(worker.uuid, "worker re-registered")
        worker_pcb.mark_online()
    worker_pcb.touch()
    speed_tracker.clear_quarantine(worker.uuid)  # a reconnecting worker starts fresh
    sync_worker_state(worker.uuid)
    return worker_pcb


async def handle_socket_closed(worker_uuid, websocket):
    """A worker's socket closed. Only act if it is the worker's current socket.

    When a tab reloads, the new socket registers first and the old socket's
    close can arrive afterwards. That late close must not mark the live worker
    offline or drop its new connection.
    """
    worker = workers.get(worker_uuid)
    if worker is None:
        return False

    if worker.websocket is not websocket:
        logger.info(
            "Ignoring close of an old socket for worker %s (it has reconnected)",
            worker.uuid,
        )
        return False

    from .jobs import handle_worker_failure
    await handle_worker_failure(worker.uuid, "worker disconnected")
    worker.websocket = None
    worker.latency = 0

    logger.info("Worker disconnected: %s", worker.uuid)
    await notify_dashboards()
    return True


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

                worker_pcb = await attach_worker_pcb(worker)

                worker_uuid = worker.uuid

                logger.info("Registered worker: %s", worker.uuid)
                logger.debug("Worker metadata for %s: %s", worker.uuid, worker.metadata)

                await notify_dashboards()

                ack = RegisterAckMessage(
                    type="register_ack",
                    uuid=worker.uuid,
                    state=worker.state
                )

                await send_json(websocket, ack.model_dump())

                # A worker that just joined (or came back) can take waiting tasks.
                from .jobs import dispatch_pending
                await dispatch_pending()

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

            elif msg_type == "task_results":

                from .jobs import dispatch_pending, handle_task_result
                for item in raw["results"]:
                    await handle_task_result(
                        worker_uuid,
                        UUID(str(item["job_id"])),
                        item["task_id"],
                        item["result"],
                        item.get("attempt"),
                        item.get("execution_time_ms"),
                        dispatch=False,
                    )
                # One dispatch for the whole batch, which also sends the
                # replacement tasks to this worker together.
                await dispatch_pending()

            elif msg_type == "task_error":

                from .jobs import handle_task_error
                await handle_task_error(
                    worker_uuid,
                    UUID(str(raw["job_id"])),
                    raw["task_id"],
                    raw.get("attempt"),
                    str(raw.get("error", "task failed")),
                )

    except WebSocketDisconnect as error:

        logger.info(
            "Worker WebSocket closed: %s (code=%s reason=%r)",
            worker_uuid,
            error.code,
            error.reason,
        )

        if worker_uuid is not None:
            await handle_socket_closed(worker_uuid, websocket)

        else:
            logger.warning("Unknown worker disconnected")
    except Exception:
        logger.error("WebSocket failure for worker %s", worker_uuid, exc_info=True)
        raise
