"""Focused unit tests for dispatch/aggregation/webhook reliability helpers."""

from __future__ import annotations


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


def test_reset_timeout_partitions_clears_assignment():
    from registry.tasks.proof_aggregate import _reset_timeout_partitions

    parts = [_Partition(), _Partition(), _Partition()]
    count = _reset_timeout_partitions(parts)

    assert count == 3
    assert all(p.status == "pending" for p in parts)
    assert all(p.assigned_prover is None for p in parts)
    assert all(p.assigned_at is None for p in parts)
    assert all(p.error == "Reset after proving timeout" for p in parts)


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
