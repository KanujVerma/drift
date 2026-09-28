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

import sys
from dataclasses import replace
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

import pytest
from observation_test_support import ObservationHarness
from pydantic import ValidationError

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
from drift.domain.evaluator_lanes import (
    ExploratoryEvaluationAdmissionV1,
    exploratory_evaluation_admission_hash,
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
    data = f'{{"issue":76,"synthetic":"{label}"}}'.encode()
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
