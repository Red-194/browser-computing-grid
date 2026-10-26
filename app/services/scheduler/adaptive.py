"""Shared machinery for the algorithms that use measured speed.

An adaptive algorithm only decides two things, and subclasses override them:

    order(tasks, costs)    in what order to hand tasks out
    pick(...)              which worker gets the next task

Everything else is the same for all of them: find the workers with a free slot
(leaving out quarantined ones), estimate how long each task would take on each
worker from what has been measured, and keep a running tally of the work given
out in this pass so one fast worker is not handed everything.
"""
from dataclasses import dataclass

from . import stats
from .base import Scheduler, open_workers

# Used for a worker we know nothing about when nobody else has been measured.
UNKNOWN_SECONDS = 1.0
# Hold a task back if a busy worker would finish it in less than this fraction
# of the time the best free worker would take. Below 1 so near-ties do not make
# the scheduler dither.
HOLD_RATIO = 0.7
# ...and only if waiting saves at least this many seconds. For tasks that take
# milliseconds the round trip to a worker (not in our estimates) costs more than
# the wait would save, so holding back would only slow the job down.
HOLD_MIN_SAVING = 1.0


@dataclass
class Candidate:
    """A worker with a free slot, and how much is already queued on it."""

    worker: object
    free: int
    running: int  # tasks it already holds
    extra: float = 0.0  # estimated seconds of work given to it in this pass
    assigned: int = 0  # tasks given to it in this pass

    @property
    def uuid(self) -> str:
        return self.worker.uuid

    def finish_time(self, seconds: float) -> float:
        """When a task of `seconds` would be done: everything queued before it,
        then the task itself. Queued tasks are assumed to be about this size."""
        return self.running * seconds + self.extra + seconds


class AdaptiveScheduler(Scheduler):
    name = "adaptive"

    def __init__(self, tracker: stats.SpeedTracker | None = None):
        self.tracker = tracker or stats.tracker

    # --------------------------------------------------------- the pass

    def schedule(self, tasks, workers, worker_pcbs=None, costs=None, now=None):
        costs = costs or {}
        if not tasks:
            return []

        candidates = []
        for worker, free in open_workers(workers, worker_pcbs, self.tracker, now):
            pcb = worker_pcbs.get(worker.uuid) if worker_pcbs else None
            candidates.append(Candidate(worker, free, len(pcb.running) if pcb else 0))
        if not candidates:
            return []

        busy = self.busy_workers(workers, worker_pcbs, candidates, now)

        assignments = []
        remaining = self.before(list(tasks), candidates, costs, assignments)

        for task in self.order(remaining, costs):
            open_candidates = [c for c in candidates if c.free > 0]
            if not open_candidates:
                break
            cost = costs.get(task.key, 1.0)
            estimates = {c.uuid: self.estimate(c, task, cost) for c in open_candidates}
            guess = self.guess(estimates)
            choice = self.pick(task, cost, open_candidates, estimates, guess)
            if self.better_to_wait(task, cost, choice, estimates, guess, busy):
                continue  # leave it waiting; a smaller task may suit this worker
            self.give(choice, task, estimates[choice.uuid], guess, assignments)

        return assignments

    # ------------------------------------------------ hooks to override

    def before(self, tasks, candidates, costs, assignments):
        """Run before the main pass. May assign some tasks itself; returns the
        tasks still to be handed out."""
        return tasks

    def order(self, tasks, costs):
        return tasks

    def pick(self, task, cost, candidates, estimates, guess) -> Candidate:
        raise NotImplementedError

    # ------------------------------------------------------- helpers

    def busy_workers(self, workers, worker_pcbs, candidates, now):
        """Online workers that are working but have no free slot right now, as
        (worker, tasks held). Their next free slot is a way to finish a task."""
        if not worker_pcbs:
            return []
        free = {c.uuid for c in candidates}
        busy = []
        for worker in workers:
            pcb = worker_pcbs.get(worker.uuid)
            if (
                pcb is not None
                and pcb.is_online
                and pcb.running
                and worker.uuid not in free
                and not self.tracker.is_quarantined(worker.uuid, now)
            ):
                busy.append((worker, len(pcb.running)))
        return busy

    def better_to_wait(self, task, cost, choice, estimates, guess, busy) -> bool:
        """True if a busy worker would finish this task clearly sooner than the
        best free worker, even after waiting for its queue to clear.

        This keeps a slow worker from taking the last tasks of a job while a fast
        one is only moments from being free. A busy worker's wait is taken as its
        whole queue (a cautious guess: some of it is probably already done).
        """
        free_finish = choice.finish_time(self.seconds(estimates[choice.uuid], guess))
        for worker, held in busy:
            estimate = self.tracker.estimate(worker.uuid, task.workload, cost)
            if estimate is None or estimate.mean <= 0:
                continue
            wait_finish = (held + 1) * estimate.mean
            if (
                wait_finish < HOLD_RATIO * free_finish
                and free_finish - wait_finish >= HOLD_MIN_SAVING
            ):
                return True
        return False

    def estimate(self, candidate: Candidate, task, cost: float):
        return self.tracker.estimate(candidate.uuid, task.workload, cost)

    @staticmethod
    def guess(estimates) -> float:
        """Seconds to assume for a worker with no estimate: the fastest known
        mean, so an unknown worker is not unfairly ruled out."""
        known = [e.mean for e in estimates.values() if e is not None and e.mean > 0]
        return min(known) if known else UNKNOWN_SECONDS

    @staticmethod
    def seconds(estimate, guess: float) -> float:
        return estimate.mean if estimate is not None and estimate.mean > 0 else guess

    @staticmethod
    def give(candidate: Candidate, task, estimate, guess: float, assignments) -> None:
        candidate.free -= 1
        candidate.assigned += 1
        candidate.extra += AdaptiveScheduler.seconds(estimate, guess)
        assignments.append((task, candidate.worker))
