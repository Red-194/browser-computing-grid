use runtime::kernels::mandelbrot::{self, MandelbrotInput};

#[test]
fn test_mandelbrot() {
    let input = MandelbrotInput {
        width: 10,
        height: 10,
        x_min: -2.0,
        x_max: 1.0,
        y_min: -1.5,
        y_max: 1.5,
        max_iterations: 100,
        tile_size: 10,
        row_block: 0,
        col_block: 0,
    };
    
    let output = mandelbrot::run(input);
    
    assert_eq!(output.row_block, 0);
    assert_eq!(output.col_block, 0);
    assert_eq!(output.pixel_buffer.len(), 100);
    
}

#[test]
fn test_mandelbrot_tile() {
    let input = MandelbrotInput {
        width: 20,
        height: 20,
        x_min: -2.0,
        x_max: 1.0,
        y_min: -1.5,
        y_max: 1.5,
        max_iterations: 100,
        tile_size: 10,
        row_block: 1,
        col_block: 1,
    };

    let output = mandelbrot::run(input);

    // Tile (1, 1) should be a 10x10 tile.
    assert_eq!(output.row_block, 1);
    assert_eq!(output.col_block, 1);
    assert_eq!(output.pixel_buffer.len(), 100);
}

#[test]
fn test_mandelbrot_edge_tile() {
    let input = MandelbrotInput {
        width: 25,
        height: 25,
        x_min: -2.0,
        x_max: 1.0,
        y_min: -1.5,
        y_max: 1.5,
        max_iterations: 100,
        tile_size: 10,
        row_block: 2,
        col_block: 2,
    };

    let output = mandelbrot::run(input);

    // Image is 25x25, so tile (2,2) covers only pixels 20..24.
    // Therefore this is a 5x5 tile.
    assert_eq!(output.row_block, 2);
    assert_eq!(output.col_block, 2);
    assert_eq!(output.pixel_buffer.len(), 25);
}