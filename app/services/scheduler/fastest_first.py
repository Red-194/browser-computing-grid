import logging

from .adaptive import AdaptiveScheduler

logger = logging.getLogger("grid.scheduler")


class FastestFirstScheduler(AdaptiveScheduler):
    """Give each task to the worker that would finish it soonest.

    Finish time counts what the worker already holds, so a fast worker is
    filled up first but a slow one is still used once the fast ones have queues.
    A worker with no history of its own is assumed to be about average (see
    stats.py), so it still gets a fair share and its speed is learned.
    """

    name = "fastest_first"

    def pick(self, task, cost, candidates, estimates, guess):
        return min(
            candidates,
            key=lambda c: (
                c.finish_time(self.seconds(estimates[c.uuid], guess)),
                -c.free,
                c.uuid,
            ),
        )
