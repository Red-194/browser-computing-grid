from ...models.worker import WorkerStates


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
            return []

        assignments = []

        for task in tasks:

            worker = available_workers[
                self.index % len(available_workers)
            ]

            assignments.append((task, worker))
            self.index += 1

        return assignments