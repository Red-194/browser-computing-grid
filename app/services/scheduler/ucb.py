import logging
import math

from .adaptive import AdaptiveScheduler

logger = logging.getLogger("grid.scheduler")

# How much a lightly sampled worker's finish time is discounted. Higher means
# more trying out of workers the scheduler is unsure about.
EXPLORATION = 0.5


class UcbScheduler(AdaptiveScheduler):
    """Fastest-first with an optimism bonus (upper confidence bound).

    A plain speed-aware scheduler can lock onto the first fast worker it sees
    and never notice that a slow-looking one has recovered (a tab brought back
    to the front, say). Here a worker with few samples for this workload has its
    expected finish time divided by `1 + EXPLORATION * sqrt(ln(N + 2) / (n + 1))`,
    where n is its own sample count and N the workload's total. The bonus fades
    as samples accumulate, so the scheduler explores early and exploits later.
    """

    name = "ucb"

    def pick(self, task, cost, candidates, estimates, guess):
        total = self.tracker.total_samples(task.workload)

        def score(c):
            seconds = self.seconds(estimates[c.uuid], guess)
            own = self.tracker.samples(c.uuid, task.workload)
            bonus = EXPLORATION * math.sqrt(math.log(total + 2) / (own + 1))
            return (c.finish_time(seconds) / (1 + bonus), -c.free, c.uuid)

        return min(candidates, key=score)
