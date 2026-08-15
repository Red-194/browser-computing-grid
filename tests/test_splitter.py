from uuid import uuid4

from app.models.jobs import JobSubmission
from app.services.splitters.mandelbrot import MandelbrotSplitter


def test_mandelbrot_splitter():

    job = JobSubmission(
        job_id=uuid4(),
        workload="mandelbrot",
        config={
            "width": 256,
            "height": 256,
            "x_min": -2.5,
            "x_max": 1.0,
            "y_min": -1.0,
            "y_max": 1.0,
            "max_iterations": 500,
            "tile_size": 128,
        },
    )

    tasks = MandelbrotSplitter.split(job)

    assert len(tasks) == 4

    assert all(
        task.workload == "mandelbrot"
        for task in tasks
    )

    assert all(
        task.job_id == job.job_id
        for task in tasks
    )

    assert [task.task_id for task in tasks] == [0, 1, 2, 3]

    positions = {
        (task.config.row_block, task.config.col_block)
        for task in tasks
    }

    assert positions == {
        (0, 0),
        (0, 1),
        (1, 0),
        (1, 1),
    }