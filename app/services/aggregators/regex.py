import json


class RegexAggregator:
    """Add up match counts for each pattern."""

    result_type = "application/json"

    def __init__(self, config):
        self.patterns = config.patterns
        self.seen_task_ids: set[int] = set()
        self.per_pattern = [
            {
                "pattern": pattern,
                "texts_scanned": 0,
                "matched_texts": 0,
                "total_matches": 0,
                "limit_hits": 0,
                "compile_error": None,
                "total_time_ms": 0.0,
            }
            for pattern in config.patterns
        ]

    def add_result(self, result):
        task_id = result["_task_id"]
        if task_id in self.seen_task_ids:
            return  # duplicate result, ignore
        self.seen_task_ids.add(task_id)

        stats = self.per_pattern[result["pattern_id"]]
        stats["texts_scanned"] += result["texts_scanned"]
        stats["matched_texts"] += result["matched_texts"]
        stats["total_matches"] += result["total_matches"]
        stats["limit_hits"] += result["limit_hits"]
        stats["total_time_ms"] += result.get("_execution_time_ms") or 0.0
        if result.get("compile_error"):
            stats["compile_error"] = result["compile_error"]

    def is_complete(self, total_tasks):
        return len(self.seen_task_ids) >= total_tasks

    def get_result(self):
        return json.dumps(
            {"patterns": self.per_pattern}, separators=(",", ":")
        ).encode("utf-8")
