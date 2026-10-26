from io import BytesIO

from PIL import Image


class RaytracingAggregator:
    """Place RGB tiles into the final image and retain per-tile work metrics."""

    result_type = "image/png"
    WORK_COUNTERS = (
        "primary_rays",
        "total_rays",
        "sphere_tests",
        "box_tests",
        "plane_tests",
        "shadow_rays",
        "reflection_rays",
        "refraction_rays",
        "light_samples",
    )

    def __init__(self, config):
        self.width = config.width
        self.height = config.height
        self.tile_size = config.tile_size
        self.buffer = bytearray(self.width * self.height * 3)
        self.seen_task_ids: set[int] = set()
        self.task_stats: dict[int, dict] = {}

    def add_result(self, result):
        task_id = result["_task_id"]
        if task_id in self.seen_task_ids:
            return

        row_block = result["row_block"]
        col_block = result["col_block"]
        start_x = col_block * self.tile_size
        start_y = row_block * self.tile_size
        if start_x < 0 or start_y < 0 or start_x >= self.width or start_y >= self.height:
            raise ValueError("ray-tracing tile is outside the output image")

        expected_width = min(self.tile_size, self.width - start_x)
        expected_height = min(self.tile_size, self.height - start_y)
        tile_width = result["tile_width"]
        tile_height = result["tile_height"]
        if (tile_width, tile_height) != (expected_width, expected_height):
            raise ValueError(
                "invalid ray-tracing tile dimensions: "
                f"expected {expected_width}x{expected_height}, "
                f"received {tile_width}x{tile_height}"
            )

        pixels = result["pixel_buffer"]
        expected_bytes = tile_width * tile_height * 3
        if len(pixels) != expected_bytes:
            raise ValueError(
                f"invalid ray-tracing pixel buffer: expected {expected_bytes} bytes, "
                f"received {len(pixels)}"
            )

        pixels = bytes(pixels)
        for y in range(tile_height):
            source = y * tile_width * 3
            destination = ((start_y + y) * self.width + start_x) * 3
            row_bytes = tile_width * 3
            self.buffer[destination:destination + row_bytes] = pixels[source:source + row_bytes]

        self.seen_task_ids.add(task_id)
        work = result.get("work_stats") or {}
        self.task_stats[task_id] = {
            "row_block": row_block,
            "col_block": col_block,
            "work_stats": {
                name: int(work.get(name, 0))
                for name in self.WORK_COUNTERS
            },
            "execution_time_ms": result.get("_execution_time_ms"),
        }
        stats = self.task_stats[task_id]["work_stats"]
        stats["actual_work_units"] = (
            stats["total_rays"] + stats["sphere_tests"] + stats["box_tests"]
            + stats["plane_tests"] + stats["light_samples"]
        )

    def is_complete(self, total_tasks):
        return len(self.seen_task_ids) >= total_tasks

    def get_stats(self):
        totals = {name: 0 for name in self.WORK_COUNTERS}
        for tile in self.task_stats.values():
            for name, value in tile["work_stats"].items():
                if name in totals:
                    totals[name] += value
        totals["actual_work_units"] = (
            totals["total_rays"] + totals["sphere_tests"] + totals["box_tests"]
            + totals["plane_tests"] + totals["light_samples"]
        )
        return {
            "completed_tiles": len(self.task_stats),
            "totals": totals,
            "tiles": [
                {"task_id": task_id, **self.task_stats[task_id]}
                for task_id in sorted(self.task_stats)
            ],
        }

    def get_result(self):
        image = Image.frombytes("RGB", (self.width, self.height), bytes(self.buffer))
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
