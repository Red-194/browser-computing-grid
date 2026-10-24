"""Tests for the task, worker and job control blocks (no browser, no network)."""
import json
from uuid import uuid4

import pytest

from app.models.pcb import (
    CompletionOutcome,
    InvalidTransition,
    JobPCB,
    JobStatus,
    TaskPCB,
    TaskState,
    WorkerPCB,
)
from app.models.worker import WorkerStates


def make_task(**overrides):
    return TaskPCB(job_id=uuid4(), task_id=0, workload="compression", **overrides)


# ----------------------------------------------------------------- task life


def test_new_task_waits_with_no_worker():
    task = make_task()
    assert task.state == TaskState.WAITING
    assert task.worker_uuid is None
    assert task.attempt == 0
    assert task.retries == 0
    assert not task.is_final


def test_task_goes_waiting_running_done():
    task = make_task()
    attempt = task.assign("w1", now=10.0)
    assert attempt == 1
    assert task.state == TaskState.RUNNING
    assert task.worker_uuid == "w1"
    assert task.assigned_at == 10.0

    assert task.complete(attempt, now=12.5) == CompletionOutcome.ACCEPTED
    assert task.state == TaskState.DONE
    assert task.finished_at == 12.5
    assert task.is_final


def test_requeue_returns_task_to_waiting_and_counts_a_retry():
    task = make_task()
    task.assign("w1", now=1.0)

    assert task.requeue("worker offline", now=2.0) == TaskState.WAITING
    assert task.retries == 1
    assert task.worker_uuid is None
    assert task.assigned_at is None
    assert task.last_error == "worker offline"

    assert task.assign("w2", now=3.0) == 2  # next attempt gets the next number
    assert task.worker_uuid == "w2"


def test_task_fails_after_retries_are_used_up():
    task = make_task(max_retries=2)
    for attempt in range(2):
        task.assign(f"w{attempt}")
        assert task.requeue("lost") == TaskState.WAITING

    task.assign("w9")
    assert task.requeue("lost again", now=50.0) == TaskState.FAILED
    assert task.retries == 2
    assert task.is_final
    assert task.finished_at == 50.0
    assert task.last_error == "lost again"


def test_zero_retries_fails_on_first_loss():
    task = make_task(max_retries=0)
    task.assign("w1")
    assert task.requeue("lost") == TaskState.FAILED


def test_fail_gives_up_without_retrying():
    task = make_task()
    task.fail("bad config", now=5.0)
    assert task.state == TaskState.FAILED
    assert task.retries == 0
    assert task.last_error == "bad config"


@pytest.mark.parametrize("final", ["done", "failed"])
def test_final_tasks_cannot_move_again(final):
    task = make_task()
    attempt = task.assign("w1")
    if final == "done":
        task.complete(attempt)
    else:
        task.fail("x")

    for action in (
        lambda: task.assign("w2"),
        lambda: task.requeue("again"),
        lambda: task.fail("again"),
    ):
        with pytest.raises(InvalidTransition):
            action()


def test_moves_that_skip_a_state_are_rejected():
    task = make_task()
    with pytest.raises(InvalidTransition):
        task.requeue("x")  # not running

    task.assign("w1")
    with pytest.raises(InvalidTransition):
        task.assign("w2")  # already running


def test_timeout_only_applies_to_running_tasks():
    task = make_task()
    assert not task.is_timed_out(timeout=5, now=100.0)  # waiting

    attempt = task.assign("w1", now=10.0)
    assert not task.is_timed_out(timeout=5, now=15.0)  # exactly at the limit
    assert task.is_timed_out(timeout=5, now=15.1)

    task.complete(attempt, now=16.0)
    assert not task.is_timed_out(timeout=5, now=999.0)  # done


def test_key_identifies_job_and_task():
    task = make_task()
    assert task.key == (task.job_id, 0)


# ------------------------------------------------- stale results and attempts


def test_result_from_an_old_attempt_is_stale_not_an_error():
    task = make_task()
    old = task.assign("w1")
    task.requeue("timed out")
    new = task.assign("w2")

    # The slow first worker answers while the second attempt is running.
    assert task.complete(old, worker_uuid="w1", digest="aaa") == CompletionOutcome.STALE
    assert task.state == TaskState.RUNNING  # still waiting for the current attempt

    assert task.complete(new, worker_uuid="w2", digest="aaa") == CompletionOutcome.ACCEPTED
    assert task.state == TaskState.DONE


def test_stale_result_after_requeue_but_before_reassignment():
    task = make_task()
    old = task.assign("w1")
    task.requeue("worker offline")  # waiting again, nobody holds it

    assert task.complete(old, worker_uuid="w1") == CompletionOutcome.STALE
    assert task.state == TaskState.WAITING


def test_stale_result_after_the_task_is_done():
    task = make_task()
    old = task.assign("w1")
    task.requeue("timed out")
    new = task.assign("w2")
    task.complete(new, digest="good")

    assert task.complete(old, worker_uuid="w1", digest="good") == CompletionOutcome.STALE
    assert task.state == TaskState.DONE
    assert task.disagreements() == []  # same answer, nothing to flag


def test_stale_answer_that_differs_is_reported_as_a_disagreement():
    task = make_task()
    old = task.assign("w1")
    task.requeue("timed out")
    new = task.assign("w2")

    task.complete(old, worker_uuid="w1", digest="WRONG")  # arrives first
    assert task.disagreements() == []  # not decided yet, task is not done

    task.complete(new, worker_uuid="w2", digest="right")
    found = task.disagreements()
    assert [(s.worker_uuid, s.attempt) for s in found] == [("w1", old)]


def test_a_repeat_of_the_accepted_answer_is_not_recorded_as_stale():
    task = make_task()
    attempt = task.assign("w1")
    task.complete(attempt, worker_uuid="w1", digest="x")

    assert task.complete(attempt, worker_uuid="w1", digest="x") == CompletionOutcome.STALE
    assert task.stale_results == []


def test_result_for_the_right_attempt_from_the_wrong_worker_is_stale():
    task = make_task()
    attempt = task.assign("w1")
    assert task.complete(attempt, worker_uuid="w2") == CompletionOutcome.STALE
    assert task.state == TaskState.RUNNING


def test_stale_answers_without_a_fingerprint_are_never_disagreements():
    task = make_task()
    old = task.assign("w1")
    task.requeue("lost")
    new = task.assign("w2")
    task.complete(old, digest=None)
    task.complete(new, digest="x")
    assert task.disagreements() == []


def test_requeue_for_an_attempt_someone_already_handled_does_nothing():
    task = make_task()
    attempt = task.assign("w1")

    # The disconnect handler and the timeout checker both notice the loss.
    assert task.requeue("worker offline", attempt=attempt) == TaskState.WAITING
    assert task.requeue("timed out", attempt=attempt) is None  # already handled
    assert task.retries == 1  # counted once, not twice


def test_requeue_for_an_old_attempt_leaves_the_new_attempt_alone():
    task = make_task()
    old = task.assign("w1")
    task.requeue("lost")
    task.assign("w2")

    assert task.requeue("late alarm about w1", attempt=old) is None
    assert task.state == TaskState.RUNNING
    assert task.worker_uuid == "w2"


# --------------------------------------------------------------- worker life


def test_new_worker_is_idle_with_a_free_slot():
    worker = WorkerPCB(uuid="w1")
    assert worker.state == WorkerStates.IDLE
    assert worker.has_free_slot
    assert worker.running == {}


def test_worker_capacity_must_be_at_least_one():
    with pytest.raises(ValueError):
        WorkerPCB(uuid="w1", capacity=0)


def test_worker_takes_a_task_then_is_idle_again():
    worker = WorkerPCB(uuid="w1", capacity=1)
    key = (uuid4(), 3)

    worker.assign(key, attempt=1)
    assert worker.state == WorkerStates.BUSY
    assert worker.running == {key: 1}
    assert not worker.has_free_slot  # capacity 1 and it is full

    assert worker.release(key) is True
    assert worker.state == WorkerStates.IDLE
    assert worker.running == {}
    assert worker.completed_tasks == 1
    assert worker.has_free_slot


def test_worker_holds_several_tasks_up_to_its_capacity():
    worker = WorkerPCB(uuid="w1", capacity=2)
    first, second, third = (uuid4(), 0), (uuid4(), 1), (uuid4(), 2)

    worker.assign(first, 1)
    assert worker.state == WorkerStates.BUSY
    assert worker.has_free_slot  # one task held, one slot left

    worker.assign(second, 1)
    assert not worker.has_free_slot
    with pytest.raises(InvalidTransition):
        worker.assign(third, 1)

    worker.release(first)
    assert worker.state == WorkerStates.BUSY  # still holds the second task
    assert worker.has_free_slot

    worker.release(second)
    assert worker.state == WorkerStates.IDLE


def test_worker_cannot_take_the_same_task_twice():
    worker = WorkerPCB(uuid="w1", capacity=3)
    key = (uuid4(), 0)
    worker.assign(key, 1)
    with pytest.raises(InvalidTransition):
        worker.assign(key, 2)


def test_releasing_a_task_the_worker_does_not_hold_is_not_an_error():
    worker = WorkerPCB(uuid="w1")
    assert worker.release((uuid4(), 9)) is False
    assert worker.completed_tasks == 0


def test_giving_up_on_a_task_does_not_count_it_as_completed():
    worker = WorkerPCB(uuid="w1")
    key = (uuid4(), 0)
    worker.assign(key, 1)
    worker.release(key, completed=False)
    assert worker.completed_tasks == 0
    assert worker.state == WorkerStates.IDLE


def test_offline_worker_cannot_take_a_task():
    worker = WorkerPCB(uuid="w1")
    worker.mark_offline()
    assert not worker.is_online
    assert not worker.has_free_slot
    with pytest.raises(InvalidTransition):
        worker.assign((uuid4(), 0), attempt=1)


def test_going_offline_hands_back_every_lost_task_and_attempt():
    worker = WorkerPCB(uuid="w1", capacity=2)
    first, second = (uuid4(), 7), (uuid4(), 8)
    worker.assign(first, attempt=2)
    worker.assign(second, attempt=1)

    lost = worker.mark_offline()
    assert sorted(lost, key=lambda item: item[0][1]) == [(first, 2), (second, 1)]
    assert worker.state == WorkerStates.OFFLINE
    assert worker.running == {}
    assert WorkerPCB(uuid="w2").mark_offline() == []  # nothing was lost


def test_reconnecting_worker_comes_back_idle_with_no_old_tasks():
    worker = WorkerPCB(uuid="w1")
    worker.assign((uuid4(), 0), attempt=1)
    worker.mark_offline()

    worker.mark_online(now=40.0)
    assert worker.state == WorkerStates.IDLE
    assert worker.running == {}
    assert worker.last_seen == 40.0


def test_silence_is_measured_from_last_contact():
    worker = WorkerPCB(uuid="w1")
    worker.touch(now=10.0)
    assert worker.silent_for(now=25.0) == 15.0
    worker.touch(now=30.0)
    assert worker.silent_for(now=31.0) == 1.0


# ------------------------------------------------------------------- job life


def test_job_creates_one_waiting_task_per_id():
    job = JobPCB.create(uuid4(), "compression", [0, 1, 2], max_retries=5)
    assert sorted(job.tasks) == [0, 1, 2]
    assert all(t.state == TaskState.WAITING for t in job.tasks.values())
    assert all(t.max_retries == 5 for t in job.tasks.values())
    assert all(t.job_id == job.job_id for t in job.tasks.values())
    assert job.status == JobStatus.RUNNING


def test_job_lists_waiting_tasks_lowest_id_first():
    job = JobPCB.create(uuid4(), "nqueens", [2, 0, 1])
    assert [t.task_id for t in job.waiting()] == [0, 1, 2]

    job.task(0).assign("w1")
    assert [t.task_id for t in job.waiting()] == [1, 2]


def test_requeued_task_is_waiting_again_for_the_job():
    job = JobPCB.create(uuid4(), "nqueens", [0, 1])
    job.task(0).assign("w1")
    job.task(0).requeue("lost")
    assert [t.task_id for t in job.waiting()] == [0, 1]


def test_job_is_done_only_when_every_task_is_done():
    job = JobPCB.create(uuid4(), "sat", [0, 1])
    attempt = job.task(0).assign("w1")
    job.task(0).complete(attempt)
    assert job.status == JobStatus.RUNNING

    attempt = job.task(1).assign("w1")
    job.task(1).complete(attempt)
    assert job.status == JobStatus.DONE


def test_job_fails_as_soon_as_one_task_fails():
    job = JobPCB.create(uuid4(), "sat", [0, 1, 2], max_retries=0)
    job.task(0).assign("w1")
    job.task(0).requeue("lost")  # no retries left

    assert job.status == JobStatus.FAILED
    assert [t.task_id for t in job.failed_tasks()] == [0]
    assert job.count(TaskState.WAITING) == 2  # the rest are still queued


def test_job_progress_counts_each_state():
    job = JobPCB.create(uuid4(), "regex", [0, 1, 2, 3])
    attempt = job.task(0).assign("w1")
    job.task(0).complete(attempt)
    job.task(1).assign("w2")
    job.task(2).fail("bad pattern")

    assert job.progress() == {
        "total": 4, "waiting": 1, "running": 1, "done": 1, "failed": 1,
    }


def test_empty_job_is_not_done():
    assert JobPCB(uuid4(), "x").status == JobStatus.RUNNING


# -------------------------------------------------------------- save and load


def test_task_survives_a_save_and_load_through_json():
    task = make_task(max_retries=4)
    old = task.assign("w1", now=1.0)
    task.requeue("timed out", now=2.0)
    new = task.assign("w2", now=3.0)
    task.complete(old, worker_uuid="w1", digest="stale")
    task.complete(new, worker_uuid="w2", digest="good", now=4.0)

    restored = TaskPCB.from_dict(json.loads(json.dumps(task.to_dict())))

    assert restored == task
    assert restored.state == TaskState.DONE
    assert [s.worker_uuid for s in restored.disagreements()] == ["w1"]


def test_worker_survives_a_save_and_load_through_json():
    worker = WorkerPCB(uuid="w1", capacity=3)
    worker.assign((uuid4(), 0), 2)
    worker.assign((uuid4(), 5), 1)
    worker.touch(now=12.0)

    restored = WorkerPCB.from_dict(json.loads(json.dumps(worker.to_dict())))

    assert restored == worker


def test_job_survives_a_save_and_load_through_json():
    job = JobPCB.create(uuid4(), "compression", [0, 1, 2])
    attempt = job.task(1).assign("w1", now=5.0)
    job.task(1).complete(attempt, digest="d")

    restored = JobPCB.from_dict(json.loads(json.dumps(job.to_dict())))

    assert restored == job
    assert restored.progress() == job.progress()


# ------------------------------------------- the two together (the key cases)


def test_lost_worker_tasks_are_requeued_and_finished_by_another_worker():
    job = JobPCB.create(uuid4(), "compression", [0, 1])
    first, second = WorkerPCB("w1", capacity=2), WorkerPCB("w2", capacity=2)

    for task in job.waiting():  # the first worker takes both tasks
        first.assign(task.key, task.assign(first.uuid))

    for key, attempt in first.mark_offline():
        task = job.task(key[1])
        assert task.requeue("worker w1 went offline", attempt=attempt) == TaskState.WAITING

    for task in job.waiting():
        attempt = task.assign(second.uuid)
        second.assign(task.key, attempt)
        assert task.complete(attempt, worker_uuid=second.uuid) == CompletionOutcome.ACCEPTED
        second.release(task.key)

    assert job.status == JobStatus.DONE
    assert all(t.retries == 1 and t.attempt == 2 for t in job.tasks.values())
    assert second.state == WorkerStates.IDLE


def test_slow_worker_answers_late_and_its_answer_is_only_compared():
    task = make_task()
    slow, fast = WorkerPCB("slow"), WorkerPCB("fast")

    first = task.assign(slow.uuid, now=0.0)
    slow.assign(task.key, first)

    assert task.is_timed_out(timeout=30, now=31.0)
    task.requeue("timed out", attempt=first)
    second = task.assign(fast.uuid, now=31.0)
    fast.assign(task.key, second)

    task.complete(second, worker_uuid="fast", digest="42")
    fast.release(task.key)

    # The slow worker is still alive and answers, correctly, after the deadline.
    assert task.complete(first, worker_uuid="slow", digest="42") == CompletionOutcome.STALE
    assert slow.release(task.key) is True  # its slot only frees when it answers
    assert task.state == TaskState.DONE
    assert task.disagreements() == []
