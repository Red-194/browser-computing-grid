import asyncio
import time
from datetime import datetime, timedelta

from app.events import notify_dashboards

from .models.protocol import PingMessage
from .models.worker import WorkerStates
from .registry import workers

HEARTBEAT_TIMEOUT = 15


async def ping_workers():

    while True:

        for worker in list(workers.values()):

            if worker.websocket is None:
                continue

            try:

                ping = PingMessage(
                    type="ping",
                    timestamp=time.perf_counter()
                )

                await worker.websocket.send_json(
                    ping.model_dump()
                )

            except Exception as e:
                print(f"Failed to ping worker {worker.uuid}: {e}")

        await asyncio.sleep(5)


async def monitor_heartbeats():

    while True:

        now = datetime.now()

        for worker in list(workers.values()):

            if worker.websocket is None:
                continue

            if now - worker.last_heartbeat > timedelta(seconds=HEARTBEAT_TIMEOUT):

                print(f"Heartbeat timeout: {worker.uuid}")

                try:
                    await worker.websocket.close()

                except Exception as e:
                    print(f"Failed to close worker {worker.uuid}: {e}")

        await asyncio.sleep(1)