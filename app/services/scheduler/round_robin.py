from ...models.worker import WorkerStates
import logging

logger = logging.getLogger("grid.scheduler")


class RoundRobinScheduler:

    def __init__(self):
        self.index = 0

    def schedule(self, tasks, workers):

        available_workers = [
            worker
            for worker in workers
            if worker.state == WorkerStates.IDLE
        ]

        if not available_workers:
            logger.debug("Round-robin scheduler found no idle workers for %d tasks", len(tasks))
            return []

        assignments = []

        for task in tasks:

            worker = available_workers[
                self.index % len(available_workers)
            ]

            assignments.append((task, worker))
            self.index += 1

        logger.debug(
            "Round-robin scheduler assigned %d tasks across %d workers",
            len(assignments),
            len(available_workers),
        )
        return assignments