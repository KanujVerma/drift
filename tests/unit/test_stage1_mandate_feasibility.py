"""Unit tests for Stage 1 study mandate and feasibility evaluation.

Workstream C, Issue 575.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.experiments.stage1_mandate_feasibility import (
    StudyMandateFeasibilityReportV1,
    create_stage1_study_mandate,
    evaluate_mandate_feasibility,
    study_mandate_to_synthetic_mandate,
)
from drift.experiments.stage1_study_freeze import STAGE1_UNIVERSE
from drift.loop.stage1_controlled_contracts import portfolio_mandate_reason
from drift.qualification.alpaca_sip_verification import EQUITY_ETFS
from drift.serialization.canonical import content_hash

H = "a" * 64


@pytest.mark.parametrize(
    "case", ["empty", "truncated", "late_invalid", "complete", "missing", "invalid"]
)
def test_feasibility_refuses_unverified_inputs(case: str) -> None:
    mandate = create_stage1_study_mandate(feasibility_report_hash=H)
    prices = {ticker: [Decimal("100")] * 253 for ticker in STAGE1_UNIVERSE}
    if case == "empty":
        prices = {ticker: [] for ticker in STAGE1_UNIVERSE}
    elif case == "truncated":
        prices["IJH"] = prices["IJH"][:1]
    elif case == "late_invalid":
        prices["IJH"][10] = Decimal("-1")
    elif case == "missing":
        del prices["GLD"]
    elif case == "invalid":
        prices["VOO"][0] = Decimal("-1")

    with pytest.raises(ValueError, match="MANDATE_FEASIBILITY_UNAVAILABLE"):
        evaluate_mandate_feasibility(
            mandate=mandate,
            dataset_reference=H,
            sessions_count=253,
            security_prices=prices,
        )


def test_create_stage1_study_mandate_locked_rules() -> None:
    mandate = create_stage1_study_mandate(feasibility_report_hash=H)
    assert mandate.maximum_etf_fraction == Decimal("0.20")
    assert mandate.maximum_equity_fraction == Decimal("0.70")
    assert mandate.maximum_bond_fraction == Decimal("0.75")
    assert mandate.maximum_gold_fraction == Decimal("0.20")
    assert mandate.maximum_gross_fraction == Decimal("1.00")
    assert mandate.maximum_turnover_fraction == Decimal("2.00")
    assert mandate.no_shorting is True
    assert mandate.no_leverage is True
    assert mandate.incoming_policy == "REJECT"
    assert mandate.feasibility_report_hash == H


def test_study_mandate_to_synthetic_mandate_conformance() -> None:
    mandate = create_stage1_study_mandate(feasibility_report_hash=H)
    sec_ids = {
        ticker: UUID(f"018e0000-0000-7000-8000-{idx:012d}")
        for idx, ticker in enumerate(STAGE1_UNIVERSE, 1)
    }
    synth = study_mandate_to_synthetic_mandate(mandate, sec_ids)

    assert len(synth.securities) == 12
    assert all(s.maximum_fraction == Decimal("0.20") for s in synth.securities)
    assert synth.maximum_gross_fraction == Decimal("1.00")
    assert synth.maximum_turnover_fraction == Decimal("2.00")

    class_caps = {c.asset_class: c.maximum_fraction for c in synth.classes}
    assert class_caps["equities"] == Decimal("0.70")
    assert class_caps["bonds"] == Decimal("0.75")
    assert class_caps["gold"] == Decimal("0.20")

    # Positive control: equal-weight book satisfies portfolio_mandate_reason
    cash = Decimal("400.00")
    price = Decimal("100.00")
    # 12 * 8 * 100 = 9600 invested, 400 cash = 10000 NAV
    quantities = {sec_ids[ticker]: 8 for ticker in STAGE1_UNIVERSE}
    prices = {sec_ids[ticker]: price for ticker in STAGE1_UNIVERSE}
    reason = portfolio_mandate_reason(
        mandate=synth,
        quantities=quantities,
        prices=prices,
        cash=cash,
        pending_claims=Decimal("0.00"),
    )
    assert reason is None

    # Negative control: security cap breach
    bad_quantities = dict(quantities)
    bad_quantities[sec_ids["VOO"]] = 30  # 30 * 100 = 3000 > 20% of 10000
    breach = portfolio_mandate_reason(
        mandate=synth,
        quantities=bad_quantities,
        prices=prices,
        cash=cash,
        pending_claims=Decimal("0.00"),
    )
    assert breach == "SECURITY_CAP"

    # Negative control: class cap breach (all equities)
    equity_heavy = {
        sec_ids[ticker]: (20 if ticker in EQUITY_ETFS else 0)
        for ticker in STAGE1_UNIVERSE
    }  # 6 * 20 * 100 = 12000 (100% equities > 70%)
    class_breach = portfolio_mandate_reason(
        mandate=synth,
        quantities=equity_heavy,
        prices=prices,
        cash=cash,
        pending_claims=Decimal("0.00"),
    )
    assert class_breach in ("CLASS_CAP", "SECURITY_CAP")


def test_synthetic_feasibility_report_tamper_fails() -> None:
    # Construct a test-only record to retain the schema hash check. It is not
    # producer evidence and is not emitted by the production evaluator.
    body = {
        "schema_version": "drift-stage1-mandate-feasibility/1",
        "report_id": "synthetic-test-only",
        "created_at": datetime(2024, 1, 1, tzinfo=UTC),
        "mandate": create_stage1_study_mandate(feasibility_report_hash=H),
        "dataset_reference": H,
        "evaluated_sessions_count": 0,
        "evaluated_families": ("B3", "B4", "B5"),
        "target_evaluations_count": 0,
        "rejected_targets_count": 1,
        "unavailable_prices_count": 0,
        "protective_corrections_count": 0,
        "partial_fills_count": 0,
        "violations": (),
        "feasibility_status": "INFEASIBLE",
    }
    report = StudyMandateFeasibilityReportV1.model_validate(
        body | {"report_hash": content_hash(body)}
    )
    raw = report.model_dump(mode="python")
    raw["report_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="FEASIBILITY_REPORT_HASH_MISMATCH"):
        StudyMandateFeasibilityReportV1.model_validate(raw)
