use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize)]
pub struct MandelbrotInput {
    pub width: u32,
    pub height: u32,
    pub x_min: f64,
    pub x_max: f64,
    pub y_min: f64,
    pub y_max: f64,
    pub max_iterations: u32,
    pub tile_size: u32,
    pub row_block: u32,
    pub col_block: u32,
}

#[derive(Serialize, Deserialize)]
pub struct MandelbrotOutput {
    pub row_block: u32,
    pub col_block: u32,
    pub pixel_buffer: Vec<u8>,
}

pub fn run(input: MandelbrotInput) -> MandelbrotOutput {
    let mut pixel_buffer = Vec::with_capacity((input.width * input.height) as usize);
    let dx = (input.x_max - input.x_min) / (input.width as f64);
    let dy = (input.y_max - input.y_min) / (input.height as f64);

    for j in 0..input.height {
        for i in 0..input.width {
            let cx = input.x_min + (i as f64) * dx;
            let cy = input.y_min + (j as f64) * dy;
            
            let mut zx = 0.0;
            let mut zy = 0.0;
            let mut iteration = 0;
            
            while zx * zx + zy * zy <= 4.0 && iteration < input.max_iterations {
                let temp_zx = zx * zx - zy * zy + cx;
                zy = 2.0 * zx * zy + cy;
                zx = temp_zx;
                iteration += 1;
            }
            
            let color = if iteration == input.max_iterations {
                0
            } else {
                ((iteration as f64 / input.max_iterations as f64) * 255.0) as u8
            };
            pixel_buffer.push(color);
        }
    }

    MandelbrotOutput {
        row_block: input.row_block,
        col_block: input.col_block,
        pixel_buffer,
    }
}
