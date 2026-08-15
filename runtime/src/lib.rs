pub mod kernels;

use wasm_bindgen::prelude::*;
use kernels::mandelbrot::{self, MandelbrotInput};

#[wasm_bindgen]
pub fn execute_task(task_type: &str, payload: JsValue) -> Result<JsValue, JsValue> {
    match task_type {
        "mandelbrot" => {
            let input: MandelbrotInput = serde_wasm_bindgen::from_value(payload)
                .map_err(|e| JsValue::from_str(&format!("Invalid mandelbrot payload: {}", e)))?;
            let output = mandelbrot::run(input);
            serde_wasm_bindgen::to_value(&output)
                .map_err(|e| JsValue::from_str(&format!("Failed to serialize output: {}", e)))
        }
        _ => Err(JsValue::from_str(&format!("Unknown task type: {}", task_type))),
    }
}
