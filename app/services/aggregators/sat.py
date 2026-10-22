import json


class SatAggregator:
    """Combine independent SAT-cube results into one JSON answer."""

    result_type = "application/json"

    def __init__(self, config):
        self.num_variables = config.num_variables
        self.completed_tasks = 0
        self.satisfying_model: list[int] | None = None
        self.completed_task_ids: set[int] = set()

    def add_result(self, result):
        # A SAT result is decisive.  Later in-flight tasks can be ignored.
        task_id = result.get("_task_id")
        if self.satisfying_model is not None or (
            task_id is not None and task_id in self.completed_task_ids
        ):
            return

        if result.get("satisfiable"):
            model = result.get("model")
            if not isinstance(model, list):
                raise ValueError("SAT result is missing its satisfying model")
            self.satisfying_model = model
            return

        if task_id is not None:
            self.completed_task_ids.add(task_id)
        self.completed_tasks += 1

    def is_complete(self, total_tasks):
        return self.satisfying_model is not None or self.completed_tasks >= total_tasks

    def get_result(self):
        return json.dumps(
            {
                "satisfiable": self.satisfying_model is not None,
                "model": self.satisfying_model,
            },
            separators=(",", ":"),
        ).encode("utf-8")


SATAggregator = SatAggregator
