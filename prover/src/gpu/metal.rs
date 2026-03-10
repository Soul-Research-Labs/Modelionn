//! Metal GPU backend for Apple Silicon.

use super::GpuDevice;
use crate::types::GpuBackendType;
use log::debug;

/// Detect Apple Metal devices.
pub fn detect_devices() -> Option<Vec<GpuDevice>> {
    #[cfg(target_os = "macos")]
    {
        // Query system_profiler for GPU info on macOS
        match std::process::Command::new("system_profiler")
            .arg("SPDisplaysDataType")
            .arg("-json")
            .output()
        {
            Ok(output) if output.status.success() => {
                let stdout = String::from_utf8_lossy(&output.stdout);
                if let Ok(json) = serde_json::from_str::<serde_json::Value>(&stdout) {
                    let mut devices = Vec::new();
                    if let Some(displays) = json.get("SPDisplaysDataType").and_then(|v| v.as_array()) {
                        for (idx, display) in displays.iter().enumerate() {
                            let name = display
                                .get("sppci_model")
                                .and_then(|v| v.as_str())
                                .unwrap_or("Apple GPU")
                                .to_string();

                            // Parse VRAM (reported in MB or as "shared" for Apple Silicon)
                            let vram_str = display
                                .get("spdisplays_vram")
                                .and_then(|v| v.as_str())
                                .unwrap_or("0");
                            let vram_mb: u64 = vram_str
                                .split_whitespace()
                                .next()
                                .and_then(|s| s.parse().ok())
                                .unwrap_or(0);

                            let cores = display
                                .get("sppci_cores")
                                .and_then(|v| v.as_str())
                                .and_then(|s| s.parse::<u32>().ok())
                                .unwrap_or(0);

                            devices.push(GpuDevice {
                                name,
                                backend: GpuBackendType::Metal,
                                device_index: idx as u32,
                                vram_total: vram_mb * 1024 * 1024,
                                vram_available: vram_mb * 1024 * 1024 / 2, // Estimate
                                compute_units: cores,
                                compute_version: "metal3".to_string(),
                                benchmark_score: 0.0,
                            });
                        }
                    }
                    if devices.is_empty() { None } else { return Some(devices); }
                }
                None
            }
            _ => {
                debug!("system_profiler unavailable");
                None
            }
        }
    }

    #[cfg(not(target_os = "macos"))]
    {
        None
    }
}
