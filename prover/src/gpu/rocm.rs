//! ROCm GPU backend for AMD GPUs.

use super::GpuDevice;
use crate::types::GpuBackendType;
use log::debug;

/// Detect AMD ROCm devices.
pub fn detect_devices() -> Option<Vec<GpuDevice>> {
    // Check rocm-smi availability
    match std::process::Command::new("rocm-smi")
        .arg("--showproductname")
        .arg("--showmeminfo")
        .arg("vram")
        .arg("--csv")
        .output()
    {
        Ok(output) if output.status.success() => {
            let stdout = String::from_utf8_lossy(&output.stdout);
            let mut devices = Vec::new();
            let mut device_idx = 0u32;

            for line in stdout.lines().skip(1) {
                // Skip header
                let parts: Vec<&str> = line.split(',').collect();
                if parts.len() >= 3 {
                    devices.push(GpuDevice {
                        name: parts.get(1).unwrap_or(&"AMD GPU").trim().to_string(),
                        backend: GpuBackendType::Rocm,
                        device_index: device_idx,
                        vram_total: parts.get(2).and_then(|s| s.trim().parse().ok()).unwrap_or(0),
                        vram_available: 0, // Would need additional query
                        compute_units: 0,
                        compute_version: String::new(),
                        benchmark_score: 0.0,
                    });
                    device_idx += 1;
                }
            }

            if devices.is_empty() { None } else { Some(devices) }
        }
        _ => {
            debug!("rocm-smi not found — no ROCm devices");
            None
        }
    }
}
