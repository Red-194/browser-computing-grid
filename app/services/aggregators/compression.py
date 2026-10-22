import json


class CompressionAggregator:
    """Add up sizes and times for each compression variant."""

    result_type = "application/json"

    def __init__(self, config):
        self.seen_task_ids: set[int] = set()
        self.variants: dict[str, dict] = {}

    def add_result(self, result):
        task_id = result["_task_id"]
        if task_id in self.seen_task_ids:
            return  # duplicate result, ignore
        self.seen_task_ids.add(task_id)

        stats = self.variants.setdefault(
            result["variant"],
            {
                "chunks": 0,
                "original_bytes": 0,
                "compressed_bytes": 0,
                "roundtrip_failures": 0,
                "errors": [],
                "total_time_ms": 0.0,
            },
        )

        stats["chunks"] += 1
        stats["total_time_ms"] += result.get("_execution_time_ms") or 0.0

        if result.get("error"):
            stats["errors"].append(result["error"])
            return

        stats["original_bytes"] += result["original_size"]
        stats["compressed_bytes"] += result["compressed_size"]
        if not result["roundtrip_ok"]:
            stats["roundtrip_failures"] += 1

    def is_complete(self, total_tasks):
        return len(self.seen_task_ids) >= total_tasks

    def get_result(self):
        report = {}
        for name, stats in self.variants.items():
            original = stats["original_bytes"]
            seconds = stats["total_time_ms"] / 1000
            report[name] = {
                **stats,
                "ratio": round(stats["compressed_bytes"] / original, 4) if original else None,
                # Speed is total bytes over total worker time, not wall-clock time.
                "mb_per_second": round(original / 1_000_000 / seconds, 2) if seconds else None,
            }

        return json.dumps(report, separators=(",", ":")).encode("utf-8")
