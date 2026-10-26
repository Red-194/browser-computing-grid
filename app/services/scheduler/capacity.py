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
