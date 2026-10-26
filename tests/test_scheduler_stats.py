"""Speed tracker, cost estimates and the adaptive capacity policy."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.pcb import WorkerPCB
from app.models.tasks import NQueensTaskConfig, Task
from app.services.scheduler import cost
from app.services.scheduler.capacity import MAX_PER_THREAD, CapacityPolicy
from app.services.scheduler.stats import (
    QUARANTINE_AFTER,
    QUARANTINE_MAX_SECONDS,
    QUARANTINE_SECONDS,
    SpeedTracker,
)


def feed(tracker, worker, workload, rate, count=3, cost_units=100.0):
    """Record `count` results at `rate` seconds per unit of work."""
    for _ in range(count):
        tracker.record_result(worker, workload, cost_units, rate * cost_units)


# ------------------------------------------------------------ the tracker


def test_nothing_is_known_before_any_result():
    assert SpeedTracker().estimate("a", "w", 10) is None


def test_a_worker_with_enough_samples_gets_its_own_estimate():
    tracker = SpeedTracker()
    feed(tracker, "a", "w", rate=0.01)  # 1 second per 100 units

    estimate = tracker.estimate("a", "w", 200)

    assert estimate.source == "worker_workload"
    assert estimate.mean == pytest.approx(2.0)
    assert estimate.std == pytest.approx(0.0)
    assert estimate.samples == 3


def test_a_worker_with_few_samples_borrows_the_workload_average_scaled_to_its_speed():
    tracker = SpeedTracker()
    feed(tracker, "slow", "w", rate=0.04)  # established, 4x slower than "fast"
    feed(tracker, "fast", "w", rate=0.01)
    feed(tracker, "fast", "other", rate=0.02, count=3)
    feed(tracker, "slow", "other", rate=0.08, count=3)
    tracker.record_result("fast", "third", 100, 1.0)  # only one sample

    estimate = tracker.estimate("fast", "third", 100)

    assert estimate.source == "scaled_workload_average"
    # "fast" has been quicker than the average worker, so its guess is below the average.
    average = tracker.estimate("brand-new", "third", 100)
    assert average.source == "workload_average"
    assert estimate.mean < average.mean


def test_a_worker_nobody_has_seen_gets_the_plain_workload_average():
    tracker = SpeedTracker()
    feed(tracker, "a", "w", rate=0.01)

    estimate = tracker.estimate("stranger", "w", 100)

    assert estimate.source == "workload_average"
    assert estimate.mean == pytest.approx(1.0)


def test_a_workload_nobody_has_run_is_unknown_even_for_known_workers():
    tracker = SpeedTracker()
    feed(tracker, "a", "w", rate=0.01)
    assert tracker.estimate("a", "different", 100) is None


def test_recent_results_count_more_and_spread_is_tracked():
    tracker = SpeedTracker()
    feed(tracker, "a", "w", rate=0.01)
    before = tracker.estimate("a", "w", 100).mean

    tracker.record_result("a", "w", 100, 3.0)  # a much slower run
    after = tracker.estimate("a", "w", 100)

    assert after.mean > before  # moved toward the new sample
    assert after.mean < 3.0  # but did not jump all the way
    assert after.std > 0


def test_zero_or_missing_times_are_ignored():
    tracker = SpeedTracker()
    tracker.record_result("a", "w", 100, 0)
    tracker.record_result("a", "w", 100, None)
    assert tracker.samples("a", "w") == 0


def test_reliability_starts_perfect_and_falls_with_timeouts_and_losses():
    tracker = SpeedTracker()
    assert tracker.reliability("a") == 1.0

    tracker.record_timeout("a")
    after_one = tracker.reliability("a")
    tracker.record_failure("a")
    after_two = tracker.reliability("a")

    assert 1.0 > after_one > after_two > 0

    for _ in range(5):
        tracker.record_result("a", "w", 1, 1.0)
    assert tracker.reliability("a") > after_two  # good results rebuild it


def test_several_timeouts_in_a_row_quarantine_a_worker_for_a_while():
    tracker = SpeedTracker()
    for _ in range(QUARANTINE_AFTER - 1):
        tracker.record_timeout("a", now=100.0)
    assert not tracker.is_quarantined("a", now=100.0)

    tracker.record_timeout("a", now=100.0)

    assert tracker.is_quarantined("a", now=100.0)
    assert tracker.is_quarantined("a", now=100.0 + QUARANTINE_SECONDS - 1)
    assert not tracker.is_quarantined("a", now=100.0 + QUARANTINE_SECONDS + 1)


def test_repeat_offenders_are_quarantined_for_longer_each_time():
    tracker = SpeedTracker()
    now = 0.0
    lengths = []
    for _ in range(4):
        for _ in range(QUARANTINE_AFTER):
            tracker.record_timeout("a", now=now)
        # How long is it quarantined for? Find the first moment it is free.
        length = 0.0
        while tracker.is_quarantined("a", now=now + length):
            length += 1.0
        lengths.append(length)
        now += length + 1  # it comes out of quarantine and fails again at once

    assert lengths[:3] == [QUARANTINE_SECONDS, 2 * QUARANTINE_SECONDS, 4 * QUARANTINE_SECONDS]
    assert lengths[3] == min(8 * QUARANTINE_SECONDS, QUARANTINE_MAX_SECONDS)


def test_a_good_result_starts_the_quarantine_length_over():
    tracker = SpeedTracker()
    for _ in range(QUARANTINE_AFTER):
        tracker.record_timeout("a", now=0.0)  # first offence: 30 s
    tracker.record_result("a", "w", 1, 1.0)  # redeemed

    for _ in range(QUARANTINE_AFTER):
        tracker.record_timeout("a", now=1000.0)

    assert tracker.is_quarantined("a", now=1000.0 + QUARANTINE_SECONDS - 1)
    assert not tracker.is_quarantined("a", now=1000.0 + QUARANTINE_SECONDS + 1)  # 30 s, not 60


def test_a_good_result_or_a_reconnect_ends_the_quarantine():
    for ending in ("result", "reconnect"):
        tracker = SpeedTracker()
        for _ in range(QUARANTINE_AFTER):
            tracker.record_timeout("a", now=0.0)
        assert tracker.is_quarantined("a", now=1.0)

        if ending == "result":
            tracker.record_result("a", "w", 1, 1.0)
        else:
            tracker.clear_quarantine("a")

        assert not tracker.is_quarantined("a", now=1.0)


def test_snapshot_lists_what_was_learned():
    tracker = SpeedTracker()
    feed(tracker, "a", "w", rate=0.01)
    tracker.record_timeout("a")

    snapshot = tracker.snapshot()

    assert snapshot["workers"]["a"]["workloads"]["w"]["samples"] == 3
    assert snapshot["workers"]["a"]["timeouts"] == 1
    assert snapshot["workers"]["a"]["quarantined"] is False
    assert snapshot["workloads"]["w"]["samples"] == 3


def test_reset_forgets_everything():
    tracker = SpeedTracker()
    feed(tracker, "a", "w", rate=0.01)
    tracker.reset()
    assert tracker.estimate("a", "w", 1) is None
    assert tracker.snapshot()["workers"] == {}


# ------------------------------------------------------------ task cost


def test_compression_cost_is_the_chunk_size_in_bytes():
    config = SimpleNamespace(data_base64="A" * 400)  # 300 bytes
    assert cost.task_cost("compression", config) == 300


def test_regex_cost_is_the_characters_scanned():
    config = SimpleNamespace(texts=["abc", "defgh", ""])
    assert cost.task_cost("regex", config) == 8


def mandelbrot_tile(row, col, **overrides):
    values = dict(width=200, height=200, x_min=-2.0, x_max=1.0, y_min=-1.5, y_max=1.5,
                  max_iterations=1000, tile_size=50, row_block=row, col_block=col)
    values.update(overrides)
    return SimpleNamespace(**values)


def test_mandelbrot_tile_inside_the_set_costs_far_more_than_one_outside():
    inside = cost.task_cost("mandelbrot", mandelbrot_tile(2, 2))  # around the origin
    outside = cost.task_cost("mandelbrot", mandelbrot_tile(0, 3))  # a corner, escapes at once
    assert inside > 50 * outside


def test_mandelbrot_cost_never_exceeds_pixels_times_iterations():
    cfg = mandelbrot_tile(2, 2)
    assert cost.task_cost("mandelbrot", cfg) <= 50 * 50 * 1000


def test_mandelbrot_edge_tile_is_priced_by_its_clipped_size():
    full = cost.task_cost("mandelbrot", mandelbrot_tile(2, 2, width=200))
    clipped = cost.task_cost("mandelbrot", mandelbrot_tile(2, 3, width=170, x_min=-2.0, x_max=1.0))
    assert clipped < full  # the last column of tiles is only 20 pixels wide
    assert cost.task_cost("mandelbrot", mandelbrot_tile(0, 9)) == 1.0  # a tile past the image


def test_nqueens_cost_grows_steeply_with_the_rows_left():
    def nq(n, depth):
        return Task(job_id=uuid4(), task_id=0, workload="nqueens",
                    config=NQueensTaskConfig(n=n, prefix=[0] * depth))

    assert cost.cost_of(nq(10, 10)) == 1.0  # nothing left to search
    assert cost.cost_of(nq(16, 2)) > 100 * cost.cost_of(nq(16, 6))
    assert cost.cost_of(nq(17, 1)) > cost.cost_of(nq(16, 1))


def test_workloads_whose_size_is_unknown_cost_one():
    assert cost.task_cost("sat", SimpleNamespace()) == 1.0
    assert cost.task_cost("not-a-workload", SimpleNamespace()) == 1.0


def test_cost_is_never_below_one_and_odd_objects_cost_one():
    assert cost.task_cost("compression", SimpleNamespace(data_base64="")) == 1.0
    assert cost.task_cost("compression", SimpleNamespace()) == 1.0  # missing field
    assert cost.cost_of(SimpleNamespace(task_id=3)) == 1.0  # no workload or config


# ------------------------------------------------------ capacity policy


def make_policy(rate=None, cores=8, **kwargs):
    tracker = SpeedTracker()
    if rate is not None:
        feed(tracker, "w1", "job", rate=rate, cost_units=1.0)
    return CapacityPolicy(tracker, **kwargs), tracker


def test_unmeasured_worker_gets_the_default_slots_capped_by_cores():
    policy, _ = make_policy()
    assert policy.slots_for("w1", cores=8, workload="job", cost=1.0) == 2
    assert policy.slots_for("w1", cores=1, workload="job", cost=1.0) == 1


def test_fast_tasks_fill_the_cores_slow_tasks_get_one_slot():
    fast, _ = make_policy(rate=0.001)  # 1 ms per task: 2000 would fit in 2 s
    slow, _ = make_policy(rate=30.0)  # 30 s per task
    medium, _ = make_policy(rate=0.5)  # 4 tasks cover 2 s

    assert fast.slots_for("w1", 8, "job", 1.0) == 8
    assert slow.slots_for("w1", 8, "job", 1.0) == 1
    assert medium.slots_for("w1", 8, "job", 1.0) == 4


def test_apply_sets_the_worker_records_capacity():
    policy, _ = make_policy(rate=30.0)
    worker = SimpleNamespace(uuid="w1", cores=8)
    pcb = WorkerPCB("w1", capacity=8)

    assert policy.apply(worker, pcb, "job", 1.0) == 1
    assert pcb.capacity == 1


def test_pool_gives_each_thread_its_own_slots():
    unmeasured, _ = make_policy()
    fast, _ = make_policy(rate=0.001)
    slow, _ = make_policy(rate=30.0)
    medium, _ = make_policy(rate=1.0)  # 2 tasks cover 2 s

    assert unmeasured.slots_for_pool("w1", 8, "job", 1.0) == 8  # one per thread, no hoarding
    assert fast.slots_for_pool("w1", 8, "job", 1.0) == 8 * MAX_PER_THREAD
    assert slow.slots_for_pool("w1", 8, "job", 1.0) == 8
    assert medium.slots_for_pool("w1", 8, "job", 1.0) == 8 * 2
    assert slow.slots_for_pool("w1", 1, "job", 1.0) == 1
