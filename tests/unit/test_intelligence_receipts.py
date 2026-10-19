"""Unit tests for research receipt persistence, lifecycle events, and cost accounting.

Verifies acceptance criteria T09, T10, T11 from research.md and DP-R3/DP-R4:
- T09: Lifecycle events retained with distinct identities and proper chaining.
- T10: Cost identity, duplicate persistence idempotency, and adjustment lineage.
- T11: Receipt crash recovery and unresolved state preservation.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from drift.intelligence.contracts import (
    ArtifactReference,
    Scope,
    StoredArtifactRef,
    UsageEntry,
)
from drift.intelligence.receipts import (
    ResearchReceiptStore,
    create_cost_receipt,
    create_started_attempt,
    create_terminal_attempt,
)


@pytest.fixture
def sample_scope() -> Scope:
    return Scope(
        experiment_id="01900000-0000-7000-8000-000000000001",
        arm_id="fixture:B",
        account_id="01900000-0000-7000-8000-000000000011",
        campaign_ref=ArtifactReference(
            id="fixture:campaign",
            version="fixture-1",
            sha256="c" * 64,
        ),
    )


@pytest.fixture
def sample_artifact_refs() -> dict[str, ArtifactReference]:
    return {
        "context_ref": ArtifactReference(
            id="fixture:context", version="v1", sha256="1" * 64
        ),
        "method_ref": ArtifactReference(
            id="fixture:method", version="v1", sha256="2" * 64
        ),
        "budget_ref": ArtifactReference(
            id="fixture:budget", version="v1", sha256="3" * 64
        ),
    }


def test_t09_attempt_lifecycle_chaining(
    sample_scope: Scope, sample_artifact_refs: dict[str, ArtifactReference]
) -> None:
    """T09: Verify started -> completed event chaining and immutability."""
    now = datetime(2024, 1, 2, 10, 0, 1, tzinfo=UTC)
    later = datetime(2024, 1, 2, 10, 0, 3, tzinfo=UTC)

    started = create_started_attempt(
        attempt_id="att-001",
        logical_request_id="req-001",
        attempt_event_id="ev-001",
        scope=sample_scope,
        context_ref=sample_artifact_refs["context_ref"],
        method_ref=sample_artifact_refs["method_ref"],
        budget_ref=sample_artifact_refs["budget_ref"],
        producer="scripted_fixture",
        started_at=now,
    )
    assert started.event_index == 0
    assert started.previous_event_ref is None
    assert started.status == "started"

    terminal = create_terminal_attempt(
        prior_attempt=started,
        attempt_event_id="ev-002",
        completed_at=later,
        status="completed",
        candidate_ref=ArtifactReference(id="cand-001", version="v1", sha256="4" * 64),
    )
    assert terminal.event_index == 1
    assert terminal.previous_event_ref is not None
    assert terminal.previous_event_ref.id == "ev-001"
    assert terminal.previous_event_ref.sha256 == started.record_hash
    assert terminal.status == "completed"


def test_t10_cost_identity_and_adjustments(sample_scope: Scope) -> None:
    """T10: Verify verified_zero, unknown, and estimate-to-actual lineage."""
    now = datetime(2024, 1, 2, 10, 0, 0, tzinfo=UTC)

    # 1. verified_zero requires raw_evidence_ref
    with pytest.raises(ValueError, match="requires non-null raw_evidence_ref"):
        create_cost_receipt(
            receipt_id="cost-001",
            scope=sample_scope,
            category="model_inference",
            billing_identity="test_billing",
            amount_basis="verified_zero",
            raw_evidence_ref=None,
        )

    zero_cost = create_cost_receipt(
        receipt_id="cost-001",
        scope=sample_scope,
        category="model_inference",
        billing_identity="test_billing",
        amount_basis="verified_zero",
        raw_evidence_ref=StoredArtifactRef(
            artifact_id="art-zero",
            kind="other",
            content_hash="5" * 64,
            location="fixture:zero-evidence",
        ),
        recorded_at=now,
    )
    assert zero_cost.amount == "0"
    assert zero_cost.currency == "USD"
    assert zero_cost.amount_basis == "verified_zero"

    # 2. unknown requires unknown_reason
    with pytest.raises(ValueError, match="requires non-empty unknown_reason"):
        create_cost_receipt(
            receipt_id="cost-002",
            scope=sample_scope,
            category="model_inference",
            billing_identity="test_billing",
            amount_basis="unknown",
            unknown_reason=None,
        )

    unknown_cost = create_cost_receipt(
        receipt_id="cost-002",
        scope=sample_scope,
        category="model_inference",
        billing_identity="test_billing",
        amount_basis="unknown",
        unknown_reason="Provider pricing rate card unavailable during study",
        usage=(UsageEntry(unit="tokens", quantity=1500),),
        recorded_at=now,
    )
    assert unknown_cost.amount is None
    assert unknown_cost.currency is None
    assert unknown_cost.unknown_reason is not None

    # 3. estimate to actual correction lineage
    est_cost = create_cost_receipt(
        receipt_id="cost-003-est",
        scope=sample_scope,
        category="model_inference",
        billing_identity="test_billing",
        amount_basis="estimate",
        amount="0.05",
        currency="USD",
        recorded_at=now,
    )
    assert est_cost.amount == "0.05"

    actual_cost = create_cost_receipt(
        receipt_id="cost-003-actual",
        scope=sample_scope,
        category="model_inference",
        billing_identity="test_billing",
        amount_basis="actual",
        amount="0.042",
        currency="USD",
        supersedes_receipt_id=est_cost.receipt_id,
        recorded_at=now,
    )
    assert actual_cost.amount == "0.042"
    assert actual_cost.supersedes_receipt_id == "cost-003-est"


def test_t10_store_idempotency_and_integrity(
    sample_scope: Scope, sample_artifact_refs: dict[str, ArtifactReference]
) -> None:
    """T10: Duplicate persistence returns same receipt; conflicting record raises."""
    store = ResearchReceiptStore()
    now = datetime(2024, 1, 2, 10, 0, 1, tzinfo=UTC)

    started = create_started_attempt(
        attempt_id="att-001",
        logical_request_id="req-001",
        attempt_event_id="ev-001",
        scope=sample_scope,
        context_ref=sample_artifact_refs["context_ref"],
        method_ref=sample_artifact_refs["method_ref"],
        budget_ref=sample_artifact_refs["budget_ref"],
        producer="scripted_fixture",
        started_at=now,
    )

    # First write
    store.record_attempt(started)
    assert store.get_attempt_event("ev-001") == started

    # Duplicate idempotent write
    store.record_attempt(started)
    assert len(store.get_attempt_events("att-001")) == 1

    # Conflicting attempt with same event ID but altered producer
    conflicting = create_started_attempt(
        attempt_id="att-001",
        logical_request_id="req-001",
        attempt_event_id="ev-001",
        scope=sample_scope,
        context_ref=sample_artifact_refs["context_ref"],
        method_ref=sample_artifact_refs["method_ref"],
        budget_ref=sample_artifact_refs["budget_ref"],
        producer="altered_malicious_producer",
        started_at=now,
    )
    with pytest.raises(ValueError, match="Integrity conflict"):
        store.record_attempt(conflicting)


def test_t11_crash_recovery_preserves_unresolved(
    sample_scope: Scope, sample_artifact_refs: dict[str, ArtifactReference]
) -> None:
    """T11: Started attempt survives crash/readback as unresolved without lost cost."""
    store_a = ResearchReceiptStore()
    now = datetime(2024, 1, 2, 10, 0, 1, tzinfo=UTC)

    # Attempt 1 is started but crashes before terminal completion
    started_crashed = create_started_attempt(
        attempt_id="att-crash",
        logical_request_id="req-crash",
        attempt_event_id="ev-crash-001",
        scope=sample_scope,
        context_ref=sample_artifact_refs["context_ref"],
        method_ref=sample_artifact_refs["method_ref"],
        budget_ref=sample_artifact_refs["budget_ref"],
        producer="scripted_fixture",
        started_at=now,
    )
    store_a.record_attempt(started_crashed)

    # Attempt 2 finishes cleanly
    started_clean = create_started_attempt(
        attempt_id="att-clean",
        logical_request_id="req-clean",
        attempt_event_id="ev-clean-001",
        scope=sample_scope,
        context_ref=sample_artifact_refs["context_ref"],
        method_ref=sample_artifact_refs["method_ref"],
        budget_ref=sample_artifact_refs["budget_ref"],
        producer="scripted_fixture",
        started_at=now,
    )
    terminal_clean = create_terminal_attempt(
        prior_attempt=started_clean,
        attempt_event_id="ev-clean-002",
        completed_at=datetime(2024, 1, 2, 10, 0, 2, tzinfo=UTC),
        status="completed",
    )
    store_a.record_attempt(started_clean)
    store_a.record_attempt(terminal_clean)

    # Cost receipt for crash attempt
    cost_crash = create_cost_receipt(
        receipt_id="cost-crash-001",
        scope=sample_scope,
        attempt_id="att-crash",
        category="model_inference",
        billing_identity="test_billing",
        amount_basis="unknown",
        unknown_reason="Call interrupted by host crash",
        recorded_at=now,
    )
    store_a.record_cost_receipt(cost_crash)

    # Export simulated persistence
    dumped: list[dict[str, Any]] = store_a.export_events()

    # Simulate crash and recovery into a fresh store
    store_recovered = ResearchReceiptStore()
    store_recovered.load_events(dumped)

    # Unresolved attempts check
    unresolved = store_recovered.get_unresolved_attempts()
    assert len(unresolved) == 1
    assert unresolved[0].attempt_id == "att-crash"
    assert unresolved[0].status == "started"

    # Verify cost was not dropped
    costs_crash = store_recovered.get_cost_receipts_for_attempt("att-crash")
    assert len(costs_crash) == 1
    assert costs_crash[0].amount_basis == "unknown"

    # Verify clean attempt is completed
    clean_latest = store_recovered.get_latest_attempt("att-clean")
    assert clean_latest is not None
    assert clean_latest.status == "completed"


def test_recovery_rejects_out_of_order_and_tampered_events_atomically(
    sample_scope: Scope, sample_artifact_refs: dict[str, ArtifactReference]
) -> None:
    """An absent predecessor or tampered frozen instance never enters a store."""
    now = datetime(2024, 1, 2, 10, 0, 1, tzinfo=UTC)
    started = create_started_attempt(
        attempt_id="att-chain",
        logical_request_id="req-chain",
        attempt_event_id="ev-chain-start",
        scope=sample_scope,
        context_ref=sample_artifact_refs["context_ref"],
        method_ref=sample_artifact_refs["method_ref"],
        budget_ref=sample_artifact_refs["budget_ref"],
        producer="scripted_fixture",
        started_at=now,
    )
    terminal = create_terminal_attempt(
        prior_attempt=started,
        attempt_event_id="ev-chain-end",
        completed_at=now,
        status="completed",
    )
    store = ResearchReceiptStore()
    with pytest.raises(ValueError, match="INVALID_ATTEMPT_CHAIN"):
        store.record_attempt(terminal)
    assert store.export_events() == []

    with pytest.raises(ValueError, match="record_hash mismatch"):
        store.record_attempt(started.model_copy(update={"producer": "unhashed-tamper"}))
    assert store.export_events() == []

    competing = create_terminal_attempt(
        prior_attempt=started,
        attempt_event_id="ev-chain-other",
        completed_at=now,
        status="completed",
    )
    with pytest.raises(ValueError, match="INVALID_ATTEMPT_CHAIN"):
        store.load_events([
            started.model_dump(mode="python"),
            terminal.model_dump(mode="python"),
            competing.model_dump(mode="python"),
        ])
    assert store.export_events() == []


def test_canonical_receipt_bytes_roundtrip_and_truncation(
    sample_scope: Scope, sample_artifact_refs: dict[str, ArtifactReference]
) -> None:
    """Crash recovery consumes complete, tamper-checked canonical JSONL only."""
    now = datetime(2024, 1, 2, 10, 0, 1, tzinfo=UTC)
    started = create_started_attempt(
        attempt_id="att-journal",
        logical_request_id="req-journal",
        attempt_event_id="ev-journal",
        scope=sample_scope,
        context_ref=sample_artifact_refs["context_ref"],
        method_ref=sample_artifact_refs["method_ref"],
        budget_ref=sample_artifact_refs["budget_ref"],
        producer="scripted_fixture",
        started_at=now,
    )
    source = ResearchReceiptStore()
    source.record_attempt(started)
    canonical = source.export_canonical_jsonl()
    recovered = ResearchReceiptStore()
    recovered.load_canonical_jsonl(canonical)
    assert recovered.get_unresolved_attempts() == (started,)
    assert recovered.export_canonical_jsonl() == canonical

    other = ResearchReceiptStore()
    with pytest.raises(ValueError, match="TRUNCATED_RECEIPT_JOURNAL"):
        other.load_canonical_jsonl(canonical.rstrip(b"\n"))
    assert other.export_events() == []


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-0.01"])
def test_cost_receipt_rejects_nonfinite_or_negative_amount(
    sample_scope: Scope, amount: str
) -> None:
    with pytest.raises(ValueError, match="INVALID_COST"):
        create_cost_receipt(
            receipt_id="cost-bad",
            scope=sample_scope,
            category="model_inference",
            billing_identity="synthetic",
            amount_basis="estimate",
            amount=amount,
            currency="USD",
        )
