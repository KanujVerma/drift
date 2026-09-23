"""Exploratory reconstructions enter and survive a bundle only by re-derivation.

Issue 55: the bundle preparation boundary derives reconstructions through the
one canonical builder rather than accepting them from the caller, and bundle
verification re-derives them and requires exact equality, as it already did
for authentic views.
"""

import pytest
from exploratory_decision_test_support import (
    JAN5,
    JAN6,
    LISTING,
    LISTING_OTHER,
    SEC,
    SEC_OTHER,
    cohort_of,
    interval,
    merged_scheduled_clock,
    scheduled_bundle,
    scheduled_session_case,
    source_request,
)
from test_evaluator_reconstruction import make_policy

from drift.domain.evaluator_bundles import EvaluationInputBundleV1
from drift.domain.evaluator_reconstruction import (
    ExploratoryReconstructedSessionObservationV1,
    exploratory_reconstruction_hash,
)
from drift.domain.securities import ListingV1, ListingVenue, SecurityV1
from drift.evaluator.bundles import (
    build_evaluation_input_bundle,
    verify_evaluation_input_bundle,
)
from drift.evaluator.reconstruction import (
    ExploratoryReconstructionReplay,
    replay_exploratory_reconstructions,
    verify_exploratory_reconstructions,
)
from drift.markets.observation_validation import M1dResolutionContext


def _replay(
    *observations: ExploratoryReconstructedSessionObservationV1,
) -> ExploratoryReconstructionReplay:
    return ExploratoryReconstructionReplay(
        policy=make_policy(),
        requests=tuple(source_request(item) for item in observations),
    )


def _cases() -> tuple[
    ExploratoryReconstructedSessionObservationV1,
    ExploratoryReconstructedSessionObservationV1,
]:
    return scheduled_session_case(JAN5)[0], scheduled_session_case(JAN6)[0]


def _context() -> M1dResolutionContext:
    return source_request(scheduled_session_case(JAN5)[0])[1]


def _built(**kwargs: object) -> EvaluationInputBundleV1:
    """The preparation boundary over the JAN5 and JAN6 scheduled sessions."""
    sessions = (scheduled_session_case(JAN5)[1], scheduled_session_case(JAN6)[1])
    return build_evaluation_input_bundle(
        evaluation_interval=interval(),
        session_clock=merged_scheduled_clock(sessions),
        context=_context(),
        security_identities=(
            SecurityV1(schema_version="1", security_id=SEC),
            SecurityV1(schema_version="1", security_id=SEC_OTHER),
        ),
        listing_identities=(
            ListingV1(schema_version="1", listing_id=LISTING, venue=ListingVenue.XNYS),
            ListingV1(
                schema_version="1", listing_id=LISTING_OTHER, venue=ListingVenue.XNYS
            ),
        ),
        **kwargs,  # type: ignore[arg-type]
    )


def _forged_close(
    observation: ExploratoryReconstructedSessionObservationV1,
) -> ExploratoryReconstructedSessionObservationV1:
    fields = tuple(
        item.model_copy(update={"source_value": item.source_value * 2})
        if item.field_name == "close"
        else item
        for item in observation.fields
    )
    draft = ExploratoryReconstructedSessionObservationV1.model_construct(
        **{**dict(observation), "fields": fields}
    )
    return observation.model_copy(
        update={
            "fields": fields,
            "reconstruction_hash": exploratory_reconstruction_hash(draft),
        }
    )


# --- the canonical builder, replayed -------------------------------------------


def test_replay_is_the_canonical_builder_over_each_request() -> None:
    jan5, jan6 = _cases()
    assert replay_exploratory_reconstructions(_replay(jan5, jan6), cohort_of()) == (
        jan5,
        jan6,
    )


def test_equality_is_over_the_multiset_of_reconstructions() -> None:
    """Equal counts are not enough: a repeated reconstruction cannot stand in."""
    jan5, jan6 = _cases()
    verify_exploratory_reconstructions(
        (jan6, jan5), replay=_replay(jan5, jan6), cohort=cohort_of()
    )

    with pytest.raises(
        ValueError,
        match=(
            r"^exploratory reconstructions do not match canonical re-derivation: "
            rf"\('{jan5.reconstruction_hash}',\)$"
        ),
    ):
        verify_exploratory_reconstructions(
            (jan5, jan5), replay=_replay(jan5, jan6), cohort=cohort_of()
        )


def test_the_declared_cohort_is_part_of_what_re_derives() -> None:
    """A reconstruction built under one cohort does not re-derive under another."""
    jan5, jan6 = _cases()

    with pytest.raises(
        ValueError, match=r"^exploratory reconstructions do not match canonical"
    ):
        verify_exploratory_reconstructions(
            (jan5, jan6),
            replay=_replay(jan5, jan6),
            cohort=cohort_of((SEC, SEC_OTHER)),
        )


# --- the preparation boundary ----------------------------------------------------


def test_the_preparation_boundary_derives_reconstructions_itself() -> None:
    jan5, jan6 = _cases()
    built = _built(
        exploratory_cohort=cohort_of(),
        exploratory_reconstruction_replay=_replay(jan5, jan6),
    )

    assert set(built.exploratory_reconstructed_observations) == {jan5, jan6}
    # Identical to assembling the genuine reconstructions by hand.
    assert built == scheduled_bundle(
        (jan5, jan6),
        (scheduled_session_case(JAN5)[1], scheduled_session_case(JAN6)[1]),
    )


@pytest.mark.parametrize("half", ["cohort", "replay"])
def test_the_preparation_boundary_refuses_half_a_replay(half: str) -> None:
    jan5, jan6 = _cases()
    kwargs: dict[str, object] = (
        {"exploratory_cohort": cohort_of()}
        if half == "cohort"
        else {"exploratory_reconstruction_replay": _replay(jan5, jan6)}
    )

    with pytest.raises(
        ValueError,
        match=(
            r"^exploratory reconstruction replay requires both its declared cohort "
            r"and its replay inputs$"
        ),
    ):
        _built(**kwargs)


# --- bundle verification ----------------------------------------------------------


def test_verification_re_derives_the_bundle_reconstructions() -> None:
    jan5, jan6 = _cases()
    built = _built(
        exploratory_cohort=cohort_of(),
        exploratory_reconstruction_replay=_replay(jan5, jan6),
    )

    verify_evaluation_input_bundle(
        bundle=built,
        context=_context(),
        exploratory_cohort=cohort_of(),
        exploratory_reconstruction_replay=_replay(jan6, jan5),
    )


def test_verification_refuses_reconstructions_it_cannot_re_derive() -> None:
    jan5, jan6 = _cases()
    carrying = scheduled_bundle(
        (jan5, jan6),
        (scheduled_session_case(JAN5)[1], scheduled_session_case(JAN6)[1]),
    )

    with pytest.raises(
        ValueError,
        match=(
            r"^bundle carries exploratory reconstructions without the replay "
            r"inputs to re-derive them$"
        ),
    ):
        verify_evaluation_input_bundle(bundle=carrying, context=_context())


def test_verification_refuses_a_forged_reconstruction() -> None:
    jan5, jan6 = _cases()
    forged = _forged_close(jan5)
    carrying = scheduled_bundle(
        (forged, jan6),
        (scheduled_session_case(JAN5)[1], scheduled_session_case(JAN6)[1]),
    )

    with pytest.raises(
        ValueError,
        match=(
            r"^exploratory reconstructions do not match canonical re-derivation: "
            rf"\('{forged.reconstruction_hash}',\)$"
        ),
    ):
        verify_evaluation_input_bundle(
            bundle=carrying,
            context=_context(),
            exploratory_cohort=cohort_of(),
            exploratory_reconstruction_replay=_replay(jan5, jan6),
        )


@pytest.mark.parametrize("half", ["cohort", "replay"])
def test_verification_refuses_half_a_replay(half: str) -> None:
    jan5, jan6 = _cases()
    built = _built(
        exploratory_cohort=cohort_of(),
        exploratory_reconstruction_replay=_replay(jan5, jan6),
    )
    kwargs: dict[str, object] = (
        {"exploratory_cohort": cohort_of()}
        if half == "cohort"
        else {"exploratory_reconstruction_replay": _replay(jan5, jan6)}
    )

    with pytest.raises(
        ValueError, match=r"^exploratory reconstruction replay requires both"
    ):
        verify_evaluation_input_bundle(
            bundle=built,
            context=_context(),
            **kwargs,  # type: ignore[arg-type]
        )


def test_a_bundle_without_reconstructions_needs_no_replay() -> None:
    """Control: the realized-evidence path is unchanged."""
    built = _built()
    assert built.exploratory_reconstructed_observations == ()

    verify_evaluation_input_bundle(bundle=built, context=_context())
