"""How much work a task is, as a single number.

The scheduler measures speed as "seconds per unit of work" so one worker's
speed on small tasks can be used to guess its time on big ones. The unit is
whatever is natural for the workload and only has to be consistent within it.

Where the size of a task cannot be known before running it, the cost is 1, so
the speed estimate becomes "seconds per task" and the spread of the samples
carries the uncertainty. SAT is only partly knowable: see `_sat`.
"""
import math


def _compression(config) -> float:
    return len(config.data_base64) * 3 / 4  # bytes in the chunk


def _regex(config) -> float:
    return sum(len(text) for text in config.texts)  # characters scanned


# Mandelbrot: a tile's cost is its pixel count times the average iterations per
# pixel, and that varies enormously (a pixel outside the set leaves in a few
# iterations, one inside runs to max_iterations). It is estimated from a small
# grid of sample pixels run for a few iterations. A sample that has not escaped
# by then is assumed to run to max_iterations: slightly pessimistic for pixels
# near the edge of the set, right for the ones inside it.
MANDELBROT_SAMPLES = 4  # samples per side, so 16 per tile
MANDELBROT_SAMPLE_ITERATIONS = 64


def _mandelbrot(config) -> float:
    start_x = config.col_block * config.tile_size
    start_y = config.row_block * config.tile_size
    tile_width = min(config.tile_size, max(0, config.width - start_x))
    tile_height = min(config.tile_size, max(0, config.height - start_y))
    pixels = tile_width * tile_height
    if pixels <= 0:
        return 1.0

    dx = (config.x_max - config.x_min) / config.width
    dy = (config.y_max - config.y_min) / config.height
    cap = min(config.max_iterations, MANDELBROT_SAMPLE_ITERATIONS)

    total = 0
    for row in range(MANDELBROT_SAMPLES):
        cy = config.y_min + (start_y + (row + 0.5) * tile_height / MANDELBROT_SAMPLES) * dy
        for col in range(MANDELBROT_SAMPLES):
            cx = config.x_min + (start_x + (col + 0.5) * tile_width / MANDELBROT_SAMPLES) * dx
            zx = zy = 0.0
            iteration = 0
            while zx * zx + zy * zy <= 4.0 and iteration < cap:
                zx, zy = zx * zx - zy * zy + cx, 2.0 * zx * zy + cy
                iteration += 1
            total += config.max_iterations if iteration == cap else iteration

    return pixels * total / (MANDELBROT_SAMPLES * MANDELBROT_SAMPLES)


def _nqueens(config) -> float:
    """Search nodes under the fixed prefix, from a curve fitted to measured counts
    (about 490 nodes with 8 rows left, 5 million with 14, 68 million with 15).
    Right to within a factor of two or so, which is enough: what matters is that a
    task with the whole board left costs thousands of times a nearly finished one."""
    rows_left = max(0, config.n - len(config.prefix))
    return math.exp(0.341 * rows_left + 0.0542 * rows_left * rows_left)


# SAT: the kernel is plain DPLL, so a task's time is the number of clause visits,
# and that depends on the formula far more than on its size. Fitted on 1,050
# random 3-SAT instances (20 to 45 variables, 3 to 6 clauses per variable) with a
# Python port of the kernel (scripts/sat_cost_study.py): the estimate ranks cost
# with Spearman 0.83 and is off by about 2.2x. Instances with the same size still
# differ by up to 30x, so that is the limit of any estimate made before running.
# Hard instances sit near 4.3 clauses per variable.
SAT_FIT = (-5.5035, 0.003, 2.9068, 0.0298)
SAT_HARD_RATIO = 4.3
# Cube tasks (a fixed prefix of variables): the fixed literals are applied and
# unit propagation run first, which is cheap. A cube that conflicts there ends
# after one pass (15x cheaper than the rest on average); otherwise the cost grows
# with the variables still free (fit on 5-variable cubes of 40-variable formulas,
# Spearman 0.42 within the cubes that survive, 0.76 including the conflicts).
SAT_CUBE_SLOPE = 0.104
SAT_CUBE_OFFSET = -0.232


def _sat_propagate(num_variables, clauses, fixed):
    """Apply `fixed` and unit-propagate. Returns the number of free variables, or
    None if that already conflicts."""
    value = [0] * (num_variables + 1)
    for literal in fixed:
        sign = 1 if literal > 0 else -1
        if value[abs(literal)] not in (0, sign):
            return None
        value[abs(literal)] = sign

    changed = True
    while changed:
        changed = False
        for clause in clauses:
            unassigned = 0
            unit = 0
            for literal in clause:
                current = value[abs(literal)] * (1 if literal > 0 else -1)
                if current == 1:
                    break
                if current == 0:
                    unassigned += 1
                    unit = literal
            else:
                if unassigned == 0:
                    return None
                if unassigned == 1:
                    value[abs(unit)] = 1 if unit > 0 else -1
                    changed = True

    return sum(1 for variable in range(1, num_variables + 1) if value[variable] == 0)


def _sat(config) -> float:
    n = config.num_variables
    m = len(config.clauses)
    if m == 0 or n <= 0:
        return 1.0

    if config.fixed_assignments:
        free = _sat_propagate(n, config.clauses, config.fixed_assignments)
        if free is None:
            return float(m)
        return m * math.exp(SAT_CUBE_SLOPE * free + SAT_CUBE_OFFSET)

    intercept, per_variable, per_log_clause, hard_weight = SAT_FIT
    ratio = m / n
    hardness = n * math.exp(-((ratio - SAT_HARD_RATIO) ** 2))
    return math.exp(
        intercept + per_variable * n + per_log_clause * math.log(m) + hard_weight * hardness
    )


def _unknown(config) -> float:
    return 1.0


_ESTIMATORS = {
    "compression": _compression,
    "regex": _regex,
    "mandelbrot": _mandelbrot,
    "nqueens": _nqueens,
    "sat": _sat,
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
