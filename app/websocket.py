import math
import time
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .events import notify_dashboards
from .models.protocol import HeartbeatMessage, PongMessage, RegisterAckMessage, RegisterMessage
from .models.worker import Worker, WorkerMetadata, WorkerStates
from .registry import workers

router = APIRouter()


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

                print(f"Registered worker: {worker.uuid}")
                print(f"Worker metadata: {worker.metadata}")

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
                print(
                    f"Heartbeat received from {worker.uuid} "
                    f"at {worker.last_heartbeat}"
                )

            elif msg_type == "pong":

                message = PongMessage.model_validate(raw)
                worker = workers.get(worker_uuid)

                if worker is None:
                    continue

                latency = (time.perf_counter() - message.timestamp) * 1000
                worker.latency = math.ceil(latency)

                print(
                    f"Latency {worker.uuid}: "
                    f"{worker.latency} ms"
                )

                await notify_dashboards()

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