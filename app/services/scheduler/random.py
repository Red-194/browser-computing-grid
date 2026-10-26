import logging
import random

from .base import Scheduler, open_workers

logger = logging.getLogger("grid.scheduler")


class RandomScheduler(Scheduler):
    """Baseline: give each task to a random worker that has a free slot."""

    name = "random"

    def schedule(self, tasks, workers, worker_pcbs=None, costs=None, now=None):
        slots = []
        for worker, free in open_workers(workers, worker_pcbs):
            slots.extend([worker] * free)

        if not slots:
            logger.debug("Random scheduler found no free workers for %d tasks", len(tasks))
            return []

        assignments = []
        for task in tasks:
            if not slots:
                break
            worker = random.choice(slots)
            assignments.append((task, worker))
            slots.remove(worker)

        logger.debug(
            "Random scheduler assigned %d tasks (%d slots left)",
            len(assignments),
            len(slots),
        )
        return assignments
