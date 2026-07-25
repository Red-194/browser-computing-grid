from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .events import router as events_router
from .monitoring import ping_workers, monitor_heartbeats
from .routes import router
from .websocket import router as websocket_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    background_tasks = [
        asyncio.create_task(ping_workers()),
        asyncio.create_task(monitor_heartbeats()),
    ]
    try:
        yield
    finally:
        for task in background_tasks:
            task.cancel()
        await asyncio.gather(*background_tasks, return_exceptions=True)


app = FastAPI(
    title="Browser Computing Grid",
    lifespan=lifespan
)

app.mount(
    "/static",
    StaticFiles(directory="app/static"),
    name="static"
)

app.include_router(router)
app.include_router(websocket_router)
app.include_router(events_router)