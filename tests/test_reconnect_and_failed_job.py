"""A reloading tab must not break its worker, and a failed job must say so."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import jobs, websocket
from app.models.pcb import JobPCB, JobStatus, TaskState, WorkerPCB
from app.models.worker import WorkerStates


class FakeAggregator:
    result_type = "application/json"

    def get_result(self):
        return b"{}"

    def add_result(self, result):
        pass


@pytest.fixture(autouse=True)
def clean_registries():
    for registry in (
        jobs.workers, jobs.worker_pcbs, jobs.job_pcbs, jobs.job_tasks,
        jobs.aggregators,
    ):
        registry.clear()
    jobs.completed_jobs.clear()
    yield
    for registry in (
        jobs.workers, jobs.worker_pcbs, jobs.job_pcbs, jobs.job_tasks,
        jobs.aggregators,
    ):
        registry.clear()
    jobs.completed_jobs.clear()


def add_job(task_ids=(0, 1), max_retries=3):
    job_id = uuid4()
    job_pcb = JobPCB.create(job_id, "test", list(task_ids), max_retries=max_retries)
    jobs.job_pcbs[str(job_id)] = job_pcb
    jobs.job_tasks[str(job_id)] = {
        task_id: SimpleNamespace(task_id=task_id) for task_id in task_ids
    }
    jobs.aggregators[str(job_id)] = FakeAggregator()
    return job_id, job_pcb


def add_worker(uuid="w1", socket=None, cores=2):
    worker = SimpleNamespace(
        uuid=uuid, ip="127.0.0.1", state=WorkerStates.IDLE, cores=cores,
        memory=0.0, latency=5, websocket=socket,
    )
    jobs.workers[uuid] = worker
    jobs.worker_pcbs[uuid] = WorkerPCB(uuid, capacity=cores)
    return worker, jobs.worker_pcbs[uuid]


def give_task(job_pcb, worker_pcb, task_id=0):
    task = job_pcb.task(task_id)
    attempt = task.assign(worker_pcb.uuid)
    worker_pcb.assign(task.key, attempt)
    return task


# ------------------------------------------------------- failed job result


def test_failed_job_says_it_failed_instead_of_still_processing():
    job_id, job_pcb = add_job(task_ids=(0, 1), max_retries=0)
    task = job_pcb.task(0)
    task.assign("w1")
    task.requeue("heartbeat timeout")  # no retries left, so the task fails

    reply = asyncio.run(jobs.result(job_id))

    assert reply["message"] == "Job failed."
    assert reply["status"] == "failed"
    assert reply["failed_tasks"] == [
        {"task_id": 0, "retries": 0, "error": "heartbeat timeout"}
    ]


def test_running_job_still_says_still_processing():
    job_id, job_pcb = add_job()
    reply = asyncio.run(jobs.result(job_id))
    assert reply == {"message": "Job is still processing.", "job_id": job_id}


def test_finished_job_returns_the_aggregated_result():
    job_id, job_pcb = add_job(task_ids=(0,))
    task = job_pcb.task(0)
    task.complete(task.assign("w1"))
    assert job_pcb.status == JobStatus.DONE

    reply = asyncio.run(jobs.result(job_id))

    assert reply.body == b"{}"
    assert reply.media_type == "application/json"


def test_failed_job_reply_lists_at_most_ten_tasks():
    job_id, job_pcb = add_job(task_ids=range(25), max_retries=0)
    for task in job_pcb.tasks.values():
        task.assign("w1")
        task.requeue("lost")

    reply = asyncio.run(jobs.result(job_id))

    assert len(reply["failed_tasks"]) == 10


# ----------------------------------------------- old socket closing late


def test_late_close_of_an_old_socket_leaves_the_live_worker_alone():
    old_socket, new_socket = object(), object()
    worker, worker_pcb = add_worker(socket=new_socket)  # already reconnected
    job_id, job_pcb = add_job()
    task = give_task(job_pcb, worker_pcb)

    handled = asyncio.run(websocket.handle_socket_closed("w1", old_socket))

    assert handled is False
    assert worker.websocket is new_socket  # the new connection is kept
    assert worker_pcb.is_online
    assert task.state == TaskState.RUNNING  # nothing was requeued


def test_close_of_the_current_socket_requeues_the_workers_tasks():
    socket = object()
    worker, worker_pcb = add_worker(socket=socket)
    job_id, job_pcb = add_job()
    task = give_task(job_pcb, worker_pcb)

    handled = asyncio.run(websocket.handle_socket_closed("w1", socket))

    assert handled is True
    assert worker.websocket is None
    assert not worker_pcb.is_online
    assert task.state == TaskState.WAITING
    assert task.retries == 1


def test_close_for_a_worker_that_is_not_registered_is_ignored():
    assert asyncio.run(websocket.handle_socket_closed("ghost", object())) is False


# ---------------------------------------------------- re-registering


def test_first_registration_creates_a_control_block_sized_by_cores():
    worker = SimpleNamespace(
        uuid="new", ip="x", state=WorkerStates.IDLE, cores=4,
        memory=0.0, latency=0, websocket=object(),
    )
    jobs.workers["new"] = worker

    worker_pcb = asyncio.run(websocket.attach_worker_pcb(worker))

    assert jobs.worker_pcbs["new"] is worker_pcb
    assert worker_pcb.capacity == 4
    assert worker_pcb.is_online
    assert worker.state == WorkerStates.IDLE


def test_reloaded_tab_gets_its_lost_tasks_requeued_and_comes_back_idle():
    worker, worker_pcb = add_worker(socket=object())
    job_id, job_pcb = add_job()
    task = give_task(job_pcb, worker_pcb)
    assert worker_pcb.running

    # The tab reloads: it registers again under the same uuid.
    worker.websocket = object()
    asyncio.run(websocket.attach_worker_pcb(worker))

    assert task.state == TaskState.WAITING  # the old session's task is requeued
    assert task.retries == 1
    assert worker_pcb.running == {}
    assert worker_pcb.is_online
    assert worker.state == WorkerStates.IDLE


def test_waiting_tasks_go_to_a_worker_that_just_registered(monkeypatch):
    sent = []

    async def fake_send(worker, task, attempt=None):
        sent.append((worker.uuid, task.task_id, attempt))
        return True

    monkeypatch.setattr(jobs, "send_task", fake_send)
    job_id, job_pcb = add_job(task_ids=(0,))
    worker, worker_pcb = add_worker(socket=object())
    task = give_task(job_pcb, worker_pcb)

    # The only worker reloads; its task is requeued, then it registers again.
    worker.websocket = object()
    asyncio.run(websocket.attach_worker_pcb(worker))
    assert task.state == TaskState.WAITING
    asyncio.run(jobs.dispatch_pending())

    assert sent == [("w1", 0, 2)]  # the second attempt, on the returned worker
    assert task.state == TaskState.RUNNING
    assert task.attempt == 2
