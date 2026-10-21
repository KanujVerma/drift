"""Synthetic regression vectors for #532, intentionally NOT executed here."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import cast

import pytest

from scripts.result_economics_preflight import preflight_result_economics

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64
E = "e" * 64


def fixture(
    *, arm: str = "B", end_nav: str = "10120", operating_cost: str = "25"
) -> dict[str, object]:
    return {
        "profile": "synthetic-result-economics-review-v1",
        "as_of_utc": "2026-01-06T12:00:00Z",
        "identity": {
            "campaign_id": "mock-E1-campaign",
            "run_id": "mock-run-1",
            "arm_id": arm,
            "checkpoint_id": "mock-checkpoint",
            "trial_id": f"mock-trial-{arm}",
            "portfolio_account_id": f"UNVERIFIED-account-{arm}",
            "e1_binding_hash": A,
            "result_hash": B if arm == "B" else C,
            "trace_hash": C,
            "bundle_hash": D,
            "book_hash": E,
            "allocation_receipt_ref": None,
            "evaluation_classification": "COMPLETE",
            "result_available_utc": "2026-01-05T20:00:00Z",
            "source_lane": "SYNTHETIC",
        },
        "book": {
            "currency": "USD",
            "flow_basis": "NO_EXTERNAL_FLOWS",
            "begin_nav_usd": "10000",
            "end_cash_usd": end_nav,
            "end_holdings_value_usd": "0",
            "end_pending_claims_value_usd": "0",
            "end_net_nav_usd": end_nav,
            "trading_fees_already_posted_usd": "5",
            "fees_embedded_in_net_nav": True,
            "marks_complete": True,
            "trading_costs_complete": True,
            "realized_pnl_complete": True,
            "requested_interval_complete": True,
            "open_execution_state": "NONE",
            "book_reconciliation_receipt_ref": "untrusted-book-witness",
        },
        "cost_scope": {
            "expected_charge_ids": [f"research-{arm}"],
            "coverage_complete": True,
            "coverage_receipt_ref": "untrusted-expense-coverage",
            "coverage_available_utc": "2026-01-06T11:00:00Z",
            "attribution_policy_ref": "unaccepted-synthetic-attribution",
        },
        "operating_receipts": [
            {
                "receipt_id": f"charge-receipt-{arm}-v1",
                "charge_id": f"research-{arm}",
                "arm_id": arm,
                "category": "RESEARCH_OPERATING_NOT_BOOKED",
                "status": "ACTUAL",
                "amount_usd": operating_cost,
                "first_available_utc": "2026-01-06T10:00:00Z",
                "supersedes_receipt_id": None,
                "evidence_ref": "untrusted-operating-charge",
            }
        ],
        "prior_result_hashes": [],
    }


def _map(record: dict[str, object], key: str) -> dict[str, object]:
    return cast(dict[str, object], record[key])


def _costs(record: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], record["operating_receipts"])


def _refuse(record: dict[str, object], reason: str) -> None:
    result = preflight_result_economics(record)
    assert not result.structurally_reviewable
    assert result.trading_net_gain_usd is None
    assert result.economic_gain_usd is None
    assert reason in result.reasons
    assert not result.proves_account_provisioning_or_result_binding
    assert not result.qualifies_scientific_result_or_execution


def test_independent_B_R_numeric_oracle_no_double_trading_fee() -> None:
    b = preflight_result_economics(fixture())
    r = preflight_result_economics(
        fixture(arm="R", end_nav="10060", operating_cost="5")
    )
    assert b.structurally_reviewable and r.structurally_reviewable
    assert b.marked_nav_reconciled
    assert b.marked_nav_usd == Decimal("10120")
    assert b.trading_net_gain_usd == Decimal("120")
    assert b.trading_return_fraction == Decimal("0.012")
    assert r.trading_net_gain_usd == Decimal("60")
    assert r.trading_return_fraction == Decimal("0.006")
    assert b.economic_gain_usd == Decimal("95")
    assert r.economic_gain_usd == Decimal("55")
    assert b.economic_gain_usd - r.economic_gain_usd == Decimal("40")
    assert b.cost_completeness == "COMPLETE"
    assert not b.proves_account_provisioning_or_result_binding
    assert not b.qualifies_scientific_result_or_execution


def test_gross_trading_fee_already_posted_stays_in_net_nav() -> None:
    data = fixture(end_nav="10095", operating_cost="7")
    result = preflight_result_economics(data)
    assert result.trading_net_gain_usd == Decimal("95")
    assert result.economic_gain_usd == Decimal("88")
    # Trading fees of 5 in the book are not deducted again.


def test_unknown_cost_does_not_forge_free_inference() -> None:
    data = fixture()
    _costs(data)[0]["status"] = "UNKNOWN"
    _costs(data)[0]["amount_usd"] = None
    result = preflight_result_economics(data)
    assert result.structurally_reviewable
    assert result.trading_net_gain_usd == Decimal("120")
    assert result.economic_gain_usd is None
    assert result.cost_completeness == "UNAVAILABLE"


def test_estimate_is_not_actual_accepted_economic_cost() -> None:
    data = fixture()
    _costs(data)[0]["status"] = "ESTIMATE"
    result = preflight_result_economics(data)
    assert result.structurally_reviewable
    assert result.trading_net_gain_usd == Decimal("120")
    assert result.economic_gain_usd is None


def test_proven_zero_operating_receipt_is_distinct_from_missing_cost() -> None:
    data = fixture(operating_cost="0")
    _costs(data)[0]["status"] = "VERIFIED_ZERO"
    result = preflight_result_economics(data)
    assert result.economic_gain_usd == Decimal("120")
    data = fixture()
    _costs(data).clear()
    result = preflight_result_economics(data)
    assert result.structurally_reviewable
    assert result.trading_net_gain_usd == Decimal("120")
    assert result.cost_completeness == "UNAVAILABLE"
    assert result.economic_gain_usd is None


def test_exact_redelivery_is_idempotent_not_second_expense() -> None:
    data = fixture()
    _costs(data).append(deepcopy(_costs(data)[0]))
    result = preflight_result_economics(data)
    assert result.economic_gain_usd == Decimal("95")
    assert result.structurally_reviewable


def test_conflicting_same_receipt_id_cannot_be_first_wins() -> None:
    data = fixture()
    copy = deepcopy(_costs(data)[0])
    copy["amount_usd"] = "100"
    _costs(data).append(copy)
    _refuse(data, "operating_receipts.1.receipt_id.conflicting_redelivery")


def test_correction_after_cutoff_does_not_rewrite_earlier_cost() -> None:
    data = fixture()
    later = deepcopy(_costs(data)[0])
    later.update(
        {
            "receipt_id": "late-expense-correction",
            "amount_usd": "40",
            "first_available_utc": "2026-01-06T13:00:00Z",
            "supersedes_receipt_id": _costs(data)[0]["receipt_id"],
        }
    )
    _costs(data).append(later)
    result = preflight_result_economics(data)
    assert result.structurally_reviewable
    assert result.economic_gain_usd == Decimal("95")
    assert result.excluded_late_receipt_ids == ("late-expense-correction",)


def test_available_correction_replaces_not_accumulates_expense() -> None:
    data = fixture()
    later = deepcopy(_costs(data)[0])
    later.update(
        {
            "receipt_id": "cost-corrected-v2",
            "amount_usd": "30",
            "first_available_utc": "2026-01-06T11:20:00Z",
            "supersedes_receipt_id": _costs(data)[0]["receipt_id"],
        }
    )
    _costs(data).append(later)
    assert preflight_result_economics(data).economic_gain_usd == Decimal("90")


def test_out_of_order_correction_lineage_is_rejected() -> None:
    data = fixture()
    later = deepcopy(_costs(data)[0])
    later.update(
        {
            "receipt_id": "cost-corrected-v2",
            "amount_usd": "30",
            "first_available_utc": "2026-01-06T11:00:00Z",
            "supersedes_receipt_id": "not-retained",
        }
    )
    _costs(data).append(later)
    _refuse(data, "operating_receipts.1.correction_lineage_mismatch")


def test_marked_pending_claim_is_not_cash() -> None:
    data = fixture()
    book = _map(data, "book")
    book["end_cash_usd"] = "10000"
    book["end_holdings_value_usd"] = "100"
    book["end_pending_claims_value_usd"] = "20"
    result = preflight_result_economics(data)
    assert result.structurally_reviewable
    assert result.marked_nav_usd == Decimal("10120")
    assert book["end_cash_usd"] == "10000"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("end_cash_usd", "10119", "book.nav_cash_holdings_claims_mismatch"),
        ("end_net_nav_usd", "NaN", "book.end_net_nav_usd.invalid"),
        ("begin_nav_usd", "0", "book.begin_nav_usd.invalid"),
        ("currency", "EUR", "book.currency.unsupported"),
        ("fees_embedded_in_net_nav", False,
         "book.trading_fees_not_proven_embedded"),
    ],
)
def test_invalid_account_math_or_double_cost_contract_refuses(
    field: str, value: object, reason: str
) -> None:
    data = fixture()
    _map(data, "book")[field] = value
    _refuse(data, reason)


def test_unknown_pending_orders_prevent_complete_trial_result() -> None:
    data = fixture()
    _map(data, "book")["open_execution_state"] = "UNKNOWN"
    result = preflight_result_economics(data)
    assert result.structurally_reviewable
    assert result.marked_nav_usd == Decimal("10120")
    assert result.trading_net_gain_usd is None
    assert result.economic_gain_usd is None
    assert "book.unresolved_execution_not_a_complete_result" in result.reasons


def test_incomplete_realized_pnl_does_not_become_complete() -> None:
    data = fixture()
    _map(data, "book")["realized_pnl_complete"] = False
    result = preflight_result_economics(data)
    assert result.structurally_reviewable
    assert result.trading_net_gain_usd is None
    assert "book.realized_pnl_complete.not_complete" in result.reasons


def test_future_result_cannot_be_scored_at_prior_cutoff() -> None:
    data = fixture()
    _map(data, "identity")["result_available_utc"] = (
        "2026-01-06T13:00:00Z"
    )
    result = preflight_result_economics(data)
    assert result.structurally_reviewable
    assert result.marked_nav_usd is None
    assert result.trading_net_gain_usd is None
    assert "result.not_available_at_cutoff" in result.reasons


def test_result_hash_replay_is_not_new_independent_observation() -> None:
    data = fixture()
    data["prior_result_hashes"] = [B]
    _refuse(data, "prior_result_hashes.same_result_not_independent")


def test_wrong_arm_or_booked_research_charge_does_not_pass() -> None:
    data = fixture()
    _costs(data)[0]["arm_id"] = "R"
    _refuse(data, "operating_receipts.0.arm_id.mismatch")
    data = fixture()
    _costs(data)[0]["category"] = "TRADING_FEES_IN_BOOK"
    _refuse(data, "operating_receipts.0.category.must_be_separate_from_book")


def test_unknown_charge_is_not_implicitly_zero_or_closed() -> None:
    data = fixture()
    _map(data, "cost_scope")["coverage_complete"] = False
    result = preflight_result_economics(data)
    assert result.trading_net_gain_usd == Decimal("120")
    assert result.economic_gain_usd is None
    data = fixture()
    _costs(data)[0]["status"] = "UNKNOWN"
    _costs(data)[0]["amount_usd"] = "0"
    _refuse(data, "operating_receipts.0.unknown_cost_cannot_be_zero")


def test_unsupported_source_grade_or_bogus_float_refuses() -> None:
    data = fixture()
    _map(data, "identity")["source_lane"] = "promotion_grade"
    _refuse(data, "identity.source_lane.must_be_synthetic")
    data = fixture()
    _map(data, "book")["end_cash_usd"] = 10120.0
    _refuse(data, "book.end_cash_usd.invalid")


def test_nested_spoofed_equality_never_invoked() -> None:
    class Spoofed:
        def __eq__(self, _: object) -> bool:
            raise AssertionError("untrusted comparison invoked")

    data = fixture()
    _map(data, "identity")["result_hash"] = Spoofed()
    result = preflight_result_economics(data)
    assert result.reasons == ("payload.not_plain_json",)
