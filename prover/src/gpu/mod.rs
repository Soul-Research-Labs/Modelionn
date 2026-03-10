//! GPU device management and backend detection.

pub mod cuda;
pub mod rocm;
pub mod metal;
pub mod webgpu;

use crate::types::GpuBackendType;
use log::info;
use serde::{Deserialize, Serialize};

/// Information about an available GPU device.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GpuDevice {
    /// Device name
    pub name: String,
    /// Backend type
    pub backend: GpuBackendType,
    /// Device index
    pub device_index: u32,
    /// Total VRAM in bytes
    pub vram_total: u64,
    /// Available VRAM in bytes
    pub vram_available: u64,
    /// Compute units (SMs for NVIDIA, CUs for AMD)
    pub compute_units: u32,
    /// Compute version string
    pub compute_version: String,
    /// Benchmark: proofs per second for a standard test circuit
    pub benchmark_score: f64,
}

/// Manages GPU device detection and selection.
pub struct GpuManager {
    devices: Vec<GpuDevice>,
}

impl GpuManager {
    /// Detect all available GPU devices across all backends.
    pub fn detect() -> Self {
        let mut devices = Vec::new();

        // Try CUDA
        if let Some(cuda_devices) = cuda::detect_devices() {
            info!("Detected {} CUDA device(s)", cuda_devices.len());
            devices.extend(cuda_devices);
        }

        // Try ROCm
        if let Some(rocm_devices) = rocm::detect_devices() {
            info!("Detected {} ROCm device(s)", rocm_devices.len());
            devices.extend(rocm_devices);
        }

        // Try Metal (macOS)
        if let Some(metal_devices) = metal::detect_devices() {
            info!("Detected {} Metal device(s)", metal_devices.len());
            devices.extend(metal_devices);
        }

        // Try WebGPU
        if let Some(wgpu_devices) = webgpu::detect_devices() {
            info!("Detected {} WebGPU device(s)", wgpu_devices.len());
            devices.extend(wgpu_devices);
        }

        if devices.is_empty() {
            info!("No GPU devices detected — falling back to CPU proving");
        } else {
            info!(
                "Total GPU devices: {} (best: {})",
                devices.len(),
                devices.first().map(|d| d.name.as_str()).unwrap_or("none")
            );
        }

        Self { devices }
    }

    /// Get all detected devices.
    pub fn devices(&self) -> &[GpuDevice] {
        &self.devices
    }

    /// Get the best available device (highest benchmark score).
    pub fn best_device(&self) -> Option<&GpuDevice> {
        self.devices.iter().max_by(|a, b| {
            a.benchmark_score
                .partial_cmp(&b.benchmark_score)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
    }

    /// Get all devices of a specific backend type.
    pub fn devices_of_type(&self, backend: GpuBackendType) -> Vec<&GpuDevice> {
        self.devices.iter().filter(|d| d.backend == backend).collect()
    }

    /// Get total available VRAM across all devices.
    pub fn total_vram_available(&self) -> u64 {
        self.devices.iter().map(|d| d.vram_available).sum()
    }
}
