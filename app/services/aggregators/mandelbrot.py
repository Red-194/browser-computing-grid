class MandelbrotAggregator:

    def __init__(self, config):
        self.width = config["width"]
        self.height = config["height"]
        self.tile_size = config["tile_size"]

        self.buffer = bytearray(self.width * self.height)

        self.completed_tasks = 0

    def add_result(self, result):
        row_block = result["row_block"]
        col_block = result["col_block"]
        pixels = result["pixel_buffer"]

        start_x = col_block * self.tile_size
        start_y = row_block * self.tile_size

        tile_width = min(
            self.tile_size,
            self.width - start_x
        )

        tile_height = min(
            self.tile_size,
            self.height - start_y
        )

        expected_size = tile_width * tile_height

        if len(pixels) != expected_size:
            raise ValueError(
                f"Invalid tile size: expected {expected_size}, "
                f"received {len(pixels)}"
            )

        for y in range(tile_height):
            source_start = y * tile_width
            source_end = source_start + tile_width

            destination_start = (
                (start_y + y) * self.width + start_x
            )

            self.buffer[
                destination_start:
                destination_start + tile_width
            ] = bytes(pixels[source_start:source_end])

        self.completed_tasks += 1

    def is_complete(self, total_tasks):
        return self.completed_tasks == total_tasks

    def get_image(self):
        return bytes(self.buffer)