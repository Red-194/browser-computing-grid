import uuid

from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

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
                    uuid= str(uuid.uuid4()),
                    ip=websocket.client.host,
                    cores=message["cores"],
                    memory=message["memory"]
                )

                workers[worker.uuid] = worker
                worker_uuid = worker.uuid

                print(f"Registered worker: {worker.uuid}")

                await websocket.send_json({
                    "type": "register_ack",
                    "uuid": worker.uuid
                })

            elif message["type"] == "heartbeat":

                workers[worker_uuid].last_heartbeat = datetime.now()

                print(f"Heartbeat received from {worker_uuid} at {workers[worker_uuid].last_heartbeat}")


    except WebSocketDisconnect:

        if worker_uuid is not None:
            workers.pop(worker_uuid, None)
            print(f"Worker disconnected: {worker_uuid}")

        else:
            print("Unknown worker disconnected.")