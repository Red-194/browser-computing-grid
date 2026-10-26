"""The scheduler working inside the controller: dispatch, timeouts and endpoints."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import jobs
from app.main import app
from app.models.pcb import CompletionOutcome, JobPCB, JobStatus, TaskPCB, TaskState, WorkerPCB
from app.models.worker import WorkerStates
from app.services import scheduler as registry
from app.services.scheduler import reallocation
from app.services.scheduler.stats import tracker as global_tracker, SpeedTracker


class RecordingAggregator:
    result_type = "application/json"

    def __init__(self):
        self.results = []

    def add_result(self, result):
        self.results.append(result)

    def get_result(self):
        return b"{}"


@pytest.fixture(autouse=True)
def clean_state():
    def clear():
        for store in (jobs.workers, jobs.worker_pcbs, jobs.job_pcbs, jobs.job_tasks,
                      jobs.aggregators):
            store.clear()
        jobs.completed_jobs.clear()
        global_tracker.reset()
        registry.set_active("random")

    clear()
    yield
    clear()


def add_job(count, workload="job", cost_units=1.0, max_retries=3):
    job_id = uuid4()
    jobs.job_pcbs[str(job_id)] = JobPCB.create(
        job_id, workload, list(range(count)), max_retries=max_retries
    )
    # Tasks shaped like the real ones for the "compression" cost estimate (3 bytes per 4 chars).
    jobs.job_tasks[str(job_id)] = {
        i: SimpleNamespace(
            task_id=i,
            workload="compression",
            config=SimpleNamespace(data_base64="A" * int(cost_units * 4 / 3)),
        )
        for i in range(count)
    }
    jobs.aggregators[str(job_id)] = RecordingAggregator()
    return job_id, jobs.job_pcbs[str(job_id)], jobs.aggregators[str(job_id)]


def add_worker(uuid, cores=4):
    worker = SimpleNamespace(
        uuid=uuid, ip="x", state=WorkerStates.IDLE, cores=cores, memory=0.0,
        latency=0, websocket=object(),
    )
    jobs.workers[uuid] = worker
    jobs.worker_pcbs[uuid] = WorkerPCB(uuid, capacity=cores)
    return worker


def patch_send(monkeypatch):
    sent = []

    async def fake_send(worker, task, attempt=None):
        sent.append((worker.uuid, task.task_id, attempt))
        return True

    monkeypatch.setattr(jobs, "send_task", fake_send)
    return sent


def teach(worker, seconds_per_task, workload="job"):
    for _ in range(3):
        global_tracker.record_result(worker, workload, 1.0, seconds_per_task)


# ---------------------------------------------------- dispatch with a scheduler


def test_dispatch_uses_the_active_scheduler_and_the_measured_speeds(monkeypatch):
    sent = patch_send(monkeypatch)
    registry.set_active("boinc")
    add_worker("fast")
    add_worker("slow")
    teach("fast", 0.1)
    teach("slow", 2.0)
    job_id, job_pcb, _ = add_job(6)

    asyncio.run(jobs.dispatch_pending(job_id))

    per_worker = {w: sum(1 for who, _, _ in sent if who == w) for w in ("fast", "slow")}
    assert per_worker["fast"] > per_worker["slow"]
    # Each of a worker's 4 threads holds one slow task, but up to 4 fast ones.
    assert jobs.worker_pcbs["slow"].capacity == 4
    # 2 s of 0.1 s tasks would be 20 per thread, but only 6 tasks are left for 8 threads.
    assert jobs.worker_pcbs["fast"].capacity == 4 * 1


def test_switching_scheduler_changes_how_the_next_job_is_spread(monkeypatch):
    patch_send(monkeypatch)
    add_worker("fast")
    add_worker("slow")
    teach("fast", 0.1)
    teach("slow", 0.1)  # equal speed, so only the algorithm differs

    registry.set_active("round_robin")
    job_id, job_pcb, _ = add_job(4)
    assignments = asyncio.run(jobs.dispatch_pending(job_id))

    assert sorted(a["worker"] for a in assignments) == ["fast", "fast", "slow", "slow"]


def test_an_accepted_result_teaches_the_tracker(monkeypatch):
    patch_send(monkeypatch)
    add_worker("w1")
    job_id, job_pcb, aggregator = add_job(1, cost_units=300)
    asyncio.run(jobs.dispatch_pending(job_id))

    outcome = asyncio.run(
        jobs.handle_task_result("w1", job_id, 0, {"value": 1}, 1, execution_time_ms=1500.0)
    )

    assert outcome == CompletionOutcome.ACCEPTED
    assert global_tracker.samples("w1", "job") == 1
    rate = global_tracker.snapshot()["workers"]["w1"]["workloads"]["job"]["seconds_per_unit"]
    assert rate == pytest.approx(1.5 / 300, rel=0.05)  # 1.5 s for about 300 bytes


def test_a_result_without_a_time_is_accepted_but_teaches_nothing(monkeypatch):
    patch_send(monkeypatch)
    add_worker("w1")
    job_id, job_pcb, _ = add_job(1)
    asyncio.run(jobs.dispatch_pending(job_id))

    asyncio.run(jobs.handle_task_result("w1", job_id, 0, {}, 1, execution_time_ms=None))

    assert job_pcb.status == JobStatus.DONE
    assert global_tracker.samples("w1", "job") == 0


def test_losing_a_worker_that_held_tasks_counts_against_it(monkeypatch):
    patch_send(monkeypatch)
    add_worker("w1")
    job_id, job_pcb, _ = add_job(2)
    asyncio.run(jobs.dispatch_pending(job_id))

    asyncio.run(jobs.handle_worker_failure("w1", "worker disconnected"))

    assert global_tracker.reliability("w1") < 1.0


def test_a_worker_that_held_nothing_is_not_blamed_for_leaving(monkeypatch):
    patch_send(monkeypatch)
    add_worker("w1")

    asyncio.run(jobs.handle_worker_failure("w1", "worker disconnected"))

    assert global_tracker.reliability("w1") == 1.0


# ------------------------------------------------------------- timeouts


def running_task(count=1, worker="w1", now=0.0):
    """A job whose first `count` tasks are running on `worker` since `now`."""
    job_id, job_pcb, aggregator = add_job(count)
    worker_pcb = jobs.worker_pcbs.get(worker) or WorkerPCB(worker, capacity=8)
    jobs.worker_pcbs[worker] = worker_pcb
    for task in list(job_pcb.tasks.values())[:count]:
        attempt = task.assign(worker, now=now)
        worker_pcb.assign(task.key, attempt)
    return job_id, job_pcb, worker_pcb, aggregator


def test_the_deadline_is_generous_without_data_and_follows_measured_speed():
    tracker = SpeedTracker()
    task = TaskPCB(uuid4(), 0, "job")
    task.assign("w1", now=0.0)
    pcb = WorkerPCB("w1")
    pcb.assign(task.key, 1)

    assert reallocation.deadline_seconds(task, pcb, 1.0, tracker) == reallocation.DEFAULT_TIMEOUT

    for _ in range(3):
        tracker.record_result("w1", "job", 1.0, 2.0)  # 2 s per task, no spread
    assert reallocation.deadline_seconds(task, pcb, 1.0, tracker) == reallocation.MIN_TIMEOUT

    slow = SpeedTracker()
    for seconds in (20, 20, 20):
        slow.record_result("w1", "job", 1.0, seconds)
    assert reallocation.deadline_seconds(task, pcb, 1.0, slow) == pytest.approx(
        20 * reallocation.SAFETY_FACTOR
    )


def test_a_task_queued_behind_others_is_allowed_more_time():
    tracker = SpeedTracker()
    task = TaskPCB(uuid4(), 0, "job")
    task.assign("w1", now=0.0)
    alone = WorkerPCB("w1")
    alone.assign(task.key, 1)
    crowded = WorkerPCB("w1", capacity=8)
    for i in range(3):
        crowded.assign((uuid4(), i), 1)

    assert reallocation.deadline_seconds(task, crowded, 1.0, tracker) == 3 * (
        reallocation.deadline_seconds(task, alone, 1.0, tracker)
    )


def test_only_tasks_past_their_deadline_are_found():
    job_id, job_pcb, worker_pcb, _ = running_task(count=1, now=0.0)
    limit = reallocation.DEFAULT_TIMEOUT
    find = lambda now: reallocation.find_timed_out(
        [job_pcb], jobs.worker_pcbs, lambda t: 1.0, global_tracker, now
    )

    assert find(limit - 1) == []
    assert [t.task_id for t in find(limit + 1)] == [0]


def test_taking_back_requeues_frees_the_slot_and_marks_the_worker():
    job_id, job_pcb, worker_pcb, _ = running_task(count=1, now=0.0)
    task = job_pcb.task(0)

    assert reallocation.take_back(task, jobs.worker_pcbs, global_tracker, now=100.0) is True

    assert task.state == TaskState.WAITING
    assert task.retries == 1
    assert worker_pcb.running == {}
    assert global_tracker.snapshot()["workers"]["w1"]["timeouts"] == 1
    # A second report for the same loss (another event got there first) does nothing.
    assert reallocation.take_back(task, jobs.worker_pcbs, global_tracker, now=100.0) is False
    assert task.retries == 1


def test_the_monitor_reassigns_a_stuck_task_and_ignores_the_late_answer(monkeypatch):
    sent = patch_send(monkeypatch)
    registry.set_active("fastest_first")
    add_worker("stuck")
    job_id, job_pcb, aggregator = add_job(1)
    asyncio.run(jobs.dispatch_pending(job_id))
    assert sent == [("stuck", 0, 1)]
    add_worker("healthy")  # joins later

    started = job_pcb.task(0).assigned_at
    taken = asyncio.run(
        reallocation.TimeoutMonitor().check_once(now=started + reallocation.DEFAULT_TIMEOUT + 1)
    )

    assert taken == 1
    assert sent[-1] == ("healthy", 0, 2)  # the quarantine is not needed yet; "healthy" is faster to pick
    assert jobs.worker_pcbs["stuck"].running == {}

    # The stuck worker finally answers for attempt 1: ignored.
    late = asyncio.run(jobs.handle_task_result("stuck", job_id, 0, {"v": "late"}, 1, 5.0))
    assert late == CompletionOutcome.STALE
    assert aggregator.results == []

    done = asyncio.run(jobs.handle_task_result("healthy", job_id, 0, {"v": "ok"}, 2, 5.0))
    assert done == CompletionOutcome.ACCEPTED
    assert job_pcb.status == JobStatus.DONE


def test_a_worker_that_times_out_repeatedly_is_left_out_of_adaptive_scheduling(monkeypatch):
    patch_send(monkeypatch)
    registry.set_active("boinc")
    add_worker("stuck")
    add_worker("healthy")
    job_id, job_pcb, _ = add_job(1, max_retries=10)

    for _ in range(3):
        task = job_pcb.task(0)
        if task.state == TaskState.WAITING:
            task.assign("stuck")
            jobs.worker_pcbs["stuck"].assign(task.key, task.attempt)
        reallocation.take_back(task, jobs.worker_pcbs, global_tracker)  # real clock

    assert global_tracker.is_quarantined("stuck")
    assignments = asyncio.run(jobs.dispatch_pending(job_id))
    assert [a["worker"] for a in assignments] == ["healthy"]


def test_the_monitor_does_nothing_when_nothing_is_late(monkeypatch):
    patch_send(monkeypatch)
    add_worker("w1")
    job_id, job_pcb, _ = add_job(2)
    asyncio.run(jobs.dispatch_pending(job_id))
    started = job_pcb.task(0).assigned_at

    assert asyncio.run(reallocation.TimeoutMonitor().check_once(now=started + 1)) == 0


def test_the_monitor_dispatches_a_job_whose_tasks_are_waiting_with_nothing_running(monkeypatch):
    sent = patch_send(monkeypatch)
    registry.set_active("boinc")
    add_worker("only")
    teach("only", 0.5)
    job_id, job_pcb, _ = add_job(2)
    assert job_pcb.count(TaskState.RUNNING) == 0 and job_pcb.count(TaskState.WAITING) == 2

    asyncio.run(reallocation.TimeoutMonitor().check_once(now=1.0))

    assert {task_id for _, task_id, _ in sent} == {0, 1}


# ----------------------------------------------------------------- endpoints


def test_scheduler_endpoints_list_switch_and_reject_unknown_names():
    client = TestClient(app)

    listing = client.get("/scheduler").json()
    assert listing["active"] == "random"
    assert "boinc" in listing["available"]

    switched = client.put("/scheduler", json={"name": "boinc"})
    assert switched.status_code == 200
    assert client.get("/scheduler").json()["active"] == "boinc"

    refused = client.put("/scheduler", json={"name": "nonsense"})
    assert refused.status_code == 404
    assert "nonsense" in refused.json()["detail"]
    assert client.get("/scheduler").json()["active"] == "boinc"  # unchanged


def test_stats_endpoint_shows_what_was_measured():
    teach("w1", 0.5)
    global_tracker.record_timeout("w1")

    stats = TestClient(app).get("/scheduler/stats").json()

    assert stats["workers"]["w1"]["workloads"]["job"]["samples"] == 3
    assert stats["workers"]["w1"]["timeouts"] == 1
    assert stats["workloads"]["job"]["samples"] == 3


# ------------------------------------------------ two dispatches at the same time


def test_two_dispatches_running_together_never_hand_out_a_task_twice(monkeypatch):
    # A result arriving while tasks are being sent starts a second dispatch.
    sent = []

    async def slow_send(worker, task, attempt=None):
        await asyncio.sleep(0)  # lets the other dispatch run in the middle of this one
        sent.append((task.task_id, attempt))
        return True

    monkeypatch.setattr(jobs, "send_task", slow_send)
    add_worker("w1", cores=8)
    teach("w1", 0.001)  # fast tasks, so the worker gets all eight slots
    job_id, job_pcb, _ = add_job(6)

    async def both():
        return await asyncio.gather(jobs.dispatch_pending(job_id), jobs.dispatch_pending(job_id))

    asyncio.run(both())

    assert sorted(task_id for task_id, _ in sent) == [0, 1, 2, 3, 4, 5]  # each exactly once
    assert all(attempt == 1 for _, attempt in sent)
    assert job_pcb.count(TaskState.RUNNING) == 6
