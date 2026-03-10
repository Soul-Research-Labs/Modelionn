//! Modelionn Prover Engine — GPU-accelerated zero-knowledge proof generation.
//!
//! Supports multiple proof systems (Groth16, PLONK, Halo2, STARKs) and
//! GPU backends (CUDA, ROCm, Metal, WebGPU) for distributed collaborative proving.

pub mod backends;
pub mod gpu;
pub mod partition;
pub mod aggregate;
pub mod verify;
pub mod types;

#[cfg(feature = "python")]
pub mod python;

pub use types::*;

use std::sync::Arc;
use thiserror::Error;

#[derive(Error, Debug)]
pub enum ProverError {
    #[error("unsupported proof system: {0}")]
    UnsupportedSystem(String),
    #[error("GPU error: {0}")]
    GpuError(String),
    #[error("partition error: {0}")]
    PartitionError(String),
    #[error("verification failed: {0}")]
    VerificationFailed(String),
    #[error("aggregation failed: {0}")]
    AggregationFailed(String),
    #[error("serialization error: {0}")]
    SerializationError(String),
    #[error("circuit too large: {constraints} constraints exceed limit {limit}")]
    CircuitTooLarge { constraints: u64, limit: u64 },
    #[error("timeout after {0} seconds")]
    Timeout(u64),
    #[error("internal error: {0}")]
    Internal(String),
}

pub type ProverResult<T> = Result<T, ProverError>;

/// Top-level prover engine that dispatches to the appropriate backend.
pub struct ProverEngine {
    gpu_manager: Arc<gpu::GpuManager>,
    max_constraints: u64,
}

impl ProverEngine {
    pub fn new(max_constraints: u64) -> Self {
        Self {
            gpu_manager: Arc::new(gpu::GpuManager::detect()),
            max_constraints,
        }
    }

    /// Generate a proof for the given circuit and witness.
    pub async fn prove(
        &self,
        circuit: &Circuit,
        witness: &Witness,
        gpu_preference: Option<GpuBackendType>,
    ) -> ProverResult<Proof> {
        if circuit.num_constraints > self.max_constraints {
            return Err(ProverError::CircuitTooLarge {
                constraints: circuit.num_constraints,
                limit: self.max_constraints,
            });
        }

        let backend = self.select_backend(&circuit.proof_system, gpu_preference)?;
        backend.prove(circuit, witness).await
    }

    /// Verify a proof against a circuit and public inputs.
    pub async fn verify(
        &self,
        circuit: &Circuit,
        proof: &Proof,
        public_inputs: &[u8],
    ) -> ProverResult<bool> {
        let backend = self.select_backend(&circuit.proof_system, None)?;
        backend.verify(circuit, proof, public_inputs).await
    }

    /// Get available GPU capabilities.
    pub fn gpu_capabilities(&self) -> &[gpu::GpuDevice] {
        self.gpu_manager.devices()
    }

    fn select_backend(
        &self,
        proof_system: &ProofSystem,
        _gpu_preference: Option<GpuBackendType>,
    ) -> ProverResult<Box<dyn backends::ProverBackend>> {
        match proof_system {
            #[cfg(feature = "groth16")]
            ProofSystem::Groth16 => Ok(Box::new(backends::groth16::Groth16Backend::new(
                self.gpu_manager.clone(),
            ))),
            #[cfg(feature = "plonk")]
            ProofSystem::Plonk => Ok(Box::new(backends::plonk::PlonkBackend::new(
                self.gpu_manager.clone(),
            ))),
            #[cfg(feature = "halo2")]
            ProofSystem::Halo2 => Ok(Box::new(backends::halo2::Halo2Backend::new(
                self.gpu_manager.clone(),
            ))),
            #[cfg(feature = "stark")]
            ProofSystem::Stark => Ok(Box::new(backends::stark::StarkBackend::new(
                self.gpu_manager.clone(),
            ))),
            #[allow(unreachable_patterns)]
            _ => Err(ProverError::UnsupportedSystem(format!("{:?}", proof_system))),
        }
    }
}
