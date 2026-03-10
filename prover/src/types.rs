//! Core types used across the prover engine.

use serde::{Deserialize, Serialize};

/// Supported zero-knowledge proof systems.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProofSystem {
    Groth16,
    Plonk,
    Halo2,
    Stark,
}

/// Circuit type classification.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CircuitType {
    /// General-purpose arithmetic circuit
    General,
    /// EVM bytecode verification
    Evm,
    /// Zero-knowledge machine learning inference
    ZkMl,
    /// Custom user-defined circuit
    Custom,
}

/// GPU backend types.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GpuBackendType {
    Cuda,
    Rocm,
    Metal,
    WebGpu,
    Cpu,
}

/// A compiled circuit ready for proof generation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Circuit {
    /// Unique identifier (content-addressed hash)
    pub id: String,
    /// Human-readable name
    pub name: String,
    /// Proof system this circuit targets
    pub proof_system: ProofSystem,
    /// Circuit type classification
    pub circuit_type: CircuitType,
    /// Number of constraints
    pub num_constraints: u64,
    /// Number of public inputs
    pub num_public_inputs: u32,
    /// Number of private inputs (witness size)
    pub num_private_inputs: u32,
    /// Serialized circuit data (R1CS, PlonK gates, etc.)
    pub data: Vec<u8>,
    /// Proving key (serialized)
    pub proving_key: Vec<u8>,
    /// Verification key (serialized)
    pub verification_key: Vec<u8>,
}

/// Witness (private inputs) for a circuit.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Witness {
    /// Serialized witness assignments
    pub assignments: Vec<u8>,
    /// Public inputs (visible to verifier)
    pub public_inputs: Vec<u8>,
}

/// A generated zero-knowledge proof.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Proof {
    /// Proof system used
    pub proof_system: ProofSystem,
    /// Serialized proof bytes
    pub data: Vec<u8>,
    /// Public inputs used during proving
    pub public_inputs: Vec<u8>,
    /// Proof generation time in milliseconds
    pub generation_time_ms: u64,
    /// Size of the proof in bytes
    pub proof_size_bytes: u64,
    /// GPU backend used (if any)
    pub gpu_backend: Option<GpuBackendType>,
}

/// A partition describes a sub-circuit fragment for distributed proving.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Partition {
    /// Partition index within the circuit
    pub index: u32,
    /// Total number of partitions
    pub total: u32,
    /// Constraint range: start
    pub constraint_start: u64,
    /// Constraint range: end (exclusive)
    pub constraint_end: u64,
    /// Serialized partition circuit data
    pub data: Vec<u8>,
    /// Serialized partition witness
    pub witness_fragment: Vec<u8>,
}

/// Result of proving a single partition (a proof fragment).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProofFragment {
    /// Which partition this fragment covers
    pub partition_index: u32,
    /// Proof data for this partition
    pub proof_data: Vec<u8>,
    /// Intermediate state for aggregation
    pub commitment: Vec<u8>,
    /// Time taken in milliseconds
    pub generation_time_ms: u64,
    /// GPU backend used
    pub gpu_backend: Option<GpuBackendType>,
}

/// Plan for partitioning a circuit across multiple provers.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PartitionPlan {
    /// Circuit being partitioned
    pub circuit_id: String,
    /// Partitions to distribute
    pub partitions: Vec<Partition>,
    /// Redundancy factor (each partition assigned to N provers)
    pub redundancy: u32,
    /// Estimated total proving time in milliseconds
    pub estimated_time_ms: u64,
}

/// GPU device capabilities reported by a prover/miner.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GpuCapabilities {
    /// GPU device name (e.g., "NVIDIA RTX 4090")
    pub device_name: String,
    /// Backend type
    pub backend: GpuBackendType,
    /// Total VRAM in bytes
    pub vram_bytes: u64,
    /// Available VRAM in bytes
    pub vram_available_bytes: u64,
    /// Compute capability (CUDA) or equivalent
    pub compute_version: String,
    /// Number of compute units / SMs
    pub compute_units: u32,
    /// Benchmark score (proofs/second for standard circuit)
    pub benchmark_score: f64,
}

/// Statistics for a prover node.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProverStats {
    /// Total proofs generated
    pub total_proofs: u64,
    /// Successful proofs
    pub successful_proofs: u64,
    /// Failed proofs
    pub failed_proofs: u64,
    /// Average proof generation time in ms
    pub avg_generation_time_ms: f64,
    /// Total uptime in seconds
    pub uptime_seconds: u64,
    /// Available GPU devices
    pub gpus: Vec<GpuCapabilities>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_proof_system_serde() {
        let json = serde_json::to_string(&ProofSystem::Groth16).unwrap();
        assert_eq!(json, "\"groth16\"");
        let parsed: ProofSystem = serde_json::from_str("\"plonk\"").unwrap();
        assert_eq!(parsed, ProofSystem::Plonk);
    }

    #[test]
    fn test_circuit_type_serde() {
        let json = serde_json::to_string(&CircuitType::ZkMl).unwrap();
        assert_eq!(json, "\"zk_ml\"");
        let parsed: CircuitType = serde_json::from_str("\"evm\"").unwrap();
        assert_eq!(parsed, CircuitType::Evm);
    }

    #[test]
    fn test_gpu_backend_type_serde() {
        let json = serde_json::to_string(&GpuBackendType::Cuda).unwrap();
        assert_eq!(json, "\"cuda\"");
        let parsed: GpuBackendType = serde_json::from_str("\"metal\"").unwrap();
        assert_eq!(parsed, GpuBackendType::Metal);
    }

    #[test]
    fn test_proof_system_variants() {
        let variants = [
            ProofSystem::Groth16,
            ProofSystem::Plonk,
            ProofSystem::Halo2,
            ProofSystem::Stark,
        ];
        for v in &variants {
            let json = serde_json::to_string(v).unwrap();
            let back: ProofSystem = serde_json::from_str(&json).unwrap();
            assert_eq!(*v, back);
        }
    }

    #[test]
    fn test_circuit_serde_roundtrip() {
        let circuit = Circuit {
            id: "abc123".into(),
            name: "test".into(),
            proof_system: ProofSystem::Groth16,
            circuit_type: CircuitType::General,
            num_constraints: 1000,
            num_public_inputs: 2,
            num_private_inputs: 5,
            data: vec![1, 2, 3],
            proving_key: vec![4, 5],
            verification_key: vec![6, 7],
        };
        let json = serde_json::to_string(&circuit).unwrap();
        let back: Circuit = serde_json::from_str(&json).unwrap();
        assert_eq!(back.id, "abc123");
        assert_eq!(back.num_constraints, 1000);
        assert_eq!(back.proof_system, ProofSystem::Groth16);
    }

    #[test]
    fn test_proof_fragment_serde_roundtrip() {
        let frag = ProofFragment {
            partition_index: 3,
            proof_data: vec![10, 20],
            commitment: vec![30],
            generation_time_ms: 500,
            gpu_backend: Some(GpuBackendType::Cuda),
        };
        let json = serde_json::to_string(&frag).unwrap();
        let back: ProofFragment = serde_json::from_str(&json).unwrap();
        assert_eq!(back.partition_index, 3);
        assert_eq!(back.gpu_backend, Some(GpuBackendType::Cuda));
    }

    #[test]
    fn test_partition_plan_serde() {
        let plan = PartitionPlan {
            circuit_id: "circ-1".into(),
            partitions: vec![
                Partition {
                    index: 0,
                    total: 2,
                    constraint_start: 0,
                    constraint_end: 500,
                    data: vec![],
                    witness_fragment: vec![],
                },
            ],
            redundancy: 2,
            estimated_time_ms: 1000,
        };
        let json = serde_json::to_string(&plan).unwrap();
        let back: PartitionPlan = serde_json::from_str(&json).unwrap();
        assert_eq!(back.redundancy, 2);
        assert_eq!(back.partitions.len(), 1);
    }

    #[test]
    fn test_gpu_capabilities_serde() {
        let caps = GpuCapabilities {
            device_name: "RTX 4090".into(),
            backend: GpuBackendType::Cuda,
            vram_bytes: 24_000_000_000,
            vram_available_bytes: 20_000_000_000,
            compute_version: "8.9".into(),
            compute_units: 128,
            benchmark_score: 9500.0,
        };
        let json = serde_json::to_string(&caps).unwrap();
        let back: GpuCapabilities = serde_json::from_str(&json).unwrap();
        assert_eq!(back.device_name, "RTX 4090");
        assert_eq!(back.vram_bytes, 24_000_000_000);
    }

    #[test]
    fn test_witness_serde() {
        let w = Witness {
            assignments: vec![1, 2, 3, 4, 5],
            public_inputs: vec![10, 20],
        };
        let json = serde_json::to_string(&w).unwrap();
        let back: Witness = serde_json::from_str(&json).unwrap();
        assert_eq!(back.assignments.len(), 5);
        assert_eq!(back.public_inputs.len(), 2);
    }
}
