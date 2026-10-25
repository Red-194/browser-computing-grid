import asyncio
import logging
import time
from datetime import datetime, timedelta

from app.events import notify_dashboards

from .models.protocol import PingMessage
from .models.worker import WorkerStates
from .registry import workers

HEARTBEAT_TIMEOUT = 15
logger = logging.getLogger("grid.monitoring")


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
                logger.error("Failed to ping worker %s: %s", worker.uuid, e)

        await asyncio.sleep(5)


async def monitor_heartbeats():

    while True:

        now = datetime.now()

        for worker in list(workers.values()):

            if worker.websocket is None:
                continue

            if now - worker.last_heartbeat > timedelta(seconds=HEARTBEAT_TIMEOUT):

                logger.warning("Heartbeat timeout: %s", worker.uuid)
                from .jobs import handle_worker_failure
                await handle_worker_failure(worker.uuid, "heartbeat timeout")

                try:
                    await worker.websocket.close()

                except Exception as e:
                    logger.error("Failed to close worker %s: %s", worker.uuid, e)

        await asyncio.sleep(1)