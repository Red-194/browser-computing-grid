from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .events import router as events_router
from .routes import router
from .websocket import router as websocket_router

app = FastAPI(title="Browser Computing Grid")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(router)
app.include_router(websocket_router)
app.include_router(events_router)