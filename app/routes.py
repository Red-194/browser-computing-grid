from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from .registry import workers
from .services.request_utils import is_localhost

router = APIRouter()

templates = Jinja2Templates(directory="app/templates")


@router.get("/")
async def root(request: Request):

    if is_localhost(request):
        return RedirectResponse("/dashboard")

    return RedirectResponse("/worker")


@router.get("/dashboard")
async def dashboard(request: Request):

    if not is_localhost(request):
        return RedirectResponse("/worker")

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={}
    )


@router.get("/worker")
async def worker(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="worker.html",
        context={}
    )


@router.post("/disconnect/{worker_uuid}")
async def disconnect(worker_uuid: str):

    worker = workers.get(worker_uuid)

    if worker is None or worker.websocket is None:
        return {"success": False}

    await worker.websocket.close()
    return {"success": True}