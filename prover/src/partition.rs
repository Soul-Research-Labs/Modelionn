//! Circuit partitioning for distributed collaborative proving.
//!
//! Splits large circuits into smaller sub-circuits that can be proven
//! independently by different miners, then aggregated.

use crate::types::*;
use crate::{ProverError, ProverResult};

/// Create a partition plan for distributing a circuit across provers.
pub fn create_partition_plan(
    circuit: &Circuit,
    num_provers: u32,
    redundancy: u32,
    max_constraints_per_partition: u64,
) -> ProverResult<PartitionPlan> {
    if num_provers == 0 {
        return Err(ProverError::PartitionError("need at least 1 prover".into()));
    }
    if redundancy == 0 {
        return Err(ProverError::PartitionError("redundancy must be >= 1".into()));
    }

    let total_constraints = circuit.num_constraints;

    // Calculate optimal number of partitions
    let min_partitions_by_provers = num_provers;
    let min_partitions_by_size = if max_constraints_per_partition > 0 {
        ((total_constraints + max_constraints_per_partition - 1) / max_constraints_per_partition) as u32
    } else {
        1
    };
    let num_partitions = min_partitions_by_provers.max(min_partitions_by_size).max(1);

    let constraints_per_partition = (total_constraints + num_partitions as u64 - 1) / num_partitions as u64;

    let mut partitions = Vec::with_capacity(num_partitions as usize);
    for i in 0..num_partitions {
        let start = i as u64 * constraints_per_partition;
        let end = ((i as u64 + 1) * constraints_per_partition).min(total_constraints);

        if start >= total_constraints {
            break;
        }

        // Extract the relevant portion of circuit data for this partition
        let partition_data = extract_partition_data(&circuit.data, start, end, total_constraints);
        let witness_fragment = Vec::new(); // Will be populated when witness is assigned

        partitions.push(Partition {
            index: i,
            total: num_partitions,
            constraint_start: start,
            constraint_end: end,
            data: partition_data,
            witness_fragment,
        });
    }

    // Estimate total time: parallel execution = max partition time
    let backend_factor = match circuit.proof_system {
        ProofSystem::Groth16 => 0.005,
        ProofSystem::Plonk => 0.01,
        ProofSystem::Halo2 => 0.02,
        ProofSystem::Stark => 0.03,
    };
    let estimated_time_ms = (constraints_per_partition as f64 * backend_factor).ceil() as u64;

    Ok(PartitionPlan {
        circuit_id: circuit.id.clone(),
        partitions,
        redundancy,
        estimated_time_ms,
    })
}

/// Assign witness fragments to partitions.
pub fn assign_witness_to_partitions(
    plan: &mut PartitionPlan,
    witness: &Witness,
    total_constraints: u64,
) -> ProverResult<()> {
    let total_witness_bytes = witness.assignments.len();
    if total_witness_bytes == 0 {
        return Err(ProverError::PartitionError("empty witness".into()));
    }

    for partition in &mut plan.partitions {
        // Use integer arithmetic to avoid floating-point rounding errors
        let byte_start = ((partition.constraint_start as u128 * total_witness_bytes as u128)
            / total_constraints as u128) as usize;
        let byte_end = (((partition.constraint_end as u128 * total_witness_bytes as u128)
            + total_constraints as u128 - 1)
            / total_constraints as u128) as usize;
        let byte_end = byte_end.min(total_witness_bytes);

        partition.witness_fragment = witness.assignments[byte_start..byte_end].to_vec();
    }

    Ok(())
}

/// Extract partition-specific circuit data from the full circuit.
fn extract_partition_data(
    circuit_data: &[u8],
    constraint_start: u64,
    constraint_end: u64,
    total_constraints: u64,
) -> Vec<u8> {
    if circuit_data.is_empty() || total_constraints == 0 {
        return Vec::new();
    }

    // Integer arithmetic to avoid floating-point rounding errors
    let byte_start = ((constraint_start as u128 * circuit_data.len() as u128)
        / total_constraints as u128) as usize;
    let byte_end = (((constraint_end as u128 * circuit_data.len() as u128)
        + total_constraints as u128 - 1)
        / total_constraints as u128) as usize;
    let byte_end = byte_end.min(circuit_data.len());

    circuit_data[byte_start..byte_end].to_vec()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::*;

    fn test_circuit(num_constraints: u64) -> Circuit {
        Circuit {
            id: "test-circuit".into(),
            name: "test".into(),
            proof_system: ProofSystem::Groth16,
            circuit_type: CircuitType::General,
            num_constraints,
            num_public_inputs: 1,
            num_private_inputs: 2,
            data: vec![0u8; (num_constraints as usize).min(1024)],
            proving_key: vec![],
            verification_key: vec![],
        }
    }

    #[test]
    fn test_create_partition_plan_single() {
        let circuit = test_circuit(1000);
        let plan = create_partition_plan(&circuit, 1, 2, 10_000_000).unwrap();
        assert_eq!(plan.partitions.len(), 1);
        assert_eq!(plan.redundancy, 2);
        assert_eq!(plan.circuit_id, "test-circuit");
    }

    #[test]
    fn test_create_partition_plan_multiple_provers() {
        let circuit = test_circuit(100_000);
        let plan = create_partition_plan(&circuit, 4, 2, 10_000_000).unwrap();
        assert!(plan.partitions.len() >= 4);
        // Check partitions cover full range
        assert_eq!(plan.partitions[0].constraint_start, 0);
        let last = plan.partitions.last().unwrap();
        assert_eq!(last.constraint_end, 100_000);
    }

    #[test]
    fn test_create_partition_plan_large_circuit() {
        let circuit = test_circuit(50_000_000);
        let plan = create_partition_plan(&circuit, 2, 1, 10_000_000).unwrap();
        // Should have at least 5 partitions (50M / 10M)
        assert!(plan.partitions.len() >= 5);
    }

    #[test]
    fn test_partition_plan_zero_provers_error() {
        let circuit = test_circuit(1000);
        let result = create_partition_plan(&circuit, 0, 1, 10_000_000);
        assert!(result.is_err());
    }

    #[test]
    fn test_partition_plan_zero_redundancy_error() {
        let circuit = test_circuit(1000);
        let result = create_partition_plan(&circuit, 1, 0, 10_000_000);
        assert!(result.is_err());
    }

    #[test]
    fn test_partition_indices_sequential() {
        let circuit = test_circuit(100_000);
        let plan = create_partition_plan(&circuit, 4, 2, 10_000_000).unwrap();
        for (i, p) in plan.partitions.iter().enumerate() {
            assert_eq!(p.index, i as u32);
            assert_eq!(p.total, plan.partitions.len() as u32);
        }
    }

    #[test]
    fn test_partition_constraints_contiguous() {
        let circuit = test_circuit(100_000);
        let plan = create_partition_plan(&circuit, 4, 2, 10_000_000).unwrap();
        for i in 1..plan.partitions.len() {
            assert_eq!(
                plan.partitions[i].constraint_start,
                plan.partitions[i - 1].constraint_end,
            );
        }
    }

    #[test]
    fn test_assign_witness_to_partitions() {
        let circuit = test_circuit(1000);
        let mut plan = create_partition_plan(&circuit, 2, 1, 10_000_000).unwrap();
        let witness = Witness {
            assignments: vec![1u8; 100],
            public_inputs: vec![],
        };
        assign_witness_to_partitions(&mut plan, &witness, 1000).unwrap();
        let total_bytes: usize = plan.partitions.iter().map(|p| p.witness_fragment.len()).sum();
        assert!(total_bytes >= 100); // May overlap slightly due to ceil
    }

    #[test]
    fn test_assign_empty_witness_error() {
        let circuit = test_circuit(1000);
        let mut plan = create_partition_plan(&circuit, 1, 1, 10_000_000).unwrap();
        let witness = Witness {
            assignments: vec![],
            public_inputs: vec![],
        };
        let result = assign_witness_to_partitions(&mut plan, &witness, 1000);
        assert!(result.is_err());
    }

    #[test]
    fn test_extract_partition_data_empty() {
        let data = extract_partition_data(&[], 0, 100, 100);
        assert!(data.is_empty());
    }

    #[test]
    fn test_extract_partition_data_zero_constraints() {
        let data = extract_partition_data(&[1, 2, 3], 0, 0, 0);
        assert!(data.is_empty());
    }

    #[test]
    fn test_extract_partition_data_proportional() {
        let data: Vec<u8> = (0..100).collect();
        let extracted = extract_partition_data(&data, 0, 50, 100);
        assert_eq!(extracted.len(), 50);
        assert_eq!(extracted[0], 0);
    }

    #[test]
    fn test_estimated_time_different_systems() {
        let groth16 = test_circuit(1_000_000);
        let plan_g = create_partition_plan(&groth16, 1, 1, 1_000_000).unwrap();

        let mut stark_circuit = test_circuit(1_000_000);
        stark_circuit.proof_system = ProofSystem::Stark;
        let plan_s = create_partition_plan(&stark_circuit, 1, 1, 1_000_000).unwrap();

        // STARKs should have higher estimated time
        assert!(plan_s.estimated_time_ms > plan_g.estimated_time_ms);
    }
}
