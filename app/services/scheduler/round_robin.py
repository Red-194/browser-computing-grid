import logging

from .base import Scheduler, open_workers

logger = logging.getLogger("grid.scheduler")


class RoundRobinScheduler(Scheduler):
    """Baseline: hand tasks to the workers in turn, one each, skipping any
    that have no free slot. The turn carries over from one call to the next."""

    name = "round_robin"

    def __init__(self):
        self.index = 0

    def schedule(self, tasks, workers, worker_pcbs=None, costs=None, now=None):
        order = []
        free = {}
        for worker, slots in open_workers(workers, worker_pcbs):
            order.append(worker)
            free[worker.uuid] = slots

        if not order:
            logger.debug("Round-robin scheduler found no free workers for %d tasks", len(tasks))
            return []

        assignments = []
        for task in tasks:
            for step in range(len(order)):
                worker = order[(self.index + step) % len(order)]
                if free[worker.uuid] > 0:
                    free[worker.uuid] -= 1
                    assignments.append((task, worker))
                    self.index = (self.index + step + 1) % len(order)
                    break
            else:
                break  # every worker is full

        logger.debug(
            "Round-robin scheduler assigned %d tasks (%d slots left)",
            len(assignments),
            sum(free.values()),
        )
        return assignments
