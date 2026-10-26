from math import ceil
from uuid import uuid4

from app.models.jobs import RayTracingJob
from app.models.tasks import RayTracingTaskConfig, Task


class RaytracingSplitter:
    """Create one independent render task for each 2D image tile."""

    @staticmethod
    def split(job: RayTracingJob) -> list[Task]:
        config = job.config
        if config.tile_size <= 0:
            raise ValueError("tile_size must be greater than zero")
        if job.job_id is None:
            job.job_id = uuid4()

        row_blocks = ceil(config.height / config.tile_size)
        col_blocks = ceil(config.width / config.tile_size)
        tasks: list[Task] = []

        for row in range(row_blocks):
            for col in range(col_blocks):
                tasks.append(
                    Task(
                        job_id=job.job_id,
                        task_id=row * col_blocks + col,
                        workload="raytracing",
                        config=RayTracingTaskConfig(
                            width=config.width,
                            height=config.height,
                            tile_size=config.tile_size,
                            row_block=row,
                            col_block=col,
                            samples_per_pixel=config.samples_per_pixel,
                            max_bounces=config.max_bounces,
                            scene=config.scene,
                        ),
                    )
                )

        return tasks
