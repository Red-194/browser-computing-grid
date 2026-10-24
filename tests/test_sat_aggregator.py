import json

from app.models.jobs import SATConfig
from app.services.aggregators.sat import SATAggregator


def test_sat_aggregator_finishes_early_when_a_worker_finds_a_model():
    aggregator = SATAggregator(
        SATConfig(num_variables=2, clauses=[[1, 2]], split_depth=1)
    )

    aggregator.add_result({"satisfiable": False, "model": None})
    assert not aggregator.is_complete(2)

    aggregator.add_result({"satisfiable": True, "model": [1, 2]})
    assert aggregator.is_complete(2)
    assert json.loads(aggregator.get_result()) == {
        "satisfiable": True,
        "model": [1, 2],
    }


def test_sat_aggregator_reports_unsatisfiable_after_all_cubes_finish():
    aggregator = SATAggregator(
        SATConfig(num_variables=1, clauses=[[1], [-1]], split_depth=1)
    )

    aggregator.add_result({"satisfiable": False, "model": None})
    aggregator.add_result({"satisfiable": False, "model": None})

    assert aggregator.is_complete(2)
    assert json.loads(aggregator.get_result()) == {
        "satisfiable": False,
        "model": None,
    }
