"""How much work a task is, as a single number.

The scheduler measures speed as "seconds per unit of work" so one worker's
speed on small tasks can be used to guess its time on big ones. The unit is
whatever is natural for the workload and only has to be consistent within it.

Where the size of a task cannot be known before running it (SAT),
the cost is 1, so the speed estimate becomes "seconds per task" and the spread
of the samples carries the uncertainty.
"""
import math


def _compression(config) -> float:
    return len(config.data_base64) * 3 / 4  # bytes in the chunk


def _regex(config) -> float:
    return sum(len(text) for text in config.texts)  # characters scanned


def _mandelbrot(config) -> float:
    return config.tile_size * config.tile_size * config.max_iterations


def _nqueens(config) -> float:
    """Search nodes under the fixed prefix, from a curve fitted to measured counts
    (about 490 nodes with 8 rows left, 5 million with 14, 68 million with 15).
    Right to within a factor of two or so, which is enough: what matters is that a
    task with the whole board left costs thousands of times a nearly finished one."""
    rows_left = max(0, config.n - len(config.prefix))
    return math.exp(0.341 * rows_left + 0.0542 * rows_left * rows_left)


def _unknown(config) -> float:
    return 1.0


_ESTIMATORS = {
    "compression": _compression,
    "regex": _regex,
    "mandelbrot": _mandelbrot,
    "nqueens": _nqueens,
    "sat": _unknown,
}


def task_cost(workload: str, config) -> float:
    """Work in `config`, never below 1."""
    estimator = _ESTIMATORS.get(workload, _unknown)
    try:
        return max(1.0, float(estimator(config)))
    except (AttributeError, TypeError):
        return 1.0


def cost_of(task) -> float:
    """Cost of a full Task object (has `workload` and `config`).

    Anything without those (a stand-in object in a test) counts as 1."""
    workload = getattr(task, "workload", None)
    config = getattr(task, "config", None)
    if workload is None or config is None:
        return 1.0
    return task_cost(workload, config)
