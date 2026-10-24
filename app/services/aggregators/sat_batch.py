import json


class SatBatchAggregator:
    """Collect one SAT answer per instance."""

    result_type = "application/json"

    def __init__(self, config):
        # task id == instance index (set by SatBatchSplitter)
        self.results: dict[int, dict] = {}

    def add_result(self, result):
        task_id = result["_task_id"]
        if task_id in self.results:
            return  # duplicate result, ignore

        self.results[task_id] = {
            "instance": task_id,
            "satisfiable": bool(result.get("satisfiable")),
            "model": result.get("model"),
            "time_ms": result.get("_execution_time_ms"),
        }

    def is_complete(self, total_tasks):
        return len(self.results) >= total_tasks

    def get_result(self):
        ordered = [self.results[i] for i in sorted(self.results)]
        times = [r["time_ms"] for r in ordered if r["time_ms"] is not None]
        satisfiable = sum(1 for r in ordered if r["satisfiable"])

        return json.dumps(
            {
                "instances": len(ordered),
                "satisfiable": satisfiable,
                "unsatisfiable": len(ordered) - satisfiable,
                "min_time_ms": min(times) if times else None,
                "max_time_ms": max(times) if times else None,
                "results": ordered,
            },
            separators=(",", ":"),
        ).encode("utf-8")
