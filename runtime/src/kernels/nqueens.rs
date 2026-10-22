use serde::{Deserialize, Serialize};

/// Count N-Queens solutions below a fixed prefix of queen columns.
/// `prefix[row]` is the column of the queen already placed on that row.
#[derive(Serialize, Deserialize)]
pub struct NQueensInput {
    pub n: u32,
    pub prefix: Vec<u32>,
}

#[derive(Serialize, Deserialize)]
pub struct NQueensOutput {
    pub solutions: u64,
    // Number of queen placements tried. Shows how uneven the tasks are.
    pub nodes: u64,
}

pub fn run(input: NQueensInput) -> NQueensOutput {
    let mut output = NQueensOutput { solutions: 0, nodes: 0 };

    if input.n == 0 || input.n > 32 || input.prefix.len() > input.n as usize {
        return output;
    }

    let full: u64 = (1u64 << input.n) - 1;
    let mut cols = 0u64;
    let mut diag1 = 0u64;
    let mut diag2 = 0u64;

    // Place the fixed queens first. A bad prefix means zero solutions.
    for &col in &input.prefix {
        if col >= input.n {
            return output;
        }
        let bit = 1u64 << col;
        if bit & (cols | diag1 | diag2) != 0 {
            return output;
        }
        cols |= bit;
        diag1 = ((diag1 | bit) << 1) & full;
        diag2 = (diag2 | bit) >> 1;
    }

    search(full, cols, diag1, diag2, &mut output);
    output
}

fn search(full: u64, cols: u64, diag1: u64, diag2: u64, output: &mut NQueensOutput) {
    if cols == full {
        output.solutions += 1;
        return;
    }

    // Each 1-bit in `free` is a column where the next queen can go.
    let mut free = full & !(cols | diag1 | diag2);
    while free != 0 {
        let bit = free & free.wrapping_neg();
        free ^= bit;
        output.nodes += 1;
        search(
            full,
            cols | bit,
            ((diag1 | bit) << 1) & full,
            (diag2 | bit) >> 1,
            output,
        );
    }
}
