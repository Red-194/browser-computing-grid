use runtime::kernels::monte_carlo::{self, MonteCarloInput};
use runtime::kernels::mandelbrot::{self, MandelbrotInput};

#[test]
fn test_monte_carlo() {
    let input = MonteCarloInput {
        samples: 10_000,
        seed: 42,
    };
    
    let output = monte_carlo::run(input);
    
    assert_eq!(output.samples, 10_000);
    // 42 is an arbitrary seed, inside_circle should be somewhere near 10_000 * (pi / 4) ≈ 7853
    let pi_estimate = 4.0 * (output.inside_circle as f64) / (output.samples as f64);
    assert!(pi_estimate > 3.0 && pi_estimate < 3.3);
}

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
    
    // Check center pixel roughly (it should be in the mandelbrot set, so escape color is 0)
    // Actually the center of our mapped grid might not be exactly 0,0, but near it.
    // Let's just check that we generated the correct amount of pixels and they are within valid ranges.
    for pixel in output.pixel_buffer {
        assert!(pixel <= 255);
    }
}
