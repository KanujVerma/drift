"""Behavioral tests for channel-scoped temporal availability evidence."""

from datetime import UTC, datetime
from typing import TypedDict
from uuid import uuid7

import pytest
from pydantic import ValidationError

from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.temporal import (
    CONSERVATIVE_UPPER_BOUND_RULE_HASH,
    AvailabilityBasis,
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
    AvailabilityShape,
    ChannelKind,
    CutoffEligibility,
    RuleDerivationV1,
    SourcePrecision,
    ValidPeriodV1,
    derive_conservative_upper_bound,
    evaluate_availability,
)
from drift.serialization.canonical import content_hash

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
        location="artifacts/temporal-evidence.json",
    )


PUBLIC = AvailabilityChannelV1(kind=ChannelKind.PUBLIC, identifier="sec-edgar")
VENDOR = AvailabilityChannelV1(kind=ChannelKind.VENDOR, identifier="vendor-a")
STRICT = AvailabilityPolicyV1(policy_id="strict")
RULE_REFERENCE = artifact_reference(CONSERVATIVE_UPPER_BOUND_RULE_HASH)
RULE_ALLOWED = AvailabilityPolicyV1(
    policy_id="allow-conservative-upper-bound",
    permitted_rule_hashes=(CONSERVATIVE_UPPER_BOUND_RULE_HASH,),
)


def exact_source_evidence(
    *,
    source_time_label: str = "2022-05-05T20:00:00Z",
    bound: datetime | None = None,
    **changes: object,
) -> AvailabilityEvidenceV1:
    if bound is None:
        bound = utc(2022, 5, 5, 20)
    values: dict[str, object] = {
        "channel": PUBLIC,
        "shape": AvailabilityShape.EXACT,
        "lower_bound": bound,
        "upper_bound": bound,
        "precision": SourcePrecision.SECOND,
        "source_time_label": source_time_label,
        "basis": AvailabilityBasis.SOURCE_OBSERVED,
    }
    values.update(changes)
    return AvailabilityEvidenceV1.model_validate(values)


def bounded_date_evidence(**changes: object) -> AvailabilityEvidenceV1:
    values: dict[str, object] = {
        "channel": PUBLIC,
        "shape": AvailabilityShape.BOUNDED,
        "lower_bound": utc(2022, 5, 5),
        "upper_bound": utc(2022, 5, 6),
        "precision": SourcePrecision.DATE,
        "source_time_label": "2022-05-05",
        "source_timezone": "UTC",
        "basis": AvailabilityBasis.SOURCE_OBSERVED,
        "evidence_reference": artifact_reference(),
    }
    values.update(changes)
    return AvailabilityEvidenceV1.model_validate(values)


RAW_BOUNDED = bounded_date_evidence()
DERIVED_UPPER = derive_conservative_upper_bound(RAW_BOUNDED, RULE_REFERENCE)
EVIDENCE = {
    "exact": exact_source_evidence(),
    "bounded": RAW_BOUNDED,
    "unknown": AvailabilityEvidenceV1(
        channel=PUBLIC,
        shape=AvailabilityShape.UNKNOWN,
        precision=SourcePrecision.UNKNOWN,
        source_time_label="release time not retained",
        basis=AvailabilityBasis.SOURCE_OBSERVED,
    ),
    "derived_upper": DERIVED_UPPER,
}
RAW_EVIDENCE_BY_HASH = {content_hash(RAW_BOUNDED): RAW_BOUNDED}


class AvailabilityQueryArguments(TypedDict):
    evidence: AvailabilityEvidenceV1
    channel: AvailabilityChannelV1
    policy: AvailabilityPolicyV1
    cutoff: datetime
    retained_evidence: dict[str, AvailabilityEvidenceV1]


@pytest.mark.parametrize(
    ("case", "cutoff", "requested_channel", "policy", "expected"),
    (
        (
            "exact",
            utc(2022, 5, 5, 19, 59),
            PUBLIC,
            STRICT,
            CutoffEligibility.INELIGIBLE,
        ),
        (
            "exact",
            utc(2022, 5, 5, 20),
            PUBLIC,
            STRICT,
            CutoffEligibility.ELIGIBLE,
        ),
        (
            "bounded",
            utc(2022, 5, 5),
            PUBLIC,
            STRICT,
            CutoffEligibility.INDETERMINATE,
        ),
        (
            "bounded",
            utc(2022, 5, 6),
            PUBLIC,
            STRICT,
            CutoffEligibility.ELIGIBLE,
        ),
        (
            "unknown",
            utc(2030, 1, 1),
            PUBLIC,
            STRICT,
            CutoffEligibility.INDETERMINATE,
        ),
        (
            "exact",
            utc(2022, 5, 6),
            VENDOR,
            STRICT,
            CutoffEligibility.INDETERMINATE,
        ),
        (
            "derived_upper",
            utc(2022, 5, 6),
            PUBLIC,
            STRICT,
            CutoffEligibility.INELIGIBLE,
        ),
        (
            "derived_upper",
            utc(2022, 5, 6),
            PUBLIC,
            RULE_ALLOWED,
            CutoffEligibility.ELIGIBLE,
        ),
    ),
)
def test_cutoff_eligibility_table(
    case: str,
    cutoff: datetime,
    requested_channel: AvailabilityChannelV1,
    policy: AvailabilityPolicyV1,
    expected: CutoffEligibility,
) -> None:
    """A wrong cutoff branch must change tri-state historical eligibility."""
    result = evaluate_availability(
        EVIDENCE[case], requested_channel, policy, cutoff, RAW_EVIDENCE_BY_HASH
    )
    assert result.classification is expected


@pytest.mark.parametrize(
    ("source_time_label", "bound"),
    (
        ("2022-05-05T20:00:00", utc(2022, 5, 5, 20)),
        ("2022-05-05 20:00:00Z", utc(2022, 5, 5, 20)),
        ("2022-05-05T20:00:00Z", utc(2022, 5, 5, 20, 0, 1)),
    ),
)
def test_exact_second_rejects_malformed_unzoned_or_mismatched_labels(
    source_time_label: str,
    bound: datetime,
) -> None:
    """Exact evidence must be bound to the source's offset-bearing second."""
    with pytest.raises(ValidationError, match="offset-bearing ISO second"):
        exact_source_evidence(source_time_label=source_time_label, bound=bound)


def test_exact_second_normalizes_offset_label_to_equal_utc_bounds() -> None:
    """An offset source label must preserve its real instant in UTC."""
    evidence = exact_source_evidence(
        source_time_label="2022-05-05T16:00:00-04:00",
        bound=utc(2022, 5, 5, 20),
    )
    assert evidence.lower_bound == evidence.upper_bound == utc(2022, 5, 5, 20)


def test_date_and_minute_windows_are_computed_from_source_timezones() -> None:
    """Changing a local source label must not invent a UTC midnight instant."""
    date_evidence = bounded_date_evidence(
        source_time_label="2022-03-13",
        source_timezone="America/New_York",
        lower_bound=utc(2022, 3, 13, 5),
        upper_bound=utc(2022, 3, 14, 4),
    )
    minute_evidence = AvailabilityEvidenceV1(
        channel=PUBLIC,
        shape=AvailabilityShape.BOUNDED,
        lower_bound=utc(2022, 5, 5, 20),
        upper_bound=utc(2022, 5, 5, 20, 1),
        precision=SourcePrecision.MINUTE,
        source_time_label="2022-05-05T16:00",
        source_timezone="America/New_York",
        basis=AvailabilityBasis.SOURCE_OBSERVED,
    )
    assert date_evidence.upper_bound == utc(2022, 3, 14, 4)
    assert minute_evidence.lower_bound == utc(2022, 5, 5, 20)


@pytest.mark.parametrize(
    ("values", "message"),
    (
        (
            {
                "channel": PUBLIC,
                "shape": AvailabilityShape.BOUNDED,
                "lower_bound": utc(2022, 5, 6),
                "upper_bound": utc(2022, 5, 5),
                "precision": SourcePrecision.INTERVAL,
                "source_time_label": "reported window",
                "basis": AvailabilityBasis.SOURCE_OBSERVED,
            },
            "ordered bounds",
        ),
        (
            {
                "channel": PUBLIC,
                "shape": AvailabilityShape.BOUNDED,
                "lower_bound": utc(2022, 5, 5),
                "upper_bound": utc(2022, 5, 5),
                "precision": SourcePrecision.INTERVAL,
                "source_time_label": "reported window",
                "basis": AvailabilityBasis.SOURCE_OBSERVED,
            },
            "ordered bounds",
        ),
        (
            {
                "channel": PUBLIC,
                "shape": AvailabilityShape.EXACT,
                "lower_bound": utc(2022, 5, 5, 20),
                "upper_bound": utc(2022, 5, 5, 20, 1),
                "precision": SourcePrecision.SECOND,
                "source_time_label": "2022-05-05T20:00:00Z",
                "basis": AvailabilityBasis.SOURCE_OBSERVED,
            },
            "equal bounds",
        ),
        (
            {
                "channel": PUBLIC,
                "shape": AvailabilityShape.UNKNOWN,
                "lower_bound": utc(2022, 5, 5),
                "precision": SourcePrecision.UNKNOWN,
                "basis": AvailabilityBasis.SOURCE_OBSERVED,
            },
            "unknown evidence cannot have bounds",
        ),
        (
            {
                "channel": PUBLIC,
                "shape": AvailabilityShape.BOUNDED,
                "lower_bound": utc(2022, 5, 5),
                "upper_bound": utc(2022, 5, 6),
                "precision": SourcePrecision.INTERVAL,
                "basis": AvailabilityBasis.SOURCE_OBSERVED,
            },
            "source label",
        ),
        (
            {
                "channel": PUBLIC,
                "shape": AvailabilityShape.BOUNDED,
                "lower_bound": utc(2022, 5, 5),
                "upper_bound": utc(2022, 5, 6),
                "precision": SourcePrecision.DATE,
                "source_time_label": "2022-05-05",
                "basis": AvailabilityBasis.SOURCE_OBSERVED,
            },
            "timezone",
        ),
        (
            {
                "channel": PUBLIC,
                "shape": AvailabilityShape.EXACT,
                "lower_bound": utc(2022, 5, 5),
                "upper_bound": utc(2022, 5, 5),
                "precision": SourcePrecision.DATE,
                "source_time_label": "2022-05-05",
                "source_timezone": "UTC",
                "basis": AvailabilityBasis.SOURCE_OBSERVED,
            },
            "only rule-derived",
        ),
        (
            {
                "channel": PUBLIC,
                "shape": AvailabilityShape.EXACT,
                "lower_bound": utc(2022, 5, 5),
                "upper_bound": utc(2022, 5, 5),
                "precision": SourcePrecision.MINUTE,
                "source_time_label": "2022-05-05T00:00",
                "source_timezone": "UTC",
                "basis": AvailabilityBasis.VENDOR_DELIVERY,
            },
            "only rule-derived",
        ),
        (
            {
                "channel": PUBLIC,
                "shape": AvailabilityShape.EXACT,
                "lower_bound": utc(2022, 5, 5),
                "upper_bound": utc(2022, 5, 5),
                "precision": SourcePrecision.SESSION,
                "source_time_label": "2022-05-05 session",
                "basis": AvailabilityBasis.LOCAL_INGEST,
                "evidence_reference": artifact_reference(),
            },
            "only rule-derived",
        ),
        (
            {
                "channel": PUBLIC,
                "shape": AvailabilityShape.UNKNOWN,
                "precision": SourcePrecision.DATE,
                "basis": AvailabilityBasis.SOURCE_OBSERVED,
            },
            "unknown precision",
        ),
        (
            {
                "channel": PUBLIC,
                "shape": AvailabilityShape.EXACT,
                "lower_bound": utc(2022, 5, 5, 20),
                "upper_bound": utc(2022, 5, 5, 20),
                "precision": SourcePrecision.SECOND,
                "source_time_label": "2022-05-05T20:00:00Z",
                "basis": AvailabilityBasis.RULE_DERIVED,
            },
            "rule metadata",
        ),
        (
            {
                "channel": PUBLIC,
                "shape": AvailabilityShape.EXACT,
                "lower_bound": utc(2022, 5, 5, 20),
                "upper_bound": utc(2022, 5, 5, 20),
                "precision": SourcePrecision.SECOND,
                "source_time_label": "2022-05-05T20:00:00Z",
                "basis": AvailabilityBasis.SOURCE_OBSERVED,
                "rule_derivation": {
                    "rule_reference": RULE_REFERENCE,
                    "input_evidence_hash": HASH,
                },
            },
            "only permitted for rule-derived",
        ),
    ),
)
def test_evidence_rejects_incompatible_or_incomplete_temporal_claims(
    values: dict[str, object], message: str
) -> None:
    """Invalid evidence combinations must fail before an eligibility query."""
    with pytest.raises(ValidationError, match=message):
        AvailabilityEvidenceV1.model_validate(values)


def test_session_evidence_requires_a_retained_artifact() -> None:
    """A session label alone cannot establish a bounded availability window."""
    with pytest.raises(ValidationError, match="evidence artifact"):
        AvailabilityEvidenceV1(
            channel=PUBLIC,
            shape=AvailabilityShape.BOUNDED,
            lower_bound=utc(2022, 5, 5),
            upper_bound=utc(2022, 5, 6),
            precision=SourcePrecision.SESSION,
            source_time_label="2022-05-05 session",
            basis=AvailabilityBasis.SOURCE_OBSERVED,
        )


def test_valid_period_is_nonempty_and_half_open() -> None:
    """A fact period includes its start but not its end, and cannot be empty."""
    period = ValidPeriodV1(started_at=utc(2022, 5, 5), ended_at=utc(2022, 5, 6))
    assert period.contains(utc(2022, 5, 5))
    assert not period.contains(utc(2022, 5, 6))
    with pytest.raises(ValidationError, match="nonempty"):
        ValidPeriodV1(started_at=utc(2022, 5, 5), ended_at=utc(2022, 5, 5))


def test_derived_evidence_cannot_be_supplied_directly() -> None:
    """Only the conservative derivation function may construct trusted output."""
    with pytest.raises(ValidationError, match="conservative-upper-bound"):
        AvailabilityEvidenceV1(
            channel=PUBLIC,
            shape=AvailabilityShape.EXACT,
            lower_bound=utc(2022, 5, 6),
            upper_bound=utc(2022, 5, 6),
            precision=SourcePrecision.DATE,
            source_time_label="2022-05-05",
            source_timezone="UTC",
            basis=AvailabilityBasis.RULE_DERIVED,
            evidence_reference=RAW_BOUNDED.evidence_reference,
            rule_derivation=RuleDerivationV1(
                rule_reference=RULE_REFERENCE,
                input_evidence_hash=content_hash(RAW_BOUNDED),
            ),
        )


def test_evaluation_rejects_naive_cutoff() -> None:
    """A query with no timezone cannot claim historical eligibility."""
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_availability(
            EVIDENCE["exact"],
            PUBLIC,
            STRICT,
            datetime(2022, 5, 6),
            RAW_EVIDENCE_BY_HASH,
        )


def test_rule_derived_channel_mismatch_retains_derivation_input_hash() -> None:
    """A channel mismatch still leaves the query result auditable."""
    evidence = EVIDENCE["derived_upper"]
    assert evidence.rule_derivation is not None
    result = evaluate_availability(
        evidence, VENDOR, RULE_ALLOWED, utc(2022, 5, 6), RAW_EVIDENCE_BY_HASH
    )
    assert result.classification is CutoffEligibility.INDETERMINATE
    assert (
        result.derivation_input_evidence_hash
        == evidence.rule_derivation.input_evidence_hash
    )


def test_rule_evaluation_rejects_missing_or_tampered_retained_raw_evidence() -> None:
    """A retained rule input must exist and still hash to the derivation input."""
    missing = evaluate_availability(
        DERIVED_UPPER, PUBLIC, RULE_ALLOWED, utc(2022, 5, 6), {}
    )
    tampered_raw = bounded_date_evidence(evidence_reference=artifact_reference())
    tampered = evaluate_availability(
        DERIVED_UPPER,
        PUBLIC,
        RULE_ALLOWED,
        utc(2022, 5, 6),
        {content_hash(RAW_BOUNDED): tampered_raw},
    )
    assert missing.classification is CutoffEligibility.INDETERMINATE
    assert missing.reason == "rule_input_evidence_unavailable"
    assert tampered.classification is CutoffEligibility.INDETERMINATE
    assert tampered.reason == "rule_input_evidence_unavailable"


def test_policy_rejects_duplicate_rule_hashes() -> None:
    """Duplicate policy entries must not create ambiguous approval identity."""
    with pytest.raises(ValidationError, match="unique"):
        AvailabilityPolicyV1(
            policy_id="duplicate-rule",
            permitted_rule_hashes=(
                CONSERVATIVE_UPPER_BOUND_RULE_HASH,
                CONSERVATIVE_UPPER_BOUND_RULE_HASH,
            ),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("cutoff", utc(2022, 5, 6, 0, 1)),
        ("channel", VENDOR),
        ("policy", RULE_ALLOWED),
        ("evidence", EVIDENCE["bounded"]),
    ),
)
def test_cutoff_result_hash_changes_for_every_query_input_mutation(
    field: str, value: object
) -> None:
    """Changing a real query input must change the auditable result identity."""
    arguments: AvailabilityQueryArguments = {
        "evidence": EVIDENCE["exact"],
        "channel": PUBLIC,
        "policy": STRICT,
        "cutoff": utc(2022, 5, 6),
        "retained_evidence": RAW_EVIDENCE_BY_HASH,
    }
    result = evaluate_availability(**arguments)
    if field == "cutoff":
        assert isinstance(value, datetime)
        changed = evaluate_availability(
            arguments["evidence"],
            arguments["channel"],
            arguments["policy"],
            value,
            arguments["retained_evidence"],
        )
    elif field == "channel":
        assert isinstance(value, AvailabilityChannelV1)
        changed = evaluate_availability(
            arguments["evidence"],
            value,
            arguments["policy"],
            arguments["cutoff"],
            arguments["retained_evidence"],
        )
    elif field == "policy":
        assert isinstance(value, AvailabilityPolicyV1)
        changed = evaluate_availability(
            arguments["evidence"],
            arguments["channel"],
            value,
            arguments["cutoff"],
            arguments["retained_evidence"],
        )
    elif field == "evidence":
        assert isinstance(value, AvailabilityEvidenceV1)
        changed = evaluate_availability(
            value,
            arguments["channel"],
            arguments["policy"],
            arguments["cutoff"],
            arguments["retained_evidence"],
        )
    else:
        raise AssertionError(f"unexpected query field: {field}")
    assert content_hash(changed) != content_hash(result)
