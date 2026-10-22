import json


class NqueensAggregator:
    """Add up solutions and search nodes. Also tracks the slowest task."""

    result_type = "application/json"

    def __init__(self, config):
        self.n = config.n
        self.seen_task_ids: set[int] = set()
        self.solutions = 0
        self.nodes = 0
        self.task_nodes: list[int] = []
        self.task_times_ms: list[float] = []

    def add_result(self, result):
        task_id = result["_task_id"]
        if task_id in self.seen_task_ids:
            return  # duplicate result, ignore
        self.seen_task_ids.add(task_id)

        self.solutions += result["solutions"]
        self.nodes += result["nodes"]
        self.task_nodes.append(result["nodes"])
        if result.get("_execution_time_ms") is not None:
            self.task_times_ms.append(result["_execution_time_ms"])

    def is_complete(self, total_tasks):
        return len(self.seen_task_ids) >= total_tasks

    def get_result(self):
        return json.dumps(
            {
                "n": self.n,
                "solutions": self.solutions,
                "nodes": self.nodes,
                "tasks": len(self.task_nodes),
                # Big gap between smallest and largest = uneven tasks (stragglers).
                "min_task_nodes": min(self.task_nodes, default=None),
                "max_task_nodes": max(self.task_nodes, default=None),
                "max_task_time_ms": max(self.task_times_ms, default=None),
            },
            separators=(",", ":"),
        ).encode("utf-8")
