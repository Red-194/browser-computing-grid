import base64
import random
from uuid import uuid4

from app.models.jobs import CompressionJob
from app.models.tasks import CompressionTaskConfig, Task

WORDS = [
    "grid", "worker", "browser", "task", "kernel", "result", "chunk",
    "socket", "latency", "compute", "node", "queue", "buffer", "stream",
]


def make_test_data(size: int, seed: int) -> bytes:
    """Text-like data that compresses well, with some random bytes mixed in."""
    rng = random.Random(seed)
    parts = []
    length = 0

    while length < size:
        if rng.random() < 0.9:
            piece = (rng.choice(WORDS) + " ").encode()
        else:
            piece = rng.randbytes(rng.randint(4, 32))
        parts.append(piece)
        length += len(piece)

    return b"".join(parts)[:size]


class CompressionSplitter:
    """One task per (chunk, variant) pair."""

    @staticmethod
    def split(job: CompressionJob) -> list[Task]:
        config = job.config

        if job.job_id is None:
            job.job_id = uuid4()

        if config.data_base64 is not None:
            data = base64.b64decode(config.data_base64)
        else:
            data = make_test_data(config.synthetic_size, config.seed)

        tasks: list[Task] = []
        task_id = 0

        for chunk_id, start in enumerate(range(0, len(data), config.chunk_size)):
            chunk = data[start:start + config.chunk_size]
            encoded = base64.b64encode(chunk).decode("ascii")

            for variant in config.variants:
                tasks.append(
                    Task(
                        job_id=job.job_id,
                        task_id=task_id,
                        workload="compression",
                        config=CompressionTaskConfig(
                            variant=variant,
                            chunk_id=chunk_id,
                            data_base64=encoded,
                        ),
                    )
                )
                task_id += 1

        return tasks
