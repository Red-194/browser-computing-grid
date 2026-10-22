from uuid import uuid4

from app.models.jobs import NQueensJob
from app.models.tasks import NQueensTaskConfig, Task


def valid_prefixes(n: int, depth: int) -> list[list[int]]:
    """All ways to place queens on the first `depth` rows with no attacks."""
    prefixes: list[list[int]] = []

    def place(prefix: list[int]):
        if len(prefix) == depth:
            prefixes.append(list(prefix))
            return

        row = len(prefix)
        for col in range(n):
            # Attacked if an earlier queen shares the column or a diagonal.
            if all(
                col != c and abs(col - c) != row - r
                for r, c in enumerate(prefix)
            ):
                prefix.append(col)
                place(prefix)
                prefix.pop()

    place([])
    return prefixes


class NqueensSplitter:
    """One task per valid prefix. Tasks differ a lot in size."""

    @staticmethod
    def split(job: NQueensJob) -> list[Task]:
        config = job.config

        if job.job_id is None:
            job.job_id = uuid4()

        return [
            Task(
                job_id=job.job_id,
                task_id=task_id,
                workload="nqueens",
                config=NQueensTaskConfig(n=config.n, prefix=prefix),
            )
            for task_id, prefix in enumerate(valid_prefixes(config.n, config.split_depth))
        ]
