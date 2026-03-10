//! WebGPU backend using wgpu for cross-platform GPU compute.

use super::GpuDevice;
use crate::types::GpuBackendType;
use log::debug;

/// Detect WebGPU-compatible devices via wgpu.
pub fn detect_devices() -> Option<Vec<GpuDevice>> {
    #[cfg(feature = "webgpu")]
    {
        let instance = wgpu::Instance::new(wgpu::InstanceDescriptor {
            backends: wgpu::Backends::all(),
            ..Default::default()
        });

        let adapters: Vec<_> = instance.enumerate_adapters(wgpu::Backends::all()).collect();
        if adapters.is_empty() {
            return None;
        }

        let devices: Vec<GpuDevice> = adapters
            .iter()
            .enumerate()
            .map(|(idx, adapter)| {
                let info = adapter.get_info();
                GpuDevice {
                    name: info.name.clone(),
                    backend: GpuBackendType::WebGpu,
                    device_index: idx as u32,
                    vram_total: 0, // wgpu doesn't expose VRAM directly
                    vram_available: 0,
                    compute_units: 0,
                    compute_version: format!("{:?}", info.backend),
                    benchmark_score: 0.0,
                }
            })
            .collect();

        return Some(devices);
    }

    #[cfg(not(feature = "webgpu"))]
    {
        debug!("WebGPU feature not enabled");
        None
    }
}
