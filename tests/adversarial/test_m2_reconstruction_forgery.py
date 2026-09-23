"""M2 adversarial acceptance: reconstructions are trusted only by re-derivation.

Issue 55, adjudicated in #62 (Q1): an exploratory reconstruction is valid under
its own contract by construction, so its self-hash proves nothing about the
source it names. Once #46 let reconstructions drive EXPLORATORY decisions, a
hand-built, internally self-consistent reconstruction could steer a run. The
reconstructed lane now re-derives every reconstruction through the one
canonical builder and requires exact canonical equality. These tests attack
each binding that equality carries.
"""

# ruff: noqa: E402

import sys
from datetime import timedelta
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
    JAN7,
    LISTING_OTHER,
    ReconstructedTargetStrategy,
    bundle_of,
    promotion_admission,
    reconstructed_engine,
    replay_of,
    run_engine,
    scheduled_session_case,
    source_request,
)
from test_evaluator_engine import _bundle
from test_evaluator_reconstruction import make_policy

from drift.domain.evaluator_reconstruction import (
    ExploratoryReconstructedSessionObservationV1,
    exploratory_reconstruction_hash,
)
from drift.evaluator.reconstruction import ExploratoryReconstructionReplay

MISMATCH = r"^exploratory reconstructions do not match canonical re-derivation: "


def _forge(
    observation: ExploratoryReconstructedSessionObservationV1, **changes: Any
) -> ExploratoryReconstructedSessionObservationV1:
    """A self-consistent reconstruction no source produced."""
    draft = ExploratoryReconstructedSessionObservationV1.model_construct(
        **{**dict(observation), **changes}
    )
    forged = observation.model_copy(
        update={
            **changes,
            "reconstruction_hash": exploratory_reconstruction_hash(draft),
        }
    )
    assert forged.reconstruction_hash != observation.reconstruction_hash
    return forged


def _with_field(
    observation: ExploratoryReconstructedSessionObservationV1, name: str, value: str
) -> ExploratoryReconstructedSessionObservationV1:
    fields = tuple(
        item.model_copy(update={"source_value": Decimal(value)})
        if item.field_name == name
        else item
        for item in observation.fields
    )
    return _forge(observation, fields=fields)


def _genuine_replay(
    *observations: ExploratoryReconstructedSessionObservationV1,
) -> ExploratoryReconstructionReplay:
    """The exact source inputs of these genuine reconstructions."""
    return ExploratoryReconstructionReplay(
        policy=make_policy(),
        requests=tuple(source_request(item) for item in observations),
    )


def _engine_over_forgery(
    forged: ExploratoryReconstructedSessionObservationV1,
    genuine: ExploratoryReconstructedSessionObservationV1,
) -> None:
    """Build an engine over JAN5 forged and JAN6 genuine, replaying both sources.

    The second session is genuine so the protocol's one warmup session leaves
    a session to evaluate, and the gate under attack is the one reached.
    """
    _, session = scheduled_session_case(JAN5)
    following = scheduled_session_case(JAN6)
    reconstructed_engine(
        bundle_of(((forged, session), following)),
        replay=_genuine_replay(genuine, following[0]),
    )


# --- the attack from the issue ------------------------------------------------


def test_a_forged_close_never_reaches_an_exploratory_decision() -> None:
    """The #55 repro: a 250.000 close, self-consistently hashed, is refused."""
    genuine, session = scheduled_session_case(JAN5)
    following = scheduled_session_case(JAN6)
    forged = _with_field(genuine, "close", "250.000")
    bundle = bundle_of(((forged, session), following))
    strategy = ReconstructedTargetStrategy({})

    with pytest.raises(ValueError, match=MISMATCH) as error:
        run_engine(
            reconstructed_engine(bundle, replay=_genuine_replay(genuine, following[0])),
            strategy,
        )
    assert forged.reconstruction_hash in str(error.value)
    assert strategy.seen == []


def test_the_genuine_corpus_still_decides_on_its_source_close() -> None:
    """Control: the same corpus, unforged, runs and decides on 100.000."""
    cases = (scheduled_session_case(JAN5), scheduled_session_case(JAN6))
    strategy = ReconstructedTargetStrategy({})

    artifacts = run_engine(reconstructed_engine(bundle_of(cases)), strategy)

    assert artifacts.result.classification == "complete"
    closes = {
        str(field.source_value)
        for context in strategy.seen
        for view in context.reconstructed_decision_views
        for observation in view.observations
        for field in observation.fields
        if field.field_name == "close"
    }
    assert closes == {"100.000"}


# --- every binding the equality carries ----------------------------------------

FORGERIES: dict[str, dict[str, Any]] = {
    "source observation": {"source_observation_hash": "a" * 64},
    "observation contract": {"observation_contract_hash": "a" * 64},
    "observation selection proof": {"observation_selection_proof_hash": "a" * 64},
    "contract selection proof": {"contract_selection_proof_hash": "a" * 64},
    "scheduled selection proof": {"scheduled_selection_proof_hash": "a" * 64},
    "generated schedule artifact": {"schedule_artifact_hash": "a" * 64},
    "outcome query": {"outcome_query_hash": "a" * 64},
    "source context identity": {"source_context_hash": "a" * 64},
    "reconstruction policy": {"reconstruction_policy_hash": "a" * 64},
    "listing": {"listing_id": LISTING_OTHER},
    "currency": {"currency": "EUR"},
}


@pytest.mark.parametrize("binding", sorted(FORGERIES))
def test_a_forged_binding_fails_closed(binding: str) -> None:
    genuine, _ = scheduled_session_case(JAN5)
    forged = _forge(genuine, **FORGERIES[binding])

    with pytest.raises(ValueError, match=MISMATCH):
        _engine_over_forgery(forged, genuine)


def test_a_forged_evidence_vintage_cutoff_fails_closed() -> None:
    genuine, _ = scheduled_session_case(JAN5)
    forged = _forge(
        genuine,
        evidence_vintage_cutoff=genuine.evidence_vintage_cutoff - timedelta(hours=1),
    )

    with pytest.raises(ValueError, match=MISMATCH):
        _engine_over_forgery(forged, genuine)


@pytest.mark.parametrize("name", ["open", "high", "low", "close", "volume"])
def test_a_forged_ohlcv_value_fails_closed(name: str) -> None:
    genuine, _ = scheduled_session_case(JAN5)
    forged = _with_field(genuine, name, "97.125")

    with pytest.raises(ValueError, match=MISMATCH):
        _engine_over_forgery(forged, genuine)


def test_an_added_limitation_fails_closed() -> None:
    """Limitations are bound too, even when the run acknowledges the extra one."""
    genuine, session = scheduled_session_case(JAN5)
    forged = _forge(
        genuine,
        acknowledged_limitations=tuple(
            sorted((*genuine.acknowledged_limitations, "an invented limitation"))
        ),
    )
    assert "an invented limitation" in (
        bundle_of(((forged, session),)).required_limitations
    )

    with pytest.raises(ValueError, match=MISMATCH):
        _engine_over_forgery(forged, genuine)


def test_a_reconstruction_under_another_policy_fails_closed() -> None:
    """The replay's policy is the one the reconstructions must derive under."""
    cases = (scheduled_session_case(JAN5), scheduled_session_case(JAN6))
    replay = ExploratoryReconstructionReplay(
        policy=make_policy(policy_version="2"),
        requests=tuple(source_request(item) for item, _ in cases),
    )

    with pytest.raises(ValueError, match=MISMATCH):
        reconstructed_engine(bundle_of(cases), replay=replay)


def test_a_request_resolved_against_another_context_fails_closed() -> None:
    """A query only re-derives against the exact context it names."""
    jan5 = scheduled_session_case(JAN5)
    jan6 = scheduled_session_case(JAN6)
    query, _ = source_request(jan5[0])
    _, other_context = source_request(jan6[0])
    replay = ExploratoryReconstructionReplay(
        policy=make_policy(),
        requests=((query, other_context), source_request(jan6[0])),
    )

    with pytest.raises(ValueError):
        reconstructed_engine(bundle_of((jan5, jan6)), replay=replay)


# --- coverage is exact in both directions ---------------------------------------


def test_an_unregistered_forgery_has_no_source_to_re_derive_from() -> None:
    """With no request of its own, a forgery leaves the replay one short."""
    genuine, session = scheduled_session_case(JAN5)
    forged = _with_field(genuine, "close", "250.000")

    with pytest.raises(
        ValueError,
        match=(
            r"^exploratory reconstruction count mismatch against canonical "
            r"re-derivation: expected 1, got 2$"
        ),
    ):
        reconstructed_engine(
            bundle_of(((forged, session), scheduled_session_case(JAN6)))
        )


def test_a_reconstruction_left_out_of_the_replay_fails_closed() -> None:
    first = scheduled_session_case(JAN5)
    second = scheduled_session_case(JAN6)

    with pytest.raises(
        ValueError,
        match=r"^exploratory reconstruction count mismatch .*expected 1, got 2$",
    ):
        reconstructed_engine(
            bundle_of((first, second)), replay=_genuine_replay(first[0])
        )


def test_a_replay_deriving_more_than_the_bundle_carries_fails_closed() -> None:
    cases = (scheduled_session_case(JAN5), scheduled_session_case(JAN6))
    extra = scheduled_session_case(JAN7)

    with pytest.raises(
        ValueError,
        match=r"^exploratory reconstruction count mismatch .*expected 3, got 2$",
    ):
        reconstructed_engine(
            bundle_of(cases),
            replay=_genuine_replay(*(item for item, _ in cases), extra[0]),
        )


def test_replay_order_does_not_matter() -> None:
    """Control: equality is over the multiset, not the request order."""
    cases = (scheduled_session_case(JAN5), scheduled_session_case(JAN6))
    reversed_replay = _genuine_replay(*(item for item, _ in reversed(cases)))

    artifacts = run_engine(
        reconstructed_engine(bundle_of(cases), replay=reversed_replay),
        ReconstructedTargetStrategy({}),
    )

    assert artifacts.result.classification == "complete"


# --- the replay evidence is scoped exactly like the cohort -----------------------


def test_the_reconstructed_lane_requires_replay_evidence() -> None:
    with pytest.raises(
        ValueError,
        match=(
            r"^a scheduled session reconstruction evaluation requires the replay "
            r"evidence its reconstructions re-derive from$"
        ),
    ):
        reconstructed_engine(
            bundle_of((scheduled_session_case(JAN5), scheduled_session_case(JAN6))),
            with_replay=False,
        )


def test_replay_evidence_is_refused_on_the_realized_lane() -> None:
    with pytest.raises(
        ValueError,
        match=(
            r"^exploratory reconstruction replay evidence scopes only a scheduled "
            r"session reconstruction evaluation$"
        ),
    ):
        reconstructed_engine(
            _bundle(), with_cohort=False, replay=replay_of(()), with_replay=True
        )


def test_replay_evidence_is_refused_under_a_promotion_admission() -> None:
    realized = _bundle()

    with pytest.raises(
        ValueError,
        match=(
            r"^a promotion admission cannot evaluate exploratory reconstruction "
            r"replay evidence$"
        ),
    ):
        reconstructed_engine(
            realized,
            admission=promotion_admission(realized),
            with_cohort=False,
            replay=replay_of(()),
            with_replay=True,
        )
