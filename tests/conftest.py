import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1])
)

import pytest


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
