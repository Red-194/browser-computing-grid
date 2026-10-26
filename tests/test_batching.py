"""Tasks go to a worker in one message, and the tab's results come back in one."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import jobs, websocket
from app.models.pcb import JobPCB, TaskState, WorkerPCB
from app.models.worker import WorkerStates
from app.services.scheduler.capacity import CapacityPolicy
from app.services.scheduler.stats import SpeedTracker


class RecordingSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


class FakeAggregator:
    result_type = "application/json"

    def __init__(self):
        self.results = []

    def add_result(self, result):
        self.results.append(result)

    def get_result(self):
        return b"{}"


def make_task(task_id):
    return SimpleNamespace(
        task_id=task_id,
        workload="test",
        config=None,
        model_dump=lambda mode="json", task_id=task_id: {"task_id": task_id},
    )


@pytest.fixture
def grid(monkeypatch):
    """One worker with a recording socket and a job of 5 tasks."""
    monkeypatch.setattr(jobs, "send_tasks", websocket.send_tasks)  # the real ones
    monkeypatch.setattr(jobs, "capacity_policy", CapacityPolicy(SpeedTracker()))
    for registry in (jobs.workers, jobs.worker_pcbs, jobs.job_pcbs, jobs.job_tasks, jobs.aggregators):
        registry.clear()

    socket = RecordingSocket()
    worker = SimpleNamespace(
        uuid="w1", state=WorkerStates.IDLE, cores=3, websocket=socket, ip="x", latency=1, memory=0
    )
    job_id = uuid4()
    job_pcb = JobPCB.create(job_id, "test", [0, 1, 2, 3, 4])
    jobs.workers["w1"] = worker
    jobs.worker_pcbs["w1"] = WorkerPCB("w1", capacity=3)
    jobs.job_pcbs[str(job_id)] = job_pcb
    jobs.job_tasks[str(job_id)] = {i: make_task(i) for i in range(5)}
    jobs.aggregators[str(job_id)] = FakeAggregator()
    yield SimpleNamespace(socket=socket, job_id=job_id, job=job_pcb)
    for registry in (jobs.workers, jobs.worker_pcbs, jobs.job_pcbs, jobs.job_tasks, jobs.aggregators):
        registry.clear()


def test_everything_claimed_for_a_worker_goes_in_one_message(grid):
    asyncio.run(jobs.dispatch_pending(grid.job_id))

    assert len(grid.socket.sent) == 1
    message = grid.socket.sent[0]
    assert message["type"] == "tasks"
    assert [t["task_id"] for t in message["tasks"]] == [0, 1, 2]
    assert [t["attempt"] for t in message["tasks"]] == [1, 1, 1]
    assert all(grid.job.task(i).state == TaskState.RUNNING for i in (0, 1, 2))


def test_a_single_task_still_uses_the_plain_message(grid):
    jobs.worker_pcbs["w1"].capacity = 1
    asyncio.run(jobs.dispatch_pending(grid.job_id))
    # the capacity policy sizes slots from cores, so one thread -> one slot
    jobs.workers["w1"].cores = 1
    jobs.worker_pcbs["w1"].running.clear()
    for i in range(5):
        task = grid.job.task(i)
        if task.state == TaskState.RUNNING:
            task.requeue("reset", attempt=task.attempt)
    grid.socket.sent.clear()

    asyncio.run(jobs.dispatch_pending(grid.job_id))

    assert len(grid.socket.sent) == 1
    assert grid.socket.sent[0]["type"] == "task"


def test_a_batch_of_results_is_accepted_with_one_dispatch(grid, monkeypatch):
    asyncio.run(jobs.dispatch_pending(grid.job_id))
    grid.socket.sent.clear()
    dispatches = []

    async def counting_dispatch(job_id=None):
        dispatches.append(job_id)
        return []

    monkeypatch.setattr(jobs, "dispatch_pending", counting_dispatch)

    for task_id in (0, 1, 2):
        outcome = asyncio.run(
            jobs.handle_task_result("w1", grid.job_id, task_id, {"v": task_id}, 1, 5.0, dispatch=False)
        )
        assert outcome is not None

    assert dispatches == []  # the caller dispatches once for the whole batch
    assert grid.job.count(TaskState.DONE) == 3
    assert jobs.worker_pcbs["w1"].running == {}
