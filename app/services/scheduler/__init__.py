"""Scheduling algorithms and the registry that picks the active one.

To add an algorithm: write a `Scheduler` subclass (see base.py), then register
it at the bottom of this file. It then shows up in `GET /scheduler` and can be
chosen with the GRID_SCHEDULER environment variable or `PUT /scheduler`.
"""
import logging
import os

from .base import Scheduler

logger = logging.getLogger("grid.scheduler")

DEFAULT_SCHEDULER = "fastest_first"
ENV_VARIABLE = "GRID_SCHEDULER"

_factories: dict = {}
_active: Scheduler | None = None


def register(name: str, factory) -> None:
    _factories[name] = factory


def available() -> list[str]:
    return sorted(_factories)


def build(name: str, **kwargs) -> Scheduler:
    """A new scheduler of that name. Raises KeyError for an unknown name."""
    if name not in _factories:
        raise KeyError(f"unknown scheduler '{name}' (available: {', '.join(available())})")
    return _factories[name](**kwargs)


def active() -> Scheduler:
    """The scheduler in use. Starts from GRID_SCHEDULER, else 'random'."""
    global _active
    if _active is None:
        wanted = os.environ.get(ENV_VARIABLE, DEFAULT_SCHEDULER)
        try:
            _active = build(wanted)
        except KeyError as error:
            logger.warning("%s; using '%s'", error, DEFAULT_SCHEDULER)
            _active = build(DEFAULT_SCHEDULER)
        logger.info("Scheduler: %s", _active.name)
    return _active


def set_active(name: str) -> Scheduler:
    """Switch the scheduler for all later dispatches."""
    global _active
    _active = build(name)
    logger.info("Scheduler switched to %s", _active.name)
    return _active


# --- the algorithms ---------------------------------------------------------
from .boinc import BoincScheduler  # noqa: E402
from .fastest_first import FastestFirstScheduler  # noqa: E402
from .random import RandomScheduler  # noqa: E402
from .round_robin import RoundRobinScheduler  # noqa: E402
from .ucb import UcbScheduler  # noqa: E402

register("random", RandomScheduler)
register("round_robin", RoundRobinScheduler)
register("fastest_first", FastestFirstScheduler)
register("boinc", BoincScheduler)
register("ucb", UcbScheduler)
