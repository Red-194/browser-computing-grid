import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from .registry import workers

router = APIRouter()

subscribers: list[asyncio.Queue] = []


async def notify_dashboards():

    payload = json.dumps([
        {
            "uuid": worker.uuid,
            "ip": worker.ip,
            "state": worker.state,
            "cores": worker.cores,
            "memory": worker.memory,
            "latency": worker.latency
        }

        for worker in workers.values()
    ])

    for queue in subscribers:
        await queue.put(payload)


@router.get("/events")
async def events():

    queue = asyncio.Queue()

    subscribers.append(queue)

    async def event_stream():

        try:

            await notify_dashboards()

            while True:

                payload = await queue.get()

                yield f"data: {payload}\n\n"

        finally:

            subscribers.remove(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )