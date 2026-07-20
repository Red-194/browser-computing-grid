from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes import router
from .websocket import router as websocket_router

app = FastAPI(title="Browser Computing Grid")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(router)
app.include_router(websocket_router)