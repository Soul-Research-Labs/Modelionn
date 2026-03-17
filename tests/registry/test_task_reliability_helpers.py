"""Focused unit tests for dispatch/aggregation/webhook reliability helpers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace


class _Partition:
    def __init__(self) -> None:
        self.status = "assigned"
        self.assigned_prover = "hotkey-1"
        self.assigned_at = object()
        self.error = None


def test_build_cumulative_weights_normalized():
    from registry.tasks.proof_dispatch import _build_cumulative_weights

    cumulative = _build_cumulative_weights([9.0, 1.0])
    assert len(cumulative) == 2
    assert cumulative[0] == 0.9
    assert cumulative[1] == 1.0


def test_build_cumulative_weights_uniform_when_zero_scores():
    from registry.tasks.proof_dispatch import _build_cumulative_weights

    cumulative = _build_cumulative_weights([0.0, 0.0, 0.0])
    assert cumulative == [1.0 / 3.0, 2.0 / 3.0, 1.0]


def test_pick_weighted_index_is_stable():
    from registry.tasks.proof_dispatch import _pick_weighted_index

    weights = [0.5, 1.0]
    picks = [_pick_weighted_index(i, weights) for i in range(20)]
    assert all(p in (0, 1) for p in picks)


def test_should_skip_dispatch_only_for_non_queued_jobs():
    from registry.models.database import ProofJobStatus
    from registry.tasks.proof_dispatch import _should_skip_dispatch

    assert _should_skip_dispatch(SimpleNamespace(status=ProofJobStatus.QUEUED)) is False
    assert _should_skip_dispatch(SimpleNamespace(status=ProofJobStatus.PROVING)) is True


def test_dispatch_lock_key_uses_job_id():
    from registry.tasks.proof_dispatch import _dispatch_lock_key

    assert _dispatch_lock_key(42) == "dispatch_job_42"


def test_release_dispatch_lock_deletes_only_when_token_matches():
    from registry.tasks.proof_dispatch import _release_dispatch_lock

    class _Redis:
        def __init__(self, current_token: str):
            self.current_token = current_token
            self.deleted_keys: list[str] = []

        async def get(self, key: str) -> str:
            return self.current_token

        async def delete(self, key: str) -> None:
            self.deleted_keys.append(key)

    matching = _Redis("token-1")
    asyncio.run(_release_dispatch_lock(matching, "dispatch_job_1", "token-1"))
    assert matching.deleted_keys == ["dispatch_job_1"]

    non_matching = _Redis("token-2")
    asyncio.run(_release_dispatch_lock(non_matching, "dispatch_job_1", "token-1"))
    assert non_matching.deleted_keys == []


def test_dispatch_with_lock_releases_lock_after_success(monkeypatch):
    from registry.tasks import proof_dispatch as pd

    class _Redis:
        def __init__(self):
            self.tokens: dict[str, str] = {}
            self.deleted_keys: list[str] = []

        async def set(self, key: str, token: str, nx: bool, ex: int) -> bool:
            self.tokens[key] = token
            return True

        async def get(self, key: str) -> str | None:
            return self.tokens.get(key)

        async def delete(self, key: str) -> None:
            self.deleted_keys.append(key)
            self.tokens.pop(key, None)

    redis = _Redis()

    async def _fake_client():
        return redis

    async def _fake_dispatch_async(task, job_id: int) -> dict:
        return {"status": "dispatched", "job_id": job_id}

    monkeypatch.setattr(pd, "_get_dispatch_redis_client", _fake_client)
    monkeypatch.setattr(pd, "_dispatch_async", _fake_dispatch_async)

    result = asyncio.run(pd._dispatch_with_lock(object(), 11))

    assert result["status"] == "dispatched"
    assert redis.deleted_keys == ["dispatch_job_11"]


def test_reset_timeout_partitions_clears_assignment():
    from registry.tasks.proof_aggregate import _reset_timeout_partitions

    parts = [_Partition(), _Partition(), _Partition()]
    count = _reset_timeout_partitions(parts)

    assert count == 3
    assert all(p.status == "pending" for p in parts)
    assert all(p.assigned_prover is None for p in parts)
    assert all(p.assigned_at is None for p in parts)
    assert all(p.error == "Reset after proving timeout" for p in parts)


def test_recover_orphaned_partition_resets_proving_work(monkeypatch):
    from registry.tasks.prover_health import _recover_orphaned_partition

    part = _Partition()
    part.status = "proving"

    action = _recover_orphaned_partition(part, [], 0)

    assert action == "reset"
    assert part.status == "pending"
    assert part.assigned_prover is None
    assert part.error == "Reset after assigned prover went offline during proving"


def test_resolve_stale_job_target_matches_state_machine():
    from registry.models.database import ProofJobStatus
    from registry.tasks.prover_health import _resolve_stale_job_target

    assert _resolve_stale_job_target(ProofJobStatus.PROVING) == ProofJobStatus.TIMEOUT
    assert _resolve_stale_job_target(ProofJobStatus.DISPATCHED) == ProofJobStatus.FAILED


def test_webhook_circuit_breaker_trip_and_recovery():
    from registry.tasks import webhook_delivery as wd

    webhook_id = 12345
    wd._record_delivery_success(webhook_id)

    # Trip breaker after threshold failures.
    tripped = False
    for _ in range(wd._CIRCUIT_FAILURE_THRESHOLD):
        tripped = wd._record_delivery_failure(webhook_id)

    assert tripped is True
    assert wd._is_circuit_open(webhook_id, now=0.0) is True

    # Simulate successful delivery clears breaker state.
    wd._record_delivery_success(webhook_id)
    assert wd._is_circuit_open(webhook_id) is False
