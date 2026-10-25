from ...models.worker import WorkerStates
import logging
import random

logger = logging.getLogger("grid.scheduler")


class RandomScheduler:

    def schedule(self, tasks, workers):

        available_workers = [
            worker
            for worker in workers
            if worker.state == WorkerStates.IDLE
        ]

        if not available_workers:
            logger.debug("Random scheduler found no idle workers for %d tasks", len(tasks))
            return []

        assignments = []

        for task in tasks:
            worker = random.choice(available_workers)
            assignments.append((task, worker))

        logger.debug(
            "Random scheduler assigned %d tasks across %d workers",
            len(assignments),
            len(available_workers),
        )
        return assignments