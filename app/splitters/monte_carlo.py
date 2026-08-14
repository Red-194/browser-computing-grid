from __future__ import annotations

from random import Random

from app.models.jobs import MonteCarloJob
from app.models.tasks import MonteCarloTaskConfig, Task


class MonteCarloSplitter:

    @staticmethod
    def split(
        job: MonteCarloJob) -> list[Task]:

        num_tasks = 4

        total_samples = job.config.samples

        if total_samples <= 0:
            raise ValueError("samples must be greater than zero")

        base_samples, remainder = divmod(total_samples, num_tasks)

        rng = Random(job.config.seed)

        tasks: list[Task] = []

        for task_index in range(num_tasks):

            samples = base_samples

            if task_index < remainder:
                samples += 1

            tasks.append(
                Task(
                    job_id=job.job_id,
                    task_id=task_index,
                    workload="monte_carlo",
                    config=MonteCarloTaskConfig(
                        samples=samples,
                        seed=rng.randrange(2**32),
                    ),
                )
            )

        return tasks