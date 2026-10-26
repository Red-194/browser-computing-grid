from app.models.tasks import SATTaskConfig
from app.services.scheduler.cost import task_cost
from app.services.splitters.sat_batch import make_random_3sat


def sat_cost(num_variables, clauses, fixed=()):
    config = SATTaskConfig(
        num_variables=num_variables, clauses=clauses, fixed_assignments=list(fixed)
    )
    return task_cost("sat", config)


def formula(n, ratio, seed=1):
    return make_random_3sat(1, n, round(n * ratio), seed)[0].clauses


def test_bigger_formulas_cost_more():
    assert sat_cost(20, formula(20, 4.26)) < sat_cost(30, formula(30, 4.26)) < sat_cost(40, formula(40, 4.26))


def test_formula_near_the_hard_ratio_costs_more_than_an_easy_one():
    assert sat_cost(40, formula(40, 4.3)) > sat_cost(40, formula(40, 3.0))


def test_cube_that_conflicts_at_once_is_cheap():
    clauses = [[1], [2, 3, 4], [-2, 3, 4]]
    conflicting = sat_cost(10, clauses, [-1])
    surviving = sat_cost(10, clauses, [1])
    assert conflicting < surviving
    assert conflicting <= len(clauses)


def test_cube_with_contradictory_fixed_literals_is_cheap():
    assert sat_cost(10, [[1, 2, 3]], [1, -1]) == 1.0


def test_more_free_variables_cost_more_in_a_cube():
    clauses = formula(30, 4.26)
    assert sat_cost(30, clauses, [1, 2, 3, 4, 5, 6]) < sat_cost(30, clauses, [1])


def test_empty_formula_costs_one():
    assert sat_cost(5, []) == 1.0
