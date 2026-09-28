"""Unit tests for M1c closed-world corporate-action coverage (issue 76).

The owner ruling on #76 (option A) requires a held or traded security to carry
a closed-world, evidence-bearing corporate-action coverage record over the
evaluation interval: the requested interval, the retained provider response,
a completeness assertion and the returned actions. These tests hold the record
itself to that contract, with no provider and no evaluator in the loop. Every
check is an integrity check, refused with its contract code in the message.
"""

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.assertions import BoundaryShape, TemporalBoundaryClaimV1
from drift.domain.economic_closed_world import (
    CORPORATE_ACTION_COVERAGE_DOMAIN_CODES,
    CORPORATE_ACTION_POSITIVE_BASES,
    CORPORATE_ACTION_SNAPSHOT_LIMITATION,
    REST_CORPORATE_ACTION_EVIDENCE_FLOOR,
    ClosedWorldCorporateActionCoverageV1,
    CorporateActionCompletenessAssertionV1,
    ReturnedCorporateActionV1,
    corporate_action_covered_interval,
    corporate_action_derivation_algorithm_hash,
    corporate_action_record_hash,
)
from drift.domain.economic_common import ActionKind
from drift.domain.evaluator_lanes import LIMITATION_CA_ABSENCE_FROM_CURRENT_SNAPSHOT
from drift.domain.temporal import SourcePrecision

REPO_ROOT = Path(__file__).resolve().parents[2]
SECURITY = UUID("019b8240-0000-7000-8000-000000000101")
SOURCE = "synthetic-corporate-actions-v1"
REQUESTED_START = date(2026, 1, 5)
REQUESTED_END = date(2026, 1, 16)
SNAPSHOT = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _reference(digest: str) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=UUID("019b8240-0000-7000-8000-000000000901"),
        kind=ArtifactKind.OTHER,
        content_hash=digest,
        location=f"drift+sha256://{digest}",
    )


def _snapshot(instant: datetime = SNAPSHOT) -> TemporalBoundaryClaimV1:
    return TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.EXACT,
        lower_bound=instant,
        upper_bound=instant,
        source_precision=SourcePrecision.SECOND,
        source_time_label=instant.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_timezone=None,
        evidence_reference=_reference("a" * 64),
    )


def _assertion(**overrides: Any) -> CorporateActionCompletenessAssertionV1:
    values: dict[str, Any] = {
        "schema_version": "1",
        "basis": "provider_partially_published",
        "policy_statement_hash": "b" * 64,
        "acquisition_reconciliation_pass": True,
        "single_unpaginated_response": True,
        "measured_origin": True,
        "requested_types_documented": True,
        "returned_actions_attributed": True,
        "returned_actions_inside_requested_window": True,
    }
    values.update(overrides)
    return CorporateActionCompletenessAssertionV1.model_validate(values)


def _action(
    native_id: str = "ca-1",
    *,
    native_kind: str = "forward_splits",
    action_kind: ActionKind | None = ActionKind.FORWARD_SPLIT,
    dates: tuple[date, ...] = (date(2026, 1, 8),),
) -> ReturnedCorporateActionV1:
    return ReturnedCorporateActionV1(
        native_kind=native_kind,
        native_id=native_id,
        action_kind=action_kind,
        dates=dates,
    )


def _values(**overrides: Any) -> dict[str, Any]:
    snapshot = overrides.pop("snapshot_as_of", _snapshot())
    start = overrides.pop("requested_start_date", REQUESTED_START)
    end = overrides.pop("requested_end_date", REQUESTED_END)
    covered = corporate_action_covered_interval(start, end, snapshot)
    values: dict[str, Any] = {
        "schema_version": "1",
        "source_id": SOURCE,
        "security_id": SECURITY,
        "queried_symbol": "AAPL",
        "requested_start_date": start,
        "requested_end_date": end,
        "requested_action_classes": ("cash_dividend", "forward_split"),
        "request_binding_hash": "c" * 64,
        "response_sha256": "d" * 64,
        "response_byte_size": 120,
        "origin_observation_hash": "e" * 64,
        "returned_actions": (),
        "completeness": _assertion(),
        "covered_start_date": None if covered is None else covered[0],
        "covered_end_date": None if covered is None else covered[1],
        "snapshot_as_of": snapshot,
        "revision_support": "current_only",
        "evidence_grade": "exploratory",
        "acknowledged_limitations": (CORPORATE_ACTION_SNAPSHOT_LIMITATION,),
        "derivation_algorithm_hash": corporate_action_derivation_algorithm_hash(),
        "implementation_hash": "f" * 64,
    }
    values.update(overrides)
    return values


def _sealed(values: dict[str, Any]) -> ClosedWorldCorporateActionCoverageV1:
    """Seal ``values`` under their own record hash and validate the result."""
    body = {key: value for key, value in values.items() if key != "record_hash"}
    draft = ClosedWorldCorporateActionCoverageV1.model_construct(
        **(body | {"record_hash": "0" * 64})
    )
    return ClosedWorldCorporateActionCoverageV1.model_validate(
        body | {"record_hash": corporate_action_record_hash(draft)}
    )


def _record(**overrides: Any) -> ClosedWorldCorporateActionCoverageV1:
    return _sealed(_values(**overrides))


def _refused(code: str, **overrides: Any) -> None:
    with pytest.raises(ValidationError, match=re.escape(code)):
        _record(**overrides)


# --- the record -----------------------------------------------------------------


def test_a_quiet_response_record_covers_its_requested_interval() -> None:
    record = _record()
    assert (record.covered_start_date, record.covered_end_date) == (
        REQUESTED_START,
        REQUESTED_END,
    )
    assert record.evidence_grade == "exploratory"
    assert record.revision_support == "current_only"
    assert record.completeness.positive
    assert record.record_hash == corporate_action_record_hash(record)


def test_the_record_hash_covers_every_field() -> None:
    record = _record()
    fields = dict(record)
    for name, changed in (
        ("queried_symbol", "MSFT"),
        ("returned_actions", (_action(),)),
        ("response_sha256", "9" * 64),
        ("implementation_hash", "8" * 64),
    ):
        moved = ClosedWorldCorporateActionCoverageV1.model_construct(
            **(fields | {name: changed})
        )
        assert corporate_action_record_hash(moved) != record.record_hash, name
    unmoved = ClosedWorldCorporateActionCoverageV1.model_construct(
        **(fields | {"record_hash": "7" * 64})
    )
    assert corporate_action_record_hash(unmoved) == record.record_hash


def test_v1_a_record_whose_hash_does_not_cover_it_is_refused() -> None:
    values = _values()
    good = _sealed(values)
    with pytest.raises(ValidationError, match="ca_coverage_record_hash_mismatch"):
        ClosedWorldCorporateActionCoverageV1.model_validate(
            good.model_dump() | {"queried_symbol": "MSFT"}
        )
    # Control: the untouched dump rebuilds.
    assert ClosedWorldCorporateActionCoverageV1.model_validate(good.model_dump())


# --- V2: the covered interval ----------------------------------------------------


def test_v2_the_covered_interval_is_exactly_the_requested_interval_d2a() -> None:
    _refused(
        "ca_coverage_interval_invalid",
        covered_start_date=REQUESTED_START - timedelta(days=1),
    )
    _refused(
        "ca_coverage_interval_invalid",
        covered_end_date=REQUESTED_END + timedelta(days=1),
    )
    # Narrower is refused too: D2 (a) states the requested interval exactly.
    _refused(
        "ca_coverage_interval_invalid",
        covered_start_date=REQUESTED_START + timedelta(days=1),
    )
    _refused("ca_coverage_interval_invalid", covered_end_date=None)
    _refused(
        "ca_coverage_interval_invalid",
        covered_start_date=None,
        covered_end_date=None,
    )


def test_v2_a_reversed_requested_interval_is_refused() -> None:
    with pytest.raises(ValidationError, match="ca_coverage_interval_invalid"):
        _sealed(
            _values()
            | {
                "requested_start_date": REQUESTED_END,
                "requested_end_date": REQUESTED_START,
                "covered_start_date": None,
                "covered_end_date": None,
            }
        )


def test_v2_the_covered_interval_never_passes_the_snapshot_date() -> None:
    early = datetime(2026, 1, 10, 15, 0, tzinfo=UTC)
    record = _record(snapshot_as_of=_snapshot(early))
    assert (record.covered_start_date, record.covered_end_date) == (
        REQUESTED_START,
        date(2026, 1, 10),
    )
    with pytest.raises(ValidationError, match="ca_coverage_interval_invalid"):
        _sealed(
            _values(snapshot_as_of=_snapshot(early))
            | {"covered_end_date": REQUESTED_END}
        )


def test_v2_the_covered_interval_never_starts_before_the_evidence_floor() -> None:
    floor = REST_CORPORATE_ACTION_EVIDENCE_FLOOR
    start = floor - timedelta(days=10)
    end = floor + timedelta(days=10)
    record = _record(requested_start_date=start, requested_end_date=end)
    assert (record.covered_start_date, record.covered_end_date) == (floor, end)
    with pytest.raises(ValidationError, match="ca_coverage_interval_invalid"):
        _sealed(
            _values(requested_start_date=start, requested_end_date=end)
            | {"covered_start_date": start}
        )


def test_v2_a_request_wholly_before_the_floor_covers_nothing() -> None:
    floor = REST_CORPORATE_ACTION_EVIDENCE_FLOOR
    start = floor - timedelta(days=30)
    end = floor - timedelta(days=1)
    record = _record(requested_start_date=start, requested_end_date=end)
    assert (record.covered_start_date, record.covered_end_date) == (None, None)
    with pytest.raises(ValidationError, match="ca_coverage_interval_invalid"):
        _sealed(
            _values(requested_start_date=start, requested_end_date=end)
            | {"covered_start_date": start, "covered_end_date": end}
        )


def test_the_covered_interval_rule_is_the_clipped_requested_interval() -> None:
    snapshot = _snapshot()
    floor = REST_CORPORATE_ACTION_EVIDENCE_FLOOR
    assert corporate_action_covered_interval(
        REQUESTED_START, REQUESTED_END, snapshot
    ) == (REQUESTED_START, REQUESTED_END)
    assert corporate_action_covered_interval(
        floor - timedelta(days=1), floor, snapshot
    ) == (floor, floor)
    assert (
        corporate_action_covered_interval(
            floor - timedelta(days=2), floor - timedelta(days=1), snapshot
        )
        is None
    )
    late = SNAPSHOT.date() + timedelta(days=1)
    assert (
        corporate_action_covered_interval(late, late + timedelta(days=3), snapshot)
        is None
    )


def test_the_evidence_floor_is_the_earliest_rest_date_the_provider_record_cites() -> (
    None
):
    """D2 addition: a named constant, cited from the provider-selection record.

    The earliest action date the repository evidences a REST corporate-action
    response returning is the GE 1-for-8 reverse split, ex date 2021-08-02.
    The SSE mutation stream's 2026-07-09 floor is knowledge time, not event
    coverage, and does not bound it.
    """
    assert date(2021, 8, 2) == REST_CORPORATE_ACTION_EVIDENCE_FLOOR
    text = (REPO_ROOT / "docs/architecture/m1e-provider-selection.md").read_text(
        encoding="utf-8"
    )
    start = text.index("- **Rich Corporate Actions REST**")
    end = text.index("- **Point-in-Time Symbology", start)
    section = text[start:end]
    cited = sorted(
        date.fromisoformat(match) for match in re.findall(r"\d{4}-\d{2}-\d{2}", section)
    )
    assert cited[0] == REST_CORPORATE_ACTION_EVIDENCE_FLOOR
    assert "GE 1-for-8 split" in section and "`ex_date: 2021-08-02`" in section


# --- V3: returned actions --------------------------------------------------------


def test_v3_returned_actions_are_sorted_and_unique_by_kind_and_id() -> None:
    first, second = _action("ca-1"), _action("ca-2")
    assert _record(returned_actions=(first, second)).returned_actions == (
        first,
        second,
    )
    _refused("ca_coverage_returned_actions_invalid", returned_actions=(second, first))
    _refused("ca_coverage_returned_actions_invalid", returned_actions=(first, first))
    other_kind = _action("ca-1", native_kind="cash_dividends", action_kind=None)
    # One id in two groups is two actions.
    assert _record(returned_actions=(other_kind, first)).returned_actions


def test_v3_returned_action_dates_are_sorted_unique_and_may_be_empty() -> None:
    assert _action(dates=()).dates == ()
    with pytest.raises(ValidationError, match="ca_coverage_returned_actions_invalid"):
        _action(dates=(date(2026, 1, 9), date(2026, 1, 8)))
    with pytest.raises(ValidationError, match="ca_coverage_returned_actions_invalid"):
        _action(dates=(date(2026, 1, 8), date(2026, 1, 8)))


# --- V7: the grade follows the source --------------------------------------------


def test_v7_a_grade_above_the_source_is_refused() -> None:
    _refused("ca_coverage_grade_exceeds_source", evidence_grade="promotion")
    _refused("ca_coverage_grade_exceeds_source", revision_support="captured_history")


# --- V8: requested action classes ------------------------------------------------


def test_v8_requested_action_classes_are_nonempty_sorted_and_unique() -> None:
    _refused("ca_coverage_action_classes_incomplete", requested_action_classes=())
    _refused(
        "ca_coverage_action_classes_incomplete",
        requested_action_classes=("forward_split", "cash_dividend"),
    )
    _refused(
        "ca_coverage_action_classes_incomplete",
        requested_action_classes=("cash_dividend", "cash_dividend"),
    )


# --- remaining record integrity --------------------------------------------------


def test_the_snapshot_is_the_exact_acquisition_instant() -> None:
    bounded = TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.BOUNDED,
        lower_bound=SNAPSHOT - timedelta(hours=1),
        upper_bound=SNAPSHOT,
        source_precision=SourcePrecision.SECOND,
        source_time_label="2026-09-20T12:00:00Z",
        source_timezone=None,
        evidence_reference=_reference("a" * 64),
    )
    _refused("ca_coverage_snapshot_invalid", snapshot_as_of=bounded)


def test_a_record_naming_another_derivation_rule_is_refused() -> None:
    _refused("ca_coverage_derivation_mismatch", derivation_algorithm_hash="9" * 64)


def test_every_record_acknowledges_the_snapshot_limitation() -> None:
    _refused("ca_coverage_limitations_invalid", acknowledged_limitations=())
    _refused(
        "ca_coverage_limitations_invalid",
        acknowledged_limitations=("some-other-limitation",),
    )
    _refused(
        "ca_coverage_limitations_invalid",
        acknowledged_limitations=(
            CORPORATE_ACTION_SNAPSHOT_LIMITATION,
            "another-limitation",
        ),
    )
    extra = tuple(sorted((CORPORATE_ACTION_SNAPSHOT_LIMITATION, "another-limitation")))
    assert _record(acknowledged_limitations=extra).acknowledged_limitations == extra


def test_the_limitation_constant_is_the_one_evaluator_lanes_names() -> None:
    assert CORPORATE_ACTION_SNAPSHOT_LIMITATION == (
        "corporate-action-absence-read-from-current-provider-snapshot"
    )
    assert LIMITATION_CA_ABSENCE_FROM_CURRENT_SNAPSHOT == (
        CORPORATE_ACTION_SNAPSHOT_LIMITATION
    )


def test_every_domain_code_is_a_ca_coverage_code() -> None:
    assert CORPORATE_ACTION_COVERAGE_DOMAIN_CODES == tuple(
        sorted(CORPORATE_ACTION_COVERAGE_DOMAIN_CODES)
    )
    assert all(
        code.startswith("ca_coverage_")
        for code in CORPORATE_ACTION_COVERAGE_DOMAIN_CODES
    )


# --- the completeness assertion --------------------------------------------------


_STRUCTURAL_FLAGS = (
    "single_unpaginated_response",
    "measured_origin",
    "requested_types_documented",
    "returned_actions_attributed",
    "returned_actions_inside_requested_window",
)


def test_an_assertion_is_positive_only_when_every_check_and_the_basis_hold() -> None:
    assert _assertion().positive
    for flag in _STRUCTURAL_FLAGS:
        assert not _assertion(**{flag: False}).positive, flag
    assert not _assertion(basis="drift_asserted_unpublished").positive
    assert _assertion(basis="provider_published").positive
    assert frozenset({"provider_published", "provider_partially_published"}) == (
        CORPORATE_ACTION_POSITIVE_BASES
    )


def test_an_assertion_requires_a_passing_reconciliation() -> None:
    with pytest.raises(ValidationError):
        _assertion(acquisition_reconciliation_pass=False)


def test_a_non_positive_assertion_is_valid_data() -> None:
    record = _record(completeness=_assertion(requested_types_documented=False))
    assert not record.completeness.positive
    assert record.covered_start_date == REQUESTED_START
