"""Work stealing: an idle worker also runs a task that is still running elsewhere."""
from types import SimpleNamespace
from uuid import uuid4

from app.models.pcb import CompletionOutcome, JobPCB, TaskState, WorkerPCB
from app.services.scheduler.fastest_first import FastestFirstScheduler
from app.services.scheduler.random import RandomScheduler
from app.services.scheduler.stats import SpeedTracker


def running_task(worker="A", now=0.0):
    job = JobPCB.create(uuid4(), "test", [0])
    task = job.task(0)
    task.assign(worker, now=now)
    return task


# ---------------------------------------------------------------- the PCB

def test_first_answer_wins_and_the_other_is_stale():
    task = running_task("A")
    copy = task.assign_backup("B")
    assert copy != task.attempt and task.holders() == [("A", 1), ("B", copy)]

    assert task.complete(copy, worker_uuid="B") == CompletionOutcome.ACCEPTED
    assert task.state == TaskState.DONE and task.backups == {}
    assert task.complete(1, worker_uuid="A") == CompletionOutcome.STALE


def test_original_can_win_too():
    task = running_task("A")
    task.assign_backup("B")
    assert task.complete(1, worker_uuid="A") == CompletionOutcome.ACCEPTED


def test_losing_the_original_promotes_the_copy_without_a_retry():
    task = running_task("A")
    copy = task.assign_backup("B", now=5.0)
    assert task.requeue("worker lost", attempt=1) == TaskState.RUNNING
    assert (task.worker_uuid, task.attempt, task.retries) == ("B", copy, 0)
    assert task.assigned_at == 5.0
    assert task.complete(copy, worker_uuid="B") == CompletionOutcome.ACCEPTED


def test_losing_the_copy_leaves_the_original_running():
    task = running_task("A")
    copy = task.assign_backup("B")
    assert task.requeue("worker lost", attempt=copy) == TaskState.RUNNING
    assert task.backups == {} and task.holders() == [("A", 1)]


def test_a_worker_cannot_hold_two_copies():
    task = running_task("A")
    task.assign_backup("B")
    for worker in ("A", "B"):
        try:
            task.assign_backup(worker)
        except ValueError:
            continue
        raise AssertionError(f"{worker} was allowed a second copy")


def test_attempt_numbers_stay_unique_after_a_requeue():
    task = running_task("A")
    copy = task.assign_backup("B")
    task.requeue("lost", attempt=1)       # copy takes over
    task.requeue("lost", attempt=copy)    # and is lost too: back to waiting
    assert task.state == TaskState.WAITING
    assert task.assign("C") > copy


def test_round_trip_keeps_copies():
    task = running_task("A")
    copy = task.assign_backup("B", now=2.0)
    from app.models.pcb import TaskPCB
    again = TaskPCB.from_dict(task.to_dict())
    assert again.backups == {copy: ("B", 2.0)} and again.issued == copy


# ------------------------------------------------------------ the decision

def workers_and_pcbs(*names, busy=()):
    workers = [SimpleNamespace(uuid=n, cores=1, state="idle") for n in names]
    pcbs = {n: WorkerPCB(n, capacity=1) for n in names}
    return workers, pcbs


def trained(slow="A", fast="B"):
    tracker = SpeedTracker()
    for _ in range(5):
        tracker.record_result(slow, "test", 1.0, 10.0)
        tracker.record_result(fast, "test", 1.0, 1.0)
    return tracker


def test_idle_fast_worker_steals_from_a_slow_one():
    tracker = trained()
    task = running_task("A", now=0.0)
    workers, pcbs = workers_and_pcbs("A", "B")
    pcbs["A"].assign(task.key, 1)
    steals = FastestFirstScheduler(tracker).speculate([task], workers, pcbs, now=2.0)
    assert [(t.task_id, w.uuid) for t, w in steals] == [(0, "B")]


def test_no_steal_when_the_holder_is_about_to_finish():
    tracker = trained()
    task = running_task("A", now=0.0)
    workers, pcbs = workers_and_pcbs("A", "B")
    pcbs["A"].assign(task.key, 1)
    assert FastestFirstScheduler(tracker).speculate([task], workers, pcbs, now=9.8) == []


def test_no_steal_when_the_idle_worker_is_slower():
    tracker = trained(slow="B", fast="A")
    task = running_task("A", now=0.0)
    workers, pcbs = workers_and_pcbs("A", "B")
    pcbs["A"].assign(task.key, 1)
    assert FastestFirstScheduler(tracker).speculate([task], workers, pcbs, now=0.5) == []


def test_an_overdue_task_gets_a_copy():
    tracker = trained(slow="A", fast="B")
    task = running_task("A", now=0.0)
    workers, pcbs = workers_and_pcbs("A", "B")
    pcbs["A"].assign(task.key, 1)
    assert len(FastestFirstScheduler(tracker).speculate([task], workers, pcbs, now=60.0)) == 1


def test_a_busy_worker_does_not_steal():
    tracker = trained()
    task = running_task("A", now=0.0)
    other = JobPCB.create(uuid4(), "test", [1]).task(1)
    other.assign("B", now=0.0)
    workers, pcbs = workers_and_pcbs("A", "B")
    pcbs["A"].assign(task.key, 1)
    pcbs["B"].assign(other.key, 1)
    assert FastestFirstScheduler(tracker).speculate([task], workers, pcbs, now=2.0) == []


def test_baselines_never_steal():
    assert RandomScheduler.speculative is False
    assert RandomScheduler().speculate([running_task()], [], {}) == []


# ------------------------------------------- not back to the worker it left

def test_a_timed_out_task_does_not_go_straight_back_to_the_same_worker():
    tracker = trained()
    job = JobPCB.create(uuid4(), "test", [0])
    task = job.task(0)
    task.assign("A", now=0.0)
    task.requeue("timed out", attempt=1)
    assert task.last_worker == "A" and task.state == TaskState.WAITING

    workers, pcbs = workers_and_pcbs("A", "B")
    pcbs["B"].assign((uuid4(), 9), 1)  # B is busy, A is the only free worker
    assert FastestFirstScheduler(tracker).schedule([task], workers, pcbs) == []

    pcbs["B"].release(next(iter(pcbs["B"].running)))  # B frees up
    assignments = FastestFirstScheduler(tracker).schedule([task], workers, pcbs)
    assert [w.uuid for _, w in assignments] == ["B"]


def test_it_goes_back_if_nobody_else_exists():
    task = JobPCB.create(uuid4(), "test", [0]).task(0)
    task.assign("A", now=0.0)
    task.requeue("timed out", attempt=1)
    workers, pcbs = workers_and_pcbs("A")
    assignments = FastestFirstScheduler(trained()).schedule([task], workers, pcbs)
    assert [w.uuid for _, w in assignments] == ["A"]


def test_a_timeout_makes_the_worker_look_slower():
    from app.services.scheduler.reallocation import take_back

    tracker = trained(slow="A", fast="B")
    before = tracker.estimate("A", "test", 1.0).mean
    task = running_task("A", now=0.0)
    pcbs = {"A": WorkerPCB("A", capacity=1)}
    pcbs["A"].assign(task.key, 1)
    assert take_back(task, pcbs, tracker, now=60.0)
    assert tracker.estimate("A", "test", 1.0).mean > before
