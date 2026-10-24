import random
from uuid import uuid4

from app.models.jobs import RegexJob
from app.models.tasks import RegexTaskConfig, Task

LETTERS = "abcdefghijklmnopqrstuvwxyz"


def make_texts(count, min_length, max_length, seed) -> list[str]:
    """Random lowercase strings with different lengths."""
    rng = random.Random(seed)
    return [
        "".join(rng.choices(LETTERS, k=rng.randint(min_length, max_length)))
        for _ in range(count)
    ]


class RegexSplitter:
    """One task per (pattern, batch of texts) pair."""

    @staticmethod
    def split(job: RegexJob) -> list[Task]:
        config = job.config

        if job.job_id is None:
            job.job_id = uuid4()

        if config.texts is not None:
            texts = config.texts
        else:
            s = config.synthetic_texts
            texts = make_texts(s.count, s.min_length, s.max_length, s.seed)

        tasks: list[Task] = []
        task_id = 0

        for pattern_id, pattern in enumerate(config.patterns):
            for batch_id, start in enumerate(range(0, len(texts), config.texts_per_task)):
                tasks.append(
                    Task(
                        job_id=job.job_id,
                        task_id=task_id,
                        workload="regex",
                        config=RegexTaskConfig(
                            pattern_id=pattern_id,
                            batch_id=batch_id,
                            pattern=pattern,
                            texts=texts[start:start + config.texts_per_task],
                            mode=config.mode,
                            backtrack_limit=config.backtrack_limit,
                        ),
                    )
                )
                task_id += 1

        return tasks
