from math import ceil

from app.models.jobs import MatrixMultiplyJob
from app.models.tasks import MatrixMultiplyTaskConfig, Task


class MatrixMultiplySplitter:

    @staticmethod
    def split(job: MatrixMultiplyJob) -> list[Task]:

        rows = job.config.rows
        cols = job.config.cols
        block_size = job.config.block_size

        if block_size <= 0:
            raise ValueError("block_size must be greater than zero")

        row_blocks = ceil(rows / block_size)
        col_blocks = ceil(cols / block_size)

        tasks: list[Task] = []
        task_ctr = 0

        for row in range(row_blocks):
            for col in range(col_blocks):
                tasks.append(
                    Task(
                        job_id=job.job_id,
                        task_id=task_ctr,
                        workload="matrix_multiply",
                        config=MatrixMultiplyTaskConfig(
                            rows=rows,
                            cols=cols,
                            block_size=block_size,
                            row_block=row,
                            col_block=col,
                            random=job.config.random,
                        ),
                    )
                )
                task_ctr += 1

        return tasks