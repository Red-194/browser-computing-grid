pub mod kernels;

use kernels::{compression, mandelbrot, nqueens, raytracing, regex_scan, sat};
use serde::{de::DeserializeOwned, Serialize};
use wasm_bindgen::prelude::*;

#[wasm_bindgen]
pub fn execute_task(task_type: &str, payload: JsValue) -> Result<JsValue, JsValue> {
    match task_type {
        "mandelbrot" => run_kernel("mandelbrot", payload, mandelbrot::run),
        "sat" => run_kernel("sat", payload, sat::run),
        "compression" => run_kernel("compression", payload, compression::run),
        "regex" => run_kernel("regex", payload, regex_scan::run),
        "nqueens" => run_kernel("nqueens", payload, nqueens::run),
        "raytracing" => run_kernel("raytracing", payload, raytracing::run),
        _ => Err(JsValue::from_str(&format!("Unknown task type: {}", task_type))),
    }
}

// Read the JS payload, run the kernel, send the answer back as a JS value.
fn run_kernel<I: DeserializeOwned, O: Serialize>(
    name: &str,
    payload: JsValue,
    kernel: fn(I) -> O,
) -> Result<JsValue, JsValue> {
    let input: I = serde_wasm_bindgen::from_value(payload)
        .map_err(|e| JsValue::from_str(&format!("Invalid {} payload: {}", name, e)))?;
    serde_wasm_bindgen::to_value(&kernel(input))
        .map_err(|e| JsValue::from_str(&format!("Failed to serialize {} output: {}", name, e)))
}
