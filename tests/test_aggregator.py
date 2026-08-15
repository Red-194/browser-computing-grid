from app.services.aggregators.mandelbrot import MandelbrotAggregator


def test_mandelbrot_aggregator():

    aggregator = MandelbrotAggregator({
        "width": 256,
        "height": 256,
        "tile_size": 128
    })

    # Four 128x128 tiles with distinct values.
    tiles = [
        {
            "row_block": 1,
            "col_block": 1,
            "pixel_buffer": [4] * (128 * 128)
        },
        {
            "row_block": 0,
            "col_block": 1,
            "pixel_buffer": [2] * (128 * 128)
        },
        {
            "row_block": 1,
            "col_block": 0,
            "pixel_buffer": [3] * (128 * 128)
        },
        {
            "row_block": 0,
            "col_block": 0,
            "pixel_buffer": [1] * (128 * 128)
        }
    ]

    # Deliberately scrambled arrival order.
    for tile in tiles:
        aggregator.add_result(tile)

    assert aggregator.is_complete(4)

    image = aggregator.get_image()

    assert len(image) == 256 * 256

    # Top-left
    assert image[0] == 1

    # Top-right
    assert image[128] == 2

    # Bottom-left
    assert image[128 * 256] == 3

    # Bottom-right
    assert image[(128 * 256) + 128] == 4