"""Modelionn CLI — terminal interface for the ZK Prover Network on Bittensor."""

from __future__ import annotations

import json as json_mod
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table


def _version_str() -> str:
    try:
        from importlib.metadata import version
        return version("modelionn")
    except Exception:
        return "0.0.0-unknown"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"modelionn {_version_str()}")
        raise typer.Exit()


app = typer.Typer(
    name="modelionn",
    help="Modelionn — GPU-Accelerated ZK Prover Network on Bittensor",
)
console = Console()


@app.callback()
def main_callback(
    version: bool = typer.Option(False, "--version", "-V", callback=_version_callback, is_eager=True, help="Show version and exit."),
) -> None:
    """Modelionn CLI — GPU-Accelerated ZK Prover Network on Bittensor."""

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
    return ModelionnClient(registry_url=registry or _default_registry(), hotkey=_resolve_hotkey(hotkey))


def _json_output(data: dict | list) -> None:
    """Print JSON to stdout for machine-readable output."""
    console.print_json(json_mod.dumps(data, default=str))


import re

_SS58_PATTERN = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{46,48}$")


def _validate_hotkey(hotkey: str) -> str | None:
    """Validate a Bittensor SS58 hotkey. Returns error message or None."""
    if len(hotkey) < 8:
        return "Hotkey too short — must be a valid SS58 address (46-48 characters)."
    if len(hotkey) > 128:
        return "Hotkey too long — maximum 128 characters."
    if not _SS58_PATTERN.match(hotkey):
        return "Invalid hotkey format — must be a valid SS58 address (base58 characters, 46-48 chars)."
    return None


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
    registry: str = typer.Option("", "--registry", "-r"),
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
    registry: str = typer.Option("", "--registry", "-r"),
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
    registry: str = typer.Option("", "--registry", "-r"),
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
    registry: str = typer.Option("", "--registry", "-r"),
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
    registry: str = typer.Option("", "--registry", "-r"),
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


@app.command(name="cancel-proof")
def cancel_proof_cmd(
    task_id: str = typer.Argument(..., help="Proof job task ID to cancel"),
    registry: str = typer.Option("", "--registry", "-r"),
    hotkey: str = typer.Option("", "--hotkey", "-k"),
    output_json: bool = typer.Option(False, "--json"),
):
    """Cancel a queued or dispatched proof job."""
    client = _client(registry, hotkey)
    result = client.cancel_proof_job(task_id)
    if output_json:
        _json_output(result)
        return
    console.print(f"[green]✓[/] Proof job {task_id} cancelled")


@app.command(name="get-proof")
def get_proof_cmd(
    proof_id: int = typer.Argument(..., help="Proof ID"),
    registry: str = typer.Option("", "--registry", "-r"),
    hotkey: str = typer.Option("", "--hotkey", "-k"),
    output_json: bool = typer.Option(False, "--json"),
):
    """Get details of a specific proof."""
    client = _client(registry, hotkey)
    result = client.get_proof(proof_id)
    if output_json:
        _json_output(result)
        return
    console.print(f"Proof ID:    {result.get('id')}")
    console.print(f"Circuit:     {result.get('circuit_id')}")
    console.print(f"Proof Type:  {result.get('proof_type')}")
    console.print(f"Verified:    {'[green]yes[/]' if result.get('verified') else '[yellow]no[/]'}")
    console.print(f"Size:        {result.get('proof_size_bytes', 0):,} bytes")
    console.print(f"Gen Time:    {(result.get('generation_time_ms', 0) or 0) / 1000:.1f}s")
    console.print(f"Data CID:    {result.get('proof_data_cid', 'N/A')}")


@app.command(name="list-proofs")
def list_proofs_cmd(
    circuit_id: int | None = typer.Option(None, "--circuit-id", "-c"),
    verified: bool | None = typer.Option(None, "--verified"),
    page: int = typer.Option(1, "--page"),
    page_size: int = typer.Option(20, "--page-size"),
    registry: str = typer.Option("", "--registry", "-r"),
    hotkey: str = typer.Option("", "--hotkey", "-k"),
    output_json: bool = typer.Option(False, "--json"),
):
    """List generated proofs."""
    client = _client(registry, hotkey)
    result = client.list_proofs(circuit_id=circuit_id, verified=verified, page=page, page_size=page_size)
    if output_json:
        _json_output(result)
        return

    table = Table(title=f"Proofs (page {result.get('page', 1)}/{max(1, (result.get('total', 0) + page_size - 1) // page_size)})")
    table.add_column("ID", justify="right")
    table.add_column("Circuit", justify="right")
    table.add_column("Type")
    table.add_column("Verified")
    table.add_column("Size", justify="right")
    table.add_column("Gen Time", justify="right")

    for p in result.get("items", []):
        table.add_row(
            str(p.get("id", "")),
            str(p.get("circuit_id", "")),
            p.get("proof_type", ""),
            "[green]✓[/]" if p.get("verified") else "[dim]✗[/]",
            f"{p.get('proof_size_bytes', 0):,}",
            f"{(p.get('generation_time_ms', 0) or 0) / 1000:.1f}s",
        )
    console.print(table)
    console.print(f"Total: {result.get('total', 0)}")


@app.command(name="verify-proof")
def verify_proof_cmd(
    proof_id: int = typer.Argument(..., help="Proof ID to verify"),
    vk_cid: str = typer.Option(..., "--vk-cid", help="Verification key CID"),
    public_inputs: str = typer.Option("{}", "--inputs", help="Public inputs JSON"),
    registry: str = typer.Option("", "--registry", "-r"),
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
    registry: str = typer.Option("", "--registry", "-r"),
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
    registry: str = typer.Option("", "--registry", "-r"),
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


# ── Register prover ─────────────────────────────────────────

@app.command(name="register-prover")
def register_prover(
    gpu_name: str = typer.Option(..., "--gpu", help="GPU model name (e.g. 'NVIDIA RTX 4090')"),
    gpu_backend: str = typer.Option("cuda", "--gpu-backend", help="GPU backend: cuda, rocm, metal, cpu"),
    gpu_count: int = typer.Option(1, "--gpu-count", help="Number of GPUs"),
    vram_bytes: int = typer.Option(0, "--vram", help="Total VRAM in bytes"),
    proof_systems: str = typer.Option("groth16,plonk,halo2,stark", "--proof-systems", help="Supported proof systems (comma-separated)"),
    benchmark_score: float = typer.Option(0.0, "--benchmark-score", help="GPU benchmark score"),
    registry: str = typer.Option("", "--registry", "-r"),
    hotkey: str = typer.Option("", "--hotkey", "-k"),
    output_json: bool = typer.Option(False, "--json"),
):
    """Register this node as a ZK prover with its GPU capabilities."""
    hk = _resolve_hotkey(hotkey)
    err = _validate_hotkey(hk)
    if err:
        console.print(f"[red]Error:[/] {err}")
        raise typer.Exit(1)

    client = _client(registry, hotkey)
    data = client.register_prover(
        gpu_name=gpu_name,
        gpu_backend=gpu_backend,
        gpu_count=gpu_count,
        vram_total_bytes=vram_bytes,
        supported_proof_types=proof_systems,
        benchmark_score=benchmark_score,
    )
    if output_json:
        _json_output(data)
        return
    console.print("[green]✓[/] Prover registered successfully")
    console.print(f"  Hotkey:    {hk[:12]}…{hk[-6:]}")
    console.print(f"  GPU:       {gpu_name} ({gpu_backend})")
    console.print(f"  Systems:   {proof_systems}")


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
    if hotkey:
        err = _validate_hotkey(hotkey)
        if err:
            console.print(f"[red]{err}[/]")
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


# ── Organizations ────────────────────────────────────────────

org_app = typer.Typer(help="Organization management")
app.add_typer(org_app, name="org")


@org_app.command(name="list")
def org_list(
    registry: str = typer.Option("", "--registry", "-r"),
    hotkey: str = typer.Option("", "--hotkey", "-k"),
    output_json: bool = typer.Option(False, "--json"),
):
    """List organizations you belong to."""
    client = _client(registry, hotkey)
    result = client.list_my_orgs()
    if output_json:
        _json_output(result)
        return
    table = Table(title="My Organizations")
    table.add_column("ID", justify="right")
    table.add_column("Name", style="bold")
    table.add_column("Slug")
    for org in result:
        table.add_row(str(org.get("id", "")), org.get("name", ""), org.get("slug", ""))
    console.print(table)


@org_app.command(name="create")
def org_create(
    name: str = typer.Option(..., "--name", "-n"),
    slug: str = typer.Option(..., "--slug", "-s"),
    registry: str = typer.Option("", "--registry", "-r"),
    hotkey: str = typer.Option("", "--hotkey", "-k"),
):
    """Create a new organization."""
    client = _client(registry, hotkey)
    result = client.create_org(name=name, slug=slug)
    console.print(f"[green]✓[/] Organization created — id={result.get('id')} slug={result.get('slug')}")


@org_app.command(name="members")
def org_members(
    slug: str = typer.Argument(..., help="Organization slug"),
    registry: str = typer.Option("", "--registry", "-r"),
    output_json: bool = typer.Option(False, "--json"),
):
    """List members of an organization."""
    client = _client(registry, "")
    result = client.list_members(slug)
    if output_json:
        _json_output(result)
        return
    table = Table(title=f"Members of {slug}")
    table.add_column("User ID", justify="right")
    table.add_column("Hotkey")
    table.add_column("Role")
    for m in result.get("items", []):
        table.add_row(str(m.get("user_id", "")), m.get("hotkey", ""), m.get("role", ""))
    console.print(table)


@org_app.command(name="add-member")
def org_add_member(
    slug: str = typer.Argument(..., help="Organization slug"),
    member_hotkey: str = typer.Option(..., "--hotkey-member", help="Hotkey to add"),
    role: str = typer.Option("viewer", "--role"),
    registry: str = typer.Option("", "--registry", "-r"),
    hotkey: str = typer.Option("", "--hotkey", "-k"),
):
    """Add a member to an organization (requires ADMIN)."""
    client = _client(registry, hotkey)
    result = client.add_member(slug, hotkey=member_hotkey, role=role)
    console.print(f"[green]✓[/] Added {member_hotkey} as {result.get('role', role)}")


@org_app.command(name="remove-member")
def org_remove_member(
    slug: str = typer.Argument(..., help="Organization slug"),
    member_hotkey: str = typer.Option(..., "--hotkey-member", help="Hotkey to remove"),
    registry: str = typer.Option("", "--registry", "-r"),
    hotkey: str = typer.Option("", "--hotkey", "-k"),
):
    """Remove a member from an organization (requires ADMIN)."""
    client = _client(registry, hotkey)
    client.remove_member(slug, member_hotkey)
    console.print(f"[green]✓[/] Removed {member_hotkey} from {slug}")


# ── API Keys ────────────────────────────────────────────────

apikey_app = typer.Typer(help="API key management")
app.add_typer(apikey_app, name="api-key")


@apikey_app.command(name="create")
def apikey_create(
    label: str = typer.Option("", "--label", "-l"),
    daily_limit: int = typer.Option(1000, "--limit"),
    registry: str = typer.Option("", "--registry", "-r"),
    hotkey: str = typer.Option("", "--hotkey", "-k"),
):
    """Create a new API key."""
    client = _client(registry, hotkey)
    result = client.create_api_key(label=label, daily_limit=daily_limit)
    console.print(f"[green]✓[/] API key created")
    console.print(f"  Key:   [bold]{result.get('key', '')}[/]")
    console.print(f"  Label: {result.get('label', '')}")
    console.print(f"  Limit: {result.get('daily_limit', 1000)}/day")
    console.print("[yellow]Save this key — it will not be shown again.[/]")


@apikey_app.command(name="list")
def apikey_list(
    registry: str = typer.Option("", "--registry", "-r"),
    hotkey: str = typer.Option("", "--hotkey", "-k"),
    output_json: bool = typer.Option(False, "--json"),
):
    """List your API keys."""
    client = _client(registry, hotkey)
    result = client.list_api_keys()
    if output_json:
        _json_output(result)
        return
    table = Table(title="API Keys")
    table.add_column("ID", justify="right")
    table.add_column("Label")
    table.add_column("Daily Limit", justify="right")
    table.add_column("Used Today", justify="right")
    table.add_column("Created")
    for k in result:
        table.add_row(
            str(k.get("id", "")),
            k.get("label", ""),
            str(k.get("daily_limit", "")),
            str(k.get("requests_today", 0)),
            k.get("created_at", "")[:10],
        )
    console.print(table)


@apikey_app.command(name="revoke")
def apikey_revoke(
    key_id: int = typer.Argument(..., help="API key ID to revoke"),
    registry: str = typer.Option("", "--registry", "-r"),
    hotkey: str = typer.Option("", "--hotkey", "-k"),
):
    """Revoke an API key."""
    client = _client(registry, hotkey)
    client.revoke_api_key(key_id)
    console.print(f"[green]✓[/] API key {key_id} revoked")


# ── Webhooks ─────────────────────────────────────────────────

webhook_app = typer.Typer(help="Webhook management")
app.add_typer(webhook_app, name="webhooks")


@webhook_app.command(name="list")
def webhook_list(
    registry: str = typer.Option("", "--registry", "-r"),
    hotkey: str = typer.Option("", "--hotkey", "-k"),
    output_json: bool = typer.Option(False, "--json"),
):
    """List your webhook configurations."""
    client = _client(registry, hotkey)
    result = client.list_webhooks()
    if output_json:
        _json_output(result)
        return
    table = Table(title="Webhooks")
    table.add_column("ID", justify="right")
    table.add_column("Label")
    table.add_column("URL")
    table.add_column("Events")
    table.add_column("Active")
    for wh in result:
        active = "[green]yes[/]" if wh.get("active") else "[red]no[/]"
        table.add_row(
            str(wh.get("id", "")),
            wh.get("label", ""),
            wh.get("url", "")[:50],
            wh.get("events", ""),
            active,
        )
    console.print(table)


@webhook_app.command(name="create")
def webhook_create(
    url: str = typer.Option(..., "--url", "-u", help="Webhook endpoint URL (HTTPS required)"),
    label: str = typer.Option(..., "--label", "-l", help="Human-readable label"),
    events: str = typer.Option("*", "--events", "-e", help="Comma-separated events or * for all"),
    registry: str = typer.Option("", "--registry", "-r"),
    hotkey: str = typer.Option("", "--hotkey", "-k"),
):
    """Create a new webhook endpoint."""
    if not url.startswith("https://"):
        console.print("[red]Error:[/] Webhook URL must use HTTPS")
        raise typer.Exit(1)
    client = _client(registry, hotkey)
    result = client.create_webhook(url=url, label=label, events=events)
    console.print(f"[green]✓[/] Webhook created — id={result.get('id')}")
    console.print(f"  URL:    {result.get('url')}")
    console.print(f"  Events: {result.get('events')}")
    console.print(f"  Secret: [bold]{result.get('secret', 'N/A')}[/]")
    console.print("[yellow]Save this secret — it will not be shown again.[/]")


@webhook_app.command(name="update")
def webhook_update(
    webhook_id: int = typer.Argument(..., help="Webhook ID to update"),
    url: str | None = typer.Option(None, "--url", "-u"),
    label: str | None = typer.Option(None, "--label", "-l"),
    events: str | None = typer.Option(None, "--events", "-e"),
    active: bool | None = typer.Option(None, "--active/--inactive"),
    registry: str = typer.Option("", "--registry", "-r"),
    hotkey: str = typer.Option("", "--hotkey", "-k"),
):
    """Update a webhook configuration."""
    if url is not None and not url.startswith("https://"):
        console.print("[red]Error:[/] Webhook URL must use HTTPS")
        raise typer.Exit(1)
    client = _client(registry, hotkey)
    result = client.update_webhook(
        webhook_id, url=url, label=label, events=events, active=active,
    )
    console.print(f"[green]✓[/] Webhook {webhook_id} updated")


@webhook_app.command(name="delete")
def webhook_delete(
    webhook_id: int = typer.Argument(..., help="Webhook ID to delete"),
    registry: str = typer.Option("", "--registry", "-r"),
    hotkey: str = typer.Option("", "--hotkey", "-k"),
):
    """Delete a webhook configuration."""
    client = _client(registry, hotkey)
    client.delete_webhook(webhook_id)
    console.print(f"[green]✓[/] Webhook {webhook_id} deleted")


# ── Audit Logs ──────────────────────────────────────────────

audit_app = typer.Typer(help="Audit log queries")
app.add_typer(audit_app, name="audit")


@audit_app.command(name="list")
def audit_list(
    action: str | None = typer.Option(None, "--action"),
    resource_type: str | None = typer.Option(None, "--resource-type"),
    actor: str | None = typer.Option(None, "--actor"),
    page: int = typer.Option(1, "--page"),
    registry: str = typer.Option("", "--registry", "-r"),
    output_json: bool = typer.Option(False, "--json"),
):
    """List audit log entries."""
    from sdk.client import ModelionnClient
    c = ModelionnClient(registry_url=registry or _default_registry())
    params: dict = {"page": page}
    if action:
        params["action"] = action
    if resource_type:
        params["resource_type"] = resource_type
    if actor:
        params["actor_hotkey"] = actor
    resp = c._request_with_retry("GET", f"{c._url}/audit", params=params)
    data = resp.json()
    if output_json:
        _json_output(data)
        return
    table = Table(title="Audit Logs")
    table.add_column("ID", justify="right")
    table.add_column("Action")
    table.add_column("Actor")
    table.add_column("Resource")
    table.add_column("Time")
    for entry in data.get("items", []):
        table.add_row(
            str(entry.get("id", "")),
            entry.get("action", ""),
            (entry.get("actor_hotkey", "")[:12] + "…") if entry.get("actor_hotkey") else "",
            f"{entry.get('resource_type', '')}:{entry.get('resource_id', '')}",
            entry.get("created_at", "")[:19],
        )
    console.print(table)


@app.command(name="completion")
def show_completion(
    install: bool = typer.Option(False, "--install", help="Install completion for current shell"),
    show: bool = typer.Option(False, "--show", help="Show completion script"),
    shell: str = typer.Option("", "--shell", help="Shell type (bash|zsh|fish|powershell)"),
) -> None:
    """Manage shell tab completion.

    Run `modelionn completion --install` to enable tab completion for your shell.
    """
    import subprocess
    import sys

    if not install and not show:
        console.print("Usage: modelionn completion --install  or  modelionn completion --show")
        console.print("  --shell bash|zsh|fish|powershell  (auto-detected if omitted)")
        raise typer.Exit()

    # Auto-detect shell if not specified
    if not shell:
        parent = os.environ.get("SHELL", "")
        if "zsh" in parent:
            shell = "zsh"
        elif "fish" in parent:
            shell = "fish"
        elif "bash" in parent:
            shell = "bash"
        else:
            shell = "bash"

    shell_map = {"bash": "bash", "zsh": "zsh", "fish": "fish", "powershell": "powershell"}
    if shell not in shell_map:
        console.print(f"[red]Unsupported shell: {shell}. Use bash, zsh, fish, or powershell.[/]")
        raise typer.Exit(1)

    prog = "modelionn"
    env_var = f"_{prog.upper()}_COMPLETE"

    if show:
        result = subprocess.run(
            [sys.executable, "-m", "cli.main"],
            env={**os.environ, env_var: f"complete_{shell}"},
            capture_output=True,
            text=True,
        )
        console.print(result.stdout or result.stderr)
    elif install:
        if shell == "zsh":
            comp_dir = Path.home() / ".zfunc"
            comp_dir.mkdir(exist_ok=True)
            comp_file = comp_dir / f"_{prog}"
            result = subprocess.run(
                [sys.executable, "-m", "cli.main"],
                env={**os.environ, env_var: "complete_zsh"},
                capture_output=True,
                text=True,
            )
            comp_file.write_text(result.stdout)
            console.print(f"[green]✓[/] Completion installed to {comp_file}")
            console.print("  Add 'fpath=(~/.zfunc $fpath)' to ~/.zshrc if not already present, then restart shell.")
        elif shell == "bash":
            comp_dir = Path.home() / ".bash_completions"
            comp_dir.mkdir(exist_ok=True)
            comp_file = comp_dir / f"{prog}.sh"
            result = subprocess.run(
                [sys.executable, "-m", "cli.main"],
                env={**os.environ, env_var: "complete_bash"},
                capture_output=True,
                text=True,
            )
            comp_file.write_text(result.stdout)
            console.print(f"[green]✓[/] Completion installed to {comp_file}")
            console.print(f"  Add 'source {comp_file}' to ~/.bashrc, then restart shell.")
        elif shell == "fish":
            comp_dir = Path.home() / ".config" / "fish" / "completions"
            comp_dir.mkdir(parents=True, exist_ok=True)
            comp_file = comp_dir / f"{prog}.fish"
            result = subprocess.run(
                [sys.executable, "-m", "cli.main"],
                env={**os.environ, env_var: "complete_fish"},
                capture_output=True,
                text=True,
            )
            comp_file.write_text(result.stdout)
            console.print(f"[green]✓[/] Completion installed to {comp_file}")
        else:
            console.print("[yellow]PowerShell completion: run 'modelionn completion --show --shell powershell' and add to $PROFILE[/]")


if __name__ == "__main__":
    app()
