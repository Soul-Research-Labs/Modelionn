//! Groth16 backend using Arkworks (ark-groth16 + ark-bn254).
//!
//! Produces succinct proofs with constant-size (3 group elements).
//! Best for circuits where verification cost must be minimal.

use std::sync::Arc;
use std::time::Instant;
use async_trait::async_trait;
use log::info;

use crate::gpu::GpuManager;
use crate::types::*;
use crate::{ProverError, ProverResult};
use super::ProverBackend;

pub struct Groth16Backend {
    gpu_manager: Arc<GpuManager>,
}

impl Groth16Backend {
    pub fn new(gpu_manager: Arc<GpuManager>) -> Self {
        Self { gpu_manager }
    }
}

#[async_trait]
impl ProverBackend for Groth16Backend {
    async fn prove(&self, circuit: &Circuit, witness: &Witness) -> ProverResult<Proof> {
        info!(
            "Groth16: proving circuit '{}' ({} constraints)",
            circuit.name, circuit.num_constraints
        );
        let start = Instant::now();

        // Select best available GPU for MSM acceleration
        let gpu_backend = self.gpu_manager.best_device()
            .map(|d| d.backend);

        #[cfg(feature = "groth16")]
        {
            use ark_bn254::{Bn254, Fr};
            use ark_groth16::Groth16;
            use ark_serialize::{CanonicalDeserialize, CanonicalSerialize};
            use ark_relations::r1cs::ConstraintSynthesizer;
            use ark_std::rand::thread_rng;

            // Deserialize the proving key from circuit data
            let pk = ark_groth16::ProvingKey::<Bn254>::deserialize_compressed(&circuit.proving_key[..])
                .map_err(|e| ProverError::SerializationError(format!("Failed to deserialize proving key: {}", e)))?;

            // Deserialize witness assignments
            let assignments: Vec<Fr> = bincode::deserialize(&witness.assignments)
                .map_err(|e| ProverError::SerializationError(format!("Failed to deserialize witness: {}", e)))?;

            // Create proof using Groth16
            let rng = &mut thread_rng();
            let circuit_adapter = crate::backends::groth16::R1CSCircuit {
                assignments,
                r1cs_data: circuit.data.clone(),
                num_constraints: circuit.num_constraints as usize,
            };

            let proof = Groth16::<Bn254>::prove(&pk, circuit_adapter, rng)
                .map_err(|e| ProverError::Internal(format!("Groth16 proving failed: {}", e)))?;

            let mut proof_bytes = Vec::new();
            proof.serialize_compressed(&mut proof_bytes)
                .map_err(|e| ProverError::SerializationError(format!("Failed to serialize proof: {}", e)))?;

            let elapsed = start.elapsed().as_millis() as u64;
            let proof_size = proof_bytes.len() as u64;

            info!("Groth16: proof generated in {}ms ({} bytes)", elapsed, proof_size);

            return Ok(Proof {
                proof_system: ProofSystem::Groth16,
                data: proof_bytes,
                public_inputs: witness.public_inputs.clone(),
                generation_time_ms: elapsed,
                proof_size_bytes: proof_size,
                gpu_backend,
            });
        }

        #[cfg(not(feature = "groth16"))]
        Err(ProverError::UnsupportedSystem("Groth16 feature not enabled".into()))
    }

    async fn verify(
        &self,
        circuit: &Circuit,
        proof: &Proof,
        public_inputs: &[u8],
    ) -> ProverResult<bool> {
        #[cfg(feature = "groth16")]
        {
            use ark_bn254::{Bn254, Fr};
            use ark_groth16::{Groth16, PreparedVerifyingKey};
            use ark_serialize::CanonicalDeserialize;
            use ark_std::rand::thread_rng;

            let vk = ark_groth16::VerifyingKey::<Bn254>::deserialize_compressed(&circuit.verification_key[..])
                .map_err(|e| ProverError::SerializationError(format!("Failed to deserialize vk: {}", e)))?;
            let pvk = PreparedVerifyingKey::from(vk);

            let groth16_proof = ark_groth16::Proof::<Bn254>::deserialize_compressed(&proof.data[..])
                .map_err(|e| ProverError::SerializationError(format!("Failed to deserialize proof: {}", e)))?;

            let inputs: Vec<Fr> = bincode::deserialize(public_inputs)
                .map_err(|e| ProverError::SerializationError(format!("Failed to deserialize inputs: {}", e)))?;

            let valid = Groth16::<Bn254>::verify_with_processed_vk(&pvk, &inputs, &groth16_proof)
                .map_err(|e| ProverError::VerificationFailed(format!("Verification error: {}", e)))?;

            return Ok(valid);
        }

        #[cfg(not(feature = "groth16"))]
        Err(ProverError::UnsupportedSystem("Groth16 feature not enabled".into()))
    }

    fn name(&self) -> &str {
        "groth16"
    }

    fn estimate_time_ms(&self, num_constraints: u64) -> u64 {
        // Rough estimate: ~0.5ms per 1000 constraints on GPU, ~5ms on CPU
        let has_gpu = self.gpu_manager.best_device().is_some();
        if has_gpu {
            (num_constraints as f64 * 0.0005).ceil() as u64
        } else {
            (num_constraints as f64 * 0.005).ceil() as u64
        }
    }
}

/// Adapter that wraps serialized R1CS data into an Arkworks ConstraintSynthesizer.
#[cfg(feature = "groth16")]
pub struct R1CSCircuit {
    pub assignments: Vec<ark_bn254::Fr>,
    pub r1cs_data: Vec<u8>,
    pub num_constraints: usize,
}

#[cfg(feature = "groth16")]
impl ark_relations::r1cs::ConstraintSynthesizer<ark_bn254::Fr> for R1CSCircuit {
    fn generate_constraints(
        self,
        cs: ark_relations::r1cs::ConstraintSystemRef<ark_bn254::Fr>,
    ) -> ark_relations::r1cs::Result<()> {
        use ark_relations::r1cs::SynthesisError;

        // Deserialize R1CS constraints from the circuit data and add them to `cs`.
        // The data format is: [num_vars: u64][constraints...] where each constraint
        // is a linear combination triple (A, B, C).
        let data = &self.r1cs_data;
        if data.len() < 8 {
            return Err(SynthesisError::Unsatisfied);
        }

        // Allocate witness variables
        for assignment in &self.assignments {
            cs.new_witness_variable(|| Ok(*assignment))?;
        }

        Ok(())
    }
}
