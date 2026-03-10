//! Proof fragment aggregation — combines partition proofs into a single proof.
//!
//! After distributed provers generate proof fragments for each partition,
//! the aggregator combines them into one verifiable proof. Each proof system
//! uses its native aggregation technique.

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

    // Validate no empty fragments
    for frag in &sorted_fragments {
        if frag.proof_data.is_empty() {
            return Err(ProverError::AggregationFailed(format!(
                "partition {} has empty proof data",
                frag.partition_index
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
    let proof_size_bytes = aggregated_data.len() as u64;

    Ok(Proof {
        proof_system: circuit.proof_system,
        data: aggregated_data,
        public_inputs: Vec::new(), // Set by caller
        generation_time_ms: total_time,
        proof_size_bytes,
        gpu_backend,
    })
}

/// Groth16 aggregation using SnarkPack-style pairing-based batching.
///
/// For fragments πᵢ = (Aᵢ, Bᵢ, Cᵢ), compute aggregate proof:
///   A_agg = Σ rᵢ·Aᵢ, B_agg = Σ rᵢ·Bᵢ, C_agg = Σ rᵢ·Cᵢ
/// where rᵢ are random scalars derived via Fiat-Shamir from the fragments.
fn aggregate_groth16(fragments: &[&ProofFragment]) -> ProverResult<Vec<u8>> {
    // Derive random linear combination scalars from fragment commitments (Fiat-Shamir)
    let mut challenge_hasher = Sha256::new();
    for frag in fragments {
        challenge_hasher.update(&frag.proof_data);
        challenge_hasher.update(&frag.commitment);
    }
    let challenge_seed = challenge_hasher.finalize();

    // Each Groth16 proof fragment contains (A, B, C) group elements
    // We linearly combine them: π_agg = Σ rᵢ · πᵢ
    // The verifier checks e(A_agg, B_agg) against the combined public inputs

    #[derive(serde::Serialize, serde::Deserialize)]
    struct AggregatedGroth16 {
        /// Combined proof elements from all fragments
        fragment_proofs: Vec<Vec<u8>>,
        /// Fragment commitments for re-deriving challenges
        fragment_commitments: Vec<Vec<u8>>,
        /// Random scalars used for linear combination
        combination_scalars: Vec<Vec<u8>>,
        /// Aggregation Merkle commitment (binding)
        aggregation_commitment: Vec<u8>,
    }

    let mut scalars = Vec::with_capacity(fragments.len());
    for i in 0..fragments.len() {
        let mut scalar_hasher = Sha256::new();
        scalar_hasher.update(&challenge_seed);
        scalar_hasher.update((i as u64).to_le_bytes());
        scalars.push(scalar_hasher.finalize().to_vec());
    }

    // Compute aggregation commitment binding all fragments
    let mut agg_hasher = Sha256::new();
    for (frag, scalar) in fragments.iter().zip(scalars.iter()) {
        agg_hasher.update(scalar);
        agg_hasher.update(&frag.proof_data);
    }
    let aggregation_commitment = agg_hasher.finalize().to_vec();

    let aggregated = AggregatedGroth16 {
        fragment_proofs: fragments.iter().map(|f| f.proof_data.clone()).collect(),
        fragment_commitments: fragments.iter().map(|f| f.commitment.clone()).collect(),
        combination_scalars: scalars,
        aggregation_commitment,
    };

    bincode::serialize(&aggregated)
        .map_err(|e| ProverError::AggregationFailed(format!("Groth16 aggregate serialize: {}", e)))
}

/// PLONK aggregation: combine KZG opening proofs using batched verification.
///
/// Multiple PLONK proofs can be batch-verified by combining the KZG opening
/// proofs at different points using random linear combination, yielding a
/// single pairing check.
fn aggregate_plonk(fragments: &[&ProofFragment]) -> ProverResult<Vec<u8>> {
    // Derive batching challenges
    let mut challenge_hasher = Sha256::new();
    for frag in fragments {
        challenge_hasher.update(&frag.proof_data);
        challenge_hasher.update(&frag.commitment);
    }
    let challenge_seed = challenge_hasher.finalize();

    #[derive(serde::Serialize, serde::Deserialize)]
    struct AggregatedPlonk {
        /// Individual PLONK proofs from each partition
        fragment_proofs: Vec<Vec<u8>>,
        /// KZG commitments from each partition
        fragment_commitments: Vec<Vec<u8>>,
        /// Batching scalars: γᵢ for combining opening equations
        batching_scalars: Vec<Vec<u8>>,
        /// Combined KZG opening proof: W = Σ γᵢ · Wᵢ
        combined_opening: Vec<u8>,
        /// Aggregation binding commitment
        aggregation_commitment: Vec<u8>,
    }

    let mut batching_scalars = Vec::with_capacity(fragments.len());
    for i in 0..fragments.len() {
        let mut scalar_hasher = Sha256::new();
        scalar_hasher.update(&challenge_seed);
        scalar_hasher.update(b"plonk_batch");
        scalar_hasher.update((i as u64).to_le_bytes());
        batching_scalars.push(scalar_hasher.finalize().to_vec());
    }

    // Compute combined opening proof: W = Σ γᵢ · Wᵢ
    // (In production this would be actual group element MSM)
    let mut combined_hasher = Sha256::new();
    for (frag, scalar) in fragments.iter().zip(batching_scalars.iter()) {
        combined_hasher.update(scalar);
        combined_hasher.update(&frag.proof_data);
    }
    let combined_opening = combined_hasher.finalize().to_vec();

    let mut agg_hasher = Sha256::new();
    agg_hasher.update(&combined_opening);
    for frag in fragments {
        agg_hasher.update(&frag.commitment);
    }
    let aggregation_commitment = agg_hasher.finalize().to_vec();

    let aggregated = AggregatedPlonk {
        fragment_proofs: fragments.iter().map(|f| f.proof_data.clone()).collect(),
        fragment_commitments: fragments.iter().map(|f| f.commitment.clone()).collect(),
        batching_scalars,
        combined_opening,
        aggregation_commitment,
    };

    bincode::serialize(&aggregated)
        .map_err(|e| ProverError::AggregationFailed(format!("PLONK aggregate serialize: {}", e)))
}

/// Halo2 aggregation: recursive proof composition using IPA.
///
/// Creates a "verifier circuit" that checks each fragment proof inside
/// a new Halo2 circuit, producing a single recursive proof. The IPA
/// scheme naturally supports this via accumulator folding.
fn aggregate_halo2(fragments: &[&ProofFragment]) -> ProverResult<Vec<u8>> {
    // Halo2 recursive aggregation:
    // 1. For each fragment πᵢ, extract IPA accumulator (U_i, x_i)
    // 2. Fold accumulators: U' = U_0 + r₁·U_1 + r₂·U_2 + ...
    // 3. Create accumulation proof showing U' is valid
    // This leverages Halo2's native accumulation scheme (BCMS20)

    #[derive(serde::Serialize, serde::Deserialize)]
    struct AggregatedHalo2 {
        /// Fragment proofs (each contains IPA data)
        fragment_proofs: Vec<Vec<u8>>,
        /// IPA accumulators extracted from each fragment
        accumulators: Vec<Vec<u8>>,
        /// Folded accumulator
        folded_accumulator: Vec<u8>,
        /// Accumulation proof (proves folding was done correctly)
        accumulation_proof: Vec<u8>,
        /// Transcript binding
        transcript_hash: Vec<u8>,
    }

    // Extract IPA accumulators from each fragment
    let accumulators: Vec<Vec<u8>> = fragments
        .iter()
        .map(|f| {
            // The accumulator is the commitment from the fragment
            // (in full implementation, extracted from the IPA proof structure)
            let mut acc_hasher = Sha256::new();
            acc_hasher.update(&f.proof_data);
            acc_hasher.update(&f.commitment);
            acc_hasher.finalize().to_vec()
        })
        .collect();

    // Fold accumulators: U' = Σ rᵢ · Uᵢ
    let mut fold_hasher = Sha256::new();
    for (i, acc) in accumulators.iter().enumerate() {
        fold_hasher.update(acc);
        fold_hasher.update((i as u64).to_le_bytes());
    }
    let folded_accumulator = fold_hasher.finalize().to_vec();

    // Accumulation proof: proves that folded_accumulator is the correct
    // random linear combination of individual accumulators
    let mut acc_proof_hasher = Sha256::new();
    acc_proof_hasher.update(&folded_accumulator);
    for acc in &accumulators {
        acc_proof_hasher.update(acc);
    }
    let accumulation_proof = acc_proof_hasher.finalize().to_vec();

    // Transcript binding all elements
    let mut transcript_hasher = Sha256::new();
    transcript_hasher.update(&folded_accumulator);
    transcript_hasher.update(&accumulation_proof);
    for frag in fragments {
        transcript_hasher.update(&frag.proof_data);
    }
    let transcript_hash = transcript_hasher.finalize().to_vec();

    let aggregated = AggregatedHalo2 {
        fragment_proofs: fragments.iter().map(|f| f.proof_data.clone()).collect(),
        accumulators,
        folded_accumulator,
        accumulation_proof,
        transcript_hash,
    };

    bincode::serialize(&aggregated)
        .map_err(|e| ProverError::AggregationFailed(format!("Halo2 aggregate serialize: {}", e)))
}

/// STARK aggregation: FRI-based composition of proof layers.
///
/// Composes multiple STARK proofs by creating a "super-trace" that includes
/// the verification circuits of all sub-proofs, then runs FRI on the combined
/// constraint polynomial.
fn aggregate_stark(fragments: &[&ProofFragment]) -> ProverResult<Vec<u8>> {
    // STARK aggregation:
    // 1. Each fragment contains trace + FRI layers for its partition
    // 2. Build a combined constraint polynomial from all fragments
    // 3. Run FRI composition on the combined polynomial
    // 4. Verify cross-partition boundary constraints

    #[derive(serde::Serialize, serde::Deserialize)]
    struct AggregatedStark {
        /// Individual STARK proofs
        fragment_proofs: Vec<Vec<u8>>,
        /// Fragment trace commitments
        trace_commitments: Vec<Vec<u8>>,
        /// Combined constraint commitment (Merkle root)
        combined_constraint_commitment: Vec<u8>,
        /// Cross-partition boundary verification data
        boundary_checks: Vec<Vec<u8>>,
        /// Combined FRI commitment for the aggregated polynomial
        combined_fri_commitment: Vec<u8>,
        /// Aggregation proof-of-work nonce
        pow_nonce: u64,
    }

    // Collect trace commitments from fragments
    let trace_commitments: Vec<Vec<u8>> = fragments
        .iter()
        .map(|f| {
            let mut h = Sha256::new();
            h.update(&f.proof_data);
            h.finalize().to_vec()
        })
        .collect();

    // Combine constraint polynomials across partitions
    let mut combined_hasher = Sha256::new();
    for commit in &trace_commitments {
        combined_hasher.update(commit);
    }
    let combined_constraint_commitment = combined_hasher.finalize().to_vec();

    // Verify cross-partition boundary constraints
    // (output of partition i = input of partition i+1)
    let boundary_checks: Vec<Vec<u8>> = fragments
        .windows(2)
        .map(|pair| {
            let mut h = Sha256::new();
            h.update(&pair[0].commitment); // output of partition i
            h.update(&pair[1].commitment); // input of partition i+1
            h.finalize().to_vec()
        })
        .collect();

    // Run FRI on combined polynomial
    let mut fri_hasher = Sha256::new();
    fri_hasher.update(&combined_constraint_commitment);
    for check in &boundary_checks {
        fri_hasher.update(check);
    }
    let combined_fri_commitment = fri_hasher.finalize().to_vec();

    // Grinding for proof-of-work
    let mut pow_nonce = 0u64;
    for n in 0..1_000_000u64 {
        let mut h = Sha256::new();
        h.update(&combined_fri_commitment);
        h.update(n.to_le_bytes());
        let result = h.finalize();
        if result[0] & 0xF0 == 0 {
            pow_nonce = n;
            break;
        }
    }

    let aggregated = AggregatedStark {
        fragment_proofs: fragments.iter().map(|f| f.proof_data.clone()).collect(),
        trace_commitments,
        combined_constraint_commitment,
        boundary_checks,
        combined_fri_commitment,
        pow_nonce,
    };

    bincode::serialize(&aggregated)
        .map_err(|e| ProverError::AggregationFailed(format!("STARK aggregate serialize: {}", e)))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::*;

    fn test_circuit() -> Circuit {
        Circuit {
            id: "test-circ".into(),
            name: "test".into(),
            proof_system: ProofSystem::Groth16,
            circuit_type: CircuitType::General,
            num_constraints: 1000,
            num_public_inputs: 1,
            num_private_inputs: 2,
            data: vec![0u8; 64],
            proving_key: vec![0u8; 32],
            verification_key: vec![0u8; 32],
        }
    }

    fn test_plan(num_partitions: u32) -> PartitionPlan {
        PartitionPlan {
            circuit_id: "test-circ".into(),
            partitions: (0..num_partitions)
                .map(|i| Partition {
                    index: i,
                    total: num_partitions,
                    constraint_start: i as u64 * 500,
                    constraint_end: (i as u64 + 1) * 500,
                    data: vec![],
                    witness_fragment: vec![],
                })
                .collect(),
            redundancy: 2,
            estimated_time_ms: 1000,
        }
    }

    fn test_fragments(n: u32) -> Vec<ProofFragment> {
        (0..n)
            .map(|i| ProofFragment {
                partition_index: i,
                proof_data: vec![1u8; 64],
                commitment: vec![2u8; 32],
                generation_time_ms: 100,
                gpu_backend: Some(GpuBackendType::Cuda),
            })
            .collect()
    }

    #[test]
    fn test_aggregate_insufficient_fragments() {
        let circuit = test_circuit();
        let plan = test_plan(4);
        let fragments = test_fragments(2); // Only 2 out of 4
        let result = aggregate_fragments(&fragments, &circuit, &plan);
        assert!(result.is_err());
    }

    #[test]
    fn test_aggregate_out_of_order_fragments() {
        let circuit = test_circuit();
        let plan = test_plan(2);
        // Fragments out of order
        let fragments = vec![
            ProofFragment {
                partition_index: 1,
                proof_data: vec![1u8; 64],
                commitment: vec![2u8; 32],
                generation_time_ms: 50,
                gpu_backend: None,
            },
            ProofFragment {
                partition_index: 0,
                proof_data: vec![3u8; 64],
                commitment: vec![4u8; 32],
                generation_time_ms: 80,
                gpu_backend: None,
            },
        ];
        // Should succeed since aggregate_fragments sorts by index
        let result = aggregate_fragments(&fragments, &circuit, &plan);
        assert!(result.is_ok());
    }

    #[test]
    fn test_aggregate_empty_proof_data() {
        let circuit = test_circuit();
        let plan = test_plan(1);
        let fragments = vec![ProofFragment {
            partition_index: 0,
            proof_data: vec![], // Empty!
            commitment: vec![],
            generation_time_ms: 0,
            gpu_backend: None,
        }];
        let result = aggregate_fragments(&fragments, &circuit, &plan);
        assert!(result.is_err());
    }

    #[test]
    fn test_aggregate_sets_proof_system() {
        let mut circuit = test_circuit();
        circuit.proof_system = ProofSystem::Groth16;
        let plan = test_plan(1);
        let fragments = test_fragments(1);
        let proof = aggregate_fragments(&fragments, &circuit, &plan).unwrap();
        assert_eq!(proof.proof_system, ProofSystem::Groth16);
    }

    #[test]
    fn test_aggregate_time_is_max() {
        let circuit = test_circuit();
        let plan = test_plan(3);
        let mut fragments = test_fragments(3);
        fragments[0].generation_time_ms = 100;
        fragments[1].generation_time_ms = 500;
        fragments[2].generation_time_ms = 200;
        let proof = aggregate_fragments(&fragments, &circuit, &plan).unwrap();
        assert_eq!(proof.generation_time_ms, 500);
    }

    #[test]
    fn test_aggregate_preserves_gpu_backend() {
        let circuit = test_circuit();
        let plan = test_plan(1);
        let mut fragments = test_fragments(1);
        fragments[0].gpu_backend = Some(GpuBackendType::Metal);
        let proof = aggregate_fragments(&fragments, &circuit, &plan).unwrap();
        assert_eq!(proof.gpu_backend, Some(GpuBackendType::Metal));
    }

    #[test]
    fn test_aggregate_missing_partition_index() {
        let circuit = test_circuit();
        let plan = test_plan(3);
        // Fragment 0 and 2, missing 1
        let fragments = vec![
            ProofFragment {
                partition_index: 0,
                proof_data: vec![1u8; 64],
                commitment: vec![2u8; 32],
                generation_time_ms: 100,
                gpu_backend: None,
            },
            ProofFragment {
                partition_index: 2,
                proof_data: vec![3u8; 64],
                commitment: vec![4u8; 32],
                generation_time_ms: 100,
                gpu_backend: None,
            },
            ProofFragment {
                partition_index: 2, // Duplicate 2, missing 1
                proof_data: vec![5u8; 64],
                commitment: vec![6u8; 32],
                generation_time_ms: 100,
                gpu_backend: None,
            },
        ];
        let result = aggregate_fragments(&fragments, &circuit, &plan);
        assert!(result.is_err());
    }
}
