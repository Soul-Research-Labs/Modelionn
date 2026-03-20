#!/usr/bin/env python3
"""Simple end-to-end proof pipeline benchmark runner.

This script submits proof jobs and measures completion latency by polling
`/proofs/jobs/{task_id}` until each job reaches a terminal status.

Usage:
    python3 scripts/benchmark_proof_pipeline.py \
      --base-url http://localhost:8000 \
      --circuit-id 1 \
      --witness-cid QmExampleWitnessCid \
      --jobs 5 \
      --poll-interval 1.0

Auth (optional):
    ZKML_HOTKEY=... ZKML_SIGNATURE=... python3 scripts/benchmark_proof_pipeline.py ...
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx

TERMINAL_STATUSES = {"completed", "failed", "timeout", "cancelled"}


@dataclass
class JobResult:
    task_id: str
    status: str
    latency_s: float


def _build_summary(results: list[JobResult]) -> dict[str, Any]:
    latencies = [r.latency_s for r in results]
    completed = [r for r in results if r.status == "completed"]
    failed = [r for r in results if r.status in {"failed", "timeout", "cancelled"}]

    return {
        "jobs_total": len(results),
        "jobs_completed": len(completed),
        "jobs_failed": len(failed),
        "failure_rate": (len(failed) / len(results)) if results else 0.0,
        "latency_avg_s": statistics.fmean(latencies) if latencies else 0.0,
        "latency_p50_s": _percentile(latencies, 50),
        "latency_p95_s": _percentile(latencies, 95),
        "latency_p99_s": _percentile(latencies, 99),
        "results": [
            {"task_id": r.task_id, "status": r.status, "latency_s": round(r.latency_s, 3)}
            for r in results
        ],
    }


def _emit_summary(summary: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    print("\n==> Proof pipeline benchmark summary")
    for key, value in summary.items():
        if key == "results":
            continue
        if isinstance(value, float):
            print(f"{key}: {value:.3f}")
        else:
            print(f"{key}: {value}")


def _headers() -> dict[str, str]:
    hotkey = os.environ.get("ZKML_HOTKEY", "")
    signature = os.environ.get("ZKML_SIGNATURE", "")
    if not hotkey or not signature:
        return {}

    nonce = str(int(time.time()))
    return {
        "x-hotkey": hotkey,
        "x-signature": signature,
        "x-nonce": nonce,
    }


def _submit_job(
    client: httpx.Client,
    base_url: str,
    circuit_id: int,
    witness_cid: str,
    headers: dict[str, str],
) -> str:
    resp = client.post(
        f"{base_url}/proofs/jobs",
        json={"circuit_id": circuit_id, "witness_cid": witness_cid},
        headers=headers,
        timeout=30.0,
    )
    resp.raise_for_status()
    payload = resp.json()
    task_id = payload.get("task_id")
    if not task_id:
        raise RuntimeError(f"Missing task_id in response: {payload}")
    return task_id


def _wait_for_terminal(
    client: httpx.Client,
    base_url: str,
    task_id: str,
    headers: dict[str, str],
    poll_interval: float,
    timeout_s: float,
) -> JobResult:
    start = time.perf_counter()
    deadline = start + timeout_s

    while time.perf_counter() < deadline:
        resp = client.get(
            f"{base_url}/proofs/jobs/{task_id}",
            headers=headers,
            timeout=30.0,
        )
        resp.raise_for_status()
        status = str(resp.json().get("status", "unknown")).lower()
        if status in TERMINAL_STATUSES:
            return JobResult(
                task_id=task_id,
                status=status,
                latency_s=time.perf_counter() - start,
            )
        time.sleep(poll_interval)

    return JobResult(
        task_id=task_id,
        status="timeout",
        latency_s=timeout_s,
    )


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((pct / 100.0) * (len(ordered) - 1)))
    return ordered[index]


def run(args: argparse.Namespace) -> int:
    headers = _headers()
    with httpx.Client() as client:
        task_ids: list[str] = []
        for i in range(args.jobs):
            task_id = _submit_job(
                client=client,
                base_url=args.base_url,
                circuit_id=args.circuit_id,
                witness_cid=args.witness_cid,
                headers=headers,
            )
            task_ids.append(task_id)
            print(f"[{i + 1}/{args.jobs}] submitted {task_id}")

        results: list[JobResult] = []
        for i, task_id in enumerate(task_ids, start=1):
            result = _wait_for_terminal(
                client=client,
                base_url=args.base_url,
                task_id=task_id,
                headers=headers,
                poll_interval=args.poll_interval,
                timeout_s=args.timeout,
            )
            results.append(result)
            print(
                f"[{i}/{len(task_ids)}] {task_id} -> {result.status} in {result.latency_s:.2f}s"
            )

    summary = _build_summary(results)
    _emit_summary(summary, args.format)

    if args.max_p95_s is not None and summary["latency_p95_s"] > args.max_p95_s:
        return 3

    return 0 if summary["jobs_failed"] == 0 else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark proof pipeline latency")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--circuit-id", type=int, required=True)
    parser.add_argument("--witness-cid", required=True)
    parser.add_argument("--jobs", type=int, default=5)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--max-p95-s", type=float)
    return parser.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(run(parse_args()))
    except httpx.HTTPError as exc:
        print(f"Benchmark failed due to HTTP error: {exc}", file=sys.stderr)
        raise SystemExit(1)
