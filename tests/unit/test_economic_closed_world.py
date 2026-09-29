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
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.datasets.resolver import VerifiedArtifactBytes
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
from drift.domain.economic_queries import MarketOutcomeQueryV1
from drift.domain.economic_results import (
    EconomicCoverageResolutionV1,
    EconomicOutcomeResolutionV1,
)
from drift.domain.evaluator_lanes import LIMITATION_CA_ABSENCE_FROM_CURRENT_SNAPSHOT
from drift.domain.semantic_attestation import (
    m1c_corporate_action_coverage_attestation_hash,
)
from drift.domain.temporal import AvailabilityChannelV1, ChannelKind, SourcePrecision
from drift.markets.economic_closed_world import (
    CorporateActionCoverageError,
    build_corporate_action_coverage,
    corporate_action_window_status,
    native_outcome_covers_window,
    native_outcome_is_empty,
    verify_corporate_action_coverage,
    window_returned_actions,
)
from drift.serialization.canonical import content_hash

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


# ==============================================================================
# drift.markets.economic_closed_world: the builder, verification and the rule
# ==============================================================================


def _payload(label: str) -> VerifiedArtifactBytes:
    data = f'{{"synthetic":"{label}"}}'.encode()
    return VerifiedArtifactBytes(
        data=data, byte_size=len(data), content_hash=sha256(data).hexdigest()
    )


RESPONSE = _payload("response")
REQUEST = _payload("request")
ORIGIN = _payload("origin")
POLICY = _payload("policy")


def _support(*artifacts: VerifiedArtifactBytes) -> dict[str, VerifiedArtifactBytes]:
    chosen = artifacts or (RESPONSE, REQUEST, ORIGIN, POLICY)
    return {artifact.content_hash: artifact for artifact in chosen}


def _built(
    *,
    security_id: UUID = SECURITY,
    source_id: str = SOURCE,
    start: date = REQUESTED_START,
    end: date = REQUESTED_END,
    actions: tuple[ReturnedCorporateActionV1, ...] = (),
    completeness: CorporateActionCompletenessAssertionV1 | None = None,
    response: VerifiedArtifactBytes = RESPONSE,
) -> ClosedWorldCorporateActionCoverageV1:
    return build_corporate_action_coverage(
        source_id=source_id,
        security_id=security_id,
        queried_symbol="AAPL",
        requested_start_date=start,
        requested_end_date=end,
        requested_action_classes=("cash_dividend", "forward_split"),
        request_binding_hash=REQUEST.content_hash,
        response_sha256=response.content_hash,
        response_byte_size=response.byte_size,
        origin_observation_hash=ORIGIN.content_hash,
        returned_actions=actions,
        completeness=(
            _assertion(policy_statement_hash=POLICY.content_hash)
            if completeness is None
            else completeness
        ),
        snapshot_as_of=_snapshot(),
    )


def test_the_builder_is_the_one_stamper_of_the_attested_identity() -> None:
    record = _built()
    assert record.implementation_hash == (
        m1c_corporate_action_coverage_attestation_hash()
    )
    assert record.derivation_algorithm_hash == (
        corporate_action_derivation_algorithm_hash()
    )
    assert (record.covered_start_date, record.covered_end_date) == (
        REQUESTED_START,
        REQUESTED_END,
    )
    assert record.acknowledged_limitations == (CORPORATE_ACTION_SNAPSHOT_LIMITATION,)
    assert verify_corporate_action_coverage(record, _support()) == record


def test_the_builder_refuses_an_invalid_record_by_its_code() -> None:
    with pytest.raises(CorporateActionCoverageError) as caught:
        _built(actions=(_action("ca-2"), _action("ca-1")))
    assert caught.value.code == "ca_coverage_returned_actions_invalid"
    with pytest.raises(CorporateActionCoverageError) as reversed_interval:
        _built(start=REQUESTED_END, end=REQUESTED_START)
    assert reversed_interval.value.code == "ca_coverage_interval_invalid"


def test_v10_a_record_derived_under_another_identity_is_refused() -> None:
    record = _built()
    stale = _sealed(dict(record) | {"implementation_hash": "1" * 64})
    with pytest.raises(CorporateActionCoverageError) as caught:
        verify_corporate_action_coverage(stale)
    assert caught.value.code == "ca_coverage_implementation_identity_mismatch"
    assert verify_corporate_action_coverage(record) == record


def test_v1_verification_refuses_a_record_that_does_not_revalidate() -> None:
    record = _built()
    forged = ClosedWorldCorporateActionCoverageV1.model_construct(
        **(dict(record) | {"queried_symbol": "MSFT"})
    )
    with pytest.raises(CorporateActionCoverageError) as caught:
        verify_corporate_action_coverage(forged)
    assert caught.value.code == "ca_coverage_record_hash_mismatch"


def test_v4_the_retained_response_bytes_must_be_present_and_exact() -> None:
    record = _built()
    with pytest.raises(CorporateActionCoverageError) as missing:
        verify_corporate_action_coverage(record, _support(REQUEST, ORIGIN, POLICY))
    assert missing.value.code == "ca_coverage_response_bytes_unavailable"
    # Swapped bytes of the same length, filed under the record's digest.
    swapped = VerifiedArtifactBytes(
        data=RESPONSE.data.replace(b"response", b"RESPONSE"),
        byte_size=RESPONSE.byte_size,
        content_hash=RESPONSE.content_hash,
    )
    assert len(swapped.data) == len(RESPONSE.data)
    support = _support() | {RESPONSE.content_hash: swapped}
    with pytest.raises(CorporateActionCoverageError) as mismatch:
        verify_corporate_action_coverage(record, support)
    assert mismatch.value.code == "ca_coverage_response_hash_mismatch"
    resized = _sealed(dict(record) | {"response_byte_size": RESPONSE.byte_size + 1})
    with pytest.raises(CorporateActionCoverageError) as size:
        verify_corporate_action_coverage(resized, _support())
    assert size.value.code == "ca_coverage_response_hash_mismatch"


@pytest.mark.parametrize(
    ("dropped", "code"),
    (
        (REQUEST, "ca_coverage_request_binding_mismatch"),
        (ORIGIN, "ca_coverage_origin_unavailable"),
        (POLICY, "ca_coverage_policy_statement_unavailable"),
    ),
    ids=("request", "origin", "policy"),
)
def test_v4_every_bound_artifact_must_be_retained(
    dropped: VerifiedArtifactBytes, code: str
) -> None:
    record = _built()
    kept = tuple(
        item for item in (RESPONSE, REQUEST, ORIGIN, POLICY) if item is not dropped
    )
    with pytest.raises(CorporateActionCoverageError) as caught:
        verify_corporate_action_coverage(record, _support(*kept))
    assert caught.value.code == code


# --- 3.3 the window status ---------------------------------------------------------

JAN7, JAN8, JAN9 = date(2026, 1, 7), date(2026, 1, 8), date(2026, 1, 9)


def _status(
    records: tuple[ClosedWorldCorporateActionCoverageV1, ...],
    start: date = JAN7,
    end: date = JAN9,
    security_id: UUID = SECURITY,
) -> str:
    return corporate_action_window_status(records, security_id, start, end)


def test_no_record_is_never_no_action() -> None:
    assert _status(()) == "indeterminate"
    other = UUID("019b8240-0000-7000-8000-000000000201")
    assert _status((_built(security_id=other),)) == "indeterminate"


def test_a_covered_quiet_window_evidences_no_action() -> None:
    assert _status((_built(),)) == "evidenced_no_action"
    # One day each side of the covered interval stays uncovered.
    assert _status((_built(),), REQUESTED_START - timedelta(days=1), JAN9) == (
        "indeterminate"
    )
    assert _status((_built(),), JAN7, REQUESTED_END + timedelta(days=1)) == (
        "indeterminate"
    )
    assert _status((_built(),), REQUESTED_START, REQUESTED_END) == (
        "evidenced_no_action"
    )


def test_a_non_positive_assertion_evidences_nothing() -> None:
    for flag in _STRUCTURAL_FLAGS:
        weak = _assertion(policy_statement_hash=POLICY.content_hash, **{flag: False})
        assert _status((_built(completeness=weak),)) == "indeterminate", flag
    unpublished = _assertion(
        policy_statement_hash=POLICY.content_hash,
        basis="drift_asserted_unpublished",
    )
    assert _status((_built(completeness=unpublished),)) == "indeterminate"


def test_dates_before_the_evidence_floor_are_indeterminate() -> None:
    floor = REST_CORPORATE_ACTION_EVIDENCE_FLOOR
    record = _built(start=floor - timedelta(days=5), end=floor + timedelta(days=5))
    assert _status((record,), floor, floor + timedelta(days=5)) == (
        "evidenced_no_action"
    )
    assert _status((record,), floor - timedelta(days=1), floor) == "indeterminate"


def test_d4a_any_returned_date_inside_the_window_is_actions_present() -> None:
    split = _action(dates=(JAN8,))
    assert _status((_built(actions=(split,)),)) == "actions_present"
    assert _status((_built(actions=(split,)),), JAN9, JAN9) == "evidenced_no_action"
    # A dividend whose payable date alone falls in the window still halts.
    dividend = _action(
        "ca-div",
        native_kind="cash_dividends",
        action_kind=None,
        dates=(date(2026, 1, 2), date(2026, 1, 3), JAN9),
    )
    assert _status((_built(actions=(dividend,)),), JAN9, JAN9) == "actions_present"
    assert _status((_built(actions=(dividend,)),), JAN7, JAN8) == (
        "evidenced_no_action"
    )


def test_m17_an_undated_returned_action_is_indeterminate_in_every_window() -> None:
    undated = _action("ca-undated", dates=())
    record = _built(actions=(undated,))
    for start, end in ((JAN7, JAN7), (JAN8, JAN9), (REQUESTED_START, REQUESTED_END)):
        assert _status((record,), start, end) == "indeterminate"


def test_v9_overlapping_records_that_disagree_are_indeterminate_on_the_overlap() -> (
    None
):
    quiet = _built(start=REQUESTED_START, end=JAN9)
    split = _action(dates=(JAN8,))
    loud = _built(start=JAN7, end=REQUESTED_END, actions=(split,), response=REQUEST)
    # Both records alone decide their own windows.
    assert _status((quiet,), JAN7, JAN8) == "evidenced_no_action"
    assert _status((loud,), JAN7, JAN8) == "actions_present"
    # Together they disagree about 01-07 to 01-09: never resolved by preference.
    assert _status((quiet, loud), JAN7, JAN8) == "indeterminate"
    assert _status((loud, quiet), JAN9, JAN9) == "indeterminate"
    # A window outside the overlap is still decided.
    assert _status((quiet, loud), REQUESTED_START, date(2026, 1, 6)) == (
        "evidenced_no_action"
    )


def test_v9_overlapping_records_that_agree_compose() -> None:
    first = _built(start=REQUESTED_START, end=JAN9)
    second = _built(start=JAN7, end=REQUESTED_END, response=REQUEST)
    assert _status((first, second), JAN7, JAN9) == "evidenced_no_action"
    assert _status((first, second), date(2026, 1, 12), REQUESTED_END) == (
        "evidenced_no_action"
    )


def test_two_sources_for_one_security_answer_nothing() -> None:
    first = _built()
    second = _built(source_id="another-source-v1", response=REQUEST)
    assert _status((first,)) == "evidenced_no_action"
    assert _status((first, second)) == "indeterminate"


def test_an_invalid_record_makes_every_window_indeterminate() -> None:
    record = _built()
    forged = ClosedWorldCorporateActionCoverageV1.model_construct(
        **(dict(record) | {"queried_symbol": "MSFT"})
    )
    assert _status((record, forged)) == "indeterminate"


def test_window_returned_actions_names_every_action_dated_in_the_window() -> None:
    split = _action("ca-split", dates=(JAN8,))
    later = _action("ca-later", dates=(date(2026, 1, 14),))
    record = _built(actions=(later, split))
    assert window_returned_actions((record,), SECURITY, JAN7, JAN9) == (split,)
    assert window_returned_actions((record,), SECURITY, JAN7, REQUESTED_END) == (
        later,
        split,
    )


# --- 3.4 M1c-native coverage -------------------------------------------------------


def _coverage_result(
    family: str, status: str = "complete"
) -> EconomicCoverageResolutionV1:
    return EconomicCoverageResolutionV1(
        family=family,  # type: ignore[arg-type]
        source_id="synthetic-a",
        selected_coverage_hashes=("a" * 64,),
        target_manifest_hash="b" * 64,
        status=status,  # type: ignore[arg-type]
        occurrence_identity_supported=status == "complete",
        reasons=() if status == "complete" else ("coverage_declared_partial",),
    )


def _resolution(
    *,
    kinds: tuple[ActionKind, ...] = tuple(ActionKind),
    families: tuple[EconomicCoverageResolutionV1, ...] | None = None,
    history_start: str = "2026-01-01T00:00:00Z",
    horizon: str = "2026-02-01T00:00:00Z",
    reasons: tuple[str, ...] = (),
    unknown_effects: tuple[str, ...] = (),
    uncomposed: tuple[str, ...] = (),
) -> EconomicOutcomeResolutionV1:
    query = MarketOutcomeQueryV1(
        schema_version="1",
        security_id=SECURITY,
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
        unknown_effect_hashes=unknown_effects,
        delivery_groups=(),
        uncomposed_settlement_hashes=uncomposed,
        associations=(),
        coverage_results=(
            tuple(_coverage_result(item) for item in ("effect", "settlement", "terms"))
            if families is None
            else families
        ),
        residual_resolutions=(),
        safe_projection_hashes=(),
        claim_status="continuing",
        evidence_completeness="known" if not reasons else "partial",
        support_status="indeterminate",
        reasons=reasons,
    )


def test_native_coverage_holds_only_under_all_four_conditions() -> None:
    assert native_outcome_covers_window(_resolution(), JAN7, JAN9)
    assert native_outcome_is_empty(_resolution())


def test_m10_native_coverage_refuses_a_partial_or_missing_family() -> None:
    for family in ("effect", "settlement", "terms"):
        partial = tuple(
            _coverage_result(item, "partial" if item == family else "complete")
            for item in ("effect", "settlement", "terms")
        )
        assert not native_outcome_covers_window(
            _resolution(families=partial), JAN7, JAN9
        ), family
        missing = tuple(
            _coverage_result(item)
            for item in ("effect", "settlement", "terms")
            if item != family
        )
        assert not native_outcome_covers_window(
            _resolution(families=missing), JAN7, JAN9
        ), family
    doubled = tuple(
        _coverage_result(item) for item in ("effect", "effect", "settlement", "terms")
    )
    assert not native_outcome_covers_window(_resolution(families=doubled), JAN7, JAN9)


def test_m10_native_coverage_refuses_a_subset_of_action_kinds() -> None:
    """Split coverage is not spin-off coverage (the M1 design spec, section 6)."""
    for kind in ActionKind:
        subset = tuple(item for item in ActionKind if item is not kind)
        assert not native_outcome_covers_window(
            _resolution(kinds=subset), JAN7, JAN9
        ), kind


def test_m10_native_coverage_needs_a_one_day_margin_each_side() -> None:
    assert not native_outcome_covers_window(
        _resolution(history_start="2026-01-07T00:00:00Z"), JAN7, JAN9
    )
    assert native_outcome_covers_window(
        _resolution(history_start="2026-01-06T23:59:59Z"), JAN7, JAN9
    )
    assert not native_outcome_covers_window(
        _resolution(horizon="2026-01-09T23:59:59Z"), JAN7, JAN9
    )
    assert native_outcome_covers_window(
        _resolution(horizon="2026-01-10T00:00:00Z"), JAN7, JAN9
    )


@pytest.mark.parametrize(
    "reason", ("source_revision_selection_unresolved", "economic_time_indeterminate")
)
def test_m10_native_coverage_refuses_a_reason_that_can_hide_an_action(
    reason: str,
) -> None:
    assert not native_outcome_covers_window(_resolution(reasons=(reason,)), JAN7, JAN9)
    # Control: an unrelated reason does not remove coverage.
    assert native_outcome_covers_window(
        _resolution(reasons=("economic_component_gaps",)), JAN7, JAN9
    )


def test_an_outcome_with_any_effect_or_settlement_record_is_not_empty() -> None:
    assert not native_outcome_is_empty(_resolution(unknown_effects=("a" * 64,)))
    assert not native_outcome_is_empty(_resolution(uncomposed=("b" * 64,)))


class _LyingDate(date):
    """A date whose own comparisons and formatting say it is another day."""

    def __lt__(self, other: object) -> bool:
        return False

    def __le__(self, other: object) -> bool:
        return True

    def __gt__(self, other: object) -> bool:
        return False

    def __ge__(self, other: object) -> bool:
        return True

    def isoformat(self) -> str:
        return "1999-01-01"


def test_the_record_reads_every_date_through_the_base_type() -> None:
    """Issue 123 rule: no ``date`` subclass method ever decides coverage."""
    lying = _LyingDate(REQUESTED_START.year, REQUESTED_START.month, 7)
    record = _record(returned_actions=(_action(dates=(lying,)),))
    (action,) = record.returned_actions
    assert type(action.dates[0]) is date
    assert action.dates == (date(2026, 1, 7),)
    # The record's own interval fields are rebuilt through the base type too:
    # pydantic keeps a date subclass as it is given. A record sealed over the
    # exact form rebuilds identically when lying dates stand in for its own.
    exact = _record()
    lying_fields = {
        "requested_start_date": _LyingDate(2026, 1, 5),
        "requested_end_date": _LyingDate(2026, 1, 16),
        "covered_start_date": _LyingDate(2026, 1, 5),
        "covered_end_date": _LyingDate(2026, 1, 16),
    }
    rebuilt = ClosedWorldCorporateActionCoverageV1.model_validate(
        dict(exact) | lying_fields
    )
    for field in lying_fields:
        assert type(getattr(rebuilt, field)) is date, field
    assert rebuilt == exact
    # The one stamper never seals the lying form: its hash would not cover the
    # exact form the record is read as, so the builder refuses by its code.
    with pytest.raises(CorporateActionCoverageError) as refused:
        _built(start=_LyingDate(2026, 1, 5))
    assert refused.value.code == "ca_coverage_record_hash_mismatch"
    # A lying window is read through the base type as well.
    assert _status((_built(),), lying, JAN9) == "evidenced_no_action"
    loud = _built(actions=(_action(dates=(JAN8,)),))
    assert _status((loud,), _LyingDate(2026, 1, 9), JAN9) == "evidenced_no_action"
    assert _status((loud,), _LyingDate(2026, 1, 8), JAN9) == "actions_present"
    assert native_outcome_covers_window(_resolution(), lying, JAN9)
    assert not native_outcome_covers_window(
        _resolution(history_start="2026-01-07T00:00:00Z"), lying, JAN9
    )
