"""M2 adversarial acceptance: realized PnL completeness signal (issue 152).

Issue 152 follow-up to PR #139 (owner accepted rule 2026-09-28):
Realized PnL counts only disposals with a known cost basis. An explicit result-level
signal indicates whether realized PnL covers every disposal, or names the disposals
it excludes and why (e.g. mixed acquisition cash leg, spin-off child aggregate-sale
residual, or indeterminate-basis cash in lieu).
"""

# ruff: noqa: E402

import sys
from pathlib import Path

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

from decimal import Decimal

import pytest
import test_evaluator_corporate_actions as ca
import test_evaluator_engine as eng
import test_m2_portfolio_state_v2 as pv2

from drift.domain.economic_common import ActionKind
from drift.domain.evaluator_results import (
    DISPOSAL_EXCLUSION_INDETERMINATE_POOL_CASH_IN_LIEU,
    DISPOSAL_EXCLUSION_MIXED_ACQUISITION_UNALLOCATED_BASIS,
    DISPOSAL_EXCLUSION_SPINOFF_RESIDUAL_UNALLOCATED_BASIS,
    EvaluationClassification,
)
from drift.evaluator.experiment_runner import summary_metrics_payload


def test_determinate_run_reads_realized_pnl_complete() -> None:
    """A fully determinate run reads complete with zero excluded disposals."""
    artifacts = pv2.forward_split_run()
    assert artifacts.result.classification == EvaluationClassification.COMPLETE
    completeness = artifacts.result.realized_pnl_completeness
    assert completeness.schema_version == "1"
    assert completeness.is_complete is True
    assert completeness.excluded_disposals == ()

    payload = summary_metrics_payload(artifacts.result)
    assert payload["realized_pnl_is_complete"] is True
    assert payload["realized_pnl_excluded_disposals"] == ()


def test_mixed_acquisition_names_excluded_disposal() -> None:
    """A mixed acquisition cash leg is an excluded partial disposal."""
    artifacts = pv2.mixed_acquisition_run()
    assert artifacts.result.classification == EvaluationClassification.COMPLETE
    completeness = artifacts.result.realized_pnl_completeness
    assert completeness.is_complete is False
    assert len(completeness.excluded_disposals) == 1

    disposal = completeness.excluded_disposals[0]
    assert disposal.schema_version == "1"
    assert disposal.security_id == eng.SEC_A
    assert disposal.action_kind == ActionKind.MIXED_ACQUISITION
    assert disposal.component_id == "acquisition-cash"
    assert disposal.cash_proceeds == Decimal("50")  # 10 shares * 5.00
    assert disposal.reason == DISPOSAL_EXCLUSION_MIXED_ACQUISITION_UNALLOCATED_BASIS

    payload = summary_metrics_payload(artifacts.result)
    assert payload["realized_pnl_is_complete"] is False
    disposals_payload = payload["realized_pnl_excluded_disposals"]
    assert isinstance(disposals_payload, tuple)
    assert len(disposals_payload) == 1
    first_disposal = disposals_payload[0]
    assert isinstance(first_disposal, dict)
    assert (
        first_disposal["reason"]
        == DISPOSAL_EXCLUSION_MIXED_ACQUISITION_UNALLOCATED_BASIS
    )
    assert first_disposal["cash_proceeds"] == "50"


def test_spinoff_with_residual_names_excluded_disposal() -> None:
    """A spin-off with fractional residual names an excluded disposal."""
    component = ca._shares(
        numerator="1",
        denominator="8",
        recipient=eng.SEC_B,
        meaning="additional_per_predecessor",
        treatment=ca._treatment("aggregate_sale_cash"),
        predecessor=eng.SEC_A,
    )
    terms = ca._terms(
        suffix=5100,
        action_kind=ActionKind.SPINOFF,
        components=(component,),
        dates=pv2._payable(),
        security_id=eng.SEC_A,
    )
    effect = ca._effect(
        suffix=5101,
        action_kind=ActionKind.SPINOFF,
        components=(component,),
        terms=terms,
        effective_at=pv2.ACTION_AT,
        security_id=eng.SEC_A,
    )
    outcome = ca._outcome(security_id=eng.SEC_A, terms=(terms,), effects=(effect,))
    rate = ca._cash_in_lieu_rate(effect=effect, component_id="shares-1", rate="8")

    artifacts = pv2._run(
        outcome,
        pv2._views(child=True),
        rates=(rate,),
    )
    assert artifacts.result.classification == EvaluationClassification.COMPLETE
    completeness = artifacts.result.realized_pnl_completeness
    assert completeness.is_complete is False
    assert len(completeness.excluded_disposals) == 1

    disposal = completeness.excluded_disposals[0]
    assert disposal.security_id == eng.SEC_A
    assert disposal.action_kind == ActionKind.SPINOFF
    # 10 * 1/8 = 1 2/8 -> residual 2/8 * 8 = 2
    assert disposal.cash_proceeds == Decimal("2")
    assert disposal.reason == DISPOSAL_EXCLUSION_SPINOFF_RESIDUAL_UNALLOCATED_BASIS

    payload = summary_metrics_payload(artifacts.result)
    assert payload["realized_pnl_is_complete"] is False
    disposals_payload2 = payload["realized_pnl_excluded_disposals"]
    assert isinstance(disposals_payload2, tuple)
    assert len(disposals_payload2) == 1


def test_determinate_residual_run_is_complete() -> None:
    """A reverse split residual on a known basis realizes PnL and is complete."""
    artifacts = pv2.aggregate_sale_residual_run()
    assert artifacts.result.classification == EvaluationClassification.COMPLETE
    completeness = artifacts.result.realized_pnl_completeness
    assert completeness.is_complete is True
    assert completeness.excluded_disposals == ()


def test_indeterminate_pool_cash_in_lieu_names_excluded_disposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An aggregate residual on indeterminate pool names an excluded disposal."""
    # Step 1: Spin-off without residual on day 3 pre-open renders SEC_A indeterminate.
    # Step 2: Reverse split with aggregate-sale residual on day 4 pre-open sells
    # fractional SEC_A.
    spinoff_comp = ca._shares(
        numerator="1",
        denominator="2",
        recipient=eng.SEC_B,
        meaning="additional_per_predecessor",
        treatment=ca._treatment("round_down"),
        predecessor=eng.SEC_A,
    )
    spinoff_terms = ca._terms(
        suffix=5200,
        action_kind=ActionKind.SPINOFF,
        components=(spinoff_comp,),
        security_id=eng.SEC_A,
    )
    spinoff_effect = ca._effect(
        suffix=5201,
        action_kind=ActionKind.SPINOFF,
        components=(spinoff_comp,),
        terms=spinoff_terms,
        effective_at=pv2.ACTION_AT,  # Session 3 pre-open
        security_id=eng.SEC_A,
    )

    split_comp = ca._shares(
        numerator="1",
        denominator="3",
        recipient=eng.SEC_A,
        meaning="resulting_per_predecessor",
        treatment=ca._treatment("aggregate_sale_cash"),
        predecessor=eng.SEC_A,
    )
    payable_day_4 = ca._date_fact("payable", "2026-01-09T00:00:00Z")
    split_terms = ca._terms(
        suffix=5210,
        action_kind=ActionKind.REVERSE_SPLIT,
        components=(split_comp,),
        dates=(payable_day_4,),
        security_id=eng.SEC_A,
    )
    split_effect = ca._effect(
        suffix=5211,
        action_kind=ActionKind.REVERSE_SPLIT,
        components=(split_comp,),
        terms=split_terms,
        occurrence_id="occ-2",
        effective_at="2026-01-09T00:00:00Z",  # Session 4 pre-open
        security_id=eng.SEC_A,
    )

    outcome = ca._outcome(
        security_id=eng.SEC_A,
        terms=(spinoff_terms, split_terms),
        effects=(spinoff_effect, split_effect),
    )
    rate = ca._cash_in_lieu_rate(effect=split_effect, component_id="shares-1", rate="3")

    strategy = eng.FixedTargetStrategy(
        {
            eng.DAY_1: ((eng.SEC_A, 10),),
            eng.DAY_2: ((eng.SEC_A, 10),),
            eng.DAY_3: ((eng.SEC_A, 10), (eng.SEC_B, 5)),
            pv2.DAY_4: ((eng.SEC_A, 10), (eng.SEC_B, 5)),
        }
    )
    artifacts = pv2._run_five_sessions(
        outcome,
        strategy,
        monkeypatch,
        rates=(rate,),
    )
    assert artifacts.result.classification == EvaluationClassification.COMPLETE
    completeness = artifacts.result.realized_pnl_completeness
    assert completeness.is_complete is False
    assert len(completeness.excluded_disposals) == 1

    disposal = completeness.excluded_disposals[0]
    assert disposal.security_id == eng.SEC_A
    assert disposal.action_kind == ActionKind.REVERSE_SPLIT
    assert disposal.session_key.local_date == pv2.DAY_4
    assert disposal.cash_proceeds == Decimal("1")
    assert disposal.reason == DISPOSAL_EXCLUSION_INDETERMINATE_POOL_CASH_IN_LIEU
