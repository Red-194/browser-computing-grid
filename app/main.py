from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .events import router as events_router
from .ping import ping_workers
from .routes import router
from .websocket import router as websocket_router


@asynccontextmanager
async def lifespan(app: FastAPI):

    asyncio.create_task(ping_workers())

    yield


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