"""Synthetic B3 account with nonzero costs and a modeled cash dividend.

All prices, identities, action bytes, dates, issuer and clocks are fixtures.
The result is exploratory engineering evidence, not historical data or an
authenticated E6B issuer.
"""

# ruff: noqa: E402
import json
import sys
from dataclasses import fields
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest

_UNIT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT) not in sys.path:
    sys.path.insert(0, str(_UNIT))

import test_evaluator_engine as engine_fixture
import test_exploratory_dividends as dividends
import test_stage1_original_invocation_end_to_end as fixture

from drift.domain.economic_closed_world import ReturnedCorporateActionV1
from drift.domain.evaluator_results import EvaluationClassification
from drift.evaluator.bundles import assemble_evaluation_input_bundle
from drift.evaluator.engine import SessionEvaluatorEngine, SessionEvaluatorEvidence
from drift.experiments.stage1_campaign_config import build_campaign_spec
from drift.experiments.stage1_trial_provenance import (
    build_stage1_trial_provenance_snapshot,
)
from drift.ledger.sqlite import SQLiteLedger
from drift.ledger.stage1_synthetic_account_receipts import (
    AccountAllocationFieldsV1,
    ConfiguredLocalSyntheticOriginV1,
    LocalSyntheticAccountReceiptStoreV1,
)
from drift.loop.stage1_original_result_association import read_original_result
from drift.serialization.canonical import canonical_json

if not __debug__:
    raise RuntimeError("synthetic B3 proof requires enabled assertions")


@pytest.mark.parametrize("entitled", [True, False], ids=["held-before-ex", "buy-on-ex"])
def test_synthetic_b3_accounts_reconcile_fees_and_dividend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entitled: bool
) -> None:
    dates = fixture._session_dates()
    ex_index = fixture.WARMUP + (2 if entitled else 0)
    ex_date, pay_date = dates[ex_index : ex_index + 2]
    security = fixture.SECURITIES[0]
    term, payload = dividends.make_test_dividend(
        "synthetic-dividend-1",
        security,
        "VOO",
        Decimal("2"),
        ex_date,
        ex_date,
        pay_date,
    )
    policy = dividends.make_test_policy([term], [payload])
    payload_hash = sha256(payload).hexdigest()
    returned = ReturnedCorporateActionV1(
        native_kind="cash_dividends",
        native_id=term.native_id,
        action_kind=None,
        dates=(ex_date, pay_date),
    )
    coverage = dividends.make_test_coverage_record(
        security,
        "VOO",
        dates[0],
        dates[-1],
        term.source_id,
        payload_hash,
        returned_actions=(returned,),
        payload_bytes=payload,
    )
    original_bundle = fixture._input_bundle()
    bundle = assemble_evaluation_input_bundle(
        evaluation_interval=original_bundle.evaluation_interval,
        session_clock=original_bundle.session_clock,
        security_identities=original_bundle.security_identities,
        listing_identities=original_bundle.listing_identities,
        structural_eligibilities=original_bundle.structural_eligibilities,
        economic_outcomes=original_bundle.economic_outcomes,
        authentic_decision_views=original_bundle.authentic_decision_views,
        authentic_accounting_views=original_bundle.authentic_accounting_views,
        exploratory_reconstructed_observations=original_bundle.exploratory_reconstructed_observations,
        corporate_action_coverage=tuple(
            item
            for item in original_bundle.corporate_action_coverage
            if item.security_id != security
        )
        + (coverage,),
        source_snapshot_hash=original_bundle.source_snapshot_hash,
        dataset_limitations=original_bundle.dataset_limitations,
    )
    cost_model = engine_fixture._cost_model(
        model_id="synthetic-cost-dividend-v1",
        commission="0.01",
        fixed_fee="1",
        notional_bps="10",
        slippage_bps="5",
    )

    def engine_for(input_bundle: object) -> SessionEvaluatorEngine:
        assert input_bundle is bundle
        return SessionEvaluatorEngine(
            bundle=bundle,
            admission=engine_fixture._admission(bundle),
            protocol=engine_fixture._protocol(warmup=fixture.WARMUP, cash="10000"),
            cost_model=cost_model,
            evidence=SessionEvaluatorEvidence(
                listing_role_records=tuple(
                    engine_fixture._role_record(sec, listing, suffix=1000 + index)
                    for index, (sec, listing) in enumerate(
                        zip(fixture.SECURITIES, fixture.LISTINGS, strict=True)
                    )
                ),
                exploratory_dividends=policy,
            ),
            book_currency_namespace="ISO4217",
            book_currency_code="USD",
        )

    original_manifest = fixture._manifest(bundle)
    old_campaign = original_manifest.campaign
    args = {
        field.name: getattr(old_campaign, field.name)
        for field in fields(old_campaign)
        if field.name not in {"schema_version", "campaign_spec_fingerprint"}
    }
    args["created_at"] = datetime.fromisoformat(old_campaign.created_at)
    args["frozen_at"] = datetime.fromisoformat(old_campaign.frozen_at)
    args["accepted_contract_revisions"] = dict(old_campaign.accepted_contract_revisions)
    args["cost_policy_reference"] = "fixture://nonzero-cost-dividend-v1"
    args["authorization_evidence"] = {
        "synthetic_fixture_only": True,
        "input_bundle_hash": bundle.bundle_hash,
        "cost_model_hash": cost_model.cost_model_hash,
        "dividend_terms_hash": policy.terms_hash,
        "scientifically_qualified": False,
    }
    manifest = fixture._Manifest(
        build_campaign_spec(**args), original_manifest.arms, original_manifest.bindings
    )
    assert (
        manifest.campaign.cost_policy_reference == "fixture://nonzero-cost-dividend-v1"
    )
    monkeypatch.setattr(fixture, "_engine", engine_for)
    fixture._execute_and_retain_pair(tmp_path, bundle, manifest)

    references = json.loads((tmp_path / "readback-references.json").read_bytes())
    origin = ConfiguredLocalSyntheticOriginV1(
        ledger_path=tmp_path / "original-accounts.sqlite3",
        issuer_instance_id=UUID(references["issuer_instance_id"]),
    )
    ledger_hash = sha256(origin.ledger_path.read_bytes()).hexdigest()
    events = SQLiteLedger.open_existing(origin.ledger_path).verified_events()
    assert len(events) == 14
    store = LocalSyntheticAccountReceiptStoreV1.open_existing(
        origin=origin, clock=lambda: fixture.BASE + timedelta(hours=1)
    )
    accounts: set[str] = set()
    for reference in references["accounts"]:
        allocation = AccountAllocationFieldsV1(**reference["fields"])
        original = store.readback_allocation(
            allocation_id=UUID(reference["allocation_id"]),
            allocation_ref=fixture._event_reference(reference["allocation_ref"]),
            witness_ref=fixture._event_reference(reference["witness_ref"]),
            expected_fields=allocation,
        )
        provenance = build_stage1_trial_provenance_snapshot(
            campaign=manifest.campaign,
            arms=manifest.arms,
            bindings=manifest.bindings,
            expected_run_ids=("RUN-001",),
            run_id="RUN-001",
            arm_id=reference["arm_id"],
            checkpoint_id="CKPT-001",
            events=(),
        )
        retained = read_original_result(
            origin=origin,
            original_account=original,
            association_ref=fixture._event_reference(reference["association_ref"]),
            provenance=provenance,
            campaign=manifest.campaign,
            arms=manifest.arms,
            bindings=manifest.bindings,
            expected_run_ids=("RUN-001",),
            clock=lambda: fixture.BASE + timedelta(hours=1),
        )
        assert not retained.original_issuer_authenticated_for_e6b
        assert not retained.scientifically_qualified
        assert retained.account_id == allocation.portfolio_account_id
        assert retained.result_hash == reference["result_hash"]
        assert retained.trace_hash == reference["trace_hash"]
        assert retained.final_book_hash == reference["final_book_hash"]
        assert str(retained.operational_m0_run_id) == reference["m0_run_id"]
        assert str(retained.invocation_binding.m0_run_id) == reference["m0_run_id"]
        assert (
            str(retained.invocation_binding.m0_audit_event_id)
            == reference["m0_audit_event_id"]
        )
        assert retained.original_artifacts_bytes == canonical_json(
            retained.original_artifacts
        )
        other = next(
            item
            for item in references["accounts"]
            if item["arm_id"] != reference["arm_id"]
        )
        with pytest.raises(ValueError, match="RESULT_E1_SCOPE_ORIGIN_MISMATCH"):
            read_original_result(
                origin=origin,
                original_account=original,
                association_ref=fixture._event_reference(other["association_ref"]),
                provenance=provenance,
                campaign=manifest.campaign,
                arms=manifest.arms,
                bindings=manifest.bindings,
                expected_run_ids=("RUN-001",),
                clock=lambda: fixture.BASE + timedelta(hours=1),
            )
        accounts.add(retained.account_id)
        artifacts = retained.original_artifacts
        assert artifacts.result.classification is EvaluationClassification.COMPLETE
        assert artifacts.result.lane == "exploratory"
        assert artifacts.result.is_promotion_grade_evidence is False
        assert (
            artifacts.result.run_identity.cost_model_hash == cost_model.cost_model_hash
        )
        book = artifacts.final_state
        fill_events = [
            event for event in artifacts.trace.events if event.kind == "fill"
        ]
        assert all(event.session_index == fixture.WARMUP for event in fill_events)
        fills = [event.fill for event in fill_events]
        assert len(fills) == 12
        assert all(fill.side == "buy" and fill.quantity == 8 for fill in fills)
        assert all(fill.unadjusted_open_price == Decimal("100") for fill in fills)
        assert all(fill.fill_price == Decimal("100.05") for fill in fills)
        assert all(fill.transaction_costs == Decimal("1.88") for fill in fills)
        assert all(fill.cash_delta == Decimal("-802.28") for fill in fills)
        decisions = [
            event
            for event in artifacts.trace.events
            if event.kind == "strategy_decision"
        ]
        assert decisions[0].session_index == fixture.WARMUP - 1
        assert decisions[0].decision_cutoff < datetime.combine(
            dates[fixture.WARMUP], time(14, 30), tzinfo=UTC
        )
        applied = [
            event
            for event in artifacts.trace.events
            if event.kind == "corporate_action_applied"
        ]
        settlements = [
            event for event in artifacts.trace.events if event.kind == "claim_settled"
        ]
        dividend_cash = Decimal("16") if entitled else Decimal("0")
        if entitled:
            assert len(applied) == len(settlements) == 1
            assert applied[0].session_key.local_date == ex_date
            assert settlements[0].session_key.local_date == pay_date
            assert settlements[0].settled_cash == dividend_cash
            assert applied[0].recorded_claim_ids == settlements[0].claim_ids
        else:
            # Entitlement is computed before the next-open purchase.
            assert not applied
            assert not settlements
        assert {h.security_id: h.quantity for h in book.holdings} == {
            sec: 8 for sec in fixture.SECURITIES
        }
        # Synthetic numeric caps only; this is not a mandate-admission verdict.
        labeled = dict(zip(fixture.TICKERS, fixture.SECURITIES, strict=True))
        values = {holding.security_id: Decimal("800") for holding in book.holdings}
        equity = sum(
            values[labeled[name]] for name in ("VOO", "IJH", "IJR", "QQQ", "VEA", "VWO")
        )
        bonds = sum(
            values[labeled[name]] for name in ("SHY", "IEF", "TLT", "TIP", "LQD")
        )
        assert max(values.values()) <= book.net_asset_value * Decimal("0.20")
        assert equity <= book.net_asset_value * Decimal("0.70")
        assert bonds <= book.net_asset_value * Decimal("0.75")
        assert values[labeled["GLD"]] <= book.net_asset_value * Decimal("0.20")
        assert sum(values.values()) <= book.net_asset_value
        # Twelve 8-share buys: 96 * 100.05 + 12 * 1.88 = 9627.36.
        # Eight shares held before ex-date receive 2 USD each on payable date.
        assert (
            book.cash_balance == Decimal("10000") - Decimal("9627.36") + dividend_cash
        )
        assert book.holdings_market_value == Decimal("9600")
        assert book.net_asset_value == Decimal("9972.64") + dividend_cash
        assert not book.pending_cash_claims
        if entitled:
            assert len(book.settled_claim_ids) == 1
            assert set(book.settled_claim_ids) == set(settlements[0].claim_ids)
        else:
            assert not book.settled_claim_ids
        metrics = artifacts.result.metrics
        assert metrics.evaluated_session_count == len(dates) == 379
        assert (
            tuple(point.session_key.local_date for point in metrics.equity_series)
            == dates
        )
        assert metrics.initial_net_asset_value == Decimal("10000")
        assert metrics.ending_net_asset_value == Decimal("9972.64") + dividend_cash
        assert metrics.net_profit_and_loss == Decimal("-27.36") + dividend_cash
        assert metrics.cumulative_transaction_costs == Decimal("22.56")
        assert metrics.gross_traded_notional == Decimal("9604.80")
        assert metrics.gross_traded_notional <= metrics.initial_net_asset_value * 2
        on_ex = metrics.equity_series[ex_index]
        on_pay = metrics.equity_series[ex_index + 1]
        assert on_ex.cash_balance == Decimal("372.64")
        assert on_ex.pending_claims_value == dividend_cash
        assert on_ex.net_asset_value == Decimal("9972.64") + dividend_cash
        assert on_pay.cash_balance == Decimal("372.64") + dividend_cash
        assert on_pay.pending_claims_value == 0
        assert on_pay.net_asset_value == on_ex.net_asset_value
    assert len(accounts) == 2
    assert sha256(origin.ledger_path.read_bytes()).hexdigest() == ledger_hash
