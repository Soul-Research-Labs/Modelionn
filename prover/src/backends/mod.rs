//! Proof system backends — trait definition and implementations.

pub mod groth16;
pub mod plonk;
pub mod halo2;
pub mod stark;

use async_trait::async_trait;
use crate::{Circuit, Proof, ProverResult, Witness};

/// Trait that all proof system backends must implement.
#[async_trait]
pub trait ProverBackend: Send + Sync {
    /// Generate a proof for the given circuit and witness.
    async fn prove(&self, circuit: &Circuit, witness: &Witness) -> ProverResult<Proof>;

    /// Verify a proof against a circuit and public inputs.
    async fn verify(
        &self,
        circuit: &Circuit,
        proof: &Proof,
        public_inputs: &[u8],
    ) -> ProverResult<bool>;

    /// Return the name of this backend.
    fn name(&self) -> &str;

    /// Estimate proving time in milliseconds for a circuit of given constraint count.
    fn estimate_time_ms(&self, num_constraints: u64) -> u64;
}
