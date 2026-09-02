"""Behavioral tests for immutable fact revisions and cutoff selection."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypedDict, cast
from uuid import UUID, uuid7

import pytest
from pydantic import ValidationError

from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.revisions import (
    FactVersionV1,
    LogicalFactKeyV1,
    RevisionKind,
    select_fact_version,
    validate_revision_chain,
)
from drift.domain.temporal import (
    AvailabilityBasis,
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
    AvailabilityShape,
    ChannelKind,
    CutoffEligibility,
    SourcePrecision,
    ValidPeriodV1,
)
from drift.serialization.canonical import canonical_json, content_hash

HASH = "a" * 64


def utc(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def artifact_reference(content_hash_value: str = HASH) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=uuid7(),
        kind=ArtifactKind.OTHER,
        content_hash=content_hash_value,
        location="artifacts/revision-source.json",
    )


PUBLIC = AvailabilityChannelV1(kind=ChannelKind.PUBLIC, identifier="sec-edgar")
VENDOR = AvailabilityChannelV1(kind=ChannelKind.VENDOR, identifier="vendor-a")
STRICT = AvailabilityPolicyV1(policy_id="strict")
RULE_ALLOWED = AvailabilityPolicyV1(policy_id="rule-allowed")
KEY = LogicalFactKeyV1(
    source_id="synthetic-source",
    entity_key="entity-1",
    concept="reported-value",
    valid_period=ValidPeriodV1(started_at=utc(2022, 1, 1), ended_at=utc(2022, 4, 1)),
    unit="USD",
    dimensions={"reported": True},
)


class FactVersionValues(TypedDict):
    fact_version_id: UUID
    logical_key: LogicalFactKeyV1
    revision_kind: RevisionKind
    supersedes_fact_version_id: UUID | None
    source_sequence: int
    value: str | None
    null_reason: str | None
    availability: tuple[AvailabilityEvidenceV1, ...]
    source_artifact: ArtifactReference


class SelectionArguments(TypedDict):
    versions: tuple[FactVersionV1, ...]
    channel: AvailabilityChannelV1
    policy: AvailabilityPolicyV1
    cutoff: datetime
    retained_evidence: dict[str, AvailabilityEvidenceV1]


def exact_evidence(
    available: datetime,
    channel: AvailabilityChannelV1 = PUBLIC,
) -> AvailabilityEvidenceV1:
    return AvailabilityEvidenceV1(
        channel=channel,
        shape=AvailabilityShape.EXACT,
        lower_bound=available,
        upper_bound=available,
        precision=SourcePrecision.SECOND,
        source_time_label=available.isoformat().replace("+00:00", "Z"),
        basis=AvailabilityBasis.SOURCE_OBSERVED,
    )


def bounded_evidence() -> AvailabilityEvidenceV1:
    return AvailabilityEvidenceV1(
        channel=PUBLIC,
        shape=AvailabilityShape.BOUNDED,
        lower_bound=utc(2022, 5, 5),
        upper_bound=utc(2022, 5, 6),
        precision=SourcePrecision.DATE,
        source_time_label="2022-05-05",
        source_timezone="UTC",
        basis=AvailabilityBasis.SOURCE_OBSERVED,
        evidence_reference=artifact_reference(),
    )


def unknown_evidence() -> AvailabilityEvidenceV1:
    return AvailabilityEvidenceV1(
        channel=PUBLIC,
        shape=AvailabilityShape.UNKNOWN,
        precision=SourcePrecision.UNKNOWN,
        source_time_label="release time not retained",
        basis=AvailabilityBasis.SOURCE_OBSERVED,
    )


def version(
    *,
    value: str | None = "1.20",
    revision_kind: RevisionKind = RevisionKind.INITIAL,
    supersedes_fact_version_id: UUID | None = None,
    source_sequence: int = 0,
    availability: tuple[AvailabilityEvidenceV1, ...] | None = None,
    logical_key: LogicalFactKeyV1 = KEY,
    null_reason: str | None = None,
    fact_version_id: UUID | None = None,
) -> FactVersionV1:
    fact_version_id = fact_version_id or uuid7()
    availability = availability or (exact_evidence(utc(2022, 5, 5, 20)),)
    payload: FactVersionValues = {
        "fact_version_id": fact_version_id,
        "logical_key": logical_key,
        "revision_kind": revision_kind,
        "supersedes_fact_version_id": supersedes_fact_version_id,
        "source_sequence": source_sequence,
        "value": value,
        "null_reason": null_reason,
        "availability": availability,
        "source_artifact": artifact_reference(),
    }
    return FactVersionV1(**payload, payload_hash=content_hash(payload))


INITIAL = version()
RESTATED = version(
    value="0.90",
    revision_kind=RevisionKind.RESTATEMENT,
    supersedes_fact_version_id=INITIAL.fact_version_id,
    source_sequence=1,
    availability=(exact_evidence(utc(2022, 8, 1)),),
)
CORRECTED = version(
    value="0.95",
    revision_kind=RevisionKind.CORRECTION,
    supersedes_fact_version_id=RESTATED.fact_version_id,
    source_sequence=2,
    availability=(exact_evidence(utc(2022, 8, 12), VENDOR),),
)
WITHDRAWN = version(
    value=None,
    revision_kind=RevisionKind.WITHDRAWAL,
    supersedes_fact_version_id=INITIAL.fact_version_id,
    source_sequence=1,
    availability=(exact_evidence(utc(2022, 8, 15)),),
    null_reason="withdrawn",
)
UNKNOWN_LATER = version(
    value="unverified",
    revision_kind=RevisionKind.REVISION,
    supersedes_fact_version_id=INITIAL.fact_version_id,
    source_sequence=1,
    availability=(unknown_evidence(),),
)

CHAINS = {
    "original": (INITIAL,),
    "restated": (INITIAL, RESTATED),
    "restated_plus_correction": (INITIAL, RESTATED, CORRECTED),
    "bounded": (version(availability=(bounded_evidence(),)),),
    "unknown": (version(availability=(unknown_evidence(),)),),
    "withdrawn": (INITIAL, WITHDRAWN),
}
RAW_EVIDENCE_BY_HASH: dict[str, AvailabilityEvidenceV1] = {}


@pytest.mark.parametrize(
    ("case", "cutoff", "expected_class", "expected_value"),
    (
        ("original", utc(2022, 5, 4), CutoffEligibility.INELIGIBLE, None),
        ("original", utc(2022, 5, 5, 20), CutoffEligibility.ELIGIBLE, "1.20"),
        ("restated", utc(2022, 6, 1), CutoffEligibility.ELIGIBLE, "1.20"),
        ("restated", utc(2022, 8, 10), CutoffEligibility.ELIGIBLE, "0.90"),
        ("bounded", utc(2022, 5, 5, 12), CutoffEligibility.INDETERMINATE, None),
        ("unknown", utc(2030, 1, 1), CutoffEligibility.INDETERMINATE, None),
        ("withdrawn", utc(2022, 9, 1), CutoffEligibility.INELIGIBLE, None),
    ),
)
def test_revision_selection_table(
    case: str,
    cutoff: datetime,
    expected_class: CutoffEligibility,
    expected_value: str | None,
) -> None:
    """A wrong availability branch or latest-version choice changes this table."""
    result = select_fact_version(
        CHAINS[case], PUBLIC, STRICT, cutoff, RAW_EVIDENCE_BY_HASH
    )
    assert result.classification is expected_class
    actual = None if result.selected_version is None else result.selected_version.value
    assert actual == expected_value


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("cutoff", utc(2022, 8, 11)),
        ("channel", VENDOR),
        ("policy", RULE_ALLOWED),
        ("versions", CHAINS["restated_plus_correction"]),
    ),
)
def test_selection_result_hash_changes_for_every_query_input_mutation(
    field: str,
    value: object,
) -> None:
    """Dropping any query input from the result identity makes this fail."""
    arguments: SelectionArguments = {
        "versions": CHAINS["restated"],
        "channel": PUBLIC,
        "policy": STRICT,
        "cutoff": utc(2022, 8, 10),
        "retained_evidence": RAW_EVIDENCE_BY_HASH,
    }
    original = select_fact_version(**arguments)
    changed = select_fact_version(
        **cast(SelectionArguments, {**arguments, field: value})
    )
    assert canonical_json(changed) != canonical_json(original)
    assert content_hash(changed) != content_hash(original)


def test_reordered_versions_have_stable_selection_identity() -> None:
    """Accidental dependence on caller order changes the canonical result."""
    selected = select_fact_version(
        CHAINS["restated"], PUBLIC, STRICT, utc(2022, 8, 10), {}
    )
    reordered = select_fact_version(
        tuple(reversed(CHAINS["restated"])), PUBLIC, STRICT, utc(2022, 8, 10), {}
    )
    assert canonical_json(reordered) == canonical_json(selected)
    assert content_hash(reordered) == content_hash(selected)


def test_later_indeterminate_revision_does_not_erase_available_predecessor() -> None:
    """Treating an unknown later revision as an override leaks no future data."""
    result = select_fact_version(
        (INITIAL, UNKNOWN_LATER), PUBLIC, STRICT, utc(2022, 6, 1), {}
    )
    assert result.classification is CutoffEligibility.ELIGIBLE
    assert result.selected_version == INITIAL


type VersionFactory = Callable[[], tuple[FactVersionV1, ...]]


def duplicate_id_versions() -> tuple[FactVersionV1, ...]:
    return (INITIAL, INITIAL)


def missing_root_versions() -> tuple[FactVersionV1, ...]:
    return (
        version(
            revision_kind=RevisionKind.REVISION,
            supersedes_fact_version_id=uuid7(),
        ),
    )


def multiple_root_versions() -> tuple[FactVersionV1, ...]:
    return INITIAL, version()


def missing_predecessor_versions() -> tuple[FactVersionV1, ...]:
    return (
        INITIAL,
        version(
            revision_kind=RevisionKind.REVISION,
            supersedes_fact_version_id=uuid7(),
            source_sequence=1,
        ),
    )


def mismatched_key_versions() -> tuple[FactVersionV1, ...]:
    return (
        INITIAL,
        version(
            revision_kind=RevisionKind.REVISION,
            supersedes_fact_version_id=INITIAL.fact_version_id,
            source_sequence=1,
            logical_key=KEY.model_copy(update={"concept": "other"}),
        ),
    )


def branching_versions() -> tuple[FactVersionV1, ...]:
    return (
        INITIAL,
        version(
            revision_kind=RevisionKind.REVISION,
            supersedes_fact_version_id=INITIAL.fact_version_id,
            source_sequence=1,
        ),
        version(
            revision_kind=RevisionKind.CORRECTION,
            supersedes_fact_version_id=INITIAL.fact_version_id,
            source_sequence=2,
        ),
    )


def decreasing_sequence_versions() -> tuple[FactVersionV1, ...]:
    return (
        INITIAL,
        version(
            revision_kind=RevisionKind.REVISION,
            supersedes_fact_version_id=INITIAL.fact_version_id,
            source_sequence=0,
        ),
    )


def cycle_versions() -> tuple[FactVersionV1, ...]:
    """Construct an otherwise-valid two-version predecessor cycle."""
    first_id, second_id = uuid7(), uuid7()
    first = version(
        fact_version_id=first_id,
        revision_kind=RevisionKind.REVISION,
        supersedes_fact_version_id=second_id,
        source_sequence=0,
    )
    second = version(
        fact_version_id=second_id,
        revision_kind=RevisionKind.REVISION,
        supersedes_fact_version_id=first_id,
        source_sequence=1,
    )
    return first, second


@pytest.mark.parametrize(
    ("case", "versions", "code"),
    (
        ("duplicate id", duplicate_id_versions, "duplicate_fact_version_id"),
        ("missing root", missing_root_versions, "missing_initial_root"),
        ("multiple roots", multiple_root_versions, "multiple_initial_roots"),
        ("missing predecessor", missing_predecessor_versions, "missing_predecessor"),
        ("key mismatch", mismatched_key_versions, "logical_key_mismatch"),
        ("branching", branching_versions, "branching_revision_chain"),
        ("cycle", cycle_versions, "revision_cycle"),
        (
            "decreasing sequence",
            decreasing_sequence_versions,
            "non_increasing_source_sequence",
        ),
    ),
)
def test_revision_chain_rejects_malformed_structure(
    case: str,
    versions: VersionFactory,
    code: str,
) -> None:
    """Removing the corresponding chain guard returns no finding for malformed data."""
    assert code in {finding.code for finding in validate_revision_chain(versions())}


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"availability": ()}, "availability"),
        (
            {
                "availability": (
                    exact_evidence(utc(2022, 5, 5, 20)),
                    exact_evidence(utc(2022, 5, 6, 20)),
                )
            },
            "channels",
        ),
        ({"source_artifact": None}, "source artifact"),
        ({"payload_hash": "b" * 64}, "payload hash"),
        ({"value": None, "null_reason": None}, "null reason"),
        ({"revision_kind": RevisionKind.WITHDRAWAL, "value": "1.20"}, "withdrawal"),
    ),
)
def test_fact_version_rejects_invalid_immutable_payload(
    changes: dict[str, object], message: str
) -> None:
    """Removing the payload validation accepts a malformed immutable fact."""
    values = INITIAL.model_dump(mode="python")
    values.update(changes)
    with pytest.raises(ValidationError, match=message):
        FactVersionV1.model_validate(values)


def test_naive_cutoff_is_rejected() -> None:
    """Treating a naive cutoff as UTC changes a fail-closed query boundary."""
    with pytest.raises(ValueError, match="timezone-aware"):
        select_fact_version(
            CHAINS["original"], PUBLIC, STRICT, datetime(2022, 5, 5), {}
        )
