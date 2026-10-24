import random
from uuid import uuid4

from app.models.jobs import SATBatchJob, SATInstance
from app.models.tasks import SATTaskConfig, Task


def make_random_3sat(count, num_variables, num_clauses, seed) -> list[SATInstance]:
    """Build `count` random 3-SAT formulas. The same seed gives the same formulas."""
    rng = random.Random(seed)
    instances = []

    for _ in range(count):
        clauses = []
        for _ in range(num_clauses):
            variables = rng.sample(range(1, num_variables + 1), 3)
            clauses.append([v if rng.random() < 0.5 else -v for v in variables])
        instances.append(SATInstance(num_variables=num_variables, clauses=clauses))

    return instances


class SatBatchSplitter:
    """One task per SAT instance. Instances are fully independent."""

    @staticmethod
    def split(job: SATBatchJob) -> list[Task]:
        config = job.config

        if job.job_id is None:
            job.job_id = uuid4()

        if config.instances is not None:
            instances = config.instances
        else:
            r = config.random_3sat
            instances = make_random_3sat(
                r.count, r.num_variables, r.num_clauses, r.seed
            )

        # Workers run these with the normal "sat" kernel and no fixed variables.
        return [
            Task(
                job_id=job.job_id,
                task_id=index,
                workload="sat",
                config=SATTaskConfig(
                    num_variables=instance.num_variables,
                    clauses=instance.clauses,
                    fixed_assignments=[],
                ),
            )
            for index, instance in enumerate(instances)
        ]
