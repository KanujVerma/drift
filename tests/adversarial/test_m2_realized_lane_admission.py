"""M2 adversarial acceptance: a realized-clock bundle carries no reconstruction.

Issue 56 made every exploratory admission acknowledge the limitations of
reconstructions riding a realized-clock bundle. The review of issue 55 (F2,
issue 72) then found that the engine never re-derives such a riding
reconstruction: only the scheduled session reconstruction lane takes the
cohort and replay that re-derivation needs. Reviewer probe P1 showed a
realized-clock bundle carrying a forged, self-consistent reconstruction (close
250.000 and an invented limitation) run under an exploratory admission, with
the forgery bound into the result's bundle hash and admission.

The issue 72 ruling (option C) refuses the shape itself: no production
producer builds it, so a bundle on a realized clock carrying reconstructions
cannot be constructed, and therefore cannot be admitted. These tests attack
every construction route and the engine seam. The issue 56 rule itself stands:
the realized lane still validates every exploratory admission against what a
realized bundle can still oblige.
"""

# ruff: noqa: E402

import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

import pytest
from exploratory_decision_test_support import (
    JAN5,
    JAN6,
    ReconstructedTargetStrategy,
    bundle_of,
    exploratory_admission,
    reconstructed_engine,
    run_engine,
    scheduled_session_case,
)
from test_evaluator_engine import _bundle, _buy_ten

from drift.domain.evaluator_bundles import (
    EvaluationInputBundleV1,
    evaluation_input_bundle_hash,
)
from drift.domain.evaluator_lanes import ALPACA_LIMITATION_BOUNDED_COHORT
from drift.domain.evaluator_reconstruction import (
    ExploratoryReconstructedSessionObservationV1,
    exploratory_reconstruction_hash,
)
from drift.domain.evaluator_results import ExploratoryEvaluationResultV1
from drift.evaluator.bundles import assemble_evaluation_input_bundle

REFUSED = (
    r"a bundle on a realized_session_authority clock cannot carry exploratory "
    r"reconstructions \(issue 72\)"
)
INVENTED = "an invented limitation"


def _forged_jan5() -> ExploratoryReconstructedSessionObservationV1:
    """Reviewer probe P1: close 250.000 and an invented limitation, re-hashed."""
    genuine, _ = scheduled_session_case(JAN5)
    changes: dict[str, Any] = {
        "fields": tuple(
            item.model_copy(update={"source_value": Decimal("250.000")})
            if item.field_name == "close"
            else item
            for item in genuine.fields
        ),
        "acknowledged_limitations": tuple(
            sorted((*genuine.acknowledged_limitations, INVENTED))
        ),
    }
    draft = ExploratoryReconstructedSessionObservationV1.model_construct(
        **{**dict(genuine), **changes}
    )
    forged = genuine.model_copy(
        update={
            **changes,
            "reconstruction_hash": exploratory_reconstruction_hash(draft),
        }
    )
    assert forged.reconstruction_hash != genuine.reconstruction_hash
    return forged


def _genuine_jan5() -> ExploratoryReconstructedSessionObservationV1:
    return scheduled_session_case(JAN5)[0]


RIDERS: dict[str, Callable[[], ExploratoryReconstructedSessionObservationV1]] = {
    "forged (probe P1)": _forged_jan5,
    "genuine": _genuine_jan5,
}


def _unvalidated_riding_bundle(
    observation: ExploratoryReconstructedSessionObservationV1,
) -> EvaluationInputBundleV1:
    """A realized-clock bundle carrying ``observation``, built past validation.

    Its bundle hash is self-consistent, so it is exactly what a caller using
    ``model_construct`` could hand to any later boundary.
    """
    realized = _bundle()
    assert realized.session_clock.mode == "realized_session_authority"
    fields = dict(realized) | {"exploratory_reconstructed_observations": (observation,)}
    draft = EvaluationInputBundleV1.model_construct(**fields)
    return EvaluationInputBundleV1.model_construct(
        **(fields | {"bundle_hash": evaluation_input_bundle_hash(draft)})
    )


# --- no construction route builds the shape ------------------------------------


@pytest.mark.parametrize("rider", sorted(RIDERS))
def test_assembly_refuses_a_realized_bundle_carrying_a_reconstruction(
    rider: str,
) -> None:
    realized = _bundle()

    with pytest.raises(ValueError, match=REFUSED):
        assemble_evaluation_input_bundle(
            evaluation_interval=realized.evaluation_interval,
            session_clock=realized.session_clock,
            security_identities=realized.security_identities,
            listing_identities=realized.listing_identities,
            structural_eligibilities=realized.structural_eligibilities,
            economic_outcomes=realized.economic_outcomes,
            authentic_decision_views=realized.authentic_decision_views,
            authentic_accounting_views=realized.authentic_accounting_views,
            exploratory_reconstructed_observations=(RIDERS[rider](),),
        )


@pytest.mark.parametrize("rider", sorted(RIDERS))
def test_direct_validation_refuses_the_shape_even_when_self_consistent(
    rider: str,
) -> None:
    """A correct bundle hash proves only self-consistency, never admissibility."""
    payload = _unvalidated_riding_bundle(RIDERS[rider]()).model_dump()

    with pytest.raises(ValueError, match=REFUSED):
        EvaluationInputBundleV1.model_validate(payload)
    with pytest.raises(ValueError, match=REFUSED):
        EvaluationInputBundleV1(**payload)


# --- probe P1 no longer reaches an exploratory admission ------------------------


@pytest.mark.parametrize("rider", sorted(RIDERS))
def test_probe_p1_the_engine_refuses_a_riding_reconstruction(rider: str) -> None:
    """Built past the validators, the shape still dies at engine revalidation.

    Before issue 72 this engine ran, and its result bound the forgery by
    bundle hash and carried the invented limitation in its admission.
    """
    riding = _unvalidated_riding_bundle(RIDERS[rider]())
    admission = exploratory_admission(riding, limitations=riding.required_limitations)

    with pytest.raises(ValueError, match=REFUSED):
        reconstructed_engine(riding, admission=admission, with_cohort=False)


# --- the issue 56 rule stands on the realized lane ------------------------------

DECLARED = "a producer-declared dataset limitation"


def _realized_bundle_declaring_a_dataset_limitation() -> EvaluationInputBundleV1:
    """What a realized bundle can still oblige: its producer's declarations."""
    realized = _bundle()
    declared = assemble_evaluation_input_bundle(
        evaluation_interval=realized.evaluation_interval,
        session_clock=realized.session_clock,
        security_identities=realized.security_identities,
        listing_identities=realized.listing_identities,
        structural_eligibilities=realized.structural_eligibilities,
        economic_outcomes=realized.economic_outcomes,
        authentic_decision_views=realized.authentic_decision_views,
        authentic_accounting_views=realized.authentic_accounting_views,
        dataset_limitations=(DECLARED,),
    )
    assert declared.session_clock.mode == "realized_session_authority"
    assert declared.required_limitations == (DECLARED,)
    return declared


def test_the_realized_lane_refuses_an_admission_omitting_bundle_limitations() -> None:
    """Acknowledging less than the bundle obliges is refused at build (issue 56)."""
    declared = _realized_bundle_declaring_a_dataset_limitation()
    admission = exploratory_admission(
        declared, limitations=(ALPACA_LIMITATION_BOUNDED_COHORT,)
    )

    with pytest.raises(
        ValueError,
        match=r"^exploratory admission omits required bundle limitations: ",
    ) as error:
        reconstructed_engine(declared, admission=admission, with_cohort=False)
    assert DECLARED in str(error.value)


def test_a_fully_acknowledged_realized_run_is_still_admitted() -> None:
    """Control: the same bundle and lane, with every limitation acknowledged."""
    declared = _realized_bundle_declaring_a_dataset_limitation()

    artifacts = run_engine(
        reconstructed_engine(declared, with_cohort=False),
        _buy_ten(),
    )

    result = artifacts.result
    assert isinstance(result, ExploratoryEvaluationResultV1)
    assert DECLARED in result.admission.acknowledged_limitations


# --- controls --------------------------------------------------------------------


def test_a_realized_bundle_without_reconstructions_is_unaffected() -> None:
    """Control: a realized bundle obliging nothing extra runs as it always did."""
    realized = _bundle()
    assert realized.has_exploratory_reconstructions is False
    assert realized.required_limitations == ()

    artifacts = run_engine(
        reconstructed_engine(realized, with_cohort=False),
        _buy_ten(),
    )

    assert artifacts.result.lane == "exploratory"


def test_a_scheduled_bundle_still_carries_and_decides_on_reconstructions() -> None:
    """Control: the one clock whose lane re-derives reconstructions takes them."""
    bundle = bundle_of((scheduled_session_case(JAN5), scheduled_session_case(JAN6)))
    assert bundle.session_clock.mode == "scheduled_session_reconstruction"
    assert len(bundle.exploratory_reconstructed_observations) == 2

    artifacts = run_engine(
        reconstructed_engine(bundle), ReconstructedTargetStrategy({})
    )

    assert artifacts.result.classification == "complete"
