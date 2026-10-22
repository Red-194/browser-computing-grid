use runtime::kernels::compression::{self, CompressionInput};
use runtime::kernels::mandelbrot::{self, MandelbrotInput};
use runtime::kernels::nqueens::{self, NQueensInput};
use runtime::kernels::regex_scan::{self, RegexInput};
use runtime::kernels::sat::{self, SatInput};

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

#[test]
fn test_sat_kernel_returns_a_model() {
    let output = sat::run(SatInput {
        num_variables: 2,
        clauses: vec![vec![1, 2], vec![-1, 2]],
        fixed_assignments: vec![],
    });

    assert!(output.satisfiable);
    assert_eq!(output.model, Some(vec![1, 2]));
}

#[test]
fn test_sat_kernel_detects_unsatisfiable_cube() {
    let output = sat::run(SatInput {
        num_variables: 1,
        clauses: vec![vec![1], vec![-1]],
        fixed_assignments: vec![],
    });

    assert!(!output.satisfiable);
    assert_eq!(output.model, None);
}


// ---------- N-Queens ----------

#[test]
fn test_nqueens_known_solution_counts() {
    for (n, expected) in [(4, 2), (6, 4), (8, 92), (10, 724)] {
        let output = nqueens::run(NQueensInput { n, prefix: vec![] });
        assert_eq!(output.solutions, expected, "n = {}", n);
    }
}

#[test]
fn test_nqueens_prefixes_add_up_to_the_full_count() {
    // Splitting on the first queen must not change the total.
    let total: u64 = (0..8)
        .map(|col| nqueens::run(NQueensInput { n: 8, prefix: vec![col] }).solutions)
        .sum();
    assert_eq!(total, 92);
}

#[test]
fn test_nqueens_bad_prefix_gives_zero() {
    // Two queens in the same column.
    let output = nqueens::run(NQueensInput { n: 8, prefix: vec![3, 3] });
    assert_eq!(output.solutions, 0);
    assert_eq!(output.nodes, 0);
}

// ---------- Compression ----------

// "hello hello hello hello " repeated, encoded as base64.
fn sample_base64() -> String {
    let text = "hello hello hello hello ".repeat(50);
    let alphabet = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::new();
    for group in text.as_bytes().chunks(3) {
        let b = [group[0], *group.get(1).unwrap_or(&0), *group.get(2).unwrap_or(&0)];
        let n = ((b[0] as u32) << 16) | ((b[1] as u32) << 8) | b[2] as u32;
        out.push(alphabet[(n >> 18) as usize & 63] as char);
        out.push(alphabet[(n >> 12) as usize & 63] as char);
        out.push(if group.len() > 1 { alphabet[(n >> 6) as usize & 63] as char } else { '=' });
        out.push(if group.len() > 2 { alphabet[n as usize & 63] as char } else { '=' });
    }
    out
}

#[test]
fn test_base64_decoder() {
    assert_eq!(compression::decode_base64("aGVsbG8=").unwrap(), b"hello");
    assert_eq!(compression::decode_base64("").unwrap(), b"");
    assert!(compression::decode_base64("!!!").is_err());
}

#[test]
fn test_compression_roundtrip_for_every_variant() {
    for variant in ["lz4", "zstd-fastest"] {
        let output = compression::run(CompressionInput {
            variant: variant.to_string(),
            chunk_id: 7,
            data_base64: sample_base64(),
        });
        assert_eq!(output.error, None, "variant = {}", variant);
        assert_eq!(output.chunk_id, 7);
        assert_eq!(output.original_size, 1200);
        assert!(output.roundtrip_ok, "variant = {}", variant);
        // Repeated text must shrink.
        assert!(output.compressed_size < output.original_size, "variant = {}", variant);
    }
}

#[test]
fn test_compression_unknown_variant_reports_error() {
    let output = compression::run(CompressionInput {
        variant: "gzip".to_string(),
        chunk_id: 0,
        data_base64: "aGVsbG8=".to_string(),
    });
    assert!(output.error.is_some());
    assert!(!output.roundtrip_ok);
}

// ---------- Regex ----------

fn regex_input(pattern: &str, texts: &[&str], mode: &str) -> RegexInput {
    RegexInput {
        pattern_id: 1,
        batch_id: 2,
        pattern: pattern.to_string(),
        texts: texts.iter().map(|t| t.to_string()).collect(),
        mode: mode.to_string(),
        backtrack_limit: 1_000_000,
    }
}

#[test]
fn test_regex_match_mode() {
    let output = regex_scan::run(regex_input(r"^\d+$", &["123", "abc", "45"], "match"));
    assert_eq!(output.pattern_id, 1);
    assert_eq!(output.batch_id, 2);
    assert_eq!(output.texts_scanned, 3);
    assert_eq!(output.matched_texts, 2);
    assert_eq!(output.compile_error, None);
}

#[test]
fn test_regex_scan_mode_counts_every_match() {
    let output = regex_scan::run(regex_input(r"a+", &["aa b a", "xyz"], "scan"));
    assert_eq!(output.total_matches, 2);
    assert_eq!(output.matched_texts, 1);
}

#[test]
fn test_regex_reports_bad_pattern() {
    let output = regex_scan::run(regex_input("(unclosed", &["x"], "match"));
    assert!(output.compile_error.is_some());
    assert_eq!(output.texts_scanned, 0);
}

#[test]
fn test_regex_backreference_pattern_runs() {
    // Backreferences use the backtracking engine, not the plain linear one.
    let output = regex_scan::run(regex_input(r"(a+)\1", &["aaaa", "ab"], "match"));
    assert_eq!(output.compile_error, None);
    assert_eq!(output.matched_texts, 1);
}
