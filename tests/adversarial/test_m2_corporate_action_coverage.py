"""Adversarial tests for closed-world corporate-action coverage (issue 76).

Owner ruling on #76 (2026-09-24), option A, with decisions D1 to D9: a held or
traded security needs a closed-world, evidence-bearing M1c corporate-action
coverage record over the evaluation interval, or the evaluator halts
INDETERMINATE in both lanes. Silent "no corporate action" is no longer a
default. The grade follows the source: an exploratory response yields
exploratory coverage only, and nothing here can reach promotion grade.

The record enters the bundle through ``corporate_action_coverage`` (D8-a), its
limitations reach every admission through ``required_limitations``, and the
promotion gate refuses it with no new code.

Every provider byte here is a synthesized literal; nothing opens a socket or
reads a credential.
"""

# ruff: noqa: E402

import json
import sys
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

import pytest
import test_alpaca_exploratory_adapter as adapter
import test_evaluator_corporate_actions as ca
import test_evaluator_engine as eng
from exploratory_decision_test_support import (
    JAN5,
    JAN6,
    SEC,
    SEC_OTHER,
    ReconstructedTargetStrategy,
    bundle_of,
    reconstructed_engine,
    run_engine,
    three_regular_sessions,
)
from observation_test_support import ObservationHarness
from pydantic import ValidationError

import drift.adapters.alpaca_exploratory as alpaca
from drift.adapters.alpaca_exploratory import AlpacaExploratoryIntakeResult
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.assertions import (
    BoundaryShape,
    TemporalBoundaryClaimV1,
    TemporalIntervalClaimV1,
)
from drift.domain.dataset_validation import DatasetValidationError
from drift.domain.economic_closed_world import (
    CORPORATE_ACTION_SNAPSHOT_LIMITATION,
    ClosedWorldCorporateActionCoverageV1,
    CorporateActionCompletenessAssertionV1,
    ReturnedCorporateActionV1,
    corporate_action_record_hash,
)
from drift.domain.economic_common import ActionKind
from drift.domain.economic_queries import MarketOutcomeQueryV1
from drift.domain.economic_results import (
    EconomicCoverageResolutionV1,
    EconomicOutcomeResolutionV1,
)
from drift.domain.evaluator_bundles import EvaluationInputBundleV1
from drift.domain.evaluator_clock import (
    EvaluationSessionV1,
    SessionClockV1,
    evaluation_session_hash,
    session_clock_hash,
    session_order_key,
)
from drift.domain.evaluator_corporate_actions import SecurityEconomicOutcomeV1
from drift.domain.evaluator_lanes import (
    ExploratoryEvaluationAdmissionV1,
    exploratory_evaluation_admission_hash,
)
from drift.domain.evaluator_portfolio import (
    IndeterminateValuationError,
    PendingCashClaimV1,
    PortfolioStateV2,
    pending_cash_claim_id,
)
from drift.domain.evaluator_results import (
    EvaluationClassification,
    EvaluationRunArtifactsV2,
)
from drift.domain.evaluator_strategy import SecurityTargetPositionV1
from drift.domain.evaluator_trace import (
    EvaluationPhase,
    IndeterminateCauseTraceEventV1,
)
from drift.domain.securities import SecurityV1
from drift.domain.sessions import SessionKeyV1
from drift.domain.temporal import AvailabilityChannelV1, ChannelKind, SourcePrecision
from drift.evaluator.bundles import (
    assemble_evaluation_input_bundle,
    build_evaluation_input_bundle,
    validate_exploratory_admission,
    verify_evaluation_input_bundle,
)
from drift.evaluator.clock import build_scheduled_reconstruction_clock
from drift.evaluator.corporate_action_coverage import CorporateActionCoverageIndex
from drift.evaluator.corporate_actions import CorporateActionProcessor
from drift.evaluator.engine import SessionEvaluatorEngine, SessionEvaluatorEvidence
from drift.markets.economic_closed_world import (
    CorporateActionCoverageError,
    build_corporate_action_coverage,
)
from drift.serialization.canonical import content_hash

SEC_A = UUID("019b8240-0000-7000-8000-00000000a076")
SEC_B = UUID("019b8240-0000-7000-8000-00000000b076")
SEC_OUTSIDE = UUID("019b8240-0000-7000-8000-00000000c076")
DAY_1 = date(2026, 1, 5)
DAY_2 = date(2026, 1, 6)
DAY_3 = date(2026, 1, 7)
SNAPSHOT = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _artifact(label: str) -> VerifiedArtifactBytes:
    data = f'{{"issue":76,"suite":"adversarial","synthetic":"{label}"}}'.encode()
    return VerifiedArtifactBytes(
        data=data, byte_size=len(data), content_hash=sha256(data).hexdigest()
    )


RESPONSE = _artifact("quiet corporate-actions response")
REQUEST = _artifact("request declaration")
ORIGIN = _artifact("measured origin")
POLICY = _artifact("closed-world policy statement")
SUPPORT = {item.content_hash: item for item in (RESPONSE, REQUEST, ORIGIN, POLICY)}


def _snapshot() -> TemporalBoundaryClaimV1:
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.EXACT,
        lower_bound=SNAPSHOT,
        upper_bound=SNAPSHOT,
        source_precision=SourcePrecision.SECOND,
        source_time_label="2026-09-20T12:00:00Z",
        source_timezone=None,
        evidence_reference=ArtifactReference(
            artifact_id=UUID("019b8240-0000-7000-8000-000000000976"),
            kind=ArtifactKind.OTHER,
            content_hash=RESPONSE.content_hash,
            location=f"drift+sha256://{RESPONSE.content_hash}",
        ),
    )


def _assertion(**overrides: Any) -> CorporateActionCompletenessAssertionV1:
    values: dict[str, Any] = {
        "basis": "provider_partially_published",
        "policy_statement_hash": POLICY.content_hash,
        "acquisition_reconciliation_pass": True,
        "single_unpaginated_response": True,
        "measured_origin": True,
        "requested_types_documented": True,
        "returned_actions_attributed": True,
        "returned_actions_inside_requested_window": True,
    }
    return CorporateActionCompletenessAssertionV1.model_validate(values | overrides)


def coverage(
    security_id: UUID,
    *,
    start: date = DAY_1,
    end: date = DAY_3,
    actions: tuple[ReturnedCorporateActionV1, ...] = (),
    completeness: CorporateActionCompletenessAssertionV1 | None = None,
    source_id: str = "synthetic-corporate-actions-v1",
    limitations: tuple[str, ...] = (CORPORATE_ACTION_SNAPSHOT_LIMITATION,),
) -> ClosedWorldCorporateActionCoverageV1:
    """One exploratory record over ``[start, end]`` for one security."""
    return build_corporate_action_coverage(
        source_id=source_id,
        security_id=security_id,
        queried_symbol=f"SYM{str(security_id)[-3:]}",
        requested_start_date=start,
        requested_end_date=end,
        requested_action_classes=("cash_dividend", "forward_split"),
        request_binding_hash=REQUEST.content_hash,
        response_sha256=RESPONSE.content_hash,
        response_byte_size=RESPONSE.byte_size,
        origin_observation_hash=ORIGIN.content_hash,
        returned_actions=actions,
        completeness=_assertion() if completeness is None else completeness,
        snapshot_as_of=_snapshot(),
        acknowledged_limitations=limitations,
    )


def _session(day: date) -> EvaluationSessionV1:
    draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=SessionKeyV1(mic="XNYS", session_scope="regular", local_date=day),
        opened_at=datetime(day.year, day.month, day.day, 14, 30, tzinfo=UTC),
        closed_at=datetime(day.year, day.month, day.day, 21, 0, tzinfo=UTC),
        authority="realized",
        authority_record_hashes=("a" * 64,),
        authority_proof_hashes=("b" * 64,),
        session_hash="0" * 64,
    )
    return draft.model_copy(update={"session_hash": evaluation_session_hash(draft)})


def _clock() -> SessionClockV1:
    draft = SessionClockV1.model_construct(
        schema_version="1",
        mode="realized_session_authority",
        sessions=tuple(
            sorted(
                (_session(day) for day in (DAY_1, DAY_2, DAY_3)), key=session_order_key
            )
        ),
        acknowledged_limitations=(),
        clock_hash="0" * 64,
    )
    return SessionClockV1.model_validate(
        draft.model_copy(update={"clock_hash": session_clock_hash(draft)}).model_dump()
    )


def _interval() -> TemporalIntervalClaimV1:
    return TemporalIntervalClaimV1(
        schema_version="1",
        start=TemporalBoundaryClaimV1(
            schema_version="1",
            shape=BoundaryShape.EXACT,
            lower_bound=datetime(2026, 1, 5, 0, 0, tzinfo=UTC),
            upper_bound=datetime(2026, 1, 5, 0, 0, tzinfo=UTC),
            source_precision=SourcePrecision.SECOND,
            source_time_label="2026-01-05T00:00:00Z",
            source_timezone=None,
            evidence_reference=None,
        ),
        end=None,
    )


def _bundle(
    records: tuple[ClosedWorldCorporateActionCoverageV1, ...] = (),
    **overrides: Any,
) -> EvaluationInputBundleV1:
    values: dict[str, Any] = {
        "evaluation_interval": _interval(),
        "session_clock": _clock(),
        "security_identities": (
            SecurityV1(schema_version="1", security_id=SEC_A),
            SecurityV1(schema_version="1", security_id=SEC_B),
        ),
        "corporate_action_coverage": records,
    }
    return assemble_evaluation_input_bundle(**(values | overrides))


def _admission(
    bundle: EvaluationInputBundleV1, limitations: tuple[str, ...]
) -> ExploratoryEvaluationAdmissionV1:
    draft = ExploratoryEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="exploratory",
        input_bundle_hash=bundle.bundle_hash,
        acknowledged_limitations=tuple(sorted(limitations)),
        admission_hash="0" * 64,
    )
    return ExploratoryEvaluationAdmissionV1.model_validate(
        draft.model_copy(
            update={"admission_hash": exploratory_evaluation_admission_hash(draft)}
        ).model_dump()
    )


# ==========================================================================
# The bundle field (D8-a)
# ==========================================================================


def test_the_bundle_carries_coverage_records_in_canonical_order() -> None:
    first, second = coverage(SEC_A), coverage(SEC_B)
    forward = _bundle((first, second))
    backward = _bundle((second, first))
    assert forward.corporate_action_coverage == backward.corporate_action_coverage
    assert forward.bundle_hash == backward.bundle_hash
    assert set(forward.corporate_action_coverage) == {first, second}


def test_the_bundle_hash_covers_the_coverage_records() -> None:
    bare = _bundle()
    covered = _bundle((coverage(SEC_A),))
    assert bare.corporate_action_coverage == ()
    assert covered.bundle_hash != bare.bundle_hash
    stripped = EvaluationInputBundleV1.model_construct(
        **(dict(covered) | {"corporate_action_coverage": ()})
    )
    with pytest.raises(ValidationError, match="bundle hash mismatch"):
        EvaluationInputBundleV1.model_validate(stripped.model_dump())


def test_the_bundle_refuses_a_repeated_record() -> None:
    record = coverage(SEC_A)
    with pytest.raises(ValidationError, match="must not repeat an identical member"):
        _bundle((record, record))


def test_m13_every_record_limitation_is_a_required_bundle_limitation() -> None:
    assert CORPORATE_ACTION_SNAPSHOT_LIMITATION not in _bundle().required_limitations
    covered = _bundle((coverage(SEC_A),))
    assert CORPORATE_ACTION_SNAPSHOT_LIMITATION in covered.required_limitations
    extra = "an-extra-record-limitation"
    wider = coverage(
        SEC_B,
        limitations=tuple(sorted((CORPORATE_ACTION_SNAPSHOT_LIMITATION, extra))),
    )
    assert extra in _bundle((wider,)).required_limitations
    assert extra not in covered.required_limitations


def test_m13_an_admission_omitting_the_snapshot_limitation_is_refused() -> None:
    bundle = _bundle((coverage(SEC_A),))
    with pytest.raises(
        ValueError,
        match=(
            r"^exploratory admission omits required bundle limitations: "
            rf"\('{CORPORATE_ACTION_SNAPSHOT_LIMITATION}',\)$"
        ),
    ):
        validate_exploratory_admission(
            admission=_admission(bundle, ("some-other-limitation",)),
            bundle=bundle,
        )
    # Control: acknowledging it admits the bundle.
    validate_exploratory_admission(
        admission=_admission(bundle, bundle.required_limitations), bundle=bundle
    )


def test_v11_a_record_for_a_security_outside_the_bundle_is_refused() -> None:
    with pytest.raises(ValidationError, match="ca_coverage_security_not_in_bundle"):
        _bundle((coverage(SEC_OUTSIDE),))


def native_resolution(
    security_id: UUID,
    *,
    kinds: tuple[ActionKind, ...] = tuple(ActionKind),
    history_start: str = "2025-12-01T00:00:00+00:00",
    horizon: str = "2026-02-01T00:00:00+00:00",
) -> EconomicOutcomeResolutionV1:
    """A quiet M1c-native outcome: three complete families, no records."""
    query = MarketOutcomeQueryV1(
        schema_version="1",
        security_id=security_id,
        action_kinds=tuple(sorted(set(kinds), key=lambda item: item.value)),
        history_start=datetime.fromisoformat(history_start),
        requested_channel=AvailabilityChannelV1(
            kind=ChannelKind.PUBLIC, identifier="synthetic", version="v1"
        ),
        availability_policy_id="synthetic-availability",
        availability_policy_hash="a" * 64,
        source_selection_policy_hash="b" * 64,
        input_context_hash="c" * 64,
        kind="outcome",
        purpose="economic_outcome",
        economic_horizon=datetime.fromisoformat(horizon),
        evidence_vintage_cutoff=datetime.fromisoformat(horizon),
    )
    return EconomicOutcomeResolutionV1(
        schema_version="1",
        query=query,
        query_hash=content_hash(query),
        selection_proof_hash="d" * 64,
        source_selection_policy_hash=query.source_selection_policy_hash,
        input_context_hash=query.input_context_hash,
        composition_algorithm="drift-m1c-economic-composition-v1",
        composition_algorithm_spec_hash="e" * 64,
        composition_implementation_hash="f" * 64,
        selected_terms_hashes=(),
        upcoming_terms_hashes=(),
        effect_projections=(),
        cancelled_action_hashes=(),
        unknown_effect_hashes=(),
        delivery_groups=(),
        uncomposed_settlement_hashes=(),
        associations=(),
        coverage_results=tuple(
            EconomicCoverageResolutionV1(
                family=family,
                source_id="synthetic-a",
                selected_coverage_hashes=("a" * 64,),
                target_manifest_hash="b" * 64,
                status="complete",
                occurrence_identity_supported=True,
                reasons=(),
            )
            for family in ("effect", "settlement", "terms")
        ),
        residual_resolutions=(),
        safe_projection_hashes=(),
        claim_status="continuing",
        evidence_completeness="known",
        support_status="indeterminate",
        reasons=(),
    )


def test_v11_one_security_is_never_covered_by_both_sources() -> None:
    with pytest.raises(ValidationError, match="ca_coverage_mixed_sources"):
        _bundle((coverage(SEC_A),), economic_outcomes=(native_resolution(SEC_A),))
    # Control: an outcome for one security and a record for another compose.
    mixed = _bundle((coverage(SEC_B),), economic_outcomes=(native_resolution(SEC_A),))
    assert len(mixed.corporate_action_coverage) == 1


# ==========================================================================
# V4 and V10 at the bundle boundaries
# ==========================================================================


def _scheduled_case(
    support: dict[str, VerifiedArtifactBytes],
) -> tuple[Any, Any]:
    """A scheduled clock and an M1d context carrying ``support`` besides its own."""
    harness = ObservationHarness(security_id=SEC_A)
    harness.attach_sessions(schedule_state="regular", realized_outcome="missing")
    harness.context = replace(
        harness.context,
        supporting_artifacts={**harness.context.supporting_artifacts, **support},
    )
    query = harness.outcome(
        economic_horizon="2026-01-06T00:00:00Z",
        evidence_vintage_cutoff="2026-01-06T00:00:00Z",
        session_date="2026-01-05",
    )
    return build_scheduled_reconstruction_clock((query,), harness.context), (
        harness.context
    )


def _build(
    records: tuple[ClosedWorldCorporateActionCoverageV1, ...],
    support: dict[str, VerifiedArtifactBytes],
) -> EvaluationInputBundleV1:
    clock, context = _scheduled_case(support)
    return build_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=clock,
        context=context,
        security_identities=(SecurityV1(schema_version="1", security_id=SEC_A),),
        corporate_action_coverage=records,
    )


def test_building_a_bundle_verifies_each_record_against_its_context() -> None:
    record = coverage(SEC_A)
    built = _build((record,), SUPPORT)
    assert built.corporate_action_coverage == (record,)
    without_response = {
        key: value for key, value in SUPPORT.items() if key != RESPONSE.content_hash
    }
    with pytest.raises(
        CorporateActionCoverageError, match=r"^ca_coverage_response_bytes_unavailable"
    ):
        _build((record,), without_response)
    # Swapped bytes filed under the record's digest never reach V4: the M1d
    # context refuses a supporting artifact that does not hash to its name.
    swapped = VerifiedArtifactBytes(
        data=RESPONSE.data.replace(b"quiet", b"QUIET"),
        byte_size=RESPONSE.byte_size,
        content_hash=RESPONSE.content_hash,
    )
    with pytest.raises(
        DatasetValidationError, match="observation_supporting_artifact_hash_mismatch"
    ):
        _build((record,), SUPPORT | {RESPONSE.content_hash: swapped})
    # A record naming the right bytes with the wrong size is refused by V4.
    body = dict(record) | {"response_byte_size": RESPONSE.byte_size + 1}
    draft = ClosedWorldCorporateActionCoverageV1.model_construct(**body)
    resized = ClosedWorldCorporateActionCoverageV1.model_validate(
        body | {"record_hash": corporate_action_record_hash(draft)}
    )
    with pytest.raises(
        CorporateActionCoverageError, match=r"^ca_coverage_response_hash_mismatch"
    ):
        _build((resized,), SUPPORT)


def test_building_a_bundle_refuses_a_stale_coverage_identity() -> None:
    record = coverage(SEC_A)
    body = dict(record) | {"implementation_hash": "1" * 64}
    draft = ClosedWorldCorporateActionCoverageV1.model_construct(**body)
    stale = ClosedWorldCorporateActionCoverageV1.model_validate(
        body | {"record_hash": corporate_action_record_hash(draft)}
    )
    with pytest.raises(
        CorporateActionCoverageError,
        match=r"^ca_coverage_implementation_identity_mismatch",
    ):
        _build((stale,), SUPPORT)


def test_verifying_a_bundle_verifies_each_record_against_its_context() -> None:
    record = coverage(SEC_A)
    clock, context = _scheduled_case(SUPPORT)
    bundle = assemble_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=clock,
        security_identities=(SecurityV1(schema_version="1", security_id=SEC_A),),
        corporate_action_coverage=(record,),
    )
    verify_evaluation_input_bundle(bundle=bundle, context=context)
    _, bare = _scheduled_case({})
    with pytest.raises(
        CorporateActionCoverageError, match=r"^ca_coverage_response_bytes_unavailable"
    ):
        verify_evaluation_input_bundle(bundle=bundle, context=bare)


# ==========================================================================
# The pre-open rule (C1 to C5), on the processor itself
# ==========================================================================

#: A Friday and the Monday after it: Monday's window is Saturday to Monday.
FRI, SAT, SUN, MON = date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 4), DAY_1
THU = date(2026, 1, 1)
NO_COVERAGE = r"^no closed-world corporate-action coverage for "


def _split(native_id: str, *dates: date) -> ReturnedCorporateActionV1:
    return ReturnedCorporateActionV1(
        native_kind="forward_splits",
        native_id=native_id,
        action_kind=ActionKind.FORWARD_SPLIT,
        dates=dates,
    )


def _processor(
    records: tuple[ClosedWorldCorporateActionCoverageV1, ...] = (),
    days: tuple[date, ...] = (FRI, MON),
) -> CorporateActionProcessor:
    return CorporateActionProcessor(
        session_clock=eng._clock(days),
        book_currency_namespace=eng.BOOK_NAMESPACE,
        book_currency_code=eng.BOOK_CODE,
        corporate_action_coverage=CorporateActionCoverageIndex(
            records=records, lane="exploratory"
        ),
    )


def _held(day: date, security_id: UUID = SEC_A, quantity: int = 10) -> PortfolioStateV2:
    return ca._state(holdings=(ca._holding(security_id, quantity=quantity),), day=day)


def _pre_open(
    processor: CorporateActionProcessor,
    state: PortfolioStateV2,
    day: date,
    targets: tuple[SecurityTargetPositionV1, ...] = (),
    outcomes: tuple[SecurityEconomicOutcomeV1, ...] = (),
) -> tuple[PortfolioStateV2, tuple[SecurityTargetPositionV1, ...]]:
    return processor.apply_pre_open_actions(state, targets, outcomes, eng._key(day))


def test_m1_a_held_security_without_coverage_halts_indeterminate() -> None:
    """The #76 defect: no record was read as no corporate action."""
    with pytest.raises(
        IndeterminateValuationError,
        match=NO_COVERAGE + rf"{SEC_A} over \[2026-01-03, 2026-01-05\]",
    ):
        _pre_open(_processor(), _held(MON), MON)
    # Control: a quiet record over the window evidences no action.
    state = _held(MON)
    assert _pre_open(_processor((coverage(SEC_A, start=FRI, end=MON),)), state, MON)[
        0
    ] == (state)


def test_m1_coverage_of_another_security_does_not_cover_the_held_one() -> None:
    with pytest.raises(IndeterminateValuationError, match=NO_COVERAGE + str(SEC_A)):
        _pre_open(_processor((coverage(SEC_B, start=FRI, end=MON),)), _held(MON), MON)


def test_m2_a_staged_buy_of_an_unheld_security_is_exposure() -> None:
    buy = (SecurityTargetPositionV1(security_id=SEC_B, target_quantity=5),)
    quiet_a = (coverage(SEC_A, start=FRI, end=MON),)
    with pytest.raises(IndeterminateValuationError, match=NO_COVERAGE + str(SEC_B)):
        _pre_open(_processor(quiet_a), _held(MON), MON, buy)
    # An explicit zero target on an unheld security trades nothing: no exposure.
    zero = (SecurityTargetPositionV1(security_id=SEC_B, target_quantity=0),)
    _pre_open(_processor(quiet_a), _held(MON), MON, zero)


def test_m2_a_sell_of_a_holding_is_exposure() -> None:
    sell = (SecurityTargetPositionV1(security_id=SEC_A, target_quantity=0),)
    with pytest.raises(IndeterminateValuationError, match=NO_COVERAGE + str(SEC_A)):
        _pre_open(_processor(), _held(MON), MON, sell)


def _pending_claim(security_id: UUID) -> PendingCashClaimV1:
    return PendingCashClaimV1(
        claim_id=pending_cash_claim_id(
            source_id="synthetic-a",
            security_id=security_id,
            action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
            occurrence_id="occ-claim",
            component_id="cash",
        ),
        source_id="synthetic-a",
        security_id=security_id,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        occurrence_id="occ-claim",
        component_id="cash",
        entitled_quantity=10,
        cash_per_share=Decimal("0.5"),
        total_cash_expected=Decimal("5"),
        entitlement_session=FRI,
        payable_session=date(2026, 1, 20),
    )


def test_c1_a_pending_cash_claim_alone_is_not_exposure() -> None:
    """A claim is fixed in cash and cannot be re-split, so it needs no coverage."""
    state = ca._state(claims=(_pending_claim(SEC_B),), day=MON)
    unchanged, _ = _pre_open(_processor(), state, MON)
    assert unchanged == state
    # Control: the same book holding the security halts without coverage.
    with pytest.raises(IndeterminateValuationError, match=NO_COVERAGE + str(SEC_B)):
        _pre_open(
            _processor(),
            ca._state(
                holdings=(ca._holding(SEC_B, quantity=10),),
                claims=(_pending_claim(SEC_B),),
                day=MON,
            ),
            MON,
        )


def test_m3_the_window_is_every_date_after_the_previous_session() -> None:
    """C2: Monday's window is Saturday to Monday; Friday's own date is not in it."""
    state = _held(MON)
    # An action on Saturday, a non-session date, lands at Monday's pre-open.
    on_saturday = (coverage(SEC_A, start=FRI, end=MON, actions=(_split("s", SAT),)),)
    with pytest.raises(
        IndeterminateValuationError,
        match=r"^corporate-action coverage returned actions for .* forward_splits s$",
    ):
        _pre_open(_processor(on_saturday), state, MON)
    # One on Friday belongs to Friday's window, not Monday's.
    on_friday = (coverage(SEC_A, start=FRI, end=MON, actions=(_split("f", FRI),)),)
    _pre_open(_processor(on_friday), state, MON)
    # Coverage must reach back to Saturday: a record starting Sunday does not.
    from_sunday = (coverage(SEC_A, start=SUN, end=MON),)
    with pytest.raises(
        IndeterminateValuationError,
        match=NO_COVERAGE + rf"{SEC_A} over \[2026-01-03, 2026-01-05\]",
    ):
        _pre_open(_processor(from_sunday), state, MON)


def test_m3_the_first_session_owns_only_its_own_date() -> None:
    state = _held(FRI)
    # An action the day before the first session is taken as already in the
    # opening book, so it neither halts nor needs coverage.
    before = (coverage(SEC_A, start=THU, end=MON, actions=(_split("t", THU),)),)
    _pre_open(_processor(before), state, FRI)
    only_friday = (coverage(SEC_A, start=FRI, end=FRI),)
    _pre_open(_processor(only_friday), state, FRI)
    with pytest.raises(
        IndeterminateValuationError,
        match=NO_COVERAGE + rf"{SEC_A} over \[2026-01-02, 2026-01-02\]",
    ):
        _pre_open(_processor((coverage(SEC_A, start=SAT, end=MON),)), state, FRI)


def test_m9_a_returned_action_in_a_held_window_halts_and_is_named() -> None:
    records = (coverage(SEC_A, start=FRI, end=MON, actions=(_split("ca-9", MON),)),)
    with pytest.raises(
        IndeterminateValuationError,
        match=(
            rf"^corporate-action coverage returned actions for {SEC_A} over "
            r"\[2026-01-03, 2026-01-05\] that no M2 accounting evidence accounts "
            r"for: forward_splits ca-9$"
        ),
    ):
        _pre_open(_processor(records), _held(MON), MON)


def test_m6_a_non_positive_assertion_does_not_cover() -> None:
    weak = _assertion(requested_types_documented=False)
    records = (coverage(SEC_A, start=FRI, end=MON, completeness=weak),)
    with pytest.raises(
        IndeterminateValuationError, match=NO_COVERAGE + r".* \(indeterminate\)$"
    ):
        _pre_open(_processor(records), _held(MON), MON)


def test_m17_an_undated_returned_action_halts_every_held_window() -> None:
    records = (coverage(SEC_A, start=FRI, end=MON, actions=(_split("u"),)),)
    for day in (FRI, MON):
        with pytest.raises(IndeterminateValuationError, match=NO_COVERAGE):
            _pre_open(_processor(records), _held(day), day)


def test_m14_v9_overlapping_records_that_disagree_are_never_resolved() -> None:
    """V9: a window touching a disagreeing overlap halts, though neither alone would.

    Tuesday's window is Tuesday alone. The loud record's split is dated
    Sunday, inside the overlap but outside the window, so either record on its
    own evidences no action on Tuesday. Together they disagree about the
    overlap, and a conflict is never resolved by preference.
    """
    tue = date(2026, 1, 6)
    days = (FRI, MON, tue)
    quiet = coverage(SEC_A, start=FRI, end=tue)
    loud = coverage(SEC_A, start=SAT, end=tue, actions=(_split("x", SUN),))
    state = _held(tue)
    for alone in (quiet, loud):
        assert _pre_open(_processor((alone,), days), state, tue)[0] == state
    with pytest.raises(
        IndeterminateValuationError,
        match=NO_COVERAGE
        + rf"{SEC_A} over \[2026-01-06, 2026-01-06\] \(indeterminate\)$",
    ):
        _pre_open(_processor((quiet, loud), days), state, tue)


def test_m14_a_record_and_an_outcome_for_one_security_are_refused() -> None:
    outcome = ca._quiet(SEC_A)
    with pytest.raises(
        CorporateActionCoverageError, match=r"^ca_coverage_mixed_sources"
    ):
        _pre_open(
            _processor((coverage(SEC_A, start=FRI, end=MON),)),
            _held(MON),
            MON,
            outcomes=(outcome,),
        )


def test_c4_m11_a_covered_empty_outcome_is_no_action_for_a_held_security() -> None:
    state = _held(MON)
    quiet = ca._quiet(SEC_A)
    assert quiet.resolution.support_status == "indeterminate"
    assert _pre_open(_processor(), state, MON, outcomes=(quiet,))[0] == state
    # Control: the same empty outcome that is not complete coverage halts.
    uncovered = ca._outcome(
        security_id=SEC_A, support_status="indeterminate", native_coverage=False
    )
    with pytest.raises(
        IndeterminateValuationError,
        match=NO_COVERAGE + r".*its M1c economic outcome is not complete coverage",
    ):
        _pre_open(_processor(), state, MON, outcomes=(uncovered,))


@pytest.mark.parametrize("status", ("unsupported", "indeterminate"))
def test_f2_a_covered_terms_only_outcome_is_not_no_action_for_a_held_book(
    status: str,
) -> None:
    """C4 applies only to an outcome with no record of any family (review F2).

    The held security's outcome is complete M1c-native coverage but carries
    an in-window reverse-split terms record and no effect. A schedule without
    an effect is not evidence that nothing happened, and it is not supported
    evidence either, so the held book halts as it did before issue 76.
    """
    terms, _, _ = ca._split_case(
        numerator="1",
        denominator="8",
        treatment=ca._treatment("round_down"),
        suffix=9100,
    )
    outcome = ca._outcome(terms=(terms,), support_status=status)
    assert outcome.resolution.selected_terms_hashes
    state = ca._state(holdings=(ca._holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError,
        match=(
            r"^economic outcome resolution is not supported evidence for "
            rf"{ca.SEC_A}: {status}$"
        ),
    ):
        ca._processor().apply_pre_open_actions(state, (), (outcome,), ca._key())
    index = CorporateActionCoverageIndex(records=(), lane="exploratory")
    assert not index.native_no_action(outcome, ca.EFFECT_DAY, ca.EFFECT_DAY)
    # Control: the same covered outcome with no record at all is no action.
    assert index.native_no_action(ca._quiet(ca.SEC_A), ca.EFFECT_DAY, ca.EFFECT_DAY)


def test_f3_a_staged_buy_is_judged_against_the_prior_close_book() -> None:
    """C1 before dispatch (review F3): the pass may extinguish the target.

    SEC_A is not held; a buy of it is staged. Its own supported cash
    acquisition extinguishes the claim and zeroes the target during the pass,
    so the book the pass leaves is not exposed to it. Only the prior-close
    check sees the staged buy, and its outcome is not native coverage (a
    subset of kinds), so the pass halts rather than trading on it.
    """
    terms = ca._terms(
        suffix=9300,
        action_kind=ActionKind.CASH_ACQUISITION,
        components=(ca._cash(amount="12"),),
        dates=(ca._date_fact("payable", ca.PAYABLE_AT),),
    )
    effect = ca._effect(
        suffix=9301,
        action_kind=ActionKind.CASH_ACQUISITION,
        components=(ca._cash(amount="12"),),
        terms=terms,
        claim_status="extinguished",
        effective_at=ca.EFFECT_AT,
    )
    outcome = ca._outcome(
        terms=(terms,), effects=(effect,), query_kinds=(ActionKind.CASH_ACQUISITION,)
    )
    assert outcome.resolution.support_status == "supported"
    with pytest.raises(
        IndeterminateValuationError,
        match=(
            rf"^no closed-world corporate-action coverage for {ca.SEC_A} over "
            r"\[2020-06-01, 2020-06-01\]: its M1c economic outcome is not complete "
            r"coverage of every action kind over the window$"
        ),
    ):
        ca._processor().apply_pre_open_actions(
            ca._state(), (ca._target(ca.SEC_A, 5),), (outcome,), ca._key()
        )


def test_m10_an_outcome_over_a_subset_of_action_kinds_is_not_coverage() -> None:
    subset = ca._outcome(
        security_id=SEC_A,
        support_status="indeterminate",
        query_kinds=(ActionKind.FORWARD_SPLIT, ActionKind.REVERSE_SPLIT),
    )
    with pytest.raises(IndeterminateValuationError, match=NO_COVERAGE):
        _pre_open(_processor(), _held(MON), MON, outcomes=(subset,))


def test_m2_a_spin_off_child_delivered_by_the_pass_is_exposure() -> None:
    """C1: exposure is judged again against the book the pass leaves."""
    outcome = ca._spinoff_case(suffix=7600)
    state = ca._state(holdings=(ca._holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError, match=NO_COVERAGE + str(ca.SEC_CHILD)
    ):
        ca._processor().apply_pre_open_actions(state, (), (outcome,), ca._key())
    # Control: the child stated quiet, the child is credited.
    updated, _ = ca._processor().apply_pre_open_actions(
        state, (), ca._covered((outcome,), ca.SEC_CHILD), ca._key()
    )
    assert ca.SEC_CHILD in ca._quantities(updated.holdings)


def test_d7_the_processor_has_no_default_coverage() -> None:
    with pytest.raises(TypeError, match="corporate_action_coverage"):
        CorporateActionProcessor(  # type: ignore[call-arg]
            session_clock=eng._clock(),
            book_currency_namespace=eng.BOOK_NAMESPACE,
            book_currency_code=eng.BOOK_CODE,
        )
    with pytest.raises(TypeError, match="requires a CorporateActionCoverageIndex"):
        CorporateActionProcessor(
            session_clock=eng._clock(),
            book_currency_namespace=eng.BOOK_NAMESPACE,
            book_currency_code=eng.BOOK_CODE,
            corporate_action_coverage=(),  # type: ignore[arg-type]
        )


def test_an_empty_window_holds_nothing_to_cover() -> None:
    index = CorporateActionCoverageIndex(records=(), lane="exploratory")
    index.require_covered(SEC_A, None, MON, FRI)
    with pytest.raises(IndeterminateValuationError, match=NO_COVERAGE):
        index.require_covered(SEC_A, None, MON, MON)


# ==========================================================================
# The index at engine construction (V10, V12)
# ==========================================================================


def test_v12_m12_exploratory_coverage_is_refused_under_a_promotion_admission() -> None:
    with pytest.raises(
        CorporateActionCoverageError, match=r"^ca_coverage_grade_refused_by_lane"
    ):
        CorporateActionCoverageIndex(records=(coverage(SEC_A),), lane="promotion")
    # Control: a promotion index may be covered only natively, and is built.
    assert CorporateActionCoverageIndex(records=(), lane="promotion").records == ()


def test_v10_m15_a_stale_identity_is_refused_by_the_index() -> None:
    record = coverage(SEC_A)
    body = dict(record) | {"implementation_hash": "1" * 64}
    draft = ClosedWorldCorporateActionCoverageV1.model_construct(**body)
    stale = ClosedWorldCorporateActionCoverageV1.model_validate(
        body | {"record_hash": corporate_action_record_hash(draft)}
    )
    with pytest.raises(
        CorporateActionCoverageError,
        match=r"^ca_coverage_implementation_identity_mismatch",
    ):
        CorporateActionCoverageIndex(records=(stale,), lane="exploratory")


def test_v10_the_engine_refuses_a_bundle_carrying_a_stale_record() -> None:
    record = eng.quiet_coverage([eng.SEC_A], eng.DAY_0, eng.DAY_3)[0]
    body = dict(record) | {"implementation_hash": "1" * 64}
    draft = ClosedWorldCorporateActionCoverageV1.model_construct(**body)
    stale = ClosedWorldCorporateActionCoverageV1.model_validate(
        body | {"record_hash": corporate_action_record_hash(draft)}
    )
    bundle = eng._bundle(corporate_action_coverage=(stale,))
    with pytest.raises(
        CorporateActionCoverageError,
        match=r"^ca_coverage_implementation_identity_mismatch",
    ):
        eng._engine(bundle=bundle)


# ==========================================================================
# Whole runs, both lanes (criterion 1, criterion 4, C6, C7)
# ==========================================================================


def _halt_cause(artifacts: EvaluationRunArtifactsV2) -> IndeterminateCauseTraceEventV1:
    (cause,) = (
        event
        for event in artifacts.trace.events
        if isinstance(event, IndeterminateCauseTraceEventV1)
    )
    return cause


def test_c6_a_realized_run_that_buys_without_coverage_halts_at_the_pre_open() -> None:
    artifacts = eng._run(eng._engine(bundle=eng._bundle(corporate_action_coverage=())))
    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    cause = _halt_cause(artifacts)
    assert cause.phase is EvaluationPhase.PRE_OPEN_EFFECTS
    assert cause.cause == (
        f"no closed-world corporate-action coverage for {eng.SEC_A} over "
        "[2026-01-07, 2026-01-07] (indeterminate)"
    )
    assert not [event for event in artifacts.trace.events if event.kind == "fill"]
    # Control: the same run over quiet coverage completes.
    assert (
        eng._run(eng._engine()).result.classification
        is EvaluationClassification.COMPLETE
    )


def _native_twin(*, covered: bool) -> EvaluationRunArtifactsV2:
    """The realized run with SEC_A covered by its own M1c-native outcome."""
    outcome = ca._outcome(
        security_id=eng.SEC_A,
        support_status="indeterminate",
        native_coverage=covered,
    )
    bundle = eng._bundle(economic_outcomes=(outcome.resolution,))
    assert {record.security_id for record in bundle.corporate_action_coverage} == {
        eng.SEC_B
    }
    return eng._run(
        eng._engine(
            bundle=bundle,
            evidence=SessionEvaluatorEvidence(
                listing_role_records=eng.ROLE_RECORDS, economic_outcomes=(outcome,)
            ),
        )
    )


def test_criterion_1_a_realized_twin_with_native_coverage_proceeds() -> None:
    covered = _native_twin(covered=True)
    assert covered.result.classification is EvaluationClassification.COMPLETE
    assert covered.result.metrics.committed_fill_count == 1
    uncovered = _native_twin(covered=False)
    assert uncovered.result.classification is EvaluationClassification.INDETERMINATE
    assert _halt_cause(uncovered).phase is EvaluationPhase.PRE_OPEN_EFFECTS


def _reconstructed(
    records: tuple[ClosedWorldCorporateActionCoverageV1, ...] | None,
) -> EvaluationRunArtifactsV2:
    return run_engine(
        reconstructed_engine(
            bundle_of(three_regular_sessions(), corporate_action_coverage=records)
        ),
        ReconstructedTargetStrategy({JAN5: ((SEC, 10),), JAN6: ((SEC, 10),)}),
    )


def test_criterion_1_the_reconstructed_lane_inverts_the_probe() -> None:
    quiet = _reconstructed(None)
    assert quiet.result.classification is EvaluationClassification.COMPLETE
    assert quiet.result.metrics.committed_fill_count == 1
    bare = _reconstructed(())
    assert bare.result.classification is EvaluationClassification.INDETERMINATE
    assert _halt_cause(bare).cause == (
        f"no closed-world corporate-action coverage for {SEC} over "
        "[2026-01-06, 2026-01-06] (indeterminate)"
    )
    split = eng.quiet_coverage(
        (SEC, SEC_OTHER),
        JAN5,
        date(2026, 1, 7),
        returned_actions=(_split("ca-jan7", date(2026, 1, 7)),),
    )
    held = _reconstructed(split)
    assert held.result.classification is EvaluationClassification.INDETERMINATE
    cause = _halt_cause(held)
    assert cause.phase is EvaluationPhase.PRE_OPEN_EFFECTS
    assert cause.session_key.local_date == date(2026, 1, 7)
    assert cause.cause.endswith("forward_splits ca-jan7")


def test_c7_the_reconstructed_lane_refuses_bytes_its_contexts_do_not_retain() -> None:
    # SUPPORT here is not the support every reconstruction context retains.
    foreign = tuple(
        coverage(security_id, start=JAN5, end=date(2026, 1, 7))
        for security_id in (SEC, SEC_OTHER)
    )
    bundle = bundle_of(three_regular_sessions(), corporate_action_coverage=foreign)
    with pytest.raises(
        CorporateActionCoverageError, match=r"^ca_coverage_response_bytes_unavailable"
    ):
        reconstructed_engine(bundle)


def test_criterion_4_a_non_trading_run_needs_no_coverage_in_either_lane() -> None:
    """B0 is unaffected: nothing is exposed, so nothing needs coverage."""
    realized = eng._run(
        eng._engine(bundle=eng._bundle(corporate_action_coverage=())),
        eng.FixedTargetStrategy({}),
    )
    assert realized.result.classification is EvaluationClassification.COMPLETE
    reconstructed = run_engine(
        reconstructed_engine(
            bundle_of(three_regular_sessions(), corporate_action_coverage=())
        ),
        ReconstructedTargetStrategy({}),
    )
    assert reconstructed.result.classification is EvaluationClassification.COMPLETE


# ==========================================================================
# Criterion 1 through the real Alpaca bridge: the #76 review probe inverts
# ==========================================================================

#: A measured response returning one forward split for AAPL, every date of it
#: on 2026-01-08, so only the window that owns 2026-01-08 holds it.
AAPL_SPLIT_ON_JAN8 = (
    b'{"corporate_actions":{"forward_splits":[{"id":"ca-aapl-split",'
    b'"symbol":"AAPL","new_rate":2,"old_rate":1,"ex_date":"2026-01-08",'
    b'"process_date":"2026-01-08"}]},"next_page_token":null}'
)
PROBE_WARMUP = 2
BUY_AND_HOLD_AAPL = {day: ((adapter.AAPL_ID, 10),) for day in adapter.SESSION_DATES}


def _probe(intake: AlpacaExploratoryIntakeResult) -> EvaluationRunArtifactsV2:
    """The review probe: the bridge bundle, synthetic M1b roles, buy and hold."""
    engine = SessionEvaluatorEngine(
        bundle=intake.bundle,
        admission=intake.admission,
        protocol=eng._protocol(warmup=PROBE_WARMUP),
        cost_model=eng._cost_model(),
        evidence=SessionEvaluatorEvidence(
            listing_role_records=(
                eng._role_record(adapter.AAPL_ID, adapter.AAPL_LISTING, suffix=7601),
                eng._role_record(adapter.MSFT_ID, adapter.MSFT_LISTING, suffix=7621),
            ),
            exploratory_cohort=intake.cohort,
            exploratory_reconstruction_replay=intake.reconstruction_replay,
        ),
        book_currency_namespace="iso4217",
        book_currency_code="USD",
    )
    return run_engine(engine, ReconstructedTargetStrategy(BUY_AND_HOLD_AAPL))


def test_criterion_1_a_pre_76_bridge_response_halts_the_probe(tmp_path: Path) -> None:
    """No measured request, no record: the probe no longer completes."""
    intake = adapter.run_pinned_intake(tmp_path / "private")
    assert intake.corporate_action_coverage == ()
    artifacts = _probe(intake)
    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    cause = _halt_cause(artifacts)
    assert cause.phase is EvaluationPhase.PRE_OPEN_EFFECTS
    assert cause.session_key.local_date == date(2026, 1, 7)
    assert cause.cause.startswith(
        f"no closed-world corporate-action coverage for {adapter.AAPL_ID} over "
    )
    assert not [event for event in artifacts.trace.events if event.kind == "fill"]


def test_criterion_1_a_request_omitting_a_documented_type_halts_the_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The structural type check, end to end: an omitted type is unevidenced.

    With the bridge's declared types one short of the documented enumeration,
    the quiet response is read and recorded, but no record is positive, so the
    staged buy halts at the first exposed pre-open instead of trading.
    """
    monkeypatch.setattr(
        alpaca,
        "ALPACA_ACTION_TYPES",
        tuple(
            item
            for item in alpaca.ALPACA_ACTION_TYPES
            if item != "capital_gains_distribution"
        ),
    )
    intake = adapter.run_covered_intake(tmp_path / "private", adapter.QUIET_ACTIONS)
    assert len(intake.corporate_action_coverage) == 2
    assert not any(
        item.completeness.positive for item in intake.corporate_action_coverage
    )
    artifacts = _probe(intake)
    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert _halt_cause(artifacts).cause == (
        f"no closed-world corporate-action coverage for {adapter.AAPL_ID} over "
        "[2026-01-07, 2026-01-07] (indeterminate)"
    )


def test_criterion_1_the_probe_trades_over_a_quiet_positive_response(
    tmp_path: Path,
) -> None:
    intake = adapter.run_covered_intake(tmp_path / "private", adapter.QUIET_ACTIONS)
    assert all(item.completeness.positive for item in intake.corporate_action_coverage)
    artifacts = _probe(intake)
    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert artifacts.result.metrics.committed_fill_count == 1
    (holding,) = artifacts.final_state.holdings
    assert (holding.security_id, holding.quantity) == (adapter.AAPL_ID, 10)


def test_criterion_1_a_split_in_the_response_halts_at_its_own_window(
    tmp_path: Path,
) -> None:
    intake = adapter.run_covered_intake(tmp_path / "private", AAPL_SPLIT_ON_JAN8)
    artifacts = _probe(intake)
    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    cause = _halt_cause(artifacts)
    assert cause.phase is EvaluationPhase.PRE_OPEN_EFFECTS
    assert cause.session_key.local_date == date(2026, 1, 8)
    assert cause.cause == (
        f"corporate-action coverage returned actions for {adapter.AAPL_ID} over "
        "[2026-01-08, 2026-01-08] that no M2 accounting evidence accounts for: "
        "forward_splits ca-aapl-split"
    )
    # The buy at the 2026-01-07 open was filled; the split's window halts it.
    assert artifacts.result.metrics.committed_fill_count == 1


def _leaves(value: object, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            out.update(_leaves(item, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            out.update(_leaves(item, f"{prefix}[{index}]"))
    else:
        out[prefix] = value
    return out


def test_criterion_4_a_non_trading_bridge_run_moves_only_its_hashes(
    tmp_path: Path,
) -> None:
    """B0 is unaffected: over the same bridge data, with or without the records.

    The covered bundle carries two records, so its hash, and every hash that
    binds it, moves; nothing else in the run does.
    """
    bare = adapter.run_pinned_intake(tmp_path / "bare")
    covered = adapter.run_covered_intake(tmp_path / "covered")
    assert bare.corporate_action_coverage == ()
    assert len(covered.corporate_action_coverage) == 2
    assert covered.bundle.bundle_hash != bare.bundle.bundle_hash

    def b0(intake: AlpacaExploratoryIntakeResult) -> dict[str, object]:
        artifacts = run_engine(
            SessionEvaluatorEngine(
                bundle=intake.bundle,
                admission=intake.admission,
                protocol=eng._protocol(warmup=PROBE_WARMUP),
                cost_model=eng._cost_model(),
                evidence=SessionEvaluatorEvidence(
                    exploratory_cohort=intake.cohort,
                    exploratory_reconstruction_replay=intake.reconstruction_replay,
                ),
                book_currency_namespace="iso4217",
                book_currency_code="USD",
            ),
            ReconstructedTargetStrategy({}),
        )
        assert artifacts.result.classification is EvaluationClassification.COMPLETE
        return _leaves(json.loads(artifacts.result.model_dump_json()))

    before, after = b0(bare), b0(covered)
    assert set(before) == set(after)
    moved = {key for key in before if before[key] != after[key]}
    assert moved
    for key in moved:
        assert isinstance(before[key], str) and len(str(before[key])) == 64, key
        assert isinstance(after[key], str) and len(str(after[key])) == 64, key


def test_once_covered_the_bridge_trade_still_halts_at_the_open_without_roles(
    tmp_path: Path,
) -> None:
    """The issue 54 cause the pre-open now precedes is still pinned behind it.

    With positive coverage the pre-open passes, and with no M1b listing role
    evidence the next open halts INDETERMINATE in the execution phase instead
    of inventing an execution listing, exactly as before issue 76.
    """
    intake = adapter.run_covered_intake(tmp_path / "private", adapter.QUIET_ACTIONS)
    engine = SessionEvaluatorEngine(
        bundle=intake.bundle,
        admission=intake.admission,
        protocol=eng._protocol(warmup=PROBE_WARMUP),
        cost_model=eng._cost_model(),
        evidence=SessionEvaluatorEvidence(
            exploratory_cohort=intake.cohort,
            exploratory_reconstruction_replay=intake.reconstruction_replay,
        ),
        book_currency_namespace="iso4217",
        book_currency_code="USD",
    )
    artifacts = run_engine(engine, ReconstructedTargetStrategy(BUY_AND_HOLD_AAPL))
    cause = _halt_cause(artifacts)
    assert cause.phase is EvaluationPhase.OPEN_EXECUTION
    assert cause.cause_kind == "indeterminate_execution"
    assert cause.cause.startswith(
        f"no active primary listing for security {adapter.AAPL_ID} at "
    )


# ==========================================================================
# Criterion 3: the grade follows the source; promotion refuses the record
# ==========================================================================


def test_criterion_3_the_promotion_gate_refuses_a_bundle_carrying_a_record() -> None:
    """No new gate code: the record's limitation is a required limitation.

    The promotion case differs from an admitted one only in carrying one
    exploratory coverage record (and the security identity it names). A proof
    assembled directly over it still meets the gate's own limitation refusal.
    """
    import test_replay_provenance as rp
    from replay_provenance_test_support import qualified_snapshot

    from drift.domain.replay_provenance import _build_bundle_provenance_proof
    from drift.evaluator.bundles import (
        qualify_replay_context,
        validate_promotion_admission,
    )

    harness, query, reference = rp._decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    admitted = rp._promotion_bundle(harness, query, reference, snapshot)
    record = coverage(SEC_A, start=date(2026, 11, 1), end=date(2026, 11, 30))
    carried = assemble_evaluation_input_bundle(
        evaluation_interval=admitted.evaluation_interval,
        session_clock=admitted.session_clock,
        security_identities=(SecurityV1(schema_version="1", security_id=SEC_A),),
        authentic_decision_views=admitted.authentic_decision_views,
        corporate_action_coverage=(record,),
        source_snapshot_hash=admitted.source_snapshot_hash,
    )
    assert carried.required_limitations == (CORPORATE_ACTION_SNAPSHOT_LIMITATION,)
    proof = _build_bundle_provenance_proof(
        qualified_context_hash=qualified.qualified_hash,
        source_snapshot_hash=snapshot.snapshot_hash,
        bundle=carried,
    )
    with pytest.raises(
        ValueError,
        match=(
            r"^promotion evaluation cannot consume evidence declaring limitations: "
            rf"\('{CORPORATE_ACTION_SNAPSHOT_LIMITATION}',\)$"
        ),
    ):
        validate_promotion_admission(
            **rp._promotion_case(carried, proof, snapshot, qualified)
        )


def test_criterion_3_no_record_can_state_a_grade_above_exploratory() -> None:
    record = coverage(SEC_A)
    for field, value in (
        ("evidence_grade", "promotion"),
        ("revision_support", "captured_history"),
    ):
        body = dict(record) | {field: value}
        with pytest.raises(ValidationError, match="ca_coverage_grade_exceeds_source"):
            ClosedWorldCorporateActionCoverageV1.model_validate(body)


def test_criterion_5_the_bridge_contacts_the_same_three_gets_on_the_same_hosts() -> (
    None
):
    """Q13 and Q15: no new endpoint, route, host or dependency."""
    assert alpaca._OBJECT_ENDPOINTS == (
        ("alpaca-historical-bars", "data.alpaca.markets", "/v2/stocks/bars"),
        ("alpaca-market-calendar", "paper-api.alpaca.markets", "/v2/calendar"),
        ("alpaca-corporate-actions", "data.alpaca.markets", "/v1/corporate-actions"),
    )
    # The core never imports the bridge, the new modules included.
    alpaca.assert_core_isolation()
