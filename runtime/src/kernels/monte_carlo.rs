use rand::Rng;
use rand_pcg::Pcg64;
use rand::SeedableRng;
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize)]
pub struct MonteCarloInput {
    pub samples: u32,
    pub seed: u64,
}

#[derive(Serialize, Deserialize)]
pub struct MonteCarloOutput {
    pub inside_circle: u32,
    pub samples: u32,
}

pub fn run(input: MonteCarloInput) -> MonteCarloOutput {
    let mut rng = Pcg64::seed_from_u64(input.seed);
    let mut inside_circle = 0;

    for _ in 0..input.samples {
        let x: f64 = rng.r#gen();
        let y: f64 = rng.r#gen();
        if x * x + y * y <= 1.0 {
            inside_circle += 1;
        }
    }

    MonteCarloOutput {
        inside_circle,
        samples: input.samples,
    }
}
