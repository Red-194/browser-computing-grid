from app.models.jobs import SATJob
from app.models.tasks import SATTaskConfig, Task
from uuid import uuid4


class SatSplitter:
    """Split a SAT instance into independent searches over variable cubes."""

    @staticmethod
    def split(job: SATJob) -> list[Task]:
        config = job.config
        tasks: list[Task] = []

        # The controller assigns this before dispatch, while direct splitter
        # use remains convenient for tests and library callers.
        if job.job_id is None:
            job.job_id = uuid4()

        # Each bit fixes one of the first split_depth variables.  A negative
        # literal means false and a positive literal means true.
        for task_id in range(1 << config.split_depth):
            fixed_assignments = [
                variable if task_id & (1 << (variable - 1)) else -variable
                for variable in range(1, config.split_depth + 1)
            ]

            tasks.append(
                Task(
                    job_id=job.job_id,
                    task_id=task_id,
                    workload="sat",
                    config=SATTaskConfig(
                        num_variables=config.num_variables,
                        clauses=config.clauses,
                        fixed_assignments=fixed_assignments,
                    ),
                )
            )

        return tasks


SATSplitter = SatSplitter
