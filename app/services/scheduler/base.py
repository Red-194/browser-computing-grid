"""The scheduler interface and the helpers every algorithm shares.

A scheduler answers one question: of the tasks waiting, which task goes to which
worker right now? It does not send anything and it does not change any record;
`dispatch_pending` in `app/jobs.py` does that with the answer.
"""
from ...models.worker import WorkerStates


class Scheduler:
    """Base class. Subclasses set `name` and implement `schedule`."""

    name = "base"

    def schedule(self, tasks, workers, worker_pcbs=None, costs=None, now=None):
        """Return a list of (TaskPCB, worker) pairs.

        tasks:       waiting TaskPCBs, in the order they should be considered
        workers:     the registered workers (objects with `uuid`, `cores`)
        worker_pcbs: dict of worker uuid -> WorkerPCB (its free slots, load)
        now:         optional clock reading (the simulator passes a virtual one)
        costs:       optional dict of task key -> estimated work for that task
                     (see cost.py); algorithms that do not need it ignore it

        At most one assignment per free slot, and never more tasks than given.
        """
        raise NotImplementedError

    # Work stealing is off unless an algorithm turns it on, so the baselines
    # stay plain.
    speculative = False

    def speculate(self, running, workers, worker_pcbs=None, costs=None, now=None):
        """Return (TaskPCB, worker) pairs: running tasks worth also running on
        an idle worker. `running` holds RUNNING TaskPCBs that have no copy yet."""
        return []


def free_slots(worker, pcb) -> int:
    """How many more tasks this worker can take right now."""
    if pcb is not None:
        if not pcb.is_online:
            return 0
        return max(0, pcb.capacity - len(pcb.running))
    return 1 if worker.state == WorkerStates.IDLE else 0


def open_workers(workers, worker_pcbs, tracker=None, now=None):
    """Workers that can take work, as a list of (worker, free slots).

    If a tracker is given, workers it has quarantined (several timeouts in a
    row) are left out. The baseline schedulers pass no tracker, so they keep
    sending work to a bad worker, which is what makes them a fair baseline.
    """
    result = []
    for worker in workers:
        pcb = worker_pcbs.get(worker.uuid) if worker_pcbs else None
        if tracker is not None and tracker.is_quarantined(worker.uuid, now):
            continue
        slots = free_slots(worker, pcb)
        if slots > 0:
            result.append((worker, slots))
    return result
