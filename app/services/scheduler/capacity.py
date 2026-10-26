"""How many tasks a worker should hold at once.

More than one lets a worker start its next task at once instead of waiting for
the network. But a worker should not hoard: a slow device holding eight tasks
at the end of a job keeps the whole job waiting. So the number of slots follows
the worker's measured task time: enough tasks to cover about
`TARGET_QUEUE_SECONDS` of work, never more than its cores, never less than one.
"""
import math

from . import stats

TARGET_QUEUE_SECONDS = 2.0
# Used until we have measured this worker (and capped by its cores).
DEFAULT_SLOTS = 2
# Most tasks held per compute thread, running or queued (see slots_for_pool).
MAX_PER_THREAD = 64
# A worker never holds more than 1/GUIDED_DIVISOR of what is left of the job, per
# thread-share (guided self-scheduling). A deep queue deals a small job out all at
# once, so the split is fixed by guesses and one hard task on the wrong worker sets
# the finish time. Big jobs are unaffected: the 64-per-thread cap is lower.
GUIDED_DIVISOR = 2
# ...but never fewer than cover one round trip to the controller, or a thread sits
# idle between batches. Measured: without this floor the last 600 tiny N-Queens
# tasks (n=16) made the job 1.4 s slower (4.9 s to 6.3 s over 8 runs each).
ROUND_TRIP_SECONDS = 0.1


class CapacityPolicy:
    def __init__(
        self,
        tracker: stats.SpeedTracker | None = None,
        target_seconds: float = TARGET_QUEUE_SECONDS,
        default_slots: int = DEFAULT_SLOTS,
    ):
        self.tracker = tracker or stats.tracker
        self.target_seconds = target_seconds
        self.default_slots = default_slots

    def slots_for(self, worker_uuid: str, cores: int, workload: str, cost: float) -> int:
        estimate = self.tracker.estimate(worker_uuid, workload, cost)
        if estimate is None or estimate.mean <= 0:
            wanted = self.default_slots
        else:
            wanted = math.ceil(self.target_seconds / estimate.mean)
        return max(1, min(max(1, cores), wanted))

    def apply(self, worker, worker_pcb, workload: str, cost: float) -> int:
        """Set the worker record's capacity and return it."""
        worker_pcb.capacity = self.slots_for(
            worker.uuid, getattr(worker, "cores", 1) or 1, workload, cost
        )
        return worker_pcb.capacity

    # --- tabs with several compute threads --------------------------------

    def slots_for_pool(
        self,
        worker_uuid: str,
        threads: int,
        workload: str,
        cost: float,
        remaining: int | None = None,
        total_threads: int | None = None,
    ) -> int:
        """Slots for a worker whose `threads` compute threads run tasks in parallel.

        Each thread gets `slots_for` as if it were a one-thread worker: one task
        until the worker has been measured (so a new tab does not grab a whole
        small job), then enough to cover about TARGET_QUEUE_SECONDS, at most
        MAX_PER_THREAD. If the job's unfinished task count and the threads in the
        whole pool are given, a thread also holds at most its share of half of
        what is left, but never fewer tasks than cover ROUND_TRIP_SECONDS.
        """
        estimate = self.tracker.estimate(worker_uuid, workload, cost)
        if estimate is None or estimate.mean <= 0:
            per_thread = 1
        else:
            per_thread = max(1, min(MAX_PER_THREAD, math.ceil(self.target_seconds / estimate.mean)))
        if remaining is not None and total_threads and estimate is not None and estimate.mean > 0:
            share = math.ceil(remaining / (GUIDED_DIVISOR * total_threads))
            round_trip = min(MAX_PER_THREAD, math.ceil(ROUND_TRIP_SECONDS / estimate.mean))
            per_thread = min(per_thread, max(1, share, round_trip))
        return max(1, threads) * per_thread

    def apply_pool(
        self, worker, worker_pcb, workload: str, cost: float,
        remaining: int | None = None, total_threads: int | None = None,
    ) -> int:
        worker_pcb.capacity = self.slots_for_pool(
            worker.uuid, getattr(worker, "cores", 1) or 1, workload, cost, remaining, total_threads
        )
        return worker_pcb.capacity
