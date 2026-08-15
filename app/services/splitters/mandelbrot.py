from math import ceil

from app.models.jobs import JobSubmission
from app.models.tasks import MandelbrotTaskConfig, Task


class MandelbrotSplitter:

    @staticmethod
    def split(job: JobSubmission) -> list[Task]:

        config = job.config

        if config["tile_size"] <= 0:
            raise ValueError("tile_size must be greater than zero")

        row_blocks = ceil(
            config["height"] / config["tile_size"]
        )

        col_blocks = ceil(
            config["width"] / config["tile_size"]
        )

        tasks: list[Task] = []
        task_ctr = 0

        for row in range(row_blocks):
            for col in range(col_blocks):

                tasks.append(
                    Task(
                        job_id=job.job_id,
                        task_id=task_ctr,
                        workload="mandelbrot",
                        config=MandelbrotTaskConfig(
                            width=config["width"],
                            height=config["height"],
                            x_min=config["x_min"],
                            x_max=config["x_max"],
                            y_min=config["y_min"],
                            y_max=config["y_max"],
                            max_iterations=config["max_iterations"],
                            tile_size=config["tile_size"],
                            row_block=row,
                            col_block=col,
                        ),
                    )
                )

                task_ctr += 1

        return tasks