import asyncio
import time

from .registry import workers


async def ping_workers():

    while True:

        for worker in workers.values():

            if worker.websocket is None:
                continue

            try:
                await worker.websocket.send_json({
                    "type": "ping",
                    "timestamp": time.perf_counter()
                })

            except Exception:
                pass

        await asyncio.sleep(5)