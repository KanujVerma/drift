"""Closed coverage and source-policy contracts for M1c evidence inputs."""

from datetime import UTC, datetime

import pytest
from economic_test_support import (
    HASH_A,
    correct_coverage,
    coverage_inventory_hashes,
    coverage_record,
    parse_utc,
    policy_fixture,
    rebind_coverage_evidence,
    seal_record,
    source_policy,
    support_bytes,
    uid,
)
from pydantic import ValidationError

from drift.domain.assertions import BoundaryShape, TemporalBoundaryClaimV1
from drift.domain.economic_common import ActionKind, EconomicSourceKeyV1
from drift.domain.economic_coverage import (
    EconomicCoverageVersionV1,
    policy_owner,
)
from drift.domain.temporal import (
    AvailabilityBasis,
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityShape,
    ChannelKind,
    SourcePrecision,
)
from drift.serialization.canonical import content_hash


def test_source_policy_has_one_authority_per_family() -> None:
    """A second settlement owner must not become a hidden fallback authority."""
    policy = policy_fixture()

    assert len(policy.owners) == 3
    duplicate = policy.owners[-1].model_copy(update={"source_id": "synthetic-b"})

    with pytest.raises(ValidationError, match="exactly one owner"):
        policy.model_copy(update={"owners": (*policy.owners, duplicate)})


def test_source_policy_requires_each_owner_manifest_binding_and_exact_lookup() -> None:
    """An owner must select role-correct manifests from its own bound source."""
    policy = policy_fixture()
    owner = policy.owners[0]

    assert policy_owner(policy, "effect") == policy.owners[1]
    with pytest.raises(ValidationError, match="exactly one owner"):
        policy.model_copy(update={"owners": policy.owners[1:]})
    with pytest.raises(ValidationError, match="fact manifest"):
        policy.model_copy(
            update={
                "input_dataset_bindings": tuple(
                    binding
                    for binding in policy.input_dataset_bindings
                    if binding.manifest_hash != owner.fact_manifest_hash
                )
            }
        )
    fact_binding = next(
        binding
        for binding in policy.input_dataset_bindings
        if binding.manifest_hash == owner.fact_manifest_hash
    )
    wrong_source = fact_binding.model_copy(update={"source_id": "synthetic-b"})
    wrong_role = fact_binding.model_copy(update={"role": "economic_effect"})
    with pytest.raises(ValidationError, match="fact manifest"):
        policy.model_copy(
            update={
                "input_dataset_bindings": tuple(
                    wrong_source if binding == fact_binding else binding
                    for binding in policy.input_dataset_bindings
                )
            }
        )
    with pytest.raises(ValidationError, match="fact manifest"):
        policy.model_copy(
            update={
                "input_dataset_bindings": tuple(
                    wrong_role if binding == fact_binding else binding
                    for binding in policy.input_dataset_bindings
                )
            }
        )


def test_coverage_source_key_must_be_coverage_not_a_fact_family() -> None:
    """A fact record class cannot be relabelled as an evidence-coverage declaration."""
    artifact_hashes, record_hashes = coverage_inventory_hashes(1)
    coverage = coverage_record(1, "terms", HASH_A, artifact_hashes, record_hashes)

    with pytest.raises(ValidationError, match="coverage source family"):
        coverage.model_copy(
            update={
                "source_key": EconomicSourceKeyV1(
                    source_id="synthetic-a",
                    family="terms",
                    native_record_id="coverage-1",
                )
            }
        )


def test_coverage_contains_uses_half_open_declaration_for_inclusive_horizon() -> None:
    """The day after the inclusive horizon is required to contain its final instant."""
    from drift.domain.economic_coverage import coverage_contains

    artifact_hashes, record_hashes = coverage_inventory_hashes(2)
    coverage = coverage_record(2, "terms", HASH_A, artifact_hashes, record_hashes)

    assert coverage_contains(
        coverage,
        parse_utc("2020-01-01T00:00:00Z"),
        parse_utc("2021-01-01T00:00:00Z"),
    )
    assert not coverage_contains(
        coverage,
        parse_utc("2019-12-31T23:59:59Z"),
        parse_utc("2021-01-01T00:00:00Z"),
    )
    assert not coverage_contains(
        coverage,
        parse_utc("2020-01-01T00:00:00Z"),
        parse_utc("2021-01-02T00:00:00Z"),
    )


def test_coverage_contains_fails_closed_for_unknown_start_or_end() -> None:
    """Unknown source bounds cannot establish coverage containment."""
    from drift.domain.assertions import TemporalIntervalClaimV1
    from drift.domain.economic_coverage import coverage_contains

    artifact_hashes, record_hashes = coverage_inventory_hashes(23)
    coverage = coverage_record(23, "terms", HASH_A, artifact_hashes, record_hashes)
    unknown = TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.UNKNOWN,
        lower_bound=None,
        upper_bound=None,
        source_precision=SourcePrecision.UNKNOWN,
        source_time_label=None,
        source_timezone=None,
        evidence_reference=None,
    )
    for interval in (
        coverage.coverage_interval.model_copy(update={"start": unknown}),
        TemporalIntervalClaimV1(
            schema_version="1", start=coverage.coverage_interval.start, end=unknown
        ),
    ):
        unknown_coverage = coverage.model_construct(
            **{
                **{
                    field: getattr(coverage, field)
                    for field in type(coverage).model_fields
                },
                "coverage_interval": interval,
            }
        )
        assert not coverage_contains(
            unknown_coverage,
            parse_utc("2020-01-01T00:00:00Z"),
            parse_utc("2021-01-01T00:00:00Z"),
        )


def test_coverage_snapshot_rejects_every_definitely_early_channel() -> None:
    """A late channel cannot rescue another channel known to predate the snapshot."""
    artifact_hashes, record_hashes = coverage_inventory_hashes(24)
    coverage = coverage_record(24, "terms", HASH_A, artifact_hashes, record_hashes)
    early = _availability("public", "2021-01-01T00:00:00Z")
    late = _availability("vendor", "2021-01-03T00:00:00Z")

    with pytest.raises(ValidationError, match="availability"):
        _with_coverage_availability(coverage, (early, late))


def test_coverage_snapshot_preserves_equal_straddling_and_unknown_declarations() -> (
    None
):
    """Only definite early evidence is contradictory to a coverage snapshot."""
    artifact_hashes, record_hashes = coverage_inventory_hashes(25)
    coverage = coverage_record(25, "terms", HASH_A, artifact_hashes, record_hashes)

    equal = _availability("public", "2021-01-02T00:00:00Z")
    straddling = _availability(
        "public",
        "2021-01-03T00:00:00Z",
        lower="2021-01-01T00:00:00Z",
    )
    unknown = _availability("public", None)

    assert _with_coverage_availability(coverage, (equal,)).snapshot_at == parse_utc(
        "2021-01-02T00:00:00Z"
    )
    assert _with_coverage_availability(
        coverage, (straddling,)
    ).snapshot_at == parse_utc("2021-01-02T00:00:00Z")
    assert _with_coverage_availability(coverage, (unknown,)).snapshot_at == parse_utc(
        "2021-01-02T00:00:00Z"
    )


def test_coverage_preserves_scoped_split_action_classes_as_source_metadata() -> None:
    """Class completeness is query-specific, not inferred from one declaration."""
    artifact_hashes, record_hashes = coverage_inventory_hashes(3)
    coverage = coverage_record(
        3,
        "settlement",
        HASH_A,
        artifact_hashes,
        record_hashes,
        action_kinds=(ActionKind.FORWARD_SPLIT, ActionKind.REVERSE_SPLIT),
    )

    assert coverage.action_kinds == (
        ActionKind.FORWARD_SPLIT,
        ActionKind.REVERSE_SPLIT,
    )


def test_coverage_retains_report_only_occurrence_semantics_without_grouping_claim() -> (
    None
):
    """Report IDs remain source metadata, not proof that payouts are distinct."""
    artifact_hashes, record_hashes = coverage_inventory_hashes(4)
    coverage = coverage_record(
        4,
        "settlement",
        HASH_A,
        artifact_hashes,
        record_hashes,
        occurrence_key_semantics="report_ids_only",
    )

    assert coverage.occurrence_key_semantics == "report_ids_only"


@pytest.mark.parametrize("methodology", (None, "marketing-only"))
def test_coverage_requires_a_typed_methodology_artifact_reference(
    methodology: object,
) -> None:
    """A label or an absent reference is not retained methodology evidence."""
    artifact_hashes, record_hashes = coverage_inventory_hashes(5)
    coverage = coverage_record(5, "terms", HASH_A, artifact_hashes, record_hashes)

    with pytest.raises(ValidationError):
        coverage.model_copy(update={"methodology_reference": methodology})


def test_coverage_retains_current_only_revision_support_without_historical_claim() -> (
    None
):
    """Current-only is a declared limitation, not a locally invalid source row."""
    artifact_hashes, record_hashes = coverage_inventory_hashes(6)
    coverage = coverage_record(
        6,
        "effect",
        HASH_A,
        artifact_hashes,
        record_hashes,
        revision_support="current_only",
    )

    assert coverage.revision_support == "current_only"


def test_complete_coverage_rejects_gaps_and_exceptions() -> None:
    """A complete declaration cannot also enumerate a known omission."""
    artifact_hashes, record_hashes = coverage_inventory_hashes(7)
    coverage = coverage_record(7, "terms", HASH_A, artifact_hashes, record_hashes)

    values = {field: getattr(coverage, field) for field in type(coverage).model_fields}
    values["exceptions"] = ("holiday archive missing",)
    with pytest.raises(ValidationError, match="gaps or exceptions"):
        seal_record(EconomicCoverageVersionV1, values)


def test_inventory_hashes_are_unique_and_sorted_but_exact_empty_records_are_valid() -> (
    None
):
    """Inventory identity is canonical, while a validated empty dataset has no rows."""
    artifact_hashes, record_hashes = coverage_inventory_hashes(8)

    with pytest.raises(ValidationError, match="unique and sorted"):
        coverage_record(
            8,
            "terms",
            HASH_A,
            (artifact_hashes[1], artifact_hashes[0]),
            record_hashes,
        )
    with pytest.raises(ValidationError, match="unique and sorted"):
        coverage_record(
            9,
            "terms",
            HASH_A,
            artifact_hashes,
            (record_hashes[0], record_hashes[0]),
        )
    exact_empty = coverage_record(10, "terms", HASH_A, artifact_hashes, ())
    assert exact_empty.inventory_record_hashes == ()


def test_snapshot_is_normalized_to_utc_and_requires_timezone() -> None:
    """Coverage vintages compare instants, never lexical timestamp spellings."""
    artifact_hashes, record_hashes = coverage_inventory_hashes(10)
    coverage = coverage_record(
        10,
        "terms",
        HASH_A,
        artifact_hashes,
        record_hashes,
        snapshot_at="2021-01-01T18:00:00-06:00",
    )

    assert coverage.snapshot_at == datetime(2021, 1, 2, tzinfo=UTC)
    with pytest.raises(ValidationError, match="timezone-aware"):
        coverage.model_copy(update={"snapshot_at": datetime(2021, 1, 2)})


def test_complete_coverage_snapshot_cannot_precede_its_declared_scope() -> None:
    """A complete scope cannot reach beyond its locally retained snapshot instant."""
    artifact_hashes, record_hashes = coverage_inventory_hashes(11)

    with pytest.raises(ValidationError, match="snapshot"):
        coverage_record(
            11,
            "terms",
            HASH_A,
            artifact_hashes,
            record_hashes,
            snapshot_at="2021-01-01T00:00:00Z",
        )


def test_coverage_correction_preserves_the_prior_immutable_version() -> None:
    """A later correction is a new hash-bound version, not a mutable rewrite."""
    artifact_hashes, record_hashes = coverage_inventory_hashes(12)
    coverage = coverage_record(12, "terms", HASH_A, artifact_hashes, record_hashes)
    corrected = correct_coverage(
        coverage,
        13,
        "2021-01-03T00:00:00Z",
        changes={"security_id": uid(22)},
    )

    assert coverage.revision.source_sequence == 0
    assert coverage.completeness == "complete"
    assert coverage.security_id == uid(21)
    assert corrected.revision.source_sequence == 1
    assert corrected.security_id == uid(22)
    assert (
        corrected.revision.supersedes_record_version_id
        == coverage.revision.record_version_id
    )
    assert content_hash(corrected) != content_hash(coverage)
    assert (
        str(uid(22)) in support_bytes(corrected.revision.source_artifact).data.decode()
    )


def test_coverage_source_bytes_bind_security_identity() -> None:
    """Different security IDs with the same suffix and time change source bytes."""
    artifact_hashes, record_hashes = coverage_inventory_hashes(26)
    first = coverage_record(
        26, "terms", HASH_A, artifact_hashes, record_hashes, security_id=uid(21)
    )
    second = coverage_record(
        26, "terms", HASH_A, artifact_hashes, record_hashes, security_id=uid(22)
    )

    assert content_hash(first) != content_hash(second)
    assert (
        first.revision.source_artifact.content_hash
        != second.revision.source_artifact.content_hash
    )
    assert str(uid(21)) in support_bytes(first.revision.source_artifact).data.decode()
    assert str(uid(22)) in support_bytes(second.revision.source_artifact).data.decode()


def _with_coverage_availability(
    coverage: EconomicCoverageVersionV1,
    availability: tuple[AvailabilityEvidenceV1, ...],
) -> EconomicCoverageVersionV1:
    values = {field: getattr(coverage, field) for field in type(coverage).model_fields}
    values["revision"] = coverage.revision.model_copy(
        update={"availability": availability}
    )
    return rebind_coverage_evidence(values)


def _availability(
    channel: str, upper: str | None, *, lower: str | None = None
) -> AvailabilityEvidenceV1:
    if channel == "public":
        channel_value = AvailabilityChannelV1(
            kind=ChannelKind.PUBLIC, identifier="issuer-filings", version="v1"
        )
        basis = AvailabilityBasis.SOURCE_OBSERVED
    else:
        channel_value = AvailabilityChannelV1(
            kind=ChannelKind.VENDOR, identifier="vendor-feed", version="v1"
        )
        basis = AvailabilityBasis.VENDOR_DELIVERY
    if upper is None:
        return AvailabilityEvidenceV1(
            channel=channel_value,
            shape=AvailabilityShape.UNKNOWN,
            lower_bound=None,
            upper_bound=None,
            precision=SourcePrecision.UNKNOWN,
            source_time_label=None,
            source_timezone=None,
            basis=basis,
            evidence_reference=None,
        )
    upper_value = parse_utc(upper)
    if lower is None:
        return AvailabilityEvidenceV1(
            channel=channel_value,
            shape=AvailabilityShape.EXACT,
            lower_bound=upper_value,
            upper_bound=upper_value,
            precision=SourcePrecision.SECOND,
            source_time_label=upper,
            source_timezone=None,
            basis=basis,
            evidence_reference=None,
        )
    return AvailabilityEvidenceV1(
        channel=channel_value,
        shape=AvailabilityShape.BOUNDED,
        lower_bound=parse_utc(lower),
        upper_bound=upper_value,
        precision=SourcePrecision.INTERVAL,
        source_time_label=f"{lower}/{upper}",
        source_timezone=None,
        basis=basis,
        evidence_reference=None,
    )


def test_policy_identity_changes_when_source_scope_or_binding_changes() -> None:
    """Each source-policy decision is content-addressed by its actual boundaries."""
    policy = policy_fixture()
    settlement_owner = policy.owners[-1]
    source_changed = policy.model_copy(
        update={
            "owners": (
                *policy.owners[:-1],
                settlement_owner.model_copy(update={"source_id": "synthetic-b"}),
            ),
            "input_dataset_bindings": tuple(
                binding.model_copy(update={"source_id": "synthetic-b"})
                if binding.manifest_hash
                in {
                    settlement_owner.fact_manifest_hash,
                    settlement_owner.coverage_manifest_hash,
                }
                else binding
                for binding in policy.input_dataset_bindings
            ),
        }
    )
    scope_changed = policy.model_copy(
        update={"through": parse_utc("2021-01-02T00:00:00Z")}
    )
    binding_changed = policy.model_copy(
        update={
            "input_dataset_bindings": (
                policy.input_dataset_bindings[0].model_copy(
                    update={"bundle_hash": "f" * 64}
                ),
                *policy.input_dataset_bindings[1:],
            )
        }
    )

    assert (
        len(
            {
                content_hash(policy),
                content_hash(source_changed),
                content_hash(scope_changed),
                content_hash(binding_changed),
            }
        )
        == 4
    )


def test_policy_rejects_a_reversed_window() -> None:
    """A policy cannot silently reinterpret a backwards historical interval."""
    policy = policy_fixture()

    with pytest.raises(ValidationError, match="window reversed"):
        source_policy(
            uid(21),
            policy.input_dataset_bindings,
            policy.owners,
            parse_utc("2021-01-02T00:00:00Z"),
            parse_utc("2021-01-01T00:00:00Z"),
        )
