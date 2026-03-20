# Prover Development Guide

This guide covers the ZKML prover engine — a Rust library exposing PyO3 bindings for GPU-accelerated zero-knowledge proof generation.

---

## Architecture Overview

```
prover/
├── src/
│   ├── lib.rs            # ProverEngine: top-level dispatch + tests
│   ├── types.rs           # Proof, Circuit, Witness, Partition enums/structs
│   ├── python.rs          # PyO3 class wrappers
│   ├── partition.rs       # Constraint-range splitting for distributed proving
│   ├── aggregate.rs       # Fragment aggregation per proof system
│   ├── verify.rs          # Verification routines (groth16/plonk/halo2/stark)
│   ├── backends/
│   │   ├── mod.rs         # ProverBackend trait
│   │   ├── groth16.rs     # Arkworks BN254 pairing backend
│   │   ├── plonk.rs       # KZG commitment backend
│   │   ├── halo2.rs       # IPA commitment backend
│   │   └── stark.rs       # Winterfell FRI backend
│   └── gpu/
│       ├── mod.rs         # GpuManager: detect, select, MSM, NTT
│       ├── cuda.rs        # ICICLE runtime (NVIDIA)
│       ├── metal.rs       # Compute shaders (Apple Silicon)
│       ├── rocm.rs        # HIP kernels (AMD)
│       └── webgpu.rs      # wgpu cross-platform
└── python/                # Python source overlay for maturin
```

---

## Building

The prover is built with [maturin](https://www.maturin.rs/) which compiles the Rust code and creates a Python wheel.

### Prerequisites

- Rust 1.70+ (install via `rustup`)
- Python 3.10+
- maturin 1.4+ (`pip install maturin`)

### Development Build

```bash
cd prover
maturin develop --features "groth16,plonk"
```

### Release Build

```bash
maturin build --release --features "groth16,plonk,halo2,stark,cuda"
```

### Feature Flags

| Feature   | Default | Description                              |
| --------- | ------- | ---------------------------------------- |
| `groth16` | ✅      | Arkworks BN254 pairing-based proofs      |
| `plonk`   | ✅      | KZG commitment with custom gates         |
| `halo2`   | ✅      | IPA commitments, recursive composition   |
| `stark`   | ✅      | Winterfell FRI polynomial IOP            |
| `cuda`    | ❌      | ICICLE NVIDIA GPU acceleration           |
| `metal`   | ❌      | Apple Silicon compute shaders            |
| `webgpu`  | ❌      | Cross-platform GPU via wgpu              |
| `python`  | ❌      | Build PyO3 bindings (enabled by maturin) |

Enable GPU features for your platform:

```bash
# NVIDIA
maturin develop --features "groth16,plonk,cuda"

# macOS
maturin develop --features "groth16,plonk,metal"

# Cross-platform
maturin develop --features "groth16,plonk,webgpu"
```

---

## Core Types

### ProofSystem

```rust
pub enum ProofSystem { Groth16, Plonk, Halo2, Stark }
```

### CircuitType

```rust
pub enum CircuitType { General, Evm, ZkMl, Custom }
```

### GpuBackendType

```rust
pub enum GpuBackendType { Cuda, Rocm, Metal, WebGpu, Cpu }
```

### Circuit

```rust
pub struct Circuit {
    id: String,
    name: String,
    proof_system: ProofSystem,
    circuit_type: CircuitType,
    num_constraints: u64,
    num_public_inputs: u32,
    num_private_inputs: u32,
    data: Vec<u8>,
    proving_key: Vec<u8>,
    verification_key: Vec<u8>,
}
```

### Witness / Proof

```rust
pub struct Witness {
    assignments: Vec<u8>,
    public_inputs: Vec<u8>,
}

pub struct Proof {
    version: u32,           // PROOF_FORMAT_VERSION = 1
    proof_system: ProofSystem,
    data: Vec<u8>,
    public_inputs: Vec<u8>,
    generation_time_ms: u64,
    proof_size_bytes: u64,
    gpu_backend: Option<GpuBackendType>,
}
```

---

## ProverEngine

The entry point for proof generation and verification.

```rust
impl ProverEngine {
    pub fn new(max_constraints: u64) -> Self;
    pub async fn prove(
        &self,
        circuit: &Circuit,
        witness: &Witness,
        gpu_preference: Option<GpuBackendType>,
    ) -> ProverResult<Proof>;
    pub async fn verify(
        &self,
        circuit: &Circuit,
        proof: &Proof,
        public_inputs: &[u8],
    ) -> ProverResult<bool>;
    pub fn gpu_capabilities(&self) -> &[GpuDevice];
}
```

`select_backend()` chooses the appropriate `ProverBackend` based on the circuit's proof system and the GPU preference.

### ProverBackend Trait

```rust
#[async_trait]
pub trait ProverBackend: Send + Sync {
    async fn prove(&self, circuit: &Circuit, witness: &Witness) -> ProverResult<Proof>;
    async fn verify(&self, circuit: &Circuit, proof: &Proof, public_inputs: &[u8]) -> ProverResult<bool>;
    fn name(&self) -> &str;
    fn estimate_time_ms(&self, num_constraints: u64) -> u64;
}
```

All four backends (`Groth16Backend`, `PlonkBackend`, `Halo2Backend`, `StarkBackend`) implement this trait and accept an `Arc<GpuManager>` at construction.

---

## GPU Acceleration

### GpuManager

Detects available hardware and exposes MSM/NTT primitives:

```rust
impl GpuManager {
    pub fn detect() -> Self;
    pub fn best_device(&self) -> Option<&GpuDevice>;
    pub fn msm(&self, scalars: &[u8], points: &[u8], result: &mut [u8]) -> Result<(), String>;
    pub fn ntt(&self, coefficients: &[u8], result: &mut [u8], inverse: bool) -> Result<(), String>;
}
```

### Backend-specific acceleration

| Backend | CUDA                | Metal                                | ROCm              | WebGPU         |
| ------- | ------------------- | ------------------------------------ | ----------------- | -------------- |
| MSM     | ICICLE BN254 kernel | Bucket accumulation (16-bit windows) | HIP bucket method | Compute shader |
| NTT     | ICICLE kernel       | Cooley-Tukey butterfly               | rocFFT-alike      | Compute shader |

Detection is automatic:

- **CUDA**: `icicle_cuda_runtime::device::get_device_count()` or `nvidia-smi` fallback
- **Metal**: `system_profiler SPDisplaysDataType --json`
- **ROCm**: `rocm-smi --showproductname --showmeminfo vram`
- **WebGPU**: `wgpu::Instance::enumerate_adapters()`

---

## Partitioning & Distributed Proving

Large circuits are split across multiple provers for parallel proving.

```rust
pub fn create_partition_plan(
    circuit: &Circuit,
    num_provers: u32,
    redundancy: u32,
    max_constraints_per_partition: u64,
) -> ProverResult<PartitionPlan>;

pub fn assign_witness_to_partitions(
    plan: &mut PartitionPlan,
    witness: &Witness,
    total_constraints: u64,
) -> ProverResult<()>;
```

Each `Partition` has a constraint range (`constraint_start..constraint_end`) and the extracted circuit/witness fragment for that range.

### Aggregation

After provers generate `ProofFragment`s, they are aggregated into a single proof:

```rust
pub fn aggregate_fragments(
    fragments: &[ProofFragment],
    circuit: &Circuit,
    plan: &PartitionPlan,
) -> ProverResult<Proof>;
```

Aggregation strategy depends on the proof system:

| System      | Strategy                                                                                                   |
| ----------- | ---------------------------------------------------------------------------------------------------------- |
| **Groth16** | SnarkPack-style linear combination — Fiat-Shamir random scalars combine A/B/C points, single pairing check |
| **PLONK**   | Batched KZG opening — combine opening proofs with Fiat-Shamir γ scalars                                    |
| **Halo2**   | Recursive IPA accumulator — verifier circuit folds each fragment                                           |
| **STARK**   | FRI layer merging — combine Merkle roots and decommitment paths                                            |

---

## Proof System Comparison

| System  | Curve | Setup              | Proof Size | Verify Cost   | Post-Quantum |
| ------- | ----- | ------------------ | ---------- | ------------- | ------------ |
| Groth16 | BN254 | Trusted ceremony   | ~192 B     | O(1) pairing  | No           |
| PLONK   | BN254 | Universal SRS      | ~10 KiB    | O(1) pairings | No           |
| Halo2   | Pasta | None               | ~15 KiB    | O(log n)      | No           |
| STARK   | None  | None (transparent) | ~100 KiB   | O(log² n) FRI | Yes          |

---

## Python Bindings

The `zkml_prover._native` module exposes Rust types to Python via PyO3.

### Usage

```python
from zkml_prover._native import ProverEngine, Circuit, Witness

engine = ProverEngine(max_constraints=1_000_000_000)

circuit = Circuit(
    id="my-circuit",
    name="Example",
    proof_system="groth16",
    circuit_type="general",
    num_constraints=50000,
    num_public_inputs=3,
    num_private_inputs=10,
    data=circuit_bytes,
    proving_key=pk_bytes,
    verification_key=vk_bytes,
)

witness = Witness(
    assignments=assignment_bytes,
    public_inputs=public_input_bytes,
)

# Generate proof (auto-selects best GPU)
proof = engine.prove(circuit, witness)

# Or specify GPU backend
proof = engine.prove(circuit, witness, gpu_preference="cuda")

# Verify
valid = engine.verify(circuit, proof, public_input_bytes)

# Inspect
print(proof.proof_system)        # "groth16"
print(proof.generation_time_ms)  # 4200
print(proof.proof_size_bytes)    # 192
print(proof.to_json())           # JSON-serialized proof

# GPU info
for dev in engine.gpu_devices():
    print(dev.name, dev.backend, dev.vram_total, dev.benchmark_score)
```

### gpu_preference values

`"cuda"`, `"rocm"`, `"metal"`, `"webgpu"`, `"cpu"`, or `None` (auto-select).

---

## Adding a New Backend

1. Create `src/backends/new_system.rs` implementing `ProverBackend`
2. Add the proof system variant to `ProofSystem` in `types.rs`
3. Wire it into `select_backend()` in `lib.rs`
4. Add aggregation logic in `aggregate.rs`
5. Add verification logic in `verify.rs`
6. Gate behind a Cargo feature flag in `Cargo.toml`
7. Add PyO3 string mapping in `python.rs`

---

## Testing

### Rust tests

```bash
cd prover
cargo test                           # All tests
cargo test --features groth16        # Groth16 only
cargo test --features "groth16,cuda" # With GPU
```

### Environment variables

- `RUST_LOG=debug` — Verbose logging
- `ZKML_GPU_BACKEND=cpu` — Force CPU fallback

### Running from Python

```bash
cd prover
maturin develop
python -c "from zkml_prover._native import ProverEngine; print(ProverEngine().gpu_devices())"
```

---

## Performance Tuning

The release profile uses aggressive optimizations:

```toml
[profile.release]
opt-level = 3
lto = "fat"
codegen-units = 1
strip = true
```

### Tips

- Use `cuda` feature on NVIDIA hardware for 10× MSM speedup
- Set `max_constraints_per_partition` to match available VRAM (1M constraints ≈ 4 GB)
- Increase `redundancy` in `create_partition_plan` for fault tolerance (default: 1)
- Monitor GPU utilization with `nvidia-smi dmon` or `rocm-smi --showuse`
