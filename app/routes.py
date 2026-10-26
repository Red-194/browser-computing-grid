from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from .registry import workers
from .websocket import send_json
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


from .events import notify_dashboards

@router.post("/disconnect/{worker_uuid}")
async def disconnect(worker_uuid: str, reconnect: bool = False):
    """Disconnect a worker.

    By default the tab is told not to reconnect, so it stays gone until its
    page is reloaded. With ?reconnect=true it reconnects after a few seconds,
    which imitates a network blip.
    """

    worker = workers.get(worker_uuid)

    if worker is None:
        return {"success": False}

    # Offline -> Remove
    if worker.websocket is None:
        workers.pop(worker_uuid, None)
        await notify_dashboards()
        return {"success": True}

    # Online -> Disconnect. Tell the tab first, or it would reconnect by itself.
    try:
        await send_json(worker.websocket, {"type": "disconnect", "reconnect": reconnect})
    except Exception:
        pass  # the socket may already be dead; closing it below is what matters
    await worker.websocket.close()
    return {"success": True}