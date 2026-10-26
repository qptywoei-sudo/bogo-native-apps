//! Verification-only reference raster, matching eframe 0.36.2 app_icon.rs.
use std::path::PathBuf;

fn run() -> Result<(), String> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.len() != 4 {
        return Err("usage: bogo-runtime-icon-reference SOURCE OUTPUT WIDTH HEIGHT".into());
    }
    let source = PathBuf::from(&args[0]);
    let output = PathBuf::from(&args[1]);
    let width = args[2].parse::<u32>().map_err(|_| "invalid reference width")?;
    let height = args[3].parse::<u32>().map_err(|_| "invalid reference height")?;
    if !source.is_absolute() || !output.is_absolute() || !(1..=1024).contains(&width) || width != height {
        return Err("reference paths must be absolute and dimensions bounded".into());
    }
    if output.exists() {
        return Err("reference output must be a new owned file".into());
    }
    let decoded = image::open(&source).map_err(|e| e.to_string())?.into_rgba8();
    let (source_width, source_height) = decoded.dimensions();
    if source_width > 1024 || source_height > 1024 {
        return Err("approved runtime source exceeds the geometry bound".into());
    }
    // IconDataExt::to_image reconstructs the RGBA buffer with from_raw, so
    // match that step too instead of carrying decoder metadata into resize.
    let unscaled = image::RgbaImage::from_raw(source_width, source_height, decoded.into_raw())
        .ok_or("invalid approved IconData")?;
    // Exact eframe create_hicon_with_scale algorithm and encoder, without
    // another decoder/resizer or any change to the original source asset.
    let scaled = image::imageops::resize(&unscaled, width, height, image::imageops::Lanczos3);
    let mut png = Vec::new();
    scaled.write_to(&mut std::io::Cursor::new(&mut png), image::ImageFormat::Png).map_err(|e| e.to_string())?;
    std::fs::write(output, png).map_err(|e| e.to_string())?;
    println!("{{\"width\":{width},\"height\":{height},\"imageVersion\":\"0.25.10\",\"filter\":\"Lanczos3\"}}");
    Ok(())
}

fn main() -> std::process::ExitCode {
    match run() {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("Bogo icon reference refused: {error}");
            std::process::ExitCode::from(2)
        }
    }
}
