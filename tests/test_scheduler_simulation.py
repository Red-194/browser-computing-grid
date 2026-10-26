"""The scheduling algorithms compared on a simulated grid.

These assert relationships (who beats whom, who finishes at all), not exact
numbers, so they keep holding when a constant is tuned. The worker speeds are
assumptions; see simulator.py.
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.pcb import TaskPCB, WorkerPCB
from app.models.worker import WorkerStates
from app.services import scheduler as registry
from app.services.scheduler.simulator import SCENARIOS, Simulation, run_scenario
from app.services.scheduler.stats import SpeedTracker

ADAPTIVE = ["fastest_first", "boinc", "ucb"]
BASELINES = ["random", "round_robin"]
ALL = BASELINES + ADAPTIVE


def makespans(scenario, names=ALL, **options):
    return {name: run_scenario(scenario, name, **options).makespan for name in names}


# ----------------------------------------------------------- the simulator


def test_the_same_seed_gives_the_same_result():
    first = run_scenario("uneven_tasks", "boinc", seed=3)
    second = run_scenario("uneven_tasks", "boinc", seed=3)
    assert (first.makespan, first.accepted, first.retries) == (
        second.makespan, second.accepted, second.retries,
    )


def test_every_scenario_finishes_for_the_adaptive_algorithms():
    for scenario in SCENARIOS:
        for name in ADAPTIVE:
            assert run_scenario(scenario, name).completed, (scenario, name)


def test_no_task_is_accepted_twice_or_lost():
    result = run_scenario("worker_dies", "boinc")
    assert sum(result.accepted.values()) == 120


# ------------------------------------------------- where the algorithms tie


def test_identical_workers_and_equal_tasks_make_the_algorithms_tie():
    times = makespans("homogeneous")
    assert max(times.values()) < 1.05 * min(times.values())


def test_a_network_bound_job_is_the_same_whatever_the_algorithm():
    # Tasks compute in milliseconds but take ~100 ms to send and return:
    # which worker gets which task hardly matters.
    for scenario in ("measured_lz4", "measured_zstd"):
        times = makespans(scenario)
        assert max(times.values()) < 1.05 * min(times.values()), scenario


# --------------------------------------------- where speed awareness helps


def test_on_compute_heavy_tasks_the_adaptive_algorithms_beat_both_baselines():
    times = makespans("heterogeneous_compute")
    best_baseline = min(times["random"], times["round_robin"])

    for name in ADAPTIVE:
        assert times[name] < best_baseline, name
    assert run_scenario("heterogeneous_compute", "boinc").efficiency > 0.9


def mean_makespan(scenario, name, seeds=range(5)):
    return sum(run_scenario(scenario, name, seed=s).makespan for s in seeds) / len(seeds)


def test_when_task_sizes_are_known_boinc_style_size_matching_clearly_wins():
    # Biggest tasks first, each to the worker that finishes it soonest (LPT).
    boinc = mean_makespan("known_uneven_sizes", "boinc")
    others = {name: mean_makespan("known_uneven_sizes", name) for name in ALL if name != "boinc"}

    assert boinc < 0.85 * min(others.values()), (boinc, others)
    assert run_scenario("known_uneven_sizes", "boinc").efficiency > 0.9


def test_when_task_sizes_are_unknown_every_algorithm_finishes_but_none_is_reliably_better():
    # The scheduler is told every task costs 1 while real sizes are heavy-tailed,
    # so the finish time is decided by which worker gets the one huge task near
    # the end. This is the case speculative re-execution of stragglers would fix.
    for name in ALL:
        result = run_scenario("uneven_tasks", name)
        assert result.completed, name
        assert result.efficiency > 0.5, name


# ----------------------------------------- where timeouts and reliability help


def test_a_worker_that_dies_is_covered_by_every_algorithm():
    for name in ALL:
        result = run_scenario("worker_dies", name)
        assert result.completed, name
        assert result.retries >= 1, name


def test_a_hung_worker_sinks_the_baselines_but_not_the_adaptive_algorithms():
    # The baselines keep sending it work, every task they send it times out,
    # and tasks run out of retries; the adaptive ones quarantine it.
    for name in BASELINES:
        assert not run_scenario("worker_hangs", name).completed, name
    for name in ADAPTIVE:
        result = run_scenario("worker_hangs", name)
        assert result.completed, name
        assert result.timeouts >= 1, name


def test_without_the_timeout_monitor_a_hung_worker_stalls_the_job_for_everyone():
    for name in ALL:
        assert not run_scenario("worker_hangs", name, use_timeouts=False).completed, name


def test_a_throttled_tab_is_worked_around_by_the_adaptive_algorithms():
    for name in ADAPTIVE:
        result = run_scenario("throttled_tab", name)
        assert result.completed, name
        # After being slowed, the throttled worker (w0) does far less than an equal share.
        assert result.accepted["w0"] < 0.5 * (160 / 4), name


# ------------------------------------------------- the hold-back rule alone


def _pass(fast_running, slow_running, fast_cores=2):
    """One scheduling decision with a fast worker and a slow one."""
    tracker = SpeedTracker()
    for _ in range(3):
        tracker.record_result("fast", "job", 1.0, 1.0)
        tracker.record_result("slow", "job", 1.0, 5.0)
    workers = [
        SimpleNamespace(uuid="fast", cores=fast_cores, threads=1, state=WorkerStates.IDLE),
        SimpleNamespace(uuid="slow", cores=2, threads=1, state=WorkerStates.IDLE),
    ]
    pcbs = {"fast": WorkerPCB("fast", capacity=fast_cores), "slow": WorkerPCB("slow", capacity=2)}
    for i in range(fast_running):
        pcbs["fast"].assign((uuid4(), i), 1)
    for i in range(slow_running):
        pcbs["slow"].assign((uuid4(), 100 + i), 1)
    task = TaskPCB(uuid4(), 0, "job")
    return registry.build("fastest_first", tracker=tracker).schedule([task], workers, pcbs)


def test_a_task_waits_for_the_busy_fast_worker_instead_of_going_to_a_slow_one():
    # fast is full with 2 tasks of 1 s (frees up within ~3 s); slow would take 5 s.
    assert _pass(fast_running=2, slow_running=0) == []


def test_a_task_goes_to_the_slow_worker_when_waiting_would_be_worse():
    # fast holds 8 tasks: waiting for its queue (about 9 s) is worse than 5 s on slow.
    result = _pass(fast_running=8, slow_running=0, fast_cores=8)

    assert [worker.uuid for _, worker in result] == ["slow"]


def test_a_free_fast_worker_simply_gets_the_task():
    result = _pass(fast_running=1, slow_running=0)

    assert [worker.uuid for _, worker in result] == ["fast"]


def test_nothing_is_held_back_when_no_other_worker_is_busy():
    tracker = SpeedTracker()
    for _ in range(3):
        tracker.record_result("slow", "job", 1.0, 5.0)
    workers = [SimpleNamespace(uuid="slow", cores=2, state=WorkerStates.IDLE)]
    pcbs = {"slow": WorkerPCB("slow", capacity=2)}

    result = registry.build("boinc", tracker=tracker).schedule(
        [TaskPCB(uuid4(), 0, "job")], workers, pcbs
    )

    assert len(result) == 1  # the only worker there is must take it
