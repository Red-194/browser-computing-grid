"""The scheduling algorithms, one decision at a time (no server, no clock)."""
from collections import Counter
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.pcb import TaskPCB, WorkerPCB
from app.models.worker import WorkerStates
from app.services import scheduler as registry
from app.services.scheduler.stats import SpeedTracker

JOB = uuid4()


def make_tasks(count, workload="job", start=0):
    return [TaskPCB(JOB, start + i, workload) for i in range(count)]


def make_workers(**capacities):
    """Workers named by keyword, each with the given number of free slots."""
    workers, pcbs = [], {}
    for name, capacity in capacities.items():
        workers.append(SimpleNamespace(uuid=name, cores=capacity, threads=1, state=WorkerStates.IDLE))
        pcbs[name] = WorkerPCB(name, capacity=capacity)
    return workers, pcbs


def teach(tracker, worker, rate, workload="job", count=3):
    """Make the tracker believe `worker` needs `rate` seconds per unit of work."""
    for _ in range(count):
        tracker.record_result(worker, workload, 1.0, rate)


def count_by_worker(assignments):
    return Counter(worker.uuid for _, worker in assignments)


def build(name, tracker=None):
    kwargs = {} if name in ("random", "round_robin") else {"tracker": tracker or SpeedTracker()}
    return registry.build(name, **kwargs)


ALL = ["random", "round_robin", "fastest_first", "boinc", "ucb"]
ADAPTIVE = ["fastest_first", "boinc", "ucb"]


# ------------------------------------------------- rules for every algorithm


@pytest.mark.parametrize("name", ALL)
def test_never_more_assignments_than_free_slots_or_tasks(name):
    workers, pcbs = make_workers(a=2, b=1)
    scheduler = build(name)

    assert len(scheduler.schedule(make_tasks(10), workers, pcbs)) == 3
    assert len(scheduler.schedule(make_tasks(2), workers, pcbs)) == 2


@pytest.mark.parametrize("name", ALL)
def test_each_task_is_assigned_at_most_once(name):
    workers, pcbs = make_workers(a=4, b=4)
    tasks = make_tasks(6)

    assigned = [task.task_id for task, _ in build(name).schedule(tasks, workers, pcbs)]

    assert sorted(assigned) == [0, 1, 2, 3, 4, 5]


@pytest.mark.parametrize("name", ALL)
def test_no_tasks_or_no_workers_means_no_assignments(name):
    workers, pcbs = make_workers(a=2)
    scheduler = build(name)
    assert scheduler.schedule([], workers, pcbs) == []
    assert scheduler.schedule(make_tasks(3), [], {}) == []


@pytest.mark.parametrize("name", ALL)
def test_offline_workers_and_full_workers_get_nothing(name):
    workers, pcbs = make_workers(a=2, b=2, c=1)
    pcbs["a"].mark_offline()
    pcbs["c"].assign((JOB, 99), 1)  # c is already full

    result = build(name).schedule(make_tasks(5), workers, pcbs)

    assert set(count_by_worker(result)) == {"b"}


@pytest.mark.parametrize("name", ALL)
def test_workers_without_a_record_are_used_only_when_idle(name):
    idle = SimpleNamespace(uuid="idle", cores=1, state=WorkerStates.IDLE)
    busy = SimpleNamespace(uuid="busy", cores=1, state=WorkerStates.BUSY)

    result = build(name).schedule(make_tasks(2), [idle, busy], {})

    assert set(count_by_worker(result)) == {"idle"}


@pytest.mark.parametrize("name", ADAPTIVE)
def test_workers_that_keep_timing_out_are_left_out(name):
    tracker = SpeedTracker()
    workers, pcbs = make_workers(good=2, bad=2)
    for _ in range(3):
        tracker.record_timeout("bad", now=0.0)

    result = build(name, tracker).schedule(make_tasks(4), workers, pcbs, now=1.0)

    assert set(count_by_worker(result)) == {"good"}


@pytest.mark.parametrize("name", ["random", "round_robin"])
def test_the_baselines_ignore_timeouts(name):
    tracker = SpeedTracker()
    workers, pcbs = make_workers(good=2, bad=2)
    for _ in range(3):
        tracker.record_timeout("bad", now=0.0)

    result = build(name).schedule(make_tasks(4), workers, pcbs, now=1.0)

    assert count_by_worker(result) == {"good": 2, "bad": 2}


def test_round_robin_alternates_between_workers():
    workers, pcbs = make_workers(a=3, b=3)
    result = build("round_robin").schedule(make_tasks(4), workers, pcbs)
    assert [worker.uuid for _, worker in result] == ["a", "b", "a", "b"]


def test_round_robin_skips_full_workers_and_keeps_its_turn_between_calls():
    workers, pcbs = make_workers(a=1, b=3, c=3)
    scheduler = build("round_robin")

    first = scheduler.schedule(make_tasks(4), workers, pcbs)
    assert [worker.uuid for _, worker in first] == ["a", "b", "c", "b"]  # a ran out of slots

    second = scheduler.schedule(make_tasks(2), workers, pcbs)  # nothing was assigned in the PCBs
    assert [worker.uuid for _, worker in second] == ["c", "a"]  # carries on from where it stopped


# ---------------------------------------------------- using measured speed


@pytest.mark.parametrize("name", ADAPTIVE)
def test_the_faster_worker_gets_the_larger_share(name):
    tracker = SpeedTracker()
    teach(tracker, "fast", 1.0)
    teach(tracker, "slow", 4.0)
    workers, pcbs = make_workers(fast=6, slow=6)

    shares = count_by_worker(build(name, tracker).schedule(make_tasks(8), workers, pcbs))

    assert shares["fast"] > shares["slow"]
    assert sum(shares.values()) == 8


@pytest.mark.parametrize("name", ADAPTIVE)
def test_a_busy_fast_worker_lets_the_slow_one_help(name):
    tracker = SpeedTracker()
    teach(tracker, "fast", 1.0)
    teach(tracker, "slow", 2.0)
    workers, pcbs = make_workers(fast=10, slow=10)
    for i in range(6):  # the fast worker already holds six tasks
        pcbs["fast"].assign((JOB, 100 + i), 1)

    shares = count_by_worker(build(name, tracker).schedule(make_tasks(2), workers, pcbs))

    assert shares["slow"] == 2  # queueing behind six tasks is slower than 2 s each


def test_a_worker_never_seen_before_is_treated_as_average():
    tracker = SpeedTracker()
    teach(tracker, "known-fast", 1.0)
    teach(tracker, "known-slow", 3.0)
    workers, pcbs = make_workers(**{"known-fast": 5, "known-slow": 5, "newcomer": 5})

    shares = count_by_worker(
        build("fastest_first", tracker).schedule(make_tasks(6), workers, pcbs)
    )

    assert shares["newcomer"] >= 1  # it gets work and so gets measured


# --------------------------------------------------------------- BOINC style


def test_boinc_gives_the_biggest_task_to_the_fastest_worker():
    tracker = SpeedTracker()
    teach(tracker, "fast", 1.0)
    teach(tracker, "slow", 4.0)
    workers, pcbs = make_workers(fast=3, slow=3)
    tasks = make_tasks(5)
    costs = {tasks[0].key: 10.0, tasks[1].key: 1.0, tasks[2].key: 1.0,
             tasks[3].key: 1.0, tasks[4].key: 8.0}

    result = build("boinc", tracker).schedule(tasks, workers, pcbs, costs=costs)
    owner = {task.task_id: worker.uuid for task, worker in result}

    assert owner[0] == "fast"  # the biggest
    assert owner[4] == "fast"  # the second biggest
    assert "slow" in owner.values()  # small ones still use the slow worker


def test_boinc_sends_retries_first_and_only_to_reliable_workers():
    tracker = SpeedTracker()
    teach(tracker, "flaky-but-fast", 0.5)
    teach(tracker, "steady", 2.0)
    tracker.record_timeout("flaky-but-fast", now=0.0)
    tracker.record_timeout("flaky-but-fast", now=0.0)  # two in a row: not quarantined yet
    for _ in range(6):
        tracker.record_failure("flaky-but-fast")
    assert tracker.reliability("flaky-but-fast") < 0.5
    assert not tracker.is_quarantined("flaky-but-fast", now=1.0)
    workers, pcbs = make_workers(**{"flaky-but-fast": 1, "steady": 1})
    fresh, retried = make_tasks(2)
    retried.assign("someone")
    retried.requeue("lost")  # now waiting with retries == 1

    result = build("boinc", tracker).schedule([fresh, retried], workers, pcbs, now=1.0)
    owner = {task.task_id: worker.uuid for task, worker in result}

    assert owner[retried.task_id] == "steady"
    assert owner[fresh.task_id] == "flaky-but-fast"


def test_boinc_tries_out_unmeasured_workers_with_the_smallest_tasks():
    workers, pcbs = make_workers(a=2, b=2)
    tasks = make_tasks(4)
    costs = {tasks[0].key: 5.0, tasks[1].key: 1.0, tasks[2].key: 3.0, tasks[3].key: 2.0}

    result = build("boinc", SpeedTracker()).schedule(tasks, workers, pcbs, costs=costs)
    owner = {task.task_id: worker.uuid for task, worker in result}

    # Nothing is measured, so each worker first gets one of the smallest tasks.
    first_two = {owner[1], owner[3]} if 3 in owner and 1 in owner else set()
    assert first_two == {"a", "b"}
    assert len(result) == 4


# ----------------------------------------------------------------------- UCB


def test_ucb_tries_a_lightly_sampled_worker_before_a_well_known_equal_one():
    tracker = SpeedTracker()
    teach(tracker, "veteran", 1.0, count=30)
    teach(tracker, "rookie", 1.0, count=3)
    workers, pcbs = make_workers(veteran=2, rookie=2)

    result = build("ucb", tracker).schedule(make_tasks(1), workers, pcbs)

    assert result[0][1].uuid == "rookie"


def test_ucb_still_prefers_a_clearly_faster_worker_once_both_are_known():
    tracker = SpeedTracker()
    teach(tracker, "fast", 1.0, count=30)
    teach(tracker, "slow", 5.0, count=30)
    workers, pcbs = make_workers(fast=2, slow=2)

    result = build("ucb", tracker).schedule(make_tasks(1), workers, pcbs)

    assert result[0][1].uuid == "fast"


# ------------------------------------------------------------------ registry


def test_the_registry_lists_every_algorithm_and_rejects_unknown_names():
    assert registry.available() == sorted(ALL)
    with pytest.raises(KeyError):
        registry.build("does-not-exist")


def test_switching_the_active_scheduler_takes_effect():
    try:
        assert registry.set_active("boinc").name == "boinc"
        assert registry.active().name == "boinc"
    finally:
        registry.set_active("random")


def test_an_unknown_startup_setting_falls_back_to_random(monkeypatch):
    monkeypatch.setattr(registry, "_active", None)
    monkeypatch.setenv(registry.ENV_VARIABLE, "nonsense")
    try:
        assert registry.active().name == "random"
    finally:
        registry.set_active("random")


@pytest.mark.parametrize("name", ADAPTIVE)
def test_a_worker_with_more_threads_gets_more_of_the_work_at_the_same_speed(name):
    # Same seconds per task on each, but one tab runs 4 tasks at once and the other 1.
    tracker = SpeedTracker()
    teach(tracker, "wide", 1.0)
    teach(tracker, "narrow", 1.0)
    workers = [
        SimpleNamespace(uuid="wide", cores=4, state=WorkerStates.IDLE),
        SimpleNamespace(uuid="narrow", cores=1, state=WorkerStates.IDLE),
    ]
    pcbs = {"wide": WorkerPCB("wide", capacity=20), "narrow": WorkerPCB("narrow", capacity=20)}

    shares = count_by_worker(build(name, tracker).schedule(make_tasks(10), workers, pcbs))

    assert shares["wide"] > 2 * shares.get("narrow", 0)


@pytest.mark.parametrize("name", ADAPTIVE)
def test_a_task_taken_back_from_the_fastest_worker_goes_to_another_idle_worker(name):
    # Both workers are idle and nothing is running, so nothing will ever trigger
    # another pass: the task must be given to the other worker now, not held.
    tracker = SpeedTracker()
    teach(tracker, "fast", 1.0)
    teach(tracker, "other", 2.0)
    workers, pcbs = make_workers(fast=2, other=2)
    task = make_tasks(1)[0]
    task.last_worker = "fast"

    result = build(name, tracker).schedule([task], workers, pcbs)

    assert [worker.uuid for _, worker in result] == ["other"]


@pytest.mark.parametrize("name", ADAPTIVE)
def test_a_task_taken_back_goes_to_the_same_worker_when_the_other_is_far_slower(name):
    tracker = SpeedTracker()
    teach(tracker, "fast", 1.0)
    teach(tracker, "crawl", 50.0)
    workers, pcbs = make_workers(fast=2, crawl=2)
    task = make_tasks(1)[0]
    task.last_worker = "fast"

    result = build(name, tracker).schedule([task], workers, pcbs)

    assert [worker.uuid for _, worker in result] == ["fast"]
