//! ZKML Prover Engine — GPU-accelerated zero-knowledge proof generation.
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_prover_engine_creation() {
        let engine = ProverEngine::new(1_000_000);
        assert_eq!(engine.max_constraints, 1_000_000);
    }

    #[test]
    fn test_error_display() {
        let err = ProverError::UnsupportedSystem("unknown".into());
        assert_eq!(format!("{}", err), "unsupported proof system: unknown");

        let err = ProverError::GpuError("out of memory".into());
        assert_eq!(format!("{}", err), "GPU error: out of memory");

        let err = ProverError::CircuitTooLarge {
            constraints: 2_000_000,
            limit: 1_000_000,
        };
        let msg = format!("{}", err);
        assert!(msg.contains("2000000"));
        assert!(msg.contains("1000000"));

        let err = ProverError::Timeout(600);
        assert_eq!(format!("{}", err), "timeout after 600 seconds");
    }

    #[test]
    fn test_error_variants() {
        // Just ensure all variants can be constructed
        let _errors: Vec<ProverError> = vec![
            ProverError::UnsupportedSystem("x".into()),
            ProverError::GpuError("x".into()),
            ProverError::PartitionError("x".into()),
            ProverError::VerificationFailed("x".into()),
            ProverError::AggregationFailed("x".into()),
            ProverError::SerializationError("x".into()),
            ProverError::CircuitTooLarge { constraints: 1, limit: 0 },
            ProverError::Timeout(1),
            ProverError::Internal("x".into()),
        ];
    }

    #[tokio::test]
    async fn test_prove_circuit_too_large() {
        let engine = ProverEngine::new(1000);
        let circuit = Circuit {
            id: "big".into(),
            name: "big-circuit".into(),
            proof_system: ProofSystem::Groth16,
            circuit_type: CircuitType::General,
            num_constraints: 5000, // Exceeds limit
            num_public_inputs: 1,
            num_private_inputs: 1,
            data: vec![],
            proving_key: vec![],
            verification_key: vec![],
        };
        let witness = Witness {
            assignments: vec![0u8; 16],
            public_inputs: vec![],
        };
        let result = engine.prove(&circuit, &witness, None).await;
        assert!(result.is_err());
        match result.unwrap_err() {
            ProverError::CircuitTooLarge { constraints, limit } => {
                assert_eq!(constraints, 5000);
                assert_eq!(limit, 1000);
            }
            _ => panic!("Expected CircuitTooLarge error"),
        }
    }

    #[test]
    fn test_gpu_capabilities_empty_by_default() {
        let engine = ProverEngine::new(1_000_000);
        // detect() won't find real GPUs in CI — just checking it doesn't panic
        let _caps = engine.gpu_capabilities();
    }
}
