import logging

from .adaptive import AdaptiveScheduler

logger = logging.getLogger("grid.scheduler")

# A retried task goes only to workers at least this reliable, if there are any.
RETRY_MIN_RELIABILITY = 0.5
# How strongly an unreliable worker's finish time is inflated.
UNRELIABLE_PENALTY = 2.0


class BoincScheduler(AdaptiveScheduler):
    """Adaptive scheduling in the style of BOINC.

    Three ideas taken from BOINC's server:

    * Projected speed per (worker, workload) from measured runtimes, falling
      back to the workload average when a worker has too few samples
      (see stats.py).
    * Job size matching: the biggest tasks are handed out first, each to the
      worker that would finish it soonest, so big tasks land on fast workers
      and small ones fill the gaps.
    * Retries ("accelerated retry"): a task that has already been lost or timed
      out goes first, and only to reliable workers.

    A worker nobody has measured yet is tried out with the smallest waiting
    task, so a slow newcomer cannot hold up a big one.
    """

    name = "boinc"

    def before(self, tasks, candidates, costs, assignments):
        """Cold start: one small task for each worker that has no estimate."""
        if not tasks:
            return tasks

        workload = tasks[0].workload
        remaining = sorted(tasks, key=lambda t: (t.retries > 0, costs.get(t.key, 1.0), t.task_id))
        for candidate in candidates:
            if not remaining:
                break
            if candidate.free > 0 and self.tracker.estimate(candidate.uuid, workload, 1.0) is None:
                task = remaining.pop(0)
                self.give(candidate, task, None, self.guess({}), assignments)
        return remaining

    def order(self, tasks, costs):
        # Retries first, then the biggest tasks.
        return sorted(tasks, key=lambda t: (t.retries == 0, -costs.get(t.key, 1.0), t.task_id))

    def pick(self, task, cost, candidates, estimates, guess):
        pool = candidates
        if task.retries > 0:
            reliable = [
                c for c in candidates
                if self.tracker.reliability(c.uuid) >= RETRY_MIN_RELIABILITY
            ]
            pool = reliable or candidates

        def score(c):
            finish = c.finish_time(self.seconds(estimates[c.uuid], guess))
            reliability = self.tracker.reliability(c.uuid)
            return (finish * (1 + UNRELIABLE_PENALTY * (1 - reliability)), -c.free, c.uuid)

        return min(pool, key=score)
