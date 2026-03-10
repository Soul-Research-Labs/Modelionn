"""Modelionn CLI — terminal interface for the ZK Prover Network on Bittensor."""

from __future__ import annotations

import json as json_mod
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="modelionn", help="Modelionn — GPU-Accelerated ZK Prover Network on Bittensor")
console = Console()

# ── Config file support ──────────────────────────────────────

_CONFIG_PATH = Path.home() / ".modelionn.toml"


def _load_config() -> dict:
    """Load defaults from ~/.modelionn.toml if it exists."""
    if not _CONFIG_PATH.exists():
        return {}
    try:
        import tomllib
    except ModuleNotFoundError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ModuleNotFoundError:
            return {}
    return tomllib.loads(_CONFIG_PATH.read_text())


def _cfg(key: str, default: str = "") -> str:
    """Read a config value from file → env → default."""
    cfg = _load_config()
    env_key = f"MODELIONN_{key.upper()}"
    return os.environ.get(env_key) or cfg.get(key, default)


def _resolve_hotkey(hotkey: str) -> str:
    """Resolve hotkey from flag or config or $MODELIONN_HOTKEY env var."""
    return hotkey or _cfg("hotkey")


def _default_registry() -> str:
    return _cfg("registry", "http://localhost:8000")


def _client(registry: str, hotkey: str):
    from sdk.client import ModelionnClient
    return ModelionnClient(registry_url=registry, hotkey=_resolve_hotkey(hotkey))


def _json_output(data: dict | list) -> None:
    """Print JSON to stdout for machine-readable output."""
    console.print_json(json_mod.dumps(data, default=str))


# ── Info ─────────────────────────────────────────────────────

@app.command()
def info(
    registry: str = typer.Option("", "--registry", "-r"),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show registry health and info."""
    import httpx
    reg = registry or _default_registry()
    resp = httpx.get(f"{reg}/health", timeout=10)
    data = resp.json()
    if output_json:
        _json_output(data)
        return
    console.print(f"Registry: {reg}")
    console.print(f"Status:   [green]{data['status']}[/]")
    console.print(f"Network:  {data['network']}")


# ── ZK Circuits ──────────────────────────────────────────────

@app.command(name="circuits")
def list_circuits(
    proof_type: str | None = typer.Option(None, "--proof-type", "-p", help="groth16|plonk|halo2|stark"),
    circuit_type: str | None = typer.Option(None, "--circuit-type", "-c", help="general|evm|zkml|custom"),
    page: int = typer.Option(1, "--page"),
    registry: str = typer.Option("http://localhost:8000", "--registry", "-r"),
    output_json: bool = typer.Option(False, "--json"),
):
    """List ZK circuits in the registry."""
    client = _client(registry, "")
    result = client.list_circuits(proof_type=proof_type, circuit_type=circuit_type, page=page)

    if output_json:
        _json_output(result)
        return

    table = Table(title="Circuits")
    table.add_column("ID", justify="right")
    table.add_column("Name", style="bold")
    table.add_column("Proof System")
    table.add_column("Type")
    table.add_column("Constraints", justify="right")
    table.add_column("Proofs", justify="right")

    for c in result.get("items", []):
        table.add_row(
            str(c.get("id", "")),
            c.get("name", ""),
            c.get("proof_type", ""),
            c.get("circuit_type", ""),
            f"{c.get('num_constraints', 0):,}",
            str(c.get("proofs_generated", 0)),
        )
    console.print(table)


@app.command(name="upload-circuit")
def upload_circuit(
    name: str = typer.Option(..., "--name", "-n", help="Circuit name"),
    version: str = typer.Option("1.0", "--version", "-v"),
    proof_type: str = typer.Option("groth16", "--proof-type", "-p"),
    circuit_type: str = typer.Option("general", "--circuit-type", "-c"),
    num_constraints: int = typer.Option(..., "--constraints"),
    data_cid: str = typer.Option(..., "--cid", help="IPFS CID of circuit data"),
    proving_key_cid: str = typer.Option("", "--pk-cid"),
    verification_key_cid: str = typer.Option("", "--vk-cid"),
    registry: str = typer.Option("http://localhost:8000", "--registry", "-r"),
    hotkey: str = typer.Option("", "--hotkey", "-k"),
):
    """Upload a ZK circuit to the registry."""
    client = _client(registry, hotkey)
    with console.status(f"Uploading circuit [bold]{name}@{version}[/]…"):
        result = client.upload_circuit(
            name=name, version=version, proof_type=proof_type,
            circuit_type=circuit_type, num_constraints=num_constraints,
            data_cid=data_cid, proving_key_cid=proving_key_cid,
            verification_key_cid=verification_key_cid,
        )
    console.print(f"[green]✓[/] Circuit uploaded — id={result.get('id', 'N/A')}")
    console.print(f"  Hash: {result.get('circuit_hash', 'N/A')}")


# ── ZK Proof Jobs ────────────────────────────────────────────

@app.command(name="prove")
def request_proof(
    circuit_id: int = typer.Argument(..., help="Circuit ID to prove"),
    witness_cid: str = typer.Option(..., "--witness", "-w", help="IPFS CID of witness data"),
    partitions: int = typer.Option(4, "--partitions"),
    redundancy: int = typer.Option(2, "--redundancy"),
    registry: str = typer.Option("http://localhost:8000", "--registry", "-r"),
    hotkey: str = typer.Option("", "--hotkey", "-k"),
    output_json: bool = typer.Option(False, "--json"),
):
    """Request a ZK proof generation job."""
    client = _client(registry, hotkey)
    with console.status("Submitting proof request…"):
        result = client.request_proof(
            circuit_id, witness_cid,
            num_partitions=partitions, redundancy=redundancy,
        )
    if output_json:
        _json_output(result)
        return
    console.print(f"[green]✓[/] Proof job submitted — task_id: {result.get('task_id', 'N/A')}")
    console.print(f"  Status:     {result.get('status', 'N/A')}")
    console.print(f"  Partitions: {result.get('num_partitions', 'N/A')}")


@app.command(name="proof-status")
def proof_status(
    task_id: str = typer.Argument(..., help="Proof job task ID"),
    registry: str = typer.Option("http://localhost:8000", "--registry", "-r"),
    output_json: bool = typer.Option(False, "--json"),
):
    """Check the status of a proof generation job."""
    client = _client(registry, "")
    result = client.get_proof_job(task_id)
    if output_json:
        _json_output(result)
        return
    console.print(f"Task:       {task_id}")
    console.print(f"Status:     [bold]{result.get('status', 'unknown')}[/]")
    console.print(f"Partitions: {result.get('partitions_completed', 0)}/{result.get('num_partitions', 0)}")
    if result.get("actual_time_ms"):
        console.print(f"Time:       {result['actual_time_ms'] / 1000:.1f}s")


@app.command(name="proof-jobs")
def list_proof_jobs(
    status: str | None = typer.Option(None, "--status", "-s"),
    page: int = typer.Option(1, "--page"),
    registry: str = typer.Option("http://localhost:8000", "--registry", "-r"),
    output_json: bool = typer.Option(False, "--json"),
):
    """List proof generation jobs."""
    client = _client(registry, "")
    result = client.list_proof_jobs(status=status, page=page)
    if output_json:
        _json_output(result)
        return

    table = Table(title="Proof Jobs")
    table.add_column("Task ID")
    table.add_column("Status")
    table.add_column("Progress")
    table.add_column("Time", justify="right")

    for job in result.get("items", []):
        progress = f"{job.get('partitions_completed', 0)}/{job.get('num_partitions', 0)}"
        t = f"{job['actual_time_ms'] / 1000:.1f}s" if job.get("actual_time_ms") else "—"
        table.add_row(job.get("task_id", "")[:16] + "…", job.get("status", ""), progress, t)
    console.print(table)


@app.command(name="verify-proof")
def verify_proof_cmd(
    proof_id: int = typer.Argument(..., help="Proof ID to verify"),
    vk_cid: str = typer.Option(..., "--vk-cid", help="Verification key CID"),
    public_inputs: str = typer.Option("{}", "--inputs", help="Public inputs JSON"),
    registry: str = typer.Option("http://localhost:8000", "--registry", "-r"),
    hotkey: str = typer.Option("", "--hotkey", "-k"),
):
    """Verify a completed proof."""
    client = _client(registry, hotkey)
    with console.status("Verifying proof…"):
        result = client.verify_proof(proof_id, vk_cid, public_inputs)
    if result.get("valid"):
        console.print(f"[green]✓[/] Proof is valid (verified in {result.get('verification_time_ms', 0)}ms)")
    else:
        console.print("[red]✗[/] Proof is invalid")
        raise typer.Exit(1)


# ── ZK Prover Network ───────────────────────────────────────

@app.command(name="provers")
def list_provers(
    online_only: bool = typer.Option(False, "--online", help="Show only online provers"),
    page: int = typer.Option(1, "--page"),
    registry: str = typer.Option("http://localhost:8000", "--registry", "-r"),
    output_json: bool = typer.Option(False, "--json"),
):
    """List provers in the network."""
    client = _client(registry, "")
    result = client.list_provers(online_only=online_only, page=page)
    if output_json:
        _json_output(result)
        return

    table = Table(title="Prover Network")
    table.add_column("Hotkey")
    table.add_column("GPU")
    table.add_column("Backend")
    table.add_column("Proofs", justify="right")
    table.add_column("Uptime", justify="right")
    table.add_column("Status")

    for p in result.get("items", []):
        status = "[green]●[/] Online" if p.get("online") else "[red]●[/] Offline"
        table.add_row(
            (p.get("hotkey", "")[:12] + "…"),
            p.get("gpu_name", "CPU"),
            p.get("gpu_backend", "cpu"),
            str(p.get("successful_proofs", 0)),
            f"{p.get('uptime_ratio', 0) * 100:.0f}%",
            status,
        )
    console.print(table)


@app.command(name="network-stats")
def network_stats(
    registry: str = typer.Option("http://localhost:8000", "--registry", "-r"),
    output_json: bool = typer.Option(False, "--json"),
):
    """Show ZK prover network statistics."""
    client = _client(registry, "")
    data = client.get_network_stats()
    if output_json:
        _json_output(data)
        return
    console.print("[bold]Modelionn ZK Prover Network[/]")
    console.print(f"  Online Provers:  {data.get('online_provers', 0)}/{data.get('total_provers', 0)}")
    console.print(f"  Total Proofs:    {data.get('total_proofs_generated', 0):,}")
    console.print(f"  Total Circuits:  {data.get('total_circuits', 0)}")
    console.print(f"  Active Jobs:     {data.get('active_jobs', 0)}")
    console.print(f"  Avg Proof Time:  {data.get('avg_proof_time_ms', 0) / 1000:.1f}s")
    vram_gb = data.get("total_gpu_vram_bytes", 0) / (1024 ** 3)
    console.print(f"  Total GPU VRAM:  {vram_gb:.1f} GB")


if __name__ == "__main__":
    app()


# ── Auth status ──────────────────────────────────────────────

@app.command(name="auth")
def auth_status():
    """Show current authentication configuration."""
    cfg = _load_config()
    hotkey = os.environ.get("MODELIONN_HOTKEY") or cfg.get("hotkey", "")
    registry = os.environ.get("MODELIONN_REGISTRY") or cfg.get("registry", "")
    config_exists = _CONFIG_PATH.exists()

    console.print(f"Config file: {_CONFIG_PATH} {'[green](exists)[/]' if config_exists else '[yellow](not found)[/]'}")
    console.print(f"Registry:    {registry or '[dim]not set[/]'}")
    console.print(f"Hotkey:      {hotkey or '[dim]not set[/]'}")
    if not hotkey:
        console.print("[yellow]Run 'modelionn login --hotkey <your-hotkey>' to configure.[/]")


# ── Login / configure ───────────────────────────────────────

@app.command()
def login(
    hotkey: str = typer.Option("", "--hotkey", "-k", help="Default hotkey"),
    registry: str = typer.Option("", "--registry", "-r", help="Registry URL"),
):
    """Save default configuration to ~/.modelionn.toml."""
    if registry and not registry.startswith(("http://", "https://")):
        console.print("[red]Registry URL must start with http:// or https://[/]")
        raise typer.Exit(1)
    if hotkey and len(hotkey) < 8:
        console.print("[red]Hotkey looks too short — provide a valid Bittensor hotkey.[/]")
        raise typer.Exit(1)

    lines: list[str] = []
    if registry:
        lines.append(f'registry = "{registry}"')
    if hotkey:
        lines.append(f'hotkey = "{hotkey}"')
    if not lines:
        console.print("[yellow]No values provided. Use --hotkey and/or --registry.[/]")
        raise typer.Exit(1)

    _CONFIG_PATH.write_text("\n".join(lines) + "\n")
    console.print(f"[green]✓[/] Config saved to {_CONFIG_PATH}")
    for line in lines:
        console.print(f"  {line}")
