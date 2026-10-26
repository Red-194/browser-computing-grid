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

import time

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
# Work stealing: an idle worker copies a running task only if it expects to
# finish it in under this fraction of the time the holder still needs, and
# saves at least this many seconds. Copies cost compute, so the bar is high.
STEAL_RATIO = 0.7
STEAL_MIN_SAVING = 0.5
# A task taken back from a worker waits for another worker only if that worker
# is not much slower for this task. Otherwise a fast worker that had one bad
# timeout would sit idle while the task waited for a far slower device.
AVOID_MAX_SLOWDOWN = 3.0


def compute_threads(worker) -> int:
    """How many tasks the worker runs at once. A tab reports its thread pool as
    `cores`; a stand-in that runs its tasks one after another sets `threads=1`."""
    threads = getattr(worker, "threads", None)
    return max(1, threads or getattr(worker, "cores", 1) or 1)


@dataclass
class Candidate:
    """A worker with a free slot, and how much is already queued on it."""

    worker: object
    free: int
    running: int  # tasks it already holds
    extra: float = 0.0  # estimated seconds of work given to it in this pass
    assigned: int = 0  # tasks given to it in this pass
    threads: int = 1  # compute threads: this many queued tasks run at once

    @property
    def uuid(self) -> str:
        return self.worker.uuid

    def finish_time(self, seconds: float) -> float:
        """When a task of `seconds` would be done: everything queued before it
        (shared out over the worker's threads), then the task itself. Queued tasks
        are assumed to be about this size."""
        return (self.running * seconds + self.extra) / self.threads + seconds


class AdaptiveScheduler(Scheduler):
    name = "adaptive"
    speculative = True

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
            candidates.append(
                Candidate(worker, free, len(pcb.running) if pcb else 0, threads=compute_threads(worker))
            )
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
            if self.should_avoid(task, cost, choice, estimates, workers, worker_pcbs, now):
                continue  # it was just taken back from this worker; wait for another
            if self.better_to_wait(task, cost, choice, estimates, guess, busy):
                continue  # leave it waiting; a smaller task may suit this worker
            self.give(choice, task, estimates[choice.uuid], guess, assignments)

        return assignments

    # ------------------------------------------------ work stealing

    def speculate(self, running, workers, worker_pcbs=None, costs=None, now=None):
        """Tail-of-job work stealing.

        When nothing is waiting and a worker has gone idle, a task still running
        elsewhere may be worth running a second time here: the first answer wins.
        This catches a straggler (a slow or stuck worker, or one uneven task
        that is far bigger than its siblings) without waiting for a timeout.
        Only fully idle workers steal, and only from other workers.
        """
        costs = costs or {}
        clock = time.monotonic() if now is None else now
        idle = []
        for worker, free in open_workers(workers, worker_pcbs, self.tracker, now):
            pcb = worker_pcbs.get(worker.uuid) if worker_pcbs else None
            if pcb is None or not pcb.running:
                # At most one copy per compute thread: a copy that has to queue
                # behind other work saves nothing.
                idle.append([worker, min(free, compute_threads(worker))])
        if not idle or not running:
            return []

        def held(task):
            pcb = worker_pcbs.get(task.worker_uuid) if worker_pcbs else None
            return len(pcb.running) if pcb else 1

        def remaining(task):
            """Seconds the holder still needs; None if we cannot tell."""
            estimate = self.tracker.estimate(task.worker_uuid, task.workload, costs.get(task.key, 1.0))
            if estimate is None or estimate.mean <= 0 or task.assigned_at is None:
                return None, None
            elapsed = clock - task.assigned_at
            # On average a task sits in the middle of its holder's queue.
            expected = (held(task) + 1) / 2 * estimate.mean
            # Already overdue: it may take as long again.
            return (expected - elapsed if elapsed < expected else elapsed), estimate.mean

        steals = []
        candidates = []
        for task in running:
            left, mean = remaining(task)
            if left is not None:
                candidates.append((left, mean, task))
        for left, mean, task in sorted(candidates, key=lambda c: -c[0]):
            cost = costs.get(task.key, 1.0)
            best = None
            for entry in idle:
                worker, free = entry
                if free <= 0 or worker.uuid == task.worker_uuid:
                    continue
                estimate = self.tracker.estimate(worker.uuid, task.workload, cost)
                seconds = estimate.mean if estimate is not None and estimate.mean > 0 else mean
                if best is None or seconds < best[0]:
                    best = (seconds, entry)
            if best is None:
                continue
            seconds, entry = best
            if seconds < STEAL_RATIO * left and left - seconds >= STEAL_MIN_SAVING:
                entry[1] -= 1
                steals.append((task, entry[0]))
        return steals

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
                busy.append((worker, len(pcb.running) / compute_threads(worker)))
        return busy

    def should_avoid(self, task, cost, choice, estimates, workers, worker_pcbs, now) -> bool:
        """True if this task was just taken back from the chosen worker and some
        other usable worker (even one that is busy right now) is worth waiting for.

        Without this a task that timed out on a slow worker goes straight back to
        it whenever that is the only worker with a free slot, and times out again.
        But only a worker that is not much slower (AVOID_MAX_SLOWDOWN) counts:
        holding a heavy task for a device many times slower would be worse.
        """
        if getattr(task, "last_worker", None) != choice.uuid:
            return False
        own = estimates.get(choice.uuid)
        for worker in workers:
            if worker.uuid == choice.uuid or self.tracker.is_quarantined(worker.uuid, now):
                continue
            pcb = worker_pcbs.get(worker.uuid) if worker_pcbs else None
            if pcb is not None and not pcb.is_online:
                continue
            other = self.tracker.estimate(worker.uuid, task.workload, cost)
            if own is None or own.mean <= 0 or other is None:
                return True  # no basis to compare: prefer a different worker
            if other.mean <= AVOID_MAX_SLOWDOWN * own.mean:
                return True
        return False

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
            wait_finish = (held + 1) * estimate.mean  # held: queue per thread
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
