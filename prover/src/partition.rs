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
        let start_frac = partition.constraint_start as f64 / total_constraints as f64;
        let end_frac = partition.constraint_end as f64 / total_constraints as f64;

        let byte_start = (start_frac * total_witness_bytes as f64) as usize;
        let byte_end = (end_frac * total_witness_bytes as f64).ceil() as usize;
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

    // Proportional extraction based on constraint range
    let start_frac = constraint_start as f64 / total_constraints as f64;
    let end_frac = constraint_end as f64 / total_constraints as f64;

    let byte_start = (start_frac * circuit_data.len() as f64) as usize;
    let byte_end = (end_frac * circuit_data.len() as f64).ceil() as usize;
    let byte_end = byte_end.min(circuit_data.len());

    circuit_data[byte_start..byte_end].to_vec()
}
