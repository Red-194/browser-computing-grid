import sys
from importlib.util import find_spec
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1])
)

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def test_client_uses_uvloop_when_available(monkeypatch):
    """Use the same event loop as Uvicorn on Linux during in-process requests.

    The default asyncio portal can fail to wake from TestClient's calling
    thread in constrained Linux environments. Uvicorn selects uvloop when it
    is installed, so use that backend for tests as well. Windows has no uvloop
    dependency and keeps AnyIO's normal asyncio backend.
    """
    if find_spec("uvloop") is None:
        return

    original_init = TestClient.__init__

    def init_with_uvloop(self, *args, **kwargs):
        kwargs.setdefault("backend_options", {"use_uvloop": True})
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(TestClient, "__init__", init_with_uvloop)


@pytest.fixture(autouse=True)
def batched_sends_go_through_send_task(monkeypatch):
    """Tests fake `jobs.send_task`; make a batched send use it task by task."""
    from app import jobs

    async def forward(worker, items):
        for task, attempt in items:
            if await jobs.send_task(worker, task, attempt=attempt) is False:
                return False
        return True

    monkeypatch.setattr(jobs, "send_tasks", forward)
