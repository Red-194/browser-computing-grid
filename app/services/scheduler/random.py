from ...models.worker import WorkerStates
import random


class RandomScheduler:

    def schedule(self, tasks, workers):

        available_workers = [
            worker
            for worker in workers
            if worker.state == WorkerStates.IDLE
        ]

        if not available_workers:
            return []

        assignments = []

        for task in tasks:
            worker = random.choice(available_workers)
            assignments.append((task, worker))

        return assignments