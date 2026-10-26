"""Edge cases in dispatch: late answers, failed sends, repeated failures."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import jobs
from app.models.pcb import CompletionOutcome, JobPCB, JobStatus, TaskState, WorkerPCB
from app.models.worker import WorkerStates


class RecordingAggregator:
    result_type = "application/json"

    def __init__(self):
        self.results = []

    def add_result(self, result):
        self.results.append(result)

    def get_result(self):
        return b"{}"


@pytest.fixture(autouse=True)
def clean_registries():
    def clear():
        for registry in (
            jobs.workers, jobs.worker_pcbs, jobs.job_pcbs, jobs.job_tasks,
            jobs.aggregators,
        ):
            registry.clear()
        jobs.completed_jobs.clear()

    clear()
    yield
    clear()


def add_job(task_ids=(0,), max_retries=3):
    job_id = uuid4()
    jobs.job_pcbs[str(job_id)] = JobPCB.create(
        job_id, "test", list(task_ids), max_retries=max_retries
    )
    jobs.job_tasks[str(job_id)] = {
        task_id: SimpleNamespace(task_id=task_id) for task_id in task_ids
    }
    jobs.aggregators[str(job_id)] = RecordingAggregator()
    return job_id, jobs.job_pcbs[str(job_id)], jobs.aggregators[str(job_id)]


def add_worker(uuid, capacity=1):
    worker = SimpleNamespace(
        uuid=uuid, ip="x", state=WorkerStates.IDLE, cores=capacity,
        memory=0.0, latency=0, websocket=object(),
    )
    jobs.workers[uuid] = worker
    jobs.worker_pcbs[uuid] = WorkerPCB(uuid, capacity=capacity)
    return worker


def patch_send(monkeypatch, outcome=True):
    sent = []

    async def fake_send(worker, task, attempt=None):
        sent.append((worker.uuid, task.task_id, attempt))
        return outcome

    monkeypatch.setattr(jobs, "send_task", fake_send)
    return sent


# ---------------------------------------------------------- late answers


def test_late_answer_from_a_replaced_attempt_is_ignored(monkeypatch):
    sent = patch_send(monkeypatch)
    job_id, job_pcb, aggregator = add_job()
    add_worker("slow")

    asyncio.run(jobs.dispatch_pending(job_id))
    assert sent == [("slow", 0, 1)]

    # The slow worker is lost and a second worker takes the task over.
    asyncio.run(jobs.handle_worker_failure("slow", "heartbeat timeout"))
    add_worker("fast")
    asyncio.run(jobs.dispatch_pending(job_id))
    assert sent[-1] == ("fast", 0, 2)

    # The slow worker answers anyway, for attempt 1.
    outcome = asyncio.run(
        jobs.handle_task_result("slow", job_id, 0, {"value": "late"}, 1, 5.0)
    )

    assert outcome == CompletionOutcome.STALE
    assert aggregator.results == []  # the late answer was not used
    assert job_pcb.task(0).state == TaskState.RUNNING  # still waiting on "fast"

    outcome = asyncio.run(
        jobs.handle_task_result("fast", job_id, 0, {"value": "good"}, 2, 4.0)
    )

    assert outcome == CompletionOutcome.ACCEPTED
    assert [r["value"] for r in aggregator.results] == ["good"]
    assert job_pcb.status == JobStatus.DONE


def test_answer_with_no_attempt_number_counts_for_the_current_attempt(monkeypatch):
    patch_send(monkeypatch)
    job_id, job_pcb, aggregator = add_job()
    add_worker("w1")
    asyncio.run(jobs.dispatch_pending(job_id))

    asyncio.run(jobs.handle_task_result("w1", job_id, 0, {"value": 1}, None, 1.0))

    assert job_pcb.task(0).state == TaskState.DONE
    assert aggregator.results[0]["_task_id"] == 0
    assert aggregator.results[0]["_execution_time_ms"] == 1.0


def test_answer_for_an_unknown_job_is_dropped_quietly():
    add_worker("w1")
    outcome = asyncio.run(
        jobs.handle_task_result("w1", uuid4(), 0, {"value": 1}, 1, 1.0)
    )
    assert outcome is None


# ------------------------------------------------------- failed delivery


def test_failed_send_is_retried_and_the_job_fails_when_retries_run_out(monkeypatch):
    sent = patch_send(monkeypatch, outcome=False)  # every send fails
    job_id, job_pcb, aggregator = add_job(max_retries=2)
    worker = add_worker("w1")

    asyncio.run(jobs.dispatch_pending(job_id))

    assert len(sent) == 3  # the first try plus 2 retries, then it gives up
    assert job_pcb.task(0).state == TaskState.FAILED
    assert job_pcb.status == JobStatus.FAILED
    assert jobs.worker_pcbs["w1"].running == {}  # no slot is left held
    assert worker.state == WorkerStates.IDLE


def test_send_that_works_on_the_second_try_still_finishes(monkeypatch):
    results = iter([False, True])
    sent = []

    async def flaky_send(worker, task, attempt=None):
        sent.append(attempt)
        return next(results)

    monkeypatch.setattr(jobs, "send_task", flaky_send)
    job_id, job_pcb, aggregator = add_job()
    add_worker("w1")

    asyncio.run(jobs.dispatch_pending(job_id))

    assert sent == [1, 2]
    assert job_pcb.task(0).state == TaskState.RUNNING
    assert job_pcb.task(0).attempt == 2


# ------------------------------------------------------ repeated failures


def test_the_same_worker_loss_reported_twice_counts_once(monkeypatch):
    patch_send(monkeypatch)
    job_id, job_pcb, aggregator = add_job()
    add_worker("w1")
    asyncio.run(jobs.dispatch_pending(job_id))

    asyncio.run(jobs.handle_worker_failure("w1", "heartbeat timeout"))
    asyncio.run(jobs.handle_worker_failure("w1", "worker disconnected"))

    assert job_pcb.task(0).retries == 1
    assert job_pcb.task(0).state == TaskState.WAITING


# -------------------------------------------------------- job status page


def test_job_status_shows_progress():
    job_id, job_pcb, aggregator = add_job(task_ids=(0, 1, 2))
    task = job_pcb.task(0)
    task.complete(task.assign("w1"))

    reply = asyncio.run(jobs.get(job_id))

    assert reply["status"] == "running"
    assert reply["workload"] == "test"
    assert reply["progress"] == {
        "total": 3, "waiting": 2, "running": 0, "done": 1, "failed": 0,
    }


def test_job_status_for_an_unknown_job():
    reply = asyncio.run(jobs.get(uuid4()))
    assert reply["message"] == "Job not found."


# ------------------------------------------------------- splitter timing log


def test_submit_logs_how_long_the_splitter_took(caplog):
    from app.models.jobs import JobSubmission

    job = JobSubmission(workload="nqueens", config={"n": 6, "split_depth": 1})

    with caplog.at_level("DEBUG", logger="grid.jobs"):
        reply = asyncio.run(jobs.submit_job(job))

    messages = [record.getMessage() for record in caplog.records]
    assert any("splitter started (nqueens)" in m for m in messages)
    finished = [m for m in messages if "splitter finished" in m]
    assert len(finished) == 1
    assert f"{reply['task_count']} tasks in" in finished[0]
    assert finished[0].endswith(" s")
