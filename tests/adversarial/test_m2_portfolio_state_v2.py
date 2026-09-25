"""M2 adversarial acceptance: the versioned portfolio state (issues 49, 103, 105).

``PortfolioStateV2`` carries two facts ``PortfolioStateV1`` cannot: which
share-mutating economic effects a book has already absorbed (#49), and whether
each holding's cost basis is known (#103, #105). The runs below are end to end,
through ``SessionEvaluatorEngine``, on the shared engine fixture: ten SEC_A
shares bought at the session-2 open for 1000.00, a hold staged for session 3,
and one corporate action effective at the session-3 pre-open.

The run pins are the hash-impact record of the slice (the #80 precedent:
construction-additive, but hash-changing). A run with no spin-off, mixed
acquisition, aggregate-sale residual or continuing liquidation instalment on
an exposed security keeps its exact trace and result hashes, because position
digests are quantity-only and a known position view dumps exactly as before.
A run that exposes an indeterminate basis at a decision moves its decision
context hash, and so its trace and result hashes, by design.
"""

# ruff: noqa: E402

import sys
from pathlib import Path

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

from collections.abc import Callable
from uuid import UUID

import pytest
import test_evaluator_corporate_actions as ca
import test_evaluator_engine as eng

from drift.domain.economic_common import (
    ActionKind,
    EconomicComponentV1,
    EconomicDateFactV1,
    FractionTreatmentV1,
)
from drift.domain.economic_events import EconomicEffectVersionV1
from drift.domain.evaluator_corporate_actions import (
    CashInLieuRateV1,
    SecurityEconomicOutcomeV1,
)
from drift.domain.evaluator_results import (
    EvaluationClassification,
    EvaluationRunArtifactsV1,
)
from drift.domain.normalization import DerivedObservationViewV1
from drift.evaluator.engine import SessionEvaluatorEngine, SessionEvaluatorEvidence

#: The session-3 pre-open of the shared engine clock.
ACTION_AT = "2026-01-08T00:00:00Z"


# ==========================================================================
# Scenario builders
# ==========================================================================


def _action(
    kind: ActionKind,
    *,
    suffix: int,
    components: tuple[EconomicComponentV1, ...],
    dates: tuple[EconomicDateFactV1, ...] = (),
    claim_status: str = "continuing",
    security_id: UUID = eng.SEC_A,
) -> tuple[EconomicEffectVersionV1, SecurityEconomicOutcomeV1]:
    """One occurred SEC_A effect at the session-3 pre-open, and its outcome."""
    terms = ca._terms(
        suffix=suffix,
        action_kind=kind,
        components=components,
        dates=dates,
        security_id=security_id,
    )
    effect = ca._effect(
        suffix=suffix + 1,
        action_kind=kind,
        components=components,
        terms=terms,
        occurrence_id=f"issue-49-{suffix}",
        effective_at=ACTION_AT,
        security_id=security_id,
        claim_status=claim_status,
    )
    outcome = ca._outcome(
        security_id=security_id,
        terms=(terms,),
        effects=(effect,),
        action_kinds=(kind,),
    )
    return effect, outcome


def _shares(
    *,
    numerator: str,
    denominator: str,
    meaning: str,
    recipient: UUID = eng.SEC_A,
    treatment: FractionTreatmentV1 | None = None,
) -> EconomicComponentV1:
    return ca._shares(
        numerator=numerator,
        denominator=denominator,
        component_id="action-shares",
        recipient=recipient,
        predecessor=eng.SEC_A,
        meaning=meaning,
        treatment=treatment,
    )


def _cash(amount: str, component_id: str) -> EconomicComponentV1:
    return ca._cash(amount=amount, component_id=component_id, predecessor=eng.SEC_A)


def _payable() -> tuple[EconomicDateFactV1, ...]:
    return (ca._date_fact("payable", ACTION_AT),)


def _run(
    outcome: SecurityEconomicOutcomeV1,
    views: tuple[DerivedObservationViewV1, ...],
    *,
    rates: tuple[CashInLieuRateV1, ...] = (),
    strategy: eng.FixedTargetStrategy | None = None,
) -> EvaluationRunArtifactsV1:
    bundle = eng._bundle(
        accounting_views=views, economic_outcomes=(outcome.resolution,)
    )
    engine = SessionEvaluatorEngine(
        bundle=bundle,
        admission=eng._admission(bundle),
        protocol=eng._protocol(),
        cost_model=eng._cost_model(),
        evidence=SessionEvaluatorEvidence(
            listing_role_records=eng.ROLE_RECORDS,
            economic_outcomes=(outcome,),
            cash_in_lieu_rates=rates,
        ),
        book_currency_namespace=eng.BOOK_NAMESPACE,
        book_currency_code=eng.BOOK_CODE,
    )
    return eng._run(engine, strategy)


def _views(
    *,
    session_3: tuple[str, str] | None = None,
    child: bool = False,
) -> tuple[DerivedObservationViewV1, ...]:
    """SEC_A over sessions 0 to 3, re-priced at session 3 if asked, and SEC_B."""
    views = tuple(eng._accounting_view(eng.SEC_A, day) for day in eng.DAYS[:3])
    if session_3 is None:
        views += (eng._accounting_view(eng.SEC_A, eng.DAY_3),)
    else:
        views += (
            eng._accounting_view(
                eng.SEC_A,
                eng.DAY_3,
                open_price=session_3[0],
                close_price=session_3[1],
            ),
        )
    if child:
        views += (eng._accounting_view(eng.SEC_B, eng.DAY_3, listing_id=eng.LISTING_B),)
    return views


def _pre_action_views_and_child() -> tuple[DerivedObservationViewV1, ...]:
    """SEC_A up to session 2, and SEC_B at session 3, for a holding SEC_A leaves."""
    return tuple(eng._accounting_view(eng.SEC_A, day) for day in eng.DAYS[:3]) + (
        eng._accounting_view(eng.SEC_B, eng.DAY_3, listing_id=eng.LISTING_B),
    )


# --- runs whose basis stays known ------------------------------------------


def forward_split_run() -> EvaluationRunArtifactsV1:
    _, outcome = _action(
        ActionKind.FORWARD_SPLIT,
        suffix=4900,
        components=(
            _shares(
                numerator="2", denominator="1", meaning="resulting_per_predecessor"
            ),
        ),
    )
    return _run(outcome, _views(session_3=("55.00", "60.00")))


def stock_dividend_run() -> EvaluationRunArtifactsV1:
    _, outcome = _action(
        ActionKind.STOCK_DIVIDEND,
        suffix=4910,
        components=(
            _shares(
                numerator="1", denominator="10", meaning="additional_per_predecessor"
            ),
        ),
    )
    return _run(outcome, _views(session_3=("100.00", "109.10")))


def stock_acquisition_run() -> EvaluationRunArtifactsV1:
    _, outcome = _action(
        ActionKind.STOCK_ACQUISITION,
        suffix=4920,
        components=(
            _shares(
                numerator="3",
                denominator="2",
                meaning="resulting_per_predecessor",
                recipient=eng.SEC_B,
            ),
        ),
        claim_status="converted",
    )
    return _run(outcome, _pre_action_views_and_child())


def extinguishing_liquidation_run() -> EvaluationRunArtifactsV1:
    _, outcome = _action(
        ActionKind.LIQUIDATION,
        suffix=4930,
        components=(_cash("150", "liquidation-cash"),),
        dates=_payable(),
        claim_status="extinguished",
    )
    return _run(outcome, _views())


def cash_acquisition_run() -> EvaluationRunArtifactsV1:
    _, outcome = _action(
        ActionKind.CASH_ACQUISITION,
        suffix=4940,
        components=(_cash("150", "acquisition-cash"),),
        dates=_payable(),
        claim_status="extinguished",
    )
    return _run(outcome, _views())


def cash_dividend_run() -> EvaluationRunArtifactsV1:
    _, outcome = _action(
        ActionKind.REGULAR_CASH_DIVIDEND,
        suffix=4950,
        components=(_cash("0.5", "dividend-cash"),),
        dates=(ca._date_fact("ex", ACTION_AT), *_payable()),
    )
    return _run(outcome, _views())


# --- runs that expose an indeterminate or relieved basis --------------------


def spinoff_run() -> EvaluationRunArtifactsV1:
    _, outcome = _action(
        ActionKind.SPINOFF,
        suffix=4960,
        components=(
            _shares(
                numerator="1",
                denominator="2",
                meaning="additional_per_predecessor",
                recipient=eng.SEC_B,
            ),
        ),
    )
    return _run(outcome, _views(child=True))


def continuing_instalment_run() -> EvaluationRunArtifactsV1:
    _, outcome = _action(
        ActionKind.LIQUIDATION,
        suffix=4970,
        components=(_cash("3", "liquidation-cash"),),
        dates=(ca._date_fact("ex", ACTION_AT), *_payable()),
    )
    return _run(outcome, _views())


def mixed_acquisition_run() -> EvaluationRunArtifactsV1:
    _, outcome = _action(
        ActionKind.MIXED_ACQUISITION,
        suffix=4980,
        components=(
            _shares(
                numerator="1",
                denominator="2",
                meaning="resulting_per_predecessor",
                recipient=eng.SEC_B,
            ),
            _cash("5", "acquisition-cash"),
        ),
        dates=_payable(),
        claim_status="converted",
    )
    return _run(outcome, _pre_action_views_and_child())


def aggregate_sale_residual_run() -> EvaluationRunArtifactsV1:
    effect, outcome = _action(
        ActionKind.REVERSE_SPLIT,
        suffix=4990,
        components=(
            _shares(
                numerator="1",
                denominator="3",
                meaning="resulting_per_predecessor",
                treatment=ca._treatment("aggregate_sale_cash"),
            ),
        ),
        dates=_payable(),
    )
    rate = ca._cash_in_lieu_rate(effect=effect, component_id="action-shares", rate="3")
    return _run(outcome, _views(session_3=("330.00", "360.00")), rates=(rate,))


# ==========================================================================
# Hash-impact pins
# ==========================================================================

#: ``(classification, trace_hash, result_hash)`` of each run, taken at main
#: 5dd05cd before any V2 model existed.
RUN_PINS: dict[str, tuple[EvaluationClassification, str, str]] = {
    "forward-split": (
        EvaluationClassification.COMPLETE,
        "d483818c39bc4a2f8ae1926abc29ce1e419732773f0932201402be32a29b55f7",
        "22a7b654d166244b378dffed09864ee5f8c73dd3b16c1a71ac73f6adfec27191",
    ),
    "stock-dividend": (
        EvaluationClassification.COMPLETE,
        "ba1a70f3dd8af7e29686249abb8f2e74457ff4949fcd289d28ee063e90e566a4",
        "35041a5eb206c2cbe9e1896ac75dfa2465e4c5e8e2f589322bd77660c695b2e6",
    ),
    "stock-acquisition": (
        EvaluationClassification.COMPLETE,
        "0d6672fd317c95978870980ba814219f4c9acd93995cd058de321382a1126ab6",
        "18c13a2d2d0be0aa26b30eb9761b2ad1b3fe49be8b9812068cd871c972c82235",
    ),
    "extinguishing-liquidation": (
        EvaluationClassification.COMPLETE,
        "2c7956d6d9f0fff865a256bd3974c3b107d745dadbc1b2d3d78b8d1e8053f74b",
        "a8e96bc267d7b6d522fdda3c05cac170a5fa6c29204a358b766dd17925af2fec",
    ),
    "cash-acquisition": (
        EvaluationClassification.COMPLETE,
        "5dce66eb55c4e5bd2ae0cf56d45a4fe0a3d25d0a83735cad7080805a35d0378a",
        "2c7f5f76f6d56cf6781ecc8e5d1b038b3cd2b1fdb221289842f277957732e605",
    ),
    "cash-dividend": (
        EvaluationClassification.COMPLETE,
        "3a751f13f36a76fbc602ebbff92e46572158819a910c000efa2a37b3d0fdbb27",
        "0a86c7b3bb01a6ca19dc08fe75d9a9ce46c22ef1d1f9e25bbd0d0f4fadb44c63",
    ),
    "spinoff": (
        EvaluationClassification.COMPLETE,
        "9c459d2228778d7a1842987b91ff6549c60edb83a2161febc3d05e14a8e1cf0c",
        "9874513e520e695ed7f423e73640c2f73cd46a8d440f14559312f90df0a04094",
    ),
    "continuing-instalment": (
        EvaluationClassification.COMPLETE,
        "764aacef48770bd968281f2fd0982ab20c29fd2d8d7fcf2502a31f5a260c9454",
        "cb5351c431f7cab6a0f9c695fdf9d530249e3a4c82508dac00f03e97a801c140",
    ),
    "mixed-acquisition": (
        EvaluationClassification.COMPLETE,
        "a0126639c5ecfa4091f0265b70f59ce3337b68cbdacb7c771c1eb8afd8e70a02",
        "6bd7eeed7b5d21b91e9c5bb00f0193022979774ae92e493f0b7c8ca0c14f1ffc",
    ),
    "aggregate-sale-residual": (
        EvaluationClassification.COMPLETE,
        "f0c0b5a5d992f44475a89ad8aea521878a6323e061579a363d3b2cb7fdeb030e",
        "1e76eedc696b21f35e4aee912379fe742e2034f1bf62f7b97cf7c8d44a44c430",
    ),
}

RUNS: dict[str, Callable[[], EvaluationRunArtifactsV1]] = {
    "forward-split": forward_split_run,
    "stock-dividend": stock_dividend_run,
    "stock-acquisition": stock_acquisition_run,
    "extinguishing-liquidation": extinguishing_liquidation_run,
    "cash-acquisition": cash_acquisition_run,
    "cash-dividend": cash_dividend_run,
    "spinoff": spinoff_run,
    "continuing-instalment": continuing_instalment_run,
    "mixed-acquisition": mixed_acquisition_run,
    "aggregate-sale-residual": aggregate_sale_residual_run,
}


@pytest.mark.parametrize("name", RUNS)
def test_a_corporate_action_run_keeps_its_recorded_hashes(name: str) -> None:
    artifacts = RUNS[name]()

    assert (
        artifacts.result.classification,
        artifacts.trace.trace_hash,
        artifacts.result.result_hash,
    ) == RUN_PINS[name]
