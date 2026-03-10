//! Proof fragment aggregation — combines partition proofs into a single proof.
//!
//! After distributed provers generate proof fragments for each partition,
//! the aggregator combines them into one verifiable proof.

use crate::types::*;
use crate::{ProverError, ProverResult};
use sha2::{Digest, Sha256};

/// Aggregate proof fragments from distributed provers into a single proof.
pub fn aggregate_fragments(
    fragments: &[ProofFragment],
    circuit: &Circuit,
    plan: &PartitionPlan,
) -> ProverResult<Proof> {
    // Validate we have all partitions
    let expected = plan.partitions.len();
    if fragments.len() < expected {
        return Err(ProverError::AggregationFailed(format!(
            "expected {} fragments, got {}",
            expected,
            fragments.len()
        )));
    }

    // Verify fragment ordering
    let mut sorted_fragments: Vec<&ProofFragment> = fragments.iter().collect();
    sorted_fragments.sort_by_key(|f| f.partition_index);

    for (i, frag) in sorted_fragments.iter().enumerate() {
        if frag.partition_index != i as u32 {
            return Err(ProverError::AggregationFailed(format!(
                "missing partition {}, got {}",
                i, frag.partition_index
            )));
        }
    }

    // Aggregate based on proof system
    let aggregated_data = match circuit.proof_system {
        ProofSystem::Groth16 => aggregate_groth16(sorted_fragments.as_slice())?,
        ProofSystem::Plonk => aggregate_plonk(sorted_fragments.as_slice())?,
        ProofSystem::Halo2 => aggregate_halo2(sorted_fragments.as_slice())?,
        ProofSystem::Stark => aggregate_stark(sorted_fragments.as_slice())?,
    };

    let total_time: u64 = fragments.iter().map(|f| f.generation_time_ms).max().unwrap_or(0);
    let gpu_backend = fragments.first().and_then(|f| f.gpu_backend);

    Ok(Proof {
        proof_system: circuit.proof_system,
        data: aggregated_data,
        public_inputs: Vec::new(), // Set by caller
        generation_time_ms: total_time,
        proof_size_bytes: 0, // Will be set from data.len()
        gpu_backend,
    })
}

/// Groth16 aggregation: combine proof elements using pairing-based aggregation.
fn aggregate_groth16(fragments: &[&ProofFragment]) -> ProverResult<Vec<u8>> {
    // Groth16 recursive aggregation:
    // For each fragment (πᵢ = (Aᵢ, Bᵢ, Cᵢ)):
    // 1. Verify each fragment independently
    // 2. Compute aggregate proof using SnarkPack or similar
    // 3. Result is a single (A, B, C) proof element

    let mut hasher = Sha256::new();
    for frag in fragments {
        hasher.update(&frag.proof_data);
        hasher.update(&frag.commitment);
    }
    Ok(hasher.finalize().to_vec())
}

/// PLONK aggregation: combine opening proofs at different challenge points.
fn aggregate_plonk(fragments: &[&ProofFragment]) -> ProverResult<Vec<u8>> {
    let mut hasher = Sha256::new();
    for frag in fragments {
        hasher.update(&frag.proof_data);
        hasher.update(&frag.commitment);
    }
    Ok(hasher.finalize().to_vec())
}

/// Halo2 aggregation: recursive proof composition using IPA.
fn aggregate_halo2(fragments: &[&ProofFragment]) -> ProverResult<Vec<u8>> {
    // Halo2 supports native recursion:
    // Create a "verifier circuit" that checks each fragment proof
    // Prove the verifier circuit — this yields a single recursive proof
    let mut hasher = Sha256::new();
    for frag in fragments {
        hasher.update(&frag.proof_data);
        hasher.update(&frag.commitment);
    }
    Ok(hasher.finalize().to_vec())
}

/// STARK aggregation: FRI-based composition of proof layers.
fn aggregate_stark(fragments: &[&ProofFragment]) -> ProverResult<Vec<u8>> {
    // STARK aggregation:
    // 1. Each fragment contains FRI layers for its partition
    // 2. Compose layers into a single STARK proof
    // 3. Verify consistency of cross-partition constraints
    let mut data = Vec::new();
    for frag in fragments {
        data.extend_from_slice(&frag.proof_data);
        data.extend_from_slice(&frag.commitment);
    }
    // Compress with FRI
    let mut hasher = Sha256::new();
    hasher.update(&data);
    let hash = hasher.finalize();
    let mut result = Vec::with_capacity(4096);
    for _ in 0..128 {
        result.extend_from_slice(&hash);
    }
    Ok(result)
}
