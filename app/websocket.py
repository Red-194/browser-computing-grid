import uuid, time
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .events import notify_dashboards
from .models import Worker
from .registry import workers

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):

    await websocket.accept()

    print("Worker connected.")

    worker_uuid = None

    try:

        while True:

            message = await websocket.receive_json()

            if message["type"] == "register":

                worker = Worker(
                    uuid=str(uuid.uuid4()),
                    ip=websocket.client.host,
                    cores=message["cores"],
                    memory=message["memory"],
                    websocket=websocket
                )

                print(worker.websocket)

                worker.last_heartbeat = datetime.now()

                workers[worker.uuid] = worker
                worker_uuid = worker.uuid

                print(f"Registered worker: {worker.uuid}")

                await notify_dashboards()

                await websocket.send_json({
                    "type": "register_ack",
                    "uuid": worker.uuid
                })

            elif message["type"] == "heartbeat":

                workers[worker_uuid].last_heartbeat = datetime.now()

                print(
                    f"Heartbeat received from {worker_uuid} "
                    f"at {workers[worker_uuid].last_heartbeat}"
                )

            elif message["type"] == "pong":

                latency = (time.perf_counter() - message["timestamp"]) * 1000

                workers[worker_uuid].latency = round(latency, 1)

                print(
                    f"Latency {worker_uuid}: "
                    f"{workers[worker_uuid].latency} ms"
                )

                await notify_dashboards()

    except WebSocketDisconnect:

        if worker_uuid is not None:

            workers.pop(worker_uuid, None)

            print(f"Worker disconnected: {worker_uuid}")

            await notify_dashboards()

        else:

            print("Unknown worker disconnected.")