"""Look at and change the scheduler while the server runs.

    GET  /scheduler        which algorithm is active, and which exist
    PUT  /scheduler        {"name": "boinc"} switches it for all later dispatches;
                           {"stealing": false} turns work stealing off
    GET  /scheduler/stats  what has been measured about each worker

Like the rest of the API these have no authentication.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .services import scheduler as scheduler_registry
from .services.scheduler.stats import tracker

router = APIRouter(prefix="/scheduler", tags=["Scheduler"])


class SchedulerChoice(BaseModel):
    name: str | None = None  # leave out to keep the current algorithm
    stealing: bool | None = None  # turn work stealing on or off for it


@router.get("")
async def current():
    return {
        "active": scheduler_registry.active().name,
        "stealing": scheduler_registry.active().speculative,
        "available": scheduler_registry.available(),
    }


@router.put("")
async def switch(choice: SchedulerChoice):
    try:
        scheduler = (
            scheduler_registry.set_active(choice.name)
            if choice.name
            else scheduler_registry.active()
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error.args[0]))
    if choice.stealing is not None:
        scheduler.speculative = choice.stealing
    return {"active": scheduler.name, "stealing": scheduler.speculative, "available": scheduler_registry.available()}


@router.get("/stats")
async def stats():
    return tracker.snapshot()
