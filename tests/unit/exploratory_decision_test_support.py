"""Genuine scheduled-reconstruction corpora for the exploratory decision path.

Every observation here is built by the real exploratory reconstruction builder
and every session by the real scheduled clock builder, one M1d corpus per
session date. The per-date sessions are then merged into one clock exactly as
``test_evaluator_bundles._merged_realized_clock`` merges realized sessions:
concatenated in chronological order and re-hashed, with nothing about any
session altered. No ``RealizedSessionVersionV1`` exists anywhere in these
corpora, because every harness attaches its sessions with
``realized_outcome="missing"``.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from functools import cache
from typing import Any, Literal
from uuid import UUID

from observation_test_support import ObservationHarness, market_uid
from test_assertions import exact_boundary
from test_evaluator_engine import (
    BOOK_CODE,
    BOOK_NAMESPACE,
    CODE_VERSION_HASH,
    ENVIRONMENT_HASH,
    ROLE_RECORDS,
    STRATEGY_REFERENCE,
    _cost_model,
    _protocol,
)
from test_evaluator_reconstruction import make_cohort, make_policy

from drift.domain.assertions import TemporalIntervalClaimV1
from drift.domain.evaluator_bundles import EvaluationInputBundleV1
from drift.domain.evaluator_clock import (
    EvaluationSessionV1,
    SessionClockV1,
    session_clock_hash,
    session_order_key,
)
from drift.domain.evaluator_exploratory_strategy import (
    ExploratoryReconstructedRuntimeStrategy,
    ExploratoryStrategyDecisionContextV1,
)
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_ABSENT_HALTS,
    ALPACA_LIMITATION_BOUNDED_COHORT,
    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
    EvaluationAdmissionV1,
    ExploratoryEvaluationAdmissionV1,
    PromotionEvaluationAdmissionV1,
    exploratory_evaluation_admission_hash,
    promotion_evaluation_admission_hash,
)
from drift.domain.evaluator_protocol import EvaluationProtocolV1
from drift.domain.evaluator_reconstruction import (
    ExploratoryCohortAuthorizationV1,
    ExploratoryReconstructedSessionObservationV1,
)
from drift.domain.evaluator_results import EvaluationRunArtifactsV1
from drift.domain.evaluator_strategy import (
    RuntimeStrategy,
    SecurityTargetPositionV1,
    StrategyDecisionContextV1,
    StrategyDecisionIntentV1,
)
from drift.domain.securities import ListingV1, ListingVenue, SecurityV1
from drift.domain.strategies import StrategyReference
from drift.evaluator.bundles import (
    assemble_evaluation_input_bundle,
    build_evaluation_run_identity,
)
from drift.evaluator.clock import build_scheduled_reconstruction_clock
from drift.evaluator.engine import SessionEvaluatorEngine, SessionEvaluatorEvidence
from drift.evaluator.reconstruction import (
    ExploratoryReconstructionReplay,
    ExploratoryReconstructionRequest,
    build_exploratory_reconstructed_session_observation,
)

SEC = market_uid(200)
LISTING = market_uid(201)
SEC_OTHER = market_uid(300)
LISTING_OTHER = market_uid(301)

JAN5 = date(2026, 1, 5)
JAN6 = date(2026, 1, 6)
JAN7 = date(2026, 1, 7)

#: The generated scheduled boundaries the corpus states, in UTC. January is
#: Eastern Standard Time, so 13:00 New York is 18:00 UTC and 16:00 is 21:00.
REGULAR_CLOSE_UTC = (21, 0)
EARLY_CLOSE_UTC = (18, 0)

ScheduleState = Literal["regular", "early_close"]

type SessionCase = tuple[
    ExploratoryReconstructedSessionObservationV1, EvaluationSessionV1
]


# The exact source inputs of every genuine reconstruction built here, by hash.
# A forged reconstruction is never registered, so it has no replay request.
_SOURCE_REQUESTS: dict[str, ExploratoryReconstructionRequest] = {}


def source_request(
    observation: ExploratoryReconstructedSessionObservationV1,
) -> ExploratoryReconstructionRequest:
    """The query and context a genuine reconstruction was built from."""
    return _SOURCE_REQUESTS[observation.reconstruction_hash]


def replay_of(
    observations: Sequence[ExploratoryReconstructedSessionObservationV1],
) -> ExploratoryReconstructionReplay:
    """Replay inputs for every genuine reconstruction among these."""
    return ExploratoryReconstructionReplay(
        policy=make_policy(),
        requests=tuple(
            _SOURCE_REQUESTS[item.reconstruction_hash]
            for item in observations
            if item.reconstruction_hash in _SOURCE_REQUESTS
        ),
    )


def utc_close(day: date, state: ScheduleState) -> datetime:
    hour, minute = EARLY_CLOSE_UTC if state == "early_close" else REGULAR_CLOSE_UTC
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


@cache
def cohort_of(
    securities: tuple[UUID, ...] = (SEC,),
) -> ExploratoryCohortAuthorizationV1:
    return make_cohort(*securities)


@cache
def scheduled_session_case(
    session_date: date,
    schedule_state: ScheduleState = "regular",
    *,
    security_id: UUID = SEC,
    listing_id: UUID = LISTING,
    close: str = "100.000",
    cohort_securities: tuple[UUID, ...] = (SEC,),
) -> tuple[ExploratoryReconstructedSessionObservationV1, EvaluationSessionV1]:
    """One genuinely reconstructed observation and its own scheduled session.

    The source bar claims the same close the schedule states, so an early
    close corpus is internally consistent rather than a 13:00 schedule paired
    with a 16:00 bar.
    """
    harness = ObservationHarness(
        session_date=session_date,
        security_id=security_id,
        listing_id=listing_id,
        close=close,
        available_at=f"{session_date.isoformat()}T22:30:00Z",
        claimed_close_utc=(17, 55) if schedule_state == "early_close" else (20, 55),
    )
    harness.attach_sessions(schedule_state=schedule_state, realized_outcome="missing")
    horizon = f"{(session_date + timedelta(days=1)).isoformat()}T00:00:00Z"
    query = harness.outcome(
        economic_horizon=horizon,
        evidence_vintage_cutoff=horizon,
        session_date=session_date.isoformat(),
    )
    observation = build_exploratory_reconstructed_session_observation(
        query, harness.context, cohort_of(cohort_securities), make_policy()
    )
    _SOURCE_REQUESTS[observation.reconstruction_hash] = (query, harness.context)
    clock = build_scheduled_reconstruction_clock((query,), harness.context)
    assert len(clock.sessions) == 1
    return observation, clock.sessions[0]


def merged_scheduled_clock(
    sessions: Sequence[EvaluationSessionV1],
    *,
    limitations: tuple[str, ...] = (
        ALPACA_LIMITATION_ABSENT_HALTS,
        ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
    ),
    mode: str = "scheduled_session_reconstruction",
) -> SessionClockV1:
    """One scheduled clock over independently generated sessions."""
    draft = SessionClockV1.model_construct(
        schema_version="1",
        mode=mode,
        sessions=tuple(sorted(sessions, key=session_order_key)),
        acknowledged_limitations=tuple(sorted(limitations)),
        clock_hash="0" * 64,
    )
    return SessionClockV1.model_validate(
        draft.model_copy(update={"clock_hash": session_clock_hash(draft)}).model_dump()
    )


def three_regular_sessions() -> tuple[SessionCase, SessionCase, SessionCase]:
    return (
        scheduled_session_case(JAN5),
        scheduled_session_case(JAN6),
        scheduled_session_case(JAN7),
    )


def early_close_sessions() -> tuple[SessionCase, SessionCase]:
    """A regular session followed by a 13:00 New York scheduled early close."""
    return (scheduled_session_case(JAN5), scheduled_session_case(JAN6, "early_close"))


def interval() -> TemporalIntervalClaimV1:
    return TemporalIntervalClaimV1(schema_version="1", start=exact_boundary(), end=None)


def scheduled_bundle(
    observations: Sequence[ExploratoryReconstructedSessionObservationV1],
    sessions: Sequence[EvaluationSessionV1],
    *,
    clock: SessionClockV1 | None = None,
    source_snapshot_hash: str | None = None,
) -> EvaluationInputBundleV1:
    """A scheduled-reconstruction bundle carrying no authentic view at all."""
    unique = {session.session_key: session for session in sessions}
    return assemble_evaluation_input_bundle(
        evaluation_interval=interval(),
        session_clock=(
            merged_scheduled_clock(tuple(unique.values())) if clock is None else clock
        ),
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
        exploratory_reconstructed_observations=tuple(observations),
        source_snapshot_hash=source_snapshot_hash,
    )


def bundle_of(cases: Sequence[SessionCase], **kwargs: Any) -> EvaluationInputBundleV1:
    """The bundle over exactly these reconstructions and their own sessions."""
    return scheduled_bundle(
        tuple(observation for observation, _ in cases),
        tuple(session for _, session in cases),
        **kwargs,
    )


def exploratory_admission(
    bundle: EvaluationInputBundleV1, limitations: tuple[str, ...] | None = None
) -> ExploratoryEvaluationAdmissionV1:
    """An exploratory admission acknowledging everything the run must state."""
    acknowledged = (
        tuple(sorted({*bundle.required_limitations, ALPACA_LIMITATION_BOUNDED_COHORT}))
        if limitations is None
        else tuple(sorted(limitations))
    )
    draft = ExploratoryEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="exploratory",
        input_bundle_hash=bundle.bundle_hash,
        acknowledged_limitations=acknowledged,
        admission_hash="0" * 64,
    )
    return ExploratoryEvaluationAdmissionV1.model_validate(
        draft.model_copy(
            update={"admission_hash": exploratory_evaluation_admission_hash(draft)}
        ).model_dump()
    )


def promotion_admission(
    bundle: EvaluationInputBundleV1,
) -> PromotionEvaluationAdmissionV1:
    """A promotion admission bound to this exact bundle and nothing else.

    It binds the bundle hash on purpose, so the engine's first guard (the
    admission must admit this exact bundle) passes and the attack reaches the
    guard it is aimed at.
    """
    draft = PromotionEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="promotion",
        m1e_completion_record_hash="1" * 64,
        m1e_profile_set_hash="2" * 64,
        decision_handoff_hash="3" * 64,
        audit_handoff_hash="4" * 64,
        input_bundle_hash=bundle.bundle_hash,
        provenance_proof_hash="5" * 64,
        admission_hash="0" * 64,
    )
    return PromotionEvaluationAdmissionV1.model_validate(
        draft.model_copy(
            update={"admission_hash": promotion_evaluation_admission_hash(draft)}
        ).model_dump()
    )


def reconstructed_engine(
    bundle: EvaluationInputBundleV1,
    *,
    admission: EvaluationAdmissionV1 | None = None,
    cohort: ExploratoryCohortAuthorizationV1 | None = None,
    protocol: EvaluationProtocolV1 | None = None,
    with_cohort: bool = True,
    replay: ExploratoryReconstructionReplay | None = None,
    with_replay: bool | None = None,
) -> SessionEvaluatorEngine:
    """An engine over this bundle; replay evidence follows the cohort by default.

    Unless ``replay`` is given, the replay is rebuilt from the registered source
    inputs of the bundle's genuine reconstructions.
    """
    supplies_replay = with_cohort if with_replay is None else with_replay
    return SessionEvaluatorEngine(
        bundle=bundle,
        admission=exploratory_admission(bundle) if admission is None else admission,
        protocol=_protocol(warmup=1) if protocol is None else protocol,
        cost_model=_cost_model(),
        evidence=SessionEvaluatorEvidence(
            listing_role_records=ROLE_RECORDS,
            exploratory_cohort=(
                (cohort_of() if cohort is None else cohort) if with_cohort else None
            ),
            exploratory_reconstruction_replay=(
                (
                    replay_of(bundle.exploratory_reconstructed_observations)
                    if replay is None
                    else replay
                )
                if supplies_replay
                else None
            ),
        ),
        book_currency_namespace=BOOK_NAMESPACE,
        book_currency_code=BOOK_CODE,
    )


def run_engine(
    engine: SessionEvaluatorEngine,
    strategy: RuntimeStrategy | ExploratoryReconstructedRuntimeStrategy,
) -> EvaluationRunArtifactsV1:
    """Run any engine, in either lane, under an identity bound to its inputs."""
    return engine.run(
        strategy=strategy,
        run_identity=build_evaluation_run_identity(
            strategy_hash=STRATEGY_REFERENCE.code_hash,
            protocol_hash=engine.protocol.protocol_hash,
            cost_model_hash=engine.cost_model.cost_model_hash,
            admission=engine.admission,
            bundle=engine.bundle,
            code_version_hash=CODE_VERSION_HASH,
            environment_closure_hash=ENVIRONMENT_HASH,
        ),
    )


class ReconstructedTargetStrategy:
    """A deterministic EXPLORATORY strategy emitting pinned targets per date.

    It implements only ``decide_exploratory``: it can never be handed strong
    realized-session decision evidence, and never needs to be.
    """

    def __init__(self, targets: Mapping[date, tuple[tuple[UUID, int], ...]]) -> None:
        self.targets = targets
        self.seen: list[ExploratoryStrategyDecisionContextV1] = []

    @property
    def strategy_reference(self) -> StrategyReference:
        return STRATEGY_REFERENCE

    def decide_exploratory(
        self, context: ExploratoryStrategyDecisionContextV1
    ) -> StrategyDecisionIntentV1:
        self.seen.append(context)
        requested = self.targets.get(context.session_key.local_date, ())
        return StrategyDecisionIntentV1(
            session_key=context.session_key,
            decision_time=context.decision_cutoff,
            targets=tuple(
                SecurityTargetPositionV1(
                    security_id=security_id, target_quantity=quantity
                )
                for security_id, quantity in requested
            ),
        )


class DualLaneStrategy(ReconstructedTargetStrategy):
    """One baseline class answering both lanes, each through its own context.

    This is the shape an M3 baseline takes when it must run over realized and
    scheduled corpora alike. The engine, not the strategy, picks the method.
    """

    def __init__(
        self,
        targets: Mapping[date, tuple[tuple[UUID, int], ...]],
        realized_targets: Mapping[date, tuple[tuple[UUID, int], ...]] | None = None,
    ) -> None:
        super().__init__(targets)
        self.realized_targets = (
            targets if realized_targets is None else realized_targets
        )
        self.seen_realized: list[StrategyDecisionContextV1] = []

    def decide(self, context: StrategyDecisionContextV1) -> StrategyDecisionIntentV1:
        self.seen_realized.append(context)
        requested = self.realized_targets.get(context.session_key.local_date, ())
        return StrategyDecisionIntentV1(
            session_key=context.session_key,
            decision_time=context.decision_cutoff,
            targets=tuple(
                SecurityTargetPositionV1(
                    security_id=security_id, target_quantity=quantity
                )
                for security_id, quantity in requested
            ),
        )


class RealizedOnlyStrategy:
    """A strong-input strategy: it answers ``decide`` and nothing else."""

    def __init__(self) -> None:
        self.seen: list[StrategyDecisionContextV1] = []

    @property
    def strategy_reference(self) -> StrategyReference:
        return STRATEGY_REFERENCE

    def decide(self, context: StrategyDecisionContextV1) -> StrategyDecisionIntentV1:
        self.seen.append(context)
        return StrategyDecisionIntentV1(
            session_key=context.session_key,
            decision_time=context.decision_cutoff,
            targets=(),
        )
