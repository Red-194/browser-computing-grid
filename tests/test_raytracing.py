from io import BytesIO

import pytest
from PIL import Image
from pydantic import ValidationError

from app.models.jobs import (
    RayCamera,
    RayScene,
    RaySphere,
    RayTracingConfig,
    RayTracingJob,
)
from app.models.tasks import RayTracingTaskConfig
from app.services.aggregators.raytracing import RaytracingAggregator
from app.services.scheduler.cost import task_cost
from app.services.splitters.raytracing import RaytracingSplitter


def test_raytracing_config_defaults_to_the_benchmark_scene():
    config = RayTracingConfig()
    assert config.scene.spheres
    assert config.scene.lights
    assert config.samples_per_pixel == 2
    assert config.max_bounces == 2


def test_raytracing_config_rejects_invalid_dimensions_and_scene_values():
    with pytest.raises(ValidationError):
        RayTracingConfig(width=0)
    with pytest.raises(ValidationError):
        RaySphere(center=(0, 0, 0), radius=1, color=(1.1, 0, 0))
    with pytest.raises(ValidationError):
        RayCamera(position=(0, 0, 0), look_at=(0, 0, 0))


def test_raytracing_config_accepts_large_render_settings():
    config = RayTracingConfig(
        width=20_000,
        height=16_000,
        tile_size=1024,
        samples_per_pixel=128,
        max_bounces=16,
    )
    assert config.width * config.height == 320_000_000
    assert config.tile_size == 1024
    assert config.samples_per_pixel == 128
    assert config.max_bounces == 16


def test_raytracing_splitter_tiles_cover_non_divisible_image_once():
    config = RayTracingConfig(width=131, height=67, tile_size=64)
    tasks = RaytracingSplitter.split(RayTracingJob(workload="raytracing", config=config))

    assert len(tasks) == 3 * 2
    coverage = [[0] * config.width for _ in range(config.height)]
    by_coordinate = {}
    for task in tasks:
        task_config = task.config
        by_coordinate[(task_config.row_block, task_config.col_block)] = task
        start_x = task_config.col_block * task_config.tile_size
        start_y = task_config.row_block * task_config.tile_size
        tile_width = min(task_config.tile_size, config.width - start_x)
        tile_height = min(task_config.tile_size, config.height - start_y)
        for y in range(start_y, start_y + tile_height):
            for x in range(start_x, start_x + tile_width):
                coverage[y][x] += 1

    assert all(value == 1 for row in coverage for value in row)
    assert (0, 0) in by_coordinate and (1, 2) in by_coordinate
    assert by_coordinate[(0, 2)].config.width == 131
    assert by_coordinate[(1, 2)].config.height == 67
    assert by_coordinate[(1, 2)].task_id == 5


def _task_config(row=0, col=0, *, spp=1, bounces=2):
    config = RayTracingConfig(
        width=256,
        height=192,
        tile_size=64,
        samples_per_pixel=spp,
        max_bounces=bounces,
    )
    return RayTracingTaskConfig(
        width=config.width,
        height=config.height,
        tile_size=config.tile_size,
        row_block=row,
        col_block=col,
        samples_per_pixel=spp,
        max_bounces=bounces,
        scene=config.scene,
    )


def test_raytracing_cost_is_deterministic_and_rejects_bad_task_shapes():
    task = _task_config(row=2, col=1)
    assert task_cost("raytracing", task) == task_cost("raytracing", task)
    assert task_cost("raytracing", object()) == 1.0
    assert task_cost("raytracing", _task_config(row=20, col=0)) == 1.0


def test_raytracing_estimator_distinguishes_empty_and_object_rich_tiles():
    sky_tile = task_cost("raytracing", _task_config(row=0, col=0))
    object_tile = task_cost("raytracing", _task_config(row=2, col=1))
    assert object_tile > sky_tile * 2


def test_raytracing_estimator_scales_samples_and_reflection_work():
    one_sample = task_cost("raytracing", _task_config(row=2, col=1, spp=1, bounces=0))
    two_samples = task_cost("raytracing", _task_config(row=2, col=1, spp=2, bounces=0))
    reflected = task_cost("raytracing", _task_config(row=2, col=1, spp=1, bounces=2))
    assert two_samples == pytest.approx(one_sample * 2)
    assert reflected > one_sample


def _tile_result(task_id, row, col, width, height, color, *, rays=1, time_ms=1.0):
    return {
        "_task_id": task_id,
        "_execution_time_ms": time_ms,
        "row_block": row,
        "col_block": col,
        "tile_width": width,
        "tile_height": height,
        "pixel_buffer": list(color) * (width * height),
        "work_stats": {
            "primary_rays": rays,
            "total_rays": rays,
            "sphere_tests": rays * 2,
            "shadow_rays": 0,
            "reflection_rays": 0,
            "light_samples": 0,
        },
    }


def test_raytracing_aggregator_reconstructs_rgb_edges_and_work_stats():
    config = RayTracingConfig(width=3, height=3, tile_size=2)
    aggregator = RaytracingAggregator(config)
    aggregator.add_result(_tile_result(0, 0, 0, 2, 2, (255, 0, 0), rays=4))
    aggregator.add_result(_tile_result(1, 0, 1, 1, 2, (0, 255, 0), rays=2))
    aggregator.add_result(_tile_result(2, 1, 0, 2, 1, (0, 0, 255), rays=2))
    aggregator.add_result(_tile_result(3, 1, 1, 1, 1, (255, 255, 255), rays=1))

    assert aggregator.is_complete(4)
    image = Image.open(BytesIO(aggregator.get_result()))
    assert image.size == (3, 3)
    assert image.mode == "RGB"
    assert image.getpixel((0, 0)) == (255, 0, 0)
    assert image.getpixel((2, 0)) == (0, 255, 0)
    assert image.getpixel((0, 2)) == (0, 0, 255)
    assert image.getpixel((2, 2)) == (255, 255, 255)

    stats = aggregator.get_stats()
    assert stats["completed_tiles"] == 4
    assert stats["totals"]["primary_rays"] == 9
    assert stats["totals"]["actual_work_units"] == 27
    assert stats["tiles"][1]["work_stats"]["actual_work_units"] == 6


def test_raytracing_aggregator_ignores_duplicate_results_and_rejects_bad_tiles():
    aggregator = RaytracingAggregator(RayTracingConfig(width=2, height=2, tile_size=2))
    result = _tile_result(0, 0, 0, 2, 2, (1, 2, 3))
    aggregator.add_result(result)
    aggregator.add_result(result)
    assert aggregator.get_stats()["completed_tiles"] == 1

    with pytest.raises(ValueError, match="dimensions"):
        aggregator.add_result(_tile_result(1, 0, 0, 1, 2, (1, 2, 3)))


def test_raytracing_scene_can_be_empty_for_a_miss_only_workload():
    config = RayTracingConfig(
        width=64,
        height=64,
        tile_size=64,
        scene=RayScene(spheres=[], lights=[]),
    )
    task = RayTracingTaskConfig(
        width=config.width,
        height=config.height,
        tile_size=config.tile_size,
        row_block=0,
        col_block=0,
        samples_per_pixel=config.samples_per_pixel,
        max_bounces=config.max_bounces,
        scene=config.scene,
    )
    assert task_cost("raytracing", task) == 64 * 64 * config.samples_per_pixel
    assert config.scene.spheres == []
