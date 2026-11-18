"""Fresh-process original B3 readback over explicitly synthetic inputs."""

import hashlib
import json
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid7

import pytest
import test_stage1_original_invocation_end_to_end as fixture

from drift.domain.evaluator_bundles import EvaluationInputBundleV1
from drift.experiments.stage1_trial_provenance import (
    build_stage1_trial_provenance_snapshot,
)
from drift.ledger.stage1_synthetic_account_receipts import (
    AccountAllocationFieldsV1,
    ConfiguredLocalSyntheticOriginV1,
    LocalSyntheticAccountReceiptStoreV1,
)
from drift.loop.stage1_original_result_association import read_original_result
from drift.serialization.canonical import canonical_json

if not __debug__:
    raise RuntimeError("synthetic B3 proof requires enabled assertions")


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _produce(root: Path) -> None:
    bundle = fixture._input_bundle()
    manifest = fixture._manifest(bundle)
    (root / "synthetic-input-bundle.json").write_bytes(canonical_json(bundle))
    fixture._execute_and_retain_pair(root, bundle, manifest)


def _read_and_verify(root: Path) -> None:
    bundle = EvaluationInputBundleV1.model_validate_json(
        (root / "synthetic-input-bundle.json").read_bytes()
    )
    manifest = fixture._manifest(bundle)
    retained = json.loads((root / "readback-references.json").read_bytes())
    origin = ConfiguredLocalSyntheticOriginV1(
        ledger_path=root / "original-accounts.sqlite3",
        issuer_instance_id=UUID(retained["issuer_instance_id"]),
    )
    clock = lambda: fixture.BASE + timedelta(hours=1)  # noqa: E731
    store = LocalSyntheticAccountReceiptStoreV1.open_existing(
        origin=origin, clock=clock
    )
    accounts = []
    for ref in retained["accounts"]:
        fields = AccountAllocationFieldsV1(**ref["fields"])
        account = store.readback_allocation(
            allocation_id=UUID(ref["allocation_id"]),
            allocation_ref=fixture._event_reference(ref["allocation_ref"]),
            witness_ref=fixture._event_reference(ref["witness_ref"]),
            expected_fields=fields,
        )
        provenance = build_stage1_trial_provenance_snapshot(
            campaign=manifest.campaign,
            arms=manifest.arms,
            bindings=manifest.bindings,
            expected_run_ids=("RUN-001",),
            run_id="RUN-001",
            arm_id=ref["arm_id"],
            checkpoint_id="CKPT-001",
            events=(),
        )
        result = read_original_result(
            origin=origin,
            original_account=account,
            association_ref=fixture._event_reference(ref["association_ref"]),
            provenance=provenance,
            campaign=manifest.campaign,
            arms=manifest.arms,
            bindings=manifest.bindings,
            expected_run_ids=("RUN-001",),
            clock=clock,
        )
        assert result.account_id == fields.portfolio_account_id
        assert result.result_hash == ref["result_hash"]
        assert result.trace_hash == ref["trace_hash"]
        assert result.final_book_hash == ref["final_book_hash"]
        assert str(result.operational_m0_run_id) == ref["m0_run_id"]
        assert str(result.invocation_binding.m0_run_id) == ref["m0_run_id"]
        assert (
            str(result.invocation_binding.m0_audit_event_id) == ref["m0_audit_event_id"]
        )
        assert result.original_issuer_authenticated_for_e6b is False
        assert result.scientifically_qualified is False
        artifacts = result.original_artifacts
        assert artifacts.result.lane == "exploratory"
        assert artifacts.result.is_promotion_grade_evidence is False
        assert artifacts.result.metrics.evaluated_session_count == 379
        fixture._assert_actual_b3_result(artifacts)
        fills = [event.fill for event in artifacts.trace.events if event.kind == "fill"]
        assert len(fills) == 12
        assert all(
            fill.side == "buy"
            and fill.quantity == 8
            and fill.unadjusted_open_price == fill.fill_price == Decimal("100")
            and fill.transaction_costs == 0
            for fill in fills
        )
        gross = sum((fill.gross_notional for fill in fills), Decimal(0))
        fees = sum((fill.transaction_costs for fill in fills), Decimal(0))
        book = artifacts.final_state
        assert gross == Decimal("9600") and fees == 0
        assert Decimal("10000") - gross - fees == book.cash_balance == Decimal("400")
        assert len(book.holdings) == 12
        assert all(holding.quantity == 8 for holding in book.holdings)
        assert book.holdings_market_value == Decimal("9600")
        assert not book.pending_cash_claims and book.pending_claims_value == 0
        assert book.cash_balance + book.holdings_market_value == book.net_asset_value
        assert book.net_asset_value == Decimal("10000")
        accounts.append((ref, account, provenance, result))

    assert len(accounts) == 2
    first, second = accounts
    assert first[1].fields.portfolio_account_id != second[1].fields.portfolio_account_id
    assert first[3].operational_m0_run_id != second[3].operational_m0_run_id
    with pytest.raises(ValueError, match="RESULT_E1_SCOPE_ORIGIN_MISMATCH"):
        read_original_result(
            origin=origin,
            original_account=first[1],
            association_ref=fixture._event_reference(second[0]["association_ref"]),
            provenance=first[2],
            campaign=manifest.campaign,
            arms=manifest.arms,
            bindings=manifest.bindings,
            expected_run_ids=("RUN-001",),
            clock=clock,
        )
    wrong_origin = ConfiguredLocalSyntheticOriginV1(
        ledger_path=origin.ledger_path, issuer_instance_id=uuid7()
    )
    wrong_store = LocalSyntheticAccountReceiptStoreV1.open_existing(
        origin=wrong_origin, clock=clock
    )
    ref = first[0]
    with pytest.raises(ValueError, match="ORIGINAL_EVENT_OR_ISSUER_MISMATCH"):
        wrong_store.readback_allocation(
            allocation_id=UUID(ref["allocation_id"]),
            allocation_ref=fixture._event_reference(ref["allocation_ref"]),
            witness_ref=fixture._event_reference(ref["witness_ref"]),
            expected_fields=AccountAllocationFieldsV1(**ref["fields"]),
        )


def test_synthetic_b3_originals_survive_fresh_process_readback(tmp_path: Path) -> None:
    script = Path(__file__).resolve()
    subprocess.run(
        [sys.executable, "-B", str(script), "produce", str(tmp_path)],
        check=True,
        timeout=600,
    )
    ledger = tmp_path / "original-accounts.sqlite3"
    before = _digest(ledger)
    subprocess.run(
        [sys.executable, "-B", str(script), "read", str(tmp_path)],
        check=True,
        timeout=600,
    )
    assert _digest(ledger) == before


if __name__ == "__main__":
    mode, directory = sys.argv[1:]
    if mode == "produce":
        _produce(Path(directory))
    elif mode == "read":
        _read_and_verify(Path(directory))
    else:
        raise ValueError("unsupported synthetic fixture mode")
