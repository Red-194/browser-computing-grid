from app.models.jobs import MandelbrotConfig
from app.services.aggregators.mandelbrot import MandelbrotAggregator


def test_mandelbrot_aggregator():

    config = MandelbrotConfig(
        width=256,
        height=256,
        x_min=-2.5,
        x_max=1.0,
        y_min=-1.0,
        y_max=1.0,
        max_iterations=500,
        tile_size=128,
    )

    aggregator = MandelbrotAggregator(config)

    # Four 128x128 tiles with distinct values.
    tiles = [
        {
            "row_block": 1,
            "col_block": 1,
            "pixel_buffer": [4] * (128 * 128),
        },
        {
            "row_block": 0,
            "col_block": 1,
            "pixel_buffer": [2] * (128 * 128),
        },
        {
            "row_block": 1,
            "col_block": 0,
            "pixel_buffer": [3] * (128 * 128),
        },
        {
            "row_block": 0,
            "col_block": 0,
            "pixel_buffer": [1] * (128 * 128),
        },
    ]

    for tile in tiles:
        aggregator.add_result(tile)

    assert aggregator.is_complete(4)

    image = aggregator.get_result()

    assert image is not None

    # PNG signature
    assert image[:8] == b"\x89PNG\r\n\x1a\n"