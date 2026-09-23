"""M2 adversarial acceptance: every exploratory admission is validated (#56).

Invariant 4 of the issue 42 ruling: exploratory limitations must propagate
into the resulting evidence and artifacts. The EXPLORATORY reconstructed lane
validated its admission against the bundle, but the realized lane did not, so
an exploratory admission over a realized-clock bundle that also carries
reconstructions could omit the reconstructions' limitations and still produce
an ``ExploratoryEvaluationResultV1``. These tests attack that seam.
"""

# ruff: noqa: E402

import sys
from pathlib import Path

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

import pytest
from exploratory_decision_test_support import (
    JAN5,
    exploratory_admission,
    reconstructed_engine,
    run_engine,
    scheduled_session_case,
)
from test_evaluator_engine import _bundle, _buy_ten

from drift.domain.evaluator_bundles import EvaluationInputBundleV1
from drift.domain.evaluator_results import ExploratoryEvaluationResultV1
from drift.evaluator.bundles import assemble_evaluation_input_bundle


def _realized_bundle_with_a_riding_reconstruction() -> EvaluationInputBundleV1:
    """A realized-clock bundle that also carries one exploratory reconstruction."""
    realized = _bundle()
    observation, _ = scheduled_session_case(JAN5)
    riding = assemble_evaluation_input_bundle(
        evaluation_interval=realized.evaluation_interval,
        session_clock=realized.session_clock,
        security_identities=realized.security_identities,
        listing_identities=realized.listing_identities,
        structural_eligibilities=realized.structural_eligibilities,
        economic_outcomes=realized.economic_outcomes,
        authentic_decision_views=realized.authentic_decision_views,
        authentic_accounting_views=realized.authentic_accounting_views,
        exploratory_reconstructed_observations=(observation,),
    )
    assert riding.session_clock.mode == "realized_session_authority"
    assert riding.has_exploratory_reconstructions is True
    assert len(riding.required_limitations) >= 2
    return riding


def test_the_realized_lane_refuses_an_admission_omitting_bundle_limitations() -> None:
    """Acknowledging only some of what the bundle obliges is refused at build."""
    riding = _realized_bundle_with_a_riding_reconstruction()
    kept, *omitted = sorted(riding.required_limitations)
    admission = exploratory_admission(riding, limitations=(kept,))

    with pytest.raises(
        ValueError,
        match=r"^exploratory admission omits required bundle limitations: ",
    ) as error:
        reconstructed_engine(riding, admission=admission, with_cohort=False)
    for limitation in omitted:
        assert limitation in str(error.value)


def test_a_fully_acknowledged_realized_run_is_still_admitted() -> None:
    """Control: the same bundle and lane, with every limitation acknowledged."""
    riding = _realized_bundle_with_a_riding_reconstruction()
    admission = exploratory_admission(riding, limitations=riding.required_limitations)

    artifacts = run_engine(
        reconstructed_engine(riding, admission=admission, with_cohort=False),
        _buy_ten(),
    )

    result = artifacts.result
    assert isinstance(result, ExploratoryEvaluationResultV1)
    assert set(riding.required_limitations) <= set(
        result.admission.acknowledged_limitations
    )


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
