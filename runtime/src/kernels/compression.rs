use serde::{Deserialize, Serialize};

/// Compress one chunk with one algorithm, then decompress it to check it.
/// `variant` is one of: "lz4", "zstd-fastest".
/// (The ruzstd crate only implements its fastest level so far; its other
/// levels panic. Add more arms here once ruzstd supports them.)
#[derive(Serialize, Deserialize)]
pub struct CompressionInput {
    pub variant: String,
    pub chunk_id: u32,
    pub data_base64: String,
}

#[derive(Serialize, Deserialize)]
pub struct CompressionOutput {
    pub variant: String,
    pub chunk_id: u32,
    pub original_size: u32,
    pub compressed_size: u32,
    pub roundtrip_ok: bool,
    pub error: Option<String>,
}

pub fn run(input: CompressionInput) -> CompressionOutput {
    let mut output = CompressionOutput {
        variant: input.variant.clone(),
        chunk_id: input.chunk_id,
        original_size: 0,
        compressed_size: 0,
        roundtrip_ok: false,
        error: None,
    };

    let data = match decode_base64(&input.data_base64) {
        Ok(data) => data,
        Err(message) => {
            output.error = Some(message);
            return output;
        }
    };
    output.original_size = data.len() as u32;

    match compress_and_check(&input.variant, &data) {
        Ok((compressed_size, roundtrip_ok)) => {
            output.compressed_size = compressed_size as u32;
            output.roundtrip_ok = roundtrip_ok;
        }
        Err(message) => output.error = Some(message),
    }

    output
}

// Returns (compressed size, true if decompressing gives back the same bytes).
fn compress_and_check(variant: &str, data: &[u8]) -> Result<(usize, bool), String> {
    match variant {
        "lz4" => {
            let packed = lz4_flex::block::compress_prepend_size(data);
            let unpacked = lz4_flex::block::decompress_size_prepended(&packed)
                .map_err(|e| format!("lz4 decompress failed: {}", e))?;
            Ok((packed.len(), unpacked == data))
        }
        "zstd-fastest" => zstd_roundtrip(data, ruzstd::encoding::CompressionLevel::Fastest),
        _ => Err(format!("Unknown compression variant: {}", variant)),
    }
}

fn zstd_roundtrip(
    data: &[u8],
    level: ruzstd::encoding::CompressionLevel,
) -> Result<(usize, bool), String> {
    use ruzstd::io::Read;

    let packed = ruzstd::encoding::compress_to_vec(data, level);
    let mut decoder = ruzstd::decoding::StreamingDecoder::new(&packed[..])
        .map_err(|e| format!("zstd decoder failed: {}", e))?;
    let mut unpacked = Vec::new();
    decoder
        .read_to_end(&mut unpacked)
        .map_err(|e| format!("zstd decompress failed: {}", e))?;
    Ok((packed.len(), unpacked == data))
}

// Small standard base64 decoder, so we need no extra crate.
pub fn decode_base64(text: &str) -> Result<Vec<u8>, String> {
    let mut bytes = Vec::with_capacity(text.len() / 4 * 3);
    let mut buffer = 0u32;
    let mut bits = 0u32;

    for ch in text.bytes() {
        let value = match ch {
            b'A'..=b'Z' => ch - b'A',
            b'a'..=b'z' => ch - b'a' + 26,
            b'0'..=b'9' => ch - b'0' + 52,
            b'+' => 62,
            b'/' => 63,
            b'=' => break,
            b'\r' | b'\n' | b' ' => continue,
            _ => return Err(format!("Invalid base64 character: {}", ch as char)),
        };
        buffer = (buffer << 6) | value as u32;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            bytes.push((buffer >> bits) as u8);
            buffer &= (1 << bits) - 1;
        }
    }

    Ok(bytes)
}
