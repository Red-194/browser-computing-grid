from uuid import uuid4

from app.models.jobs import SATJob
from app.services.splitters.sat import SATSplitter


def test_sat_splitter_creates_one_cube_per_prefix_assignment():
    job = SATJob(
        job_id=uuid4(),
        workload="sat",
        config={
            "num_variables": 3,
            "clauses": [[1, 2], [-1, 3]],
            "split_depth": 2,
        },
    )

    tasks = SATSplitter.split(job)

    assert [task.task_id for task in tasks] == [0, 1, 2, 3]
    assert all(task.workload == "sat" for task in tasks)
    assert all(task.job_id == job.job_id for task in tasks)
    assert [task.config.fixed_assignments for task in tasks] == [
        [-1, -2], [1, -2], [-1, 2], [1, 2],
    ]
