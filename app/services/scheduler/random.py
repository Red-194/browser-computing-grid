from ...models.worker import WorkerStates
import logging
import random

logger = logging.getLogger("grid.scheduler")


class RandomScheduler:

    def schedule(self, tasks, workers, worker_pcbs=None):

        available_workers = []
        for worker in workers:
            pcb = worker_pcbs.get(worker.uuid) if worker_pcbs else None
            if pcb is not None and not pcb.is_online:
                continue
            if pcb is None and worker.state != WorkerStates.IDLE:
                continue
            slots = pcb.capacity - len(pcb.running) if pcb else 1
            available_workers.extend([worker] * max(0, slots))

        if not available_workers:
            logger.debug("Random scheduler found no idle workers for %d tasks", len(tasks))
            return []

        assignments = []

        for task in tasks:
            if not available_workers:
                break
            worker = random.choice(available_workers)
            assignments.append((task, worker))
            available_workers.remove(worker)

        logger.debug(
            "Random scheduler assigned %d tasks across %d workers",
            len(assignments),
            len(available_workers),
        )
        return assignments