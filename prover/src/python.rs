//! PyO3 Python bindings for the ZKML prover engine.

#[cfg(feature = "python")]
use pyo3::prelude::*;

#[cfg(feature = "python")]
#[pymodule]
fn zkml_prover(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyProverEngine>()?;
    m.add_class::<PyCircuit>()?;
    m.add_class::<PyWitness>()?;
    m.add_class::<PyProof>()?;
    m.add_class::<PyGpuDevice>()?;
    m.add_class::<PyPartitionPlan>()?;
    Ok(())
}

#[cfg(feature = "python")]
#[pyclass(name = "ProverEngine")]
struct PyProverEngine {
    inner: crate::ProverEngine,
}

#[cfg(feature = "python")]
#[pymethods]
impl PyProverEngine {
    #[new]
    #[pyo3(signature = (max_constraints=1_000_000_000))]
    fn new(max_constraints: u64) -> Self {
        Self {
            inner: crate::ProverEngine::new(max_constraints),
        }
    }

    fn prove<'py>(
        &self,
        py: Python<'py>,
        circuit: &PyCircuit,
        witness: &PyWitness,
        gpu_preference: Option<String>,
    ) -> PyResult<PyProof> {
        let gpu_pref = gpu_preference.and_then(|s| match s.as_str() {
            "cuda" => Some(crate::GpuBackendType::Cuda),
            "rocm" => Some(crate::GpuBackendType::Rocm),
            "metal" => Some(crate::GpuBackendType::Metal),
            "webgpu" => Some(crate::GpuBackendType::WebGpu),
            "cpu" => Some(crate::GpuBackendType::Cpu),
            _ => None,
        });

        let rt = tokio::runtime::Runtime::new()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

        let result = rt.block_on(self.inner.prove(&circuit.inner, &witness.inner, gpu_pref));
        match result {
            Ok(proof) => Ok(PyProof { inner: proof }),
            Err(e) => Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string())),
        }
    }

    fn verify(
        &self,
        circuit: &PyCircuit,
        proof: &PyProof,
        public_inputs: Vec<u8>,
    ) -> PyResult<bool> {
        let rt = tokio::runtime::Runtime::new()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

        let result = rt.block_on(self.inner.verify(&circuit.inner, &proof.inner, &public_inputs));
        match result {
            Ok(valid) => Ok(valid),
            Err(e) => Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string())),
        }
    }

    fn gpu_devices(&self) -> Vec<PyGpuDevice> {
        self.inner
            .gpu_capabilities()
            .iter()
            .map(|d| PyGpuDevice {
                name: d.name.clone(),
                backend: format!("{:?}", d.backend),
                device_index: d.device_index,
                vram_total: d.vram_total,
                vram_available: d.vram_available,
                compute_units: d.compute_units,
                benchmark_score: d.benchmark_score,
            })
            .collect()
    }
}

#[cfg(feature = "python")]
#[pyclass(name = "Circuit")]
#[derive(Clone)]
struct PyCircuit {
    inner: crate::Circuit,
}

#[cfg(feature = "python")]
#[pymethods]
impl PyCircuit {
    #[new]
    #[pyo3(signature = (id, name, proof_system, circuit_type, num_constraints, num_public_inputs, num_private_inputs, data, proving_key, verification_key))]
    fn new(
        id: String,
        name: String,
        proof_system: String,
        circuit_type: String,
        num_constraints: u64,
        num_public_inputs: u32,
        num_private_inputs: u32,
        data: Vec<u8>,
        proving_key: Vec<u8>,
        verification_key: Vec<u8>,
    ) -> PyResult<Self> {
        let ps = match proof_system.as_str() {
            "groth16" => crate::ProofSystem::Groth16,
            "plonk" => crate::ProofSystem::Plonk,
            "halo2" => crate::ProofSystem::Halo2,
            "stark" => crate::ProofSystem::Stark,
            _ => return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
                format!("Unknown proof system: {}", proof_system),
            )),
        };
        let ct = match circuit_type.as_str() {
            "general" => crate::CircuitType::General,
            "evm" => crate::CircuitType::Evm,
            "zkml" => crate::CircuitType::ZkMl,
            "custom" => crate::CircuitType::Custom,
            _ => crate::CircuitType::General,
        };

        Ok(Self {
            inner: crate::Circuit {
                id,
                name,
                proof_system: ps,
                circuit_type: ct,
                num_constraints,
                num_public_inputs,
                num_private_inputs,
                data,
                proving_key,
                verification_key,
            },
        })
    }

    #[getter]
    fn id(&self) -> &str { &self.inner.id }
    #[getter]
    fn name(&self) -> &str { &self.inner.name }
    #[getter]
    fn num_constraints(&self) -> u64 { self.inner.num_constraints }
}

#[cfg(feature = "python")]
#[pyclass(name = "Witness")]
#[derive(Clone)]
struct PyWitness {
    inner: crate::Witness,
}

#[cfg(feature = "python")]
#[pymethods]
impl PyWitness {
    #[new]
    fn new(assignments: Vec<u8>, public_inputs: Vec<u8>) -> Self {
        Self {
            inner: crate::Witness {
                assignments,
                public_inputs,
            },
        }
    }
}

#[cfg(feature = "python")]
#[pyclass(name = "Proof")]
#[derive(Clone)]
struct PyProof {
    inner: crate::Proof,
}

#[cfg(feature = "python")]
#[pymethods]
impl PyProof {
    #[getter]
    fn proof_system(&self) -> String { format!("{:?}", self.inner.proof_system) }
    #[getter]
    fn data(&self) -> Vec<u8> { self.inner.data.clone() }
    #[getter]
    fn public_inputs(&self) -> Vec<u8> { self.inner.public_inputs.clone() }
    #[getter]
    fn generation_time_ms(&self) -> u64 { self.inner.generation_time_ms }
    #[getter]
    fn proof_size_bytes(&self) -> u64 { self.inner.proof_size_bytes }

    fn to_json(&self) -> PyResult<String> {
        serde_json::to_string(&self.inner)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))
    }
}

#[cfg(feature = "python")]
#[pyclass(name = "GpuDevice")]
#[derive(Clone)]
struct PyGpuDevice {
    #[pyo3(get)]
    name: String,
    #[pyo3(get)]
    backend: String,
    #[pyo3(get)]
    device_index: u32,
    #[pyo3(get)]
    vram_total: u64,
    #[pyo3(get)]
    vram_available: u64,
    #[pyo3(get)]
    compute_units: u32,
    #[pyo3(get)]
    benchmark_score: f64,
}

#[cfg(feature = "python")]
#[pyclass(name = "PartitionPlan")]
#[derive(Clone)]
struct PyPartitionPlan {
    inner: crate::PartitionPlan,
}

#[cfg(feature = "python")]
#[pymethods]
impl PyPartitionPlan {
    #[getter]
    fn circuit_id(&self) -> &str { &self.inner.circuit_id }
    #[getter]
    fn num_partitions(&self) -> usize { self.inner.partitions.len() }
    #[getter]
    fn redundancy(&self) -> u32 { self.inner.redundancy }
    #[getter]
    fn estimated_time_ms(&self) -> u64 { self.inner.estimated_time_ms }
}
