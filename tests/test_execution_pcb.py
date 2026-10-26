import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.services.scheduler.capacity import CapacityPolicy
from app.services.scheduler.stats import SpeedTracker
from app import jobs
from app.models.pcb import JobPCB, TaskState, WorkerPCB
from app.models.worker import WorkerStates


class FakeAggregator:
    result_type = "application/json"

    def __init__(self):
        self.results = []

    def add_result(self, result):
        self.results.append(result)


def setup_execution(monkeypatch, capacity=1):
    job_id = uuid4()
    job_pcb = JobPCB.create(job_id, "test", [0, 1, 2])
    worker = SimpleNamespace(uuid="worker-1", state=WorkerStates.IDLE, cores=capacity)
    payloads = {
        task_id: SimpleNamespace(
            task_id=task_id,
            model_dump=lambda mode="json", task_id=task_id: {"task_id": task_id},
        )
        for task_id in job_pcb.tasks
    }
    sent = []

    async def fake_send(worker, task, attempt=None):
        sent.append((task.task_id, attempt))
        return True

    monkeypatch.setattr(jobs, "send_task", fake_send)
    # A fresh tracker, so speeds other tests taught the shared one cannot change the slots.
    monkeypatch.setattr(jobs, "capacity_policy", CapacityPolicy(SpeedTracker()))
    jobs.workers.clear()
    jobs.worker_pcbs.clear()
    jobs.job_pcbs.clear()
    jobs.job_tasks.clear()
    jobs.aggregators.clear()
    jobs.completed_jobs.clear()
    jobs.workers[worker.uuid] = worker
    jobs.worker_pcbs[worker.uuid] = WorkerPCB(worker.uuid, capacity=capacity)
    jobs.job_pcbs[str(job_id)] = job_pcb
    jobs.job_tasks[str(job_id)] = payloads
    jobs.aggregators[str(job_id)] = FakeAggregator()
    return job_id, job_pcb, worker, sent


def test_dispatch_respects_capacity_and_releases_slot(monkeypatch):
    job_id, job_pcb, worker, sent = setup_execution(monkeypatch, capacity=1)

    asyncio.run(jobs.dispatch_pending(job_id))
    assert sent == [(0, 1)]
    assert job_pcb.task(0).state == TaskState.RUNNING
    assert job_pcb.task(1).state == TaskState.WAITING
    assert worker.state == WorkerStates.BUSY

    asyncio.run(
        jobs.handle_task_result(worker.uuid, job_id, 0, {"value": 1}, 1, 2.5)
    )
    assert job_pcb.task(0).state == TaskState.DONE
    assert job_pcb.task(1).state == TaskState.RUNNING
    assert jobs.worker_pcbs[worker.uuid].running[(job_id, 1)] == 1
    assert worker.state == WorkerStates.BUSY


def test_worker_failure_requeues_running_task(monkeypatch):
    job_id, job_pcb, worker, sent = setup_execution(monkeypatch, capacity=1)

    asyncio.run(jobs.dispatch_pending(job_id))
    asyncio.run(jobs.handle_worker_failure(worker.uuid, "worker disconnected"))

    task = job_pcb.task(0)
    assert task.state == TaskState.WAITING
    assert task.retries == 1
    assert task.attempt == 1
    assert jobs.worker_pcbs[worker.uuid].state == WorkerStates.OFFLINE
    assert worker.state == WorkerStates.OFFLINE
