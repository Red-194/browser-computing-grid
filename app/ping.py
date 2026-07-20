import asyncio
import time

from .registry import workers


async def ping_workers():

    while True:

        print(f"Workers: {len(workers)}")

        for worker in workers.values():

            if worker.websocket is not None:

                await worker.websocket.send_json({
                    "type": "ping",
                    "timestamp": time.perf_counter()
                })

        await asyncio.sleep(5)