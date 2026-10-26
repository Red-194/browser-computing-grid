"""How much work a task is, as a single number.

The scheduler measures speed as "seconds per unit of work" so one worker's
speed on small tasks can be used to guess its time on big ones. The unit is
whatever is natural for the workload and only has to be consistent within it.

Where the size of a task cannot be known before running it, the cost is 1, so
the speed estimate becomes "seconds per task" and the spread of the samples
carries the uncertainty. SAT is only partly knowable: see `_sat`.
"""
import hashlib
import math
import random


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


# Ray tracing: sample a small, fixed grid of camera rays through each tile and
# follow the same sphere/shadow/reflection decisions as the Rust kernel. Scale
# those observed operations to the whole tile and samples-per-pixel count.
RAYTRACING_COST_SAMPLES = 4
RAY_EPSILON = 1e-4


def _rt_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _rt_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _rt_scale(v, amount):
    return (v[0] * amount, v[1] * amount, v[2] * amount)


def _rt_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _rt_normalize(v):
    length = math.sqrt(_rt_dot(v, v))
    if length <= 1e-15:
        return (0.0, 0.0, 0.0)
    return _rt_scale(v, 1.0 / length)


def _rt_cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _rt_hit(origin, direction, sphere, minimum=RAY_EPSILON, maximum=math.inf):
    offset = _rt_sub(origin, sphere.center)
    half_b = _rt_dot(offset, direction)
    c = _rt_dot(offset, offset) - sphere.radius * sphere.radius
    discriminant = half_b * half_b - c
    if discriminant < 0.0:
        return None
    root = math.sqrt(discriminant)
    distance = -half_b - root
    if distance <= minimum or distance >= maximum:
        distance = -half_b + root
        if distance <= minimum or distance >= maximum:
            return None
    point = _rt_add(origin, _rt_scale(direction, distance))
    normal = _rt_normalize(_rt_sub(point, sphere.center))
    return distance, point, normal


def _rt_trace_cost(origin, direction, scene, depth, max_bounces):
    """Count approximate renderer operations for one primary/secondary ray."""
    counters = {"rays": 1, "sphere_tests": 0, "light_samples": 0}
    nearest = None
    nearest_index = -1
    closest = math.inf
    for index, sphere in enumerate(scene.spheres):
        counters["sphere_tests"] += 1
        hit = _rt_hit(origin, direction, sphere, maximum=closest)
        if hit is not None:
            closest = hit[0]
            nearest = hit
            nearest_index = index

    if nearest is None:
        return counters

    _, point, normal = nearest
    sphere = scene.spheres[nearest_index]
    for light in scene.lights:
        to_light = _rt_sub(light.position, point)
        light_distance = math.sqrt(_rt_dot(to_light, to_light))
        if light_distance <= RAY_EPSILON:
            continue
        light_direction = _rt_scale(to_light, 1.0 / light_distance)
        if _rt_dot(normal, light_direction) <= 0.0:
            continue
        counters["light_samples"] += 1
        shadow_origin = _rt_add(point, _rt_scale(normal, RAY_EPSILON))
        counters["rays"] += 1
        for index, other in enumerate(scene.spheres):
            if index == nearest_index:
                continue
            counters["sphere_tests"] += 1
            if _rt_hit(
                shadow_origin,
                light_direction,
                other,
                maximum=light_distance - RAY_EPSILON,
            ) is not None:
                break

    if sphere.reflectivity > 0.0 and depth < max_bounces:
        reflected = _rt_sub(
            direction,
            _rt_scale(normal, 2.0 * _rt_dot(direction, normal)),
        )
        child = _rt_trace_cost(
            _rt_add(point, _rt_scale(normal, RAY_EPSILON)),
            _rt_normalize(reflected),
            scene,
            depth + 1,
            max_bounces,
        )
        for key, value in child.items():
            counters[key] += value
    return counters


def _raytracing(config) -> float:
    start_x = config.col_block * config.tile_size
    start_y = config.row_block * config.tile_size
    tile_width = min(config.tile_size, max(0, config.width - start_x))
    tile_height = min(config.tile_size, max(0, config.height - start_y))
    if tile_width <= 0 or tile_height <= 0:
        return 1.0

    scene = config.scene
    camera = scene.camera
    forward = _rt_normalize(_rt_sub(camera.look_at, camera.position))
    right = _rt_normalize(_rt_cross(forward, (0.0, 1.0, 0.0)))
    if _rt_dot(right, right) <= 1e-15:
        right = (1.0, 0.0, 0.0)
    up = _rt_normalize(_rt_cross(right, forward))
    half_height = math.tan(math.radians(camera.vertical_fov_degrees) * 0.5)
    aspect = config.width / config.height
    total = 0.0

    for sample_y in range(RAYTRACING_COST_SAMPLES):
        pixel_y = start_y + (sample_y + 0.5) * tile_height / RAYTRACING_COST_SAMPLES
        screen_y = (1.0 - 2.0 * pixel_y / config.height) * half_height
        for sample_x in range(RAYTRACING_COST_SAMPLES):
            pixel_x = start_x + (sample_x + 0.5) * tile_width / RAYTRACING_COST_SAMPLES
            screen_x = (2.0 * pixel_x / config.width - 1.0) * aspect * half_height
            direction = _rt_normalize(
                _rt_add(
                    forward,
                    _rt_add(_rt_scale(right, screen_x), _rt_scale(up, screen_y)),
                )
            )
            work = _rt_trace_cost(
                camera.position, direction, scene, depth=0, max_bounces=config.max_bounces
            )
            # These are deterministic estimated work units, not milliseconds.
            total += work["rays"] + work["sphere_tests"] + work["light_samples"]

    sample_count = RAYTRACING_COST_SAMPLES ** 2
    return max(
        1.0,
        total / sample_count * tile_width * tile_height * config.samples_per_pixel,
    )

NQUEENS_EXACT_DEPTH = 2
NQUEENS_PROBES_PER_FRONTIER = 16

def _nqueens_state(config):
    """Convert an N-Queens prefix into the board state used by the solver."""
    n = config.n

    if n <= 0 or n > 32:
        return None

    full = (1 << n) - 1

    cols = 0
    diag1 = 0
    diag2 = 0

    for col in config.prefix:
        if col < 0 or col >= n:
            return None

        bit = 1 << col

        if bit & (cols | diag1 | diag2):
            return None

        cols |= bit
        diag1 = ((diag1 | bit) << 1) & full
        diag2 = ((diag2 | bit) >> 1)

    return full, cols, diag1, diag2


def _nqueens_children(state):
    """Generate all legal next states."""
    full, cols, diag1, diag2 = state

    free = full & ~(cols | diag1 | diag2)

    children = []

    while free:
        bit = free & -free
        free ^= bit

        children.append(
            (
                full,
                cols | bit,
                ((diag1 | bit) << 1) & full,
                (diag2 | bit) >> 1,
            )
        )

    return children


def _knuth_probe(state, rng):
    """
    Estimate the remaining search-tree size by following
    one random root-to-leaf path.
    """
    total = 0.0
    path_count = 1.0
    current = state

    while True:
        children = _nqueens_children(current)

        if not children:
            return total

        path_count *= len(children)
        total += path_count

        current = rng.choice(children)


def _nqueens_partial_backtrack(
    state,
    exact_depth=NQUEENS_EXACT_DEPTH,
    probes=NQUEENS_PROBES_PER_FRONTIER,
    rng=None,
):
    """
    Explore the first few levels exactly, then estimate each
    resulting subtree using Knuth probes.
    """
    if rng is None:
        rng = random.Random(0)

    frontier = [state]
    exact_nodes = 0

    # Explore the first levels exactly.
    for _ in range(exact_depth):
        next_frontier = []

        for node in frontier:
            children = _nqueens_children(node)

            exact_nodes += len(children)
            next_frontier.extend(children)

        frontier = next_frontier

        if not frontier:
            return float(exact_nodes)

    # Estimate every remaining subtree independently.
    estimated = float(exact_nodes)

    for node in frontier:
        samples = [
            _knuth_probe(node, rng)
            for _ in range(probes)
        ]

        estimated += sum(samples) / len(samples)

    return estimated


def _nqueens(config):
    """
    Estimate N-Queens work from the actual prefix/search-tree state.

    The estimate is expressed in search nodes, matching the `nodes`
    counter produced by the Rust N-Queens kernel.
    """
    state = _nqueens_state(config)

    if state is None:
        return 1.0

    rows_left = config.n - len(config.prefix)

    if rows_left <= 0:
        return 1.0

    # Deterministic seed for this particular N-Queens task.
    seed_material = (
        f"{config.n}:{','.join(map(str, config.prefix))}"
    ).encode()

    seed = int.from_bytes(
        hashlib.sha256(seed_material).digest()[:8],
        "big",
    )

    rng = random.Random(seed)

    exact_depth = min(
        NQUEENS_EXACT_DEPTH,
        rows_left,
    )

    return max(
        1.0,
        _nqueens_partial_backtrack(
            state,
            exact_depth=exact_depth,
            probes=NQUEENS_PROBES_PER_FRONTIER,
            rng=rng,
        ),
    )

# SAT: the kernel is plain DPLL, so a task's time is the number of clause visits,
# and that depends on the formula far more than on its size. Fitted on 1,050
# random 3-SAT instances (20 to 45 variables, 3 to 6 clauses per variable) with a
# Python port of the kernel (scripts/sat_cost_study.py): the estimate ranks cost
# with Spearman 0.83 and is off by about 2.2x. Instances with the same size still
# differ by up to 30x, so that is the limit of any estimate made before running.
# Hard instances sit near 4.3 clauses per variable.
SAT_FIT = (-5.5035, 0.003, 2.9068, 0.0298)
SAT_HARD_RATIO = 4.3
# Cube tasks (a fixed prefix of variables) are priced by Knuth's tree-size
# estimate: walk down the kernel's own search tree a few times, choosing a random
# branch at each step, and weight each node by 2 per branching on the way down.
# The average is an unbiased estimate of the clause visits of the whole tree. On
# 320 cubes of 45-variable formulas it ranks cost with Spearman 0.94 (8 dives), against 0.68
# for the closed-form model above applied to the cube (and 0.42 for the variable
# count). It does not help whole instances (0.50 against 0.60): the kernel stops
# at the first model, so a satisfiable instance costs less than its whole tree.
# Dives cost time at submit, on the controller's event loop: about 1 ms a dive at
# 60 variables, 3.5 ms a task with 3 dives (Spearman 0.85 on 256 cubes of 60
# variables; 1 dive 0.77, 4 dives 0.86, 8 dives 0.92 at 9 ms). A job of thousands
# of cubes therefore pays seconds once, when it is submitted.
SAT_DIVES = 3


def _sat_dive(num_variables, clauses, fixed, rng) -> float:
    """One random descent of the search tree: the clause visits it implies."""
    value = [0] * (num_variables + 1)
    for literal in fixed:
        sign = 1 if literal > 0 else -1
        if value[abs(literal)] not in (0, sign):
            return float(len(clauses))  # contradictory prefix: one pass
        value[abs(literal)] = sign

    estimate, weight = 0.0, 1.0
    while True:
        visits, conflict, changed = 0, False, True
        while changed and not conflict:
            changed = False
            for clause in clauses:
                visits += 1
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
                        conflict = True
                        break
                    if unassigned == 1:
                        changed |= value[abs(unit)] == 0
                        value[abs(unit)] = 1 if unit > 0 else -1
        estimate += weight * visits
        if conflict:
            return estimate
        free = next((v for v in range(1, num_variables + 1) if value[v] == 0), None)
        if free is None:
            return estimate  # every variable set: a model
        weight *= 2
        value[free] = 1 if rng.random() < 0.5 else -1


def _sat_cube(config) -> float:
    rng = random.Random(f"{config.num_variables}-{len(config.clauses)}-{config.fixed_assignments}")
    return sum(
        _sat_dive(config.num_variables, config.clauses, config.fixed_assignments, rng)
        for _ in range(SAT_DIVES)
    ) / SAT_DIVES


def _sat(config) -> float:
    n = config.num_variables
    m = len(config.clauses)
    if m == 0 or n <= 0:
        return 1.0

    if config.fixed_assignments:
        return _sat_cube(config)

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
    "raytracing": _raytracing,
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
