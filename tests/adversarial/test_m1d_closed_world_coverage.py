"""Adversarial tests for evidence-bearing closed-world session coverage (issue 71).

Ruling Q18 of #62, option (b), with decisions D1 to D9 adopted on 2026-09-24.
The Alpaca bridge derives a ``ClosedWorldSessionCoverageV1`` from the calendar
response it already retains (D1-a), over the bracketed hull of the returned
dates (D2-b), at exploratory grade with a named limitation (D3-a), and
materializes every evidenced non-trading date as an explicit closed row bound
to the record (D4-A). The record joins the M1d evidence identity through the M1d
context (D5-a). An INDETERMINATE date inside the run span is refused at intake
(D6-a) and, as defense in depth, the reconstructed lane refuses a scheduled
clock that steps across a date no record evidences (D6-c, D8-b). Coverage is
schedule evidence only (D7-a).

Every provider byte here is a pinned or synthesized literal; nothing opens a
socket or reads a credential.
"""

# ruff: noqa: E402

import ast
import json
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

import pytest
from exploratory_decision_test_support import (
    JAN5,
    JAN6,
    JAN7,
    ReconstructedTargetStrategy,
    bundle_of,
    promotion_admission,
    reconstructed_engine,
    scheduled_session_case,
)
from test_alpaca_exploratory_adapter import (
    AAPL_ID,
    PINNED_CORPORATE_ACTIONS,
    WINTER_OFFSET_SECONDS,
    hand_minted_admission,
    measured_over,
    pinned_request,
)
from test_evaluator_engine import _cost_model, _protocol, _run_identity

from drift.adapters.alpaca_exploratory import (
    _OBJECT_ENDPOINTS,
    _POLICY_DOCUMENTS,
    ALPACA_CALENDAR_SOURCE_ID,
    ALPACA_EXPLORATORY_LIMITATIONS,
    ALPACA_LIMITATION_CALENDAR_CLOSED_WORLD,
    ALPACA_PAPER_TRADING_HOST,
    CALENDAR_OBJECT_KEY,
    AlpacaBridgeIncompleteError,
    AlpacaBridgeProhibitedError,
    AlpacaExploratoryIntakeResult,
    AlpacaIntakeRequest,
    AlpacaNativePayloads,
    _exact_boundary,
    assert_core_isolation,
    build_bridge_admission,
    run_alpaca_exploratory_intake,
    verify_alpaca_closed_world_record,
)
from drift.datasets.hashing import assertion_version_payload
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.assertions import TemporalIntervalClaimV1
from drift.domain.evaluator_execution import IndeterminateExecutionError
from drift.domain.evaluator_results import EvaluationClassification
from drift.domain.session_closed_world import (
    ClosedWorldSessionCoverageV1,
    seal_closed_world_session_coverage,
)
from drift.domain.sessions import (
    ScheduledSessionVersionV1,
    ScheduleGenerationPolicyV1,
    SessionCoverageVersionV1,
)
from drift.evaluator.bundles import build_evaluation_input_bundle
from drift.evaluator.clock import build_scheduled_reconstruction_clock
from drift.evaluator.engine import (
    PromotionLaneDisabledError,
    SessionEvaluatorEngine,
    SessionEvaluatorEvidence,
)
from drift.evaluator.reconstruction import ExploratoryReconstructionReplay
from drift.markets.observation_validation import (
    M1dDatasetInput,
    M1dResolutionContext,
    validate_m1d_resolution_context,
)
from drift.markets.session_closed_world import (
    ClosedWorldCoverageError,
    closed_world_record_bytes,
    closed_world_record_digest,
    evidenced_session_date_status,
    expand_closed_world_coverage,
    verify_closed_world_session_coverage,
)
from drift.markets.session_generation import generate_schedule
from drift.serialization.canonical import content_hash

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Monday 2026-01-05 to Friday 2026-01-16: ten sessions and one weekend.
FORTNIGHT = tuple(date(2026, 1, day) for day in (5, 6, 7, 8, 9, 12, 13, 14, 15, 16))
WEEKEND = (date(2026, 1, 10), date(2026, 1, 11))
#: The same fortnight with Wednesday 2026-01-14 missing from the calendar.
HOLIDAY_FORTNIGHT = tuple(day for day in FORTNIGHT if day != date(2026, 1, 14))
WARMUP = 2


def _payloads(days: tuple[date, ...]) -> AlpacaNativePayloads:
    """A closed response set whose calendar and bars cover exactly ``days``."""
    calendar = [
        {
            "close": "16:00",
            "date": day.isoformat(),
            "open": "09:30",
            "settlement_date": day.isoformat(),
        }
        for day in days
    ]
    bars = {
        symbol: [
            {
                "c": "191.25",
                "h": "192.00",
                "l": "189.75",
                "n": 410000,
                "o": "190.50",
                "t": f"{day.isoformat()}T05:00:00Z",
                "v": "52000000",
            }
            for day in days
        ]
        for symbol in ("AAPL", "MSFT")
    }
    return AlpacaNativePayloads(
        bars=json.dumps({"bars": bars, "next_page_token": None}).encode("utf-8"),
        calendar=json.dumps(calendar).encode("utf-8"),
        corporate_actions=PINNED_CORPORATE_ACTIONS,
    )


def _inputs(
    days: tuple[date, ...] = FORTNIGHT,
    *,
    start: date | None = None,
    end: date | None = None,
    calendar_days: tuple[date, ...] | None = None,
) -> tuple[AlpacaIntakeRequest, AlpacaNativePayloads]:
    """A request measured over exactly the payloads it declares."""
    payloads = _payloads(days)
    if calendar_days is not None:
        payloads = replace(payloads, calendar=_payloads(calendar_days).calendar)
    offsets = {
        (day, boundary): WINTER_OFFSET_SECONDS
        for day in (*days, *(calendar_days or ()))
        for boundary in ("open", "close")
    }
    request = pinned_request(
        start_date=days[0] if start is None else start,
        end_date=days[-1] if end is None else end,
        boundary_offsets=offsets,
    )
    return measured_over(request, payloads), payloads


def _intake(
    root: Path,
    days: tuple[date, ...] = FORTNIGHT,
    *,
    start: date | None = None,
    end: date | None = None,
    calendar_days: tuple[date, ...] | None = None,
) -> AlpacaExploratoryIntakeResult:
    request, payloads = _inputs(days, start=start, end=end, calendar_days=calendar_days)
    return run_alpaca_exploratory_intake(
        request=request, payloads=payloads, private_root=root
    )


@pytest.fixture(scope="module")
def fortnight(
    tmp_path_factory: pytest.TempPathFactory,
) -> AlpacaExploratoryIntakeResult:
    return _intake(tmp_path_factory.mktemp("closed-world-fortnight"))


def _scheduled(intake: AlpacaExploratoryIntakeResult) -> M1dDatasetInput[Any]:
    return next(
        item
        for item in intake.context.session_datasets
        if item.manifest.dataset_role.name == "scheduled_session"
    )


def _coverage_dataset(intake: AlpacaExploratoryIntakeResult) -> M1dDatasetInput[Any]:
    return next(
        item
        for item in intake.context.session_datasets
        if item.manifest.dataset_role.name == "session_coverage"
    )


def _rows(
    intake: AlpacaExploratoryIntakeResult,
) -> tuple[ScheduledSessionVersionV1, ...]:
    return tuple(
        item
        for item in _scheduled(intake).records
        if isinstance(item, ScheduledSessionVersionV1)
    )


def _engine(
    intake: AlpacaExploratoryIntakeResult,
    *,
    bundle: Any = None,
    admission: Any = None,
    replay: ExploratoryReconstructionReplay | None = None,
) -> SessionEvaluatorEngine:
    bundle = intake.bundle if bundle is None else bundle
    return SessionEvaluatorEngine(
        bundle=bundle,
        admission=(
            (
                intake.admission
                if bundle is intake.bundle
                else hand_minted_admission(bundle, ALPACA_EXPLORATORY_LIMITATIONS)
            )
            if admission is None
            else admission
        ),
        protocol=_protocol(warmup=WARMUP),
        cost_model=_cost_model(),
        evidence=SessionEvaluatorEvidence(
            exploratory_cohort=intake.cohort,
            exploratory_reconstruction_replay=(
                intake.reconstruction_replay if replay is None else replay
            ),
        ),
        book_currency_namespace="iso4217",
        book_currency_code="USD",
    )


# --- acceptance 1: a covered fortnight is accepted, with exact closed rows ---------


def test_a_covered_fortnight_is_accepted_over_its_evidenced_weekend(
    fortnight: AlpacaExploratoryIntakeResult,
) -> None:
    coverage = fortnight.closed_world_coverage
    assert coverage.returned_dates == FORTNIGHT
    assert (coverage.covered_start_date, coverage.covered_end_date) == (
        FORTNIGHT[0],
        FORTNIGHT[-1],
    )
    assert coverage.evidence_grade == "exploratory"
    assert coverage.completeness.positive is True
    # The scheduled clock contains exactly the returned dates.
    assert (
        tuple(
            session.session_key.local_date
            for session in fortnight.session_clock.sessions
        )
        == FORTNIGHT
    )
    # Exactly the weekend is materialized, as explicit closed rows bound to the
    # record's bytes, and every returned date is an open row.
    rows = _rows(fortnight)
    closed = tuple(row for row in rows if row.state == "closed")
    assert tuple(row.session_key.local_date for row in closed) == WEEKEND
    assert closed == expand_closed_world_coverage(coverage)
    digest = closed_world_record_digest(coverage)
    assert {row.revision.source_artifact.content_hash for row in closed} == {digest}
    assert (
        tuple(
            sorted(row.session_key.local_date for row in rows if row.state == "regular")
        )
        == FORTNIGHT
    )
    assert fortnight.context.supporting_artifacts[digest].data == (
        closed_world_record_bytes(coverage)
    )


def test_the_derived_rows_pass_the_existing_dense_walk_unchanged(
    fortnight: AlpacaExploratoryIntakeResult,
) -> None:
    validate_m1d_resolution_context(fortnight.context)
    (coverage_row,) = _coverage_dataset(fortnight).records
    assert isinstance(coverage_row, SessionCoverageVersionV1)
    assert coverage_row.status == "expected_complete"
    assert coverage_row.exception_dates == ()
    assert (coverage_row.start_date, coverage_row.end_date) == (
        FORTNIGHT[0],
        FORTNIGHT[-1],
    )
    assert len(coverage_row.record_inventory) == len(FORTNIGHT) + len(WEEKEND)
    # The coverage claim is derived from the record, and says so.
    assert coverage_row.revision.source_artifact.content_hash == (
        closed_world_record_digest(fortnight.closed_world_coverage)
    )


def test_the_pinned_generator_generates_open_dates_and_never_opens_a_closed_one(
    fortnight: AlpacaExploratoryIntakeResult,
) -> None:
    """Delta F1: the pinned generator, unchanged, fails closed on a closed date.

    A closed row carries no boundary offsets, so its methodology set cannot
    equal the bridge policy's, and ``generate_schedule`` answers
    ``indeterminate`` rather than ``generated``. It never reads the date as
    open. Density is therefore proven by the closed-world verifier, not by
    querying the generator on closed dates.
    """
    context = fortnight.context
    digest = context.schedule_generation_policy_hash
    assert digest is not None
    policy = ScheduleGenerationPolicyV1.model_validate_json(
        context.supporting_artifacts[digest].data
    )
    open_query = next(
        query
        for query, _ in fortnight.reconstruction_replay.requests
        if query.session_date == date(2026, 1, 9)
    )
    assert generate_schedule(open_query, context, policy).classification == (
        "generated"
    )
    closed_query = open_query.model_copy(update={"session_date": date(2026, 1, 10)})
    artifact = generate_schedule(closed_query, context, policy)
    assert artifact.classification == "indeterminate"
    assert artifact.reasons == ("generation_policy_methodology_set_mismatch",)
    assert all(row.output.utc_open is None for row in artifact.rows)


def test_a_weekday_absent_from_the_calendar_is_an_evidenced_non_trading_day(
    tmp_path: Path,
) -> None:
    intake = _intake(tmp_path, HOLIDAY_FORTNIGHT)
    closed = tuple(
        row.session_key.local_date for row in _rows(intake) if row.state == "closed"
    )
    assert closed == (*WEEKEND, date(2026, 1, 14))
    assert len(intake.session_clock.sessions) == len(HOLIDAY_FORTNIGHT)


def test_a_trailing_weekend_in_the_request_stays_indeterminate(tmp_path: Path) -> None:
    """D2-b: dates past the last returned session are never read as closed."""
    intake = _intake(tmp_path, FORTNIGHT, end=date(2026, 1, 18))
    coverage = intake.closed_world_coverage
    assert coverage.requested_end_date == date(2026, 1, 18)
    assert coverage.covered_end_date == date(2026, 1, 16)
    for day in (date(2026, 1, 17), date(2026, 1, 18)):
        assert evidenced_session_date_status((coverage,), "XNAS", day) == (
            "indeterminate"
        )
        assert all(row.session_key.local_date != day for row in _rows(intake))


def test_the_engine_evaluates_a_covered_fortnight_to_completion(
    fortnight: AlpacaExploratoryIntakeResult,
) -> None:
    engine = _engine(fortnight)
    artifacts = engine.run(
        strategy=ReconstructedTargetStrategy({}),
        run_identity=_run_identity(
            admission=engine.admission,
            bundle=engine.bundle,
            protocol=engine.protocol,
            cost_model=engine.cost_model,
            evidence_hash=engine.evaluator_evidence_hash,
        ),
    )
    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert artifacts.result.is_promotion_grade_evidence is False


# --- acceptance 2: INDETERMINATE fails closed ----------------------------------------


def test_an_uncovered_fortnight_is_refused_at_intake_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1 and D6-a: an unpublished closed-world basis leaves the weekend unknown."""
    monkeypatch.setitem(
        _POLICY_DOCUMENTS["alpaca-calendar-closed-world"],
        "provider_publication",
        "not_published",
    )
    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        _intake(tmp_path / "fortnight", FORTNIGHT)
    message = str(error.value)
    assert "INDETERMINATE" in message
    assert "2026-01-10" in message and "2026-01-11" in message
    assert "2026-01-09" not in message and "2026-01-12" not in message
    # Without a gap nothing needs the basis, so a single week still passes.
    week = FORTNIGHT[:5]
    assert len(_intake(tmp_path / "week", week).session_clock.sessions) == 5


def test_a_calendar_row_outside_the_requested_window_is_refused_by_name(
    tmp_path: Path,
) -> None:
    """M1: an out-of-window row may not widen coverage."""
    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        _intake(
            tmp_path,
            FORTNIGHT,
            calendar_days=(*FORTNIGHT, date(2026, 1, 20)),
        )
    assert "2026-01-20" in str(error.value)
    assert "outside the requested window" in str(error.value)


def test_the_engine_refuses_a_clock_that_skips_a_scheduled_open_date(
    fortnight: AlpacaExploratoryIntakeResult,
) -> None:
    """R7 and M10: a hand-built bundle cannot drop a trading date."""
    dropped = date(2026, 1, 7)
    requests = tuple(
        (query, context)
        for query, context in fortnight.reconstruction_replay.requests
        if query.session_date != dropped
    )
    replay = ExploratoryReconstructionReplay(
        policy=fortnight.reconstruction_policy, requests=requests
    )
    clock = build_scheduled_reconstruction_clock(
        tuple(query for query, _ in requests if query.security_id == AAPL_ID),
        fortnight.context,
    )
    first, last = clock.sessions[0], clock.sessions[-1]
    bundle = build_evaluation_input_bundle(
        evaluation_interval=TemporalIntervalClaimV1(
            schema_version="1",
            start=_exact_boundary(first.opened_at, "a" * 64, "test:start"),
            end=_exact_boundary(last.closed_at, "a" * 64, "test:end"),
        ),
        session_clock=clock,
        context=fortnight.context,
        security_identities=fortnight.securities,
        listing_identities=fortnight.listings,
        exploratory_cohort=fortnight.cohort,
        exploratory_reconstruction_replay=replay,
        dataset_limitations=fortnight.bundle.dataset_limitations,
    )
    with pytest.raises(IndeterminateExecutionError) as error:
        _engine(fortnight, bundle=bundle, replay=replay)
    assert "XNAS 2026-01-07 (scheduled_open)" in str(error.value)


def test_the_engine_refuses_a_clock_across_an_uncovered_gap() -> None:
    """R7 and D6-c: a gap no closed-world record evidences halts INDETERMINATE."""
    with pytest.raises(IndeterminateExecutionError) as error:
        reconstructed_engine(
            bundle_of((scheduled_session_case(JAN5), scheduled_session_case(JAN7)))
        )
    assert "XNYS 2026-01-06 (indeterminate)" in str(error.value)
    # Control: the same sessions with no gap between them are admitted.
    reconstructed_engine(
        bundle_of(
            (
                scheduled_session_case(JAN5),
                scheduled_session_case(JAN6),
                scheduled_session_case(JAN7),
            )
        )
    )


# --- acceptance 3: integrity failures are refused by code ---------------------------


def _context_with_support(
    context: M1dResolutionContext,
    update: dict[str, VerifiedArtifactBytes | None],
) -> M1dResolutionContext:
    support = dict(context.supporting_artifacts)
    for key, value in update.items():
        if value is None:
            support.pop(key, None)
        else:
            support[key] = value
    return replace(context, supporting_artifacts=support)


def _refusal(context: M1dResolutionContext) -> ClosedWorldCoverageError:
    with pytest.raises(ClosedWorldCoverageError) as error:
        verify_closed_world_session_coverage(context)
    return error.value


def _code(context: M1dResolutionContext) -> str:
    return _refusal(context).code


def _expansion_mismatch(context: M1dResolutionContext, detail: str) -> None:
    refusal = _refusal(context)
    assert refusal.code == "closed_world_expansion_mismatch"
    assert detail in str(refusal)


def test_the_verifier_returns_exactly_the_bridge_record(
    fortnight: AlpacaExploratoryIntakeResult,
) -> None:
    assert verify_closed_world_session_coverage(fortnight.context) == (
        fortnight.closed_world_coverage,
    )


def test_swapped_response_bytes_of_the_same_length_are_refused(
    fortnight: AlpacaExploratoryIntakeResult,
) -> None:
    """V4 and M2."""
    coverage = fortnight.closed_world_coverage
    original = fortnight.context.supporting_artifacts[coverage.response_sha256].data
    swapped = original.replace(b"2026-01-05", b"2026-01-04", 1)
    assert len(swapped) == len(original) and swapped != original
    forged = VerifiedArtifactBytes(
        data=swapped, byte_size=len(swapped), content_hash=coverage.response_sha256
    )
    context = _context_with_support(
        fortnight.context, {coverage.response_sha256: forged}
    )
    assert _code(context) == "closed_world_response_hash_mismatch"


@pytest.mark.parametrize(
    ("field", "code"),
    (
        ("response_sha256", "closed_world_response_bytes_unavailable"),
        ("request_binding_hash", "closed_world_request_binding_mismatch"),
        ("origin_observation_hash", "closed_world_origin_unavailable"),
        ("policy", "closed_world_policy_statement_unavailable"),
    ),
)
def test_every_bound_artifact_must_be_retained_in_the_context(
    fortnight: AlpacaExploratoryIntakeResult, field: str, code: str
) -> None:
    coverage = fortnight.closed_world_coverage
    digest = (
        coverage.completeness.policy_statement_hash
        if field == "policy"
        else getattr(coverage, field)
    )
    context = _context_with_support(fortnight.context, {digest: None})
    assert _code(context) == code


def test_a_record_under_another_m1d_identity_is_refused(
    fortnight: AlpacaExploratoryIntakeResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    """V10: the record binds the m1d-evidence-v1 identity it was derived under."""
    monkeypatch.setattr(
        "drift.markets.session_closed_world.m1d_implementation_hash",
        lambda: "0" * 64,
    )
    assert _code(fortnight.context) == "closed_world_implementation_identity_mismatch"


def _resealed_row(
    row: ScheduledSessionVersionV1,
    fields: dict[str, Any] | None = None,
    **revision: Any,
) -> ScheduledSessionVersionV1:
    """The row with ``fields`` and ``revision`` changed, its payload re-sealed."""
    values = {name: getattr(row, name) for name in type(row).model_fields}
    values |= fields or {}
    values["revision"] = row.revision.model_copy(update=revision)
    provisional = ScheduledSessionVersionV1.model_construct(**values)
    values["revision"] = values["revision"].model_copy(
        update={"payload_hash": content_hash(assertion_version_payload(provisional))}
    )
    return ScheduledSessionVersionV1.model_validate(values)


def _reference(digest: str) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=UUID("019b8240-0000-7000-8000-000000000999"),
        kind=ArtifactKind.OTHER,
        content_hash=digest,
        location=f"drift+sha256://{digest}",
    )


def _with_rows(
    intake: AlpacaExploratoryIntakeResult,
    transform: Callable[[tuple[ScheduledSessionVersionV1, ...]], tuple[Any, ...]],
    *,
    support: dict[str, VerifiedArtifactBytes | None] | None = None,
) -> M1dResolutionContext:
    scheduled = _scheduled(intake)
    changed = M1dDatasetInput(
        manifest=scheduled.manifest,
        validation_run=scheduled.validation_run,
        artifacts=scheduled.artifacts,
        records=transform(_rows(intake)),
        decision=scheduled.decision,
        bundle=scheduled.bundle,
    )
    context = replace(
        intake.context,
        session_datasets=tuple(
            changed if item is scheduled else item
            for item in intake.context.session_datasets
        ),
    )
    return _context_with_support(context, support or {})


def test_a_closed_row_rebound_to_the_raw_calendar_bytes_is_refused(
    fortnight: AlpacaExploratoryIntakeResult,
) -> None:
    """V8 and M9: a closed row names the record, never the provider bytes."""
    raw = fortnight.closed_world_coverage.response_sha256

    def rebind(rows: tuple[ScheduledSessionVersionV1, ...]) -> tuple[Any, ...]:
        return tuple(
            _resealed_row(row, source_artifact=_reference(raw))
            if row.state == "closed"
            else row
            for row in rows
        )

    _expansion_mismatch(
        _with_rows(fortnight, rebind),
        "the closed schedule rows over the covered interval are not exactly the "
        "record's expansion",
    )


def test_a_closed_row_bound_to_a_different_record_is_refused(
    fortnight: AlpacaExploratoryIntakeResult,
) -> None:
    """V8 and M9: a record no coverage row of this context expands is refused."""
    other = seal_closed_world_session_coverage(
        fortnight.closed_world_coverage.model_dump(mode="python")
        | {"response_byte_size": fortnight.closed_world_coverage.response_byte_size + 1}
    )
    other_bytes = closed_world_record_bytes(other)
    other_digest = sha256(other_bytes).hexdigest()

    def rebind(rows: tuple[ScheduledSessionVersionV1, ...]) -> tuple[Any, ...]:
        return tuple(
            _resealed_row(row, source_artifact=_reference(other_digest))
            if row.state == "closed"
            else row
            for row in rows
        )

    context = _with_rows(
        fortnight,
        rebind,
        support={
            other_digest: VerifiedArtifactBytes(
                data=other_bytes, byte_size=len(other_bytes), content_hash=other_digest
            )
        },
    )
    _expansion_mismatch(
        context,
        "the closed schedule rows over the covered interval are not exactly the "
        "record's expansion",
    )


_NOT_THE_EXPANSION = (
    "the closed schedule rows over the covered interval are not exactly the "
    "record's expansion"
)
_NOT_THE_RETURNED_DATES = (
    "the open schedule rows over the covered interval are not exactly the "
    "returned dates"
)
_UNACCOUNTED_ROW = "no coverage row of this context expands to it"


@pytest.mark.parametrize(
    ("mutation", "detail"),
    (
        ("dropped", _NOT_THE_EXPANSION),
        ("duplicated-date", _NOT_THE_EXPANSION),
        ("open-on-weekend", _NOT_THE_RETURNED_DATES),
        ("open-dropped", _NOT_THE_RETURNED_DATES),
        ("closed-past-hull", _UNACCOUNTED_ROW),
    ),
)
def test_the_scheduled_rows_must_equal_the_expansion_exactly(
    fortnight: AlpacaExploratoryIntakeResult, mutation: str, detail: str
) -> None:
    """V8: exactly the expansion's closed rows and exactly the returned open rows."""

    def transform(rows: tuple[ScheduledSessionVersionV1, ...]) -> tuple[Any, ...]:
        closed = [row for row in rows if row.state == "closed"]
        opened = [row for row in rows if row.state != "closed"]
        if mutation == "dropped":
            return (*opened, *closed[1:])
        if mutation == "open-dropped":
            # A returned date loses its open row; the closed rows are intact.
            return (
                *(row for row in opened if row.session_key.local_date != JAN7),
                *closed,
            )
        if mutation == "duplicated-date":
            # A second, record-bound closed row on a returned (open) date.
            template = closed[0]
            forged = _resealed_row(
                template,
                {
                    "session_key": template.session_key.model_copy(
                        update={"local_date": date(2026, 1, 9)}
                    )
                },
            )
            return (*rows, forged)
        if mutation == "closed-past-hull":
            # A record-bound closed row on a date the record never covers.
            template = closed[-1]
            forged = _resealed_row(
                template,
                {
                    "session_key": template.session_key.model_copy(
                        update={"local_date": date(2026, 1, 17)}
                    )
                },
            )
            return (*rows, forged)
        # A Friday open row copied onto Saturday in place of its closed row.
        friday = next(
            row for row in opened if row.session_key.local_date == date(2026, 1, 9)
        )
        saturday = _resealed_row(
            friday,
            {
                "session_key": friday.session_key.model_copy(
                    update={"local_date": date(2026, 1, 10)}
                ),
                "local_open": "2026-01-10T09:30:00",
                "local_close": "2026-01-10T16:00:00",
            },
        )
        return (*opened, saturday, *closed[1:])

    with pytest.raises(ClosedWorldCoverageError) as error:
        verify_closed_world_session_coverage(_with_rows(fortnight, transform))
    assert error.value.code == "closed_world_expansion_mismatch"
    assert detail in str(error.value)


def test_a_coverage_row_wider_than_the_record_is_refused(
    fortnight: AlpacaExploratoryIntakeResult,
) -> None:
    """V8 and the widened-hull mutation at the coverage level."""
    coverage = _coverage_dataset(fortnight)
    (row,) = coverage.records
    values = {name: getattr(row, name) for name in type(row).model_fields}
    values["end_date"] = date(2026, 1, 18)
    provisional = SessionCoverageVersionV1.model_construct(**values)
    values["revision"] = row.revision.model_copy(
        update={"payload_hash": content_hash(assertion_version_payload(provisional))}
    )
    widened = SessionCoverageVersionV1.model_validate(values)
    changed: M1dDatasetInput[Any] = M1dDatasetInput(
        manifest=coverage.manifest,
        validation_run=coverage.validation_run,
        artifacts=coverage.artifacts,
        records=(widened,),
        decision=coverage.decision,
        bundle=coverage.bundle,
    )
    context = replace(
        fortnight.context,
        session_datasets=tuple(
            changed if item is coverage else item
            for item in fortnight.context.session_datasets
        ),
    )
    _expansion_mismatch(
        context,
        "the coverage row does not cover exactly the record's covered interval",
    )


# --- bridge-side checks (V5, V6) ----------------------------------------------------


def _resealed(
    record: ClosedWorldSessionCoverageV1, **update: Any
) -> ClosedWorldSessionCoverageV1:
    return seal_closed_world_session_coverage(record.model_dump(mode="python") | update)


@pytest.mark.parametrize(
    ("update", "code"),
    (
        (
            {"returned_dates": tuple(day for day in FORTNIGHT if day.day != 7)},
            "closed_world_returned_dates_disagree_with_response",
        ),
        (
            {"requested_end_date": date(2026, 1, 18)},
            "closed_world_request_binding_mismatch",
        ),
        ({"request_binding_hash": "1" * 64}, "closed_world_request_binding_mismatch"),
        ({"response_sha256": "2" * 64}, "closed_world_response_hash_mismatch"),
        ({"response_byte_size": 1}, "closed_world_response_hash_mismatch"),
        ({"origin_observation_hash": "3" * 64}, "closed_world_origin_mismatch"),
    ),
    ids=(
        "returned-dates",
        "requested-interval",
        "request-binding",
        "response-bytes",
        "response-size",
        "origin",
    ),
)
def test_the_bridge_refuses_a_record_disagreeing_with_its_acquisition(
    fortnight: AlpacaExploratoryIntakeResult, update: dict[str, Any], code: str
) -> None:
    """V5, V6 and M4: the record must describe exactly what was acquired."""
    genuine = fortnight.closed_world_coverage
    request, _payloads_used = _inputs(FORTNIGHT)
    # Control: the genuine record passes the same bridge-side checks.
    verify_alpaca_closed_world_record(
        genuine, request, fortnight.retained, fortnight.acquisition
    )
    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        verify_alpaca_closed_world_record(
            _resealed(genuine, **update),
            request,
            fortnight.retained,
            fortnight.acquisition,
        )
    assert str(error.value).startswith(code)


# --- grade, lane and limitation (D3-a, R8, acceptance 7) ------------------------------


def test_the_admission_acknowledges_the_closed_world_reading(
    fortnight: AlpacaExploratoryIntakeResult,
) -> None:
    assert (
        ALPACA_LIMITATION_CALENDAR_CLOSED_WORLD
        == "calendar-absence-read-as-closure-under-closed-world-assumption"
    )
    assert ALPACA_LIMITATION_CALENDAR_CLOSED_WORLD in ALPACA_EXPLORATORY_LIMITATIONS
    assert ALPACA_LIMITATION_CALENDAR_CLOSED_WORLD in (
        fortnight.admission.acknowledged_limitations
    )
    assert ALPACA_LIMITATION_CALENDAR_CLOSED_WORLD in (
        fortnight.bundle.dataset_limitations
    )
    omitted = tuple(
        item
        for item in ALPACA_EXPLORATORY_LIMITATIONS
        if item != ALPACA_LIMITATION_CALENDAR_CLOSED_WORLD
    )
    with pytest.raises(ValueError, match="omits required bundle limitations"):
        _engine(fortnight, admission=hand_minted_admission(fortnight.bundle, omitted))


def test_no_promotion_consumer_accepts_closed_world_evidence(
    fortnight: AlpacaExploratoryIntakeResult,
) -> None:
    """R8: exploratory in, exploratory out; the promotion lane refuses it."""
    with pytest.raises(AlpacaBridgeProhibitedError):
        build_bridge_admission(bundle=fortnight.bundle, lane="promotion")
    with pytest.raises(PromotionLaneDisabledError):
        _engine(fortnight, admission=promotion_admission(fortnight.bundle))
    grade: object = ClosedWorldSessionCoverageV1.model_fields[
        "evidence_grade"
    ].annotation
    assert grade == Literal["exploratory"]


def test_coverage_is_schedule_evidence_only(
    fortnight: AlpacaExploratoryIntakeResult,
) -> None:
    """D7-a: no realized session is ever minted from calendar coverage."""
    roles = {
        item.manifest.dataset_role.name for item in fortnight.context.session_datasets
    }
    assert roles == {"scheduled_session", "session_coverage"}
    assert fortnight.session_clock.mode == "scheduled_session_reconstruction"


def test_a_bar_on_an_evidenced_non_trading_date_is_refused(tmp_path: Path) -> None:
    """D7-a and R5: a bar on an evidenced closed date is a conflict, never a session.

    The calendar omits Saturday 2026-01-10 inside the covered hull, so it is an
    evidenced non-trading date with an explicit closed row. A bar dated on it
    contradicts that evidence; the bridge refuses the window rather than read
    the closed row as an open session or drop the bar.
    """
    saturday = date(2026, 1, 10)
    with pytest.raises(AlpacaBridgeIncompleteError) as error:
        _intake(
            tmp_path,
            tuple(sorted((*FORTNIGHT, saturday))),
            calendar_days=FORTNIGHT,
        )
    assert str(error.value) == "bar for AAPL on 2026-01-10 has no scheduled session"


# --- acceptance 5: no broker, order or trading surface -------------------------------


def test_the_bridge_still_declares_exactly_three_get_endpoints() -> None:
    assert tuple((key, host, route) for key, host, route in _OBJECT_ENDPOINTS) == (
        ("alpaca-historical-bars", "data.alpaca.markets", "/v2/stocks/bars"),
        (CALENDAR_OBJECT_KEY, ALPACA_PAPER_TRADING_HOST, "/v2/calendar"),
        ("alpaca-corporate-actions", "data.alpaca.markets", "/v1/corporate-actions"),
    )
    assert ALPACA_CALENDAR_SOURCE_ID == "alpaca-market-calendar-v2"
    assert_core_isolation()


@pytest.mark.parametrize(
    "path",
    (
        "src/drift/domain/session_closed_world.py",
        "src/drift/markets/session_closed_world.py",
    ),
)
def test_the_closed_world_modules_import_no_transport_process_or_adapter(
    path: str,
) -> None:
    tree = ast.parse((REPO_ROOT / path).read_bytes())
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module)
    forbidden = {
        "http",
        "socket",
        "ssl",
        "subprocess",
        "urllib",
        "requests",
        "httpx",
        "drift.adapters",
        "drift.evaluator",
    }
    assert not {
        root for root in roots if any(root.startswith(item) for item in forbidden)
    }


def test_the_weekend_after_the_hull_changes_nothing_when_the_record_is_resealed(
    fortnight: AlpacaExploratoryIntakeResult,
) -> None:
    """A widened hull cannot be sealed: the domain refuses the D2-b violation."""
    with pytest.raises(ValueError, match="closed_world_interval_invalid"):
        _resealed(
            fortnight.closed_world_coverage,
            covered_end_date=fortnight.closed_world_coverage.covered_end_date
            + timedelta(days=2),
        )
