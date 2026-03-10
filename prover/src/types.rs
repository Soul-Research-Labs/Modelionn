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
