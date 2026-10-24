use fancy_regex::RegexBuilder;
use serde::{Deserialize, Serialize};

/// Run one pattern over a batch of texts.
/// `mode` is "match" (does the text match at all?) or "scan" (count every match).
/// `pattern_id` and `batch_id` are copied to the output so the controller knows
/// which piece of work this result belongs to.
#[derive(Serialize, Deserialize)]
pub struct RegexInput {
    pub pattern_id: u32,
    pub batch_id: u32,
    pub pattern: String,
    pub texts: Vec<String>,
    pub mode: String,
    pub backtrack_limit: u32,
}

#[derive(Serialize, Deserialize)]
pub struct RegexOutput {
    pub pattern_id: u32,
    pub batch_id: u32,
    pub texts_scanned: u32,
    pub matched_texts: u32,
    pub total_matches: u32,
    // Texts where the engine gave up (backtrack limit or other runtime error).
    pub limit_hits: u32,
    // Set when the pattern itself is invalid (useful for parser validation).
    pub compile_error: Option<String>,
}

pub fn run(input: RegexInput) -> RegexOutput {
    let mut output = RegexOutput {
        pattern_id: input.pattern_id,
        batch_id: input.batch_id,
        texts_scanned: 0,
        matched_texts: 0,
        total_matches: 0,
        limit_hits: 0,
        compile_error: None,
    };

    if input.mode != "match" && input.mode != "scan" {
        output.compile_error = Some(format!("Unknown regex mode: {}", input.mode));
        return output;
    }

    let regex = match RegexBuilder::new(&input.pattern)
        .backtrack_limit(input.backtrack_limit as usize)
        .build()
    {
        Ok(regex) => regex,
        Err(error) => {
            output.compile_error = Some(error.to_string());
            return output;
        }
    };

    for text in &input.texts {
        output.texts_scanned += 1;

        if input.mode == "match" {
            match regex.is_match(text) {
                Ok(true) => {
                    output.matched_texts += 1;
                    output.total_matches += 1;
                }
                Ok(false) => {}
                Err(_) => output.limit_hits += 1,
            }
        } else {
            let mut count = 0;
            for found in regex.find_iter(text) {
                match found {
                    Ok(_) => count += 1,
                    Err(_) => {
                        output.limit_hits += 1;
                        break;
                    }
                }
            }
            if count > 0 {
                output.matched_texts += 1;
                output.total_matches += count;
            }
        }
    }

    output
}
