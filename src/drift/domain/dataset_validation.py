"""Shared typed findings for fail-closed dataset validation."""

from collections.abc import Sequence
from enum import StrEnum
from typing import Literal

from pydantic import field_validator, model_validator

from drift.domain.artifacts import ArtifactReference
from drift.domain.common import (
    UUID7,
    FrozenModel,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)
from drift.domain.manifests import DatasetRoleV1, TemporalContractKindV2
from drift.domain.provenance_references import validate_safe_provenance_reference
from drift.errors import DriftError


class FindingSeverity(StrEnum):
    """Severity assigned to one immutable validation finding."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ValidationScope(StrEnum):
    """Depth reached by one exact-object validation decision."""

    MANIFEST_ONLY = "manifest_only"
    RECORDS = "records"


class ValidationResult(StrEnum):
    """Fail-closed result of validating the objects named by a decision."""

    PASS = "pass"
    FAIL = "fail"


class ValidationFindingV1(FrozenModel):
    """One deterministic finding emitted by a dataset validator."""

    code: NonBlankStr
    severity: FindingSeverity
    message: NonBlankStr
    artifact_references: tuple[ArtifactReference, ...] = ()

    @field_validator("artifact_references")
    @classmethod
    def reject_credential_bearing_locators(
        cls, references: tuple[ArtifactReference, ...]
    ) -> tuple[ArtifactReference, ...]:
        return tuple(validate_safe_provenance_reference(item) for item in references)


class ValidationRunContextV1(FrozenModel):
    """Caller-supplied identity of one immutable validation run."""

    decision_id: UUID7
    validator_version: NonBlankStr
    validator_implementation_hash: SHA256Hash
    validation_profile_id: NonBlankStr
    validation_profile_hash: SHA256Hash
    checked_at: UTCDateTime


class DatasetValidationDecisionV1(FrozenModel):
    """Exact hashes, contracts, context, and findings checked in one run."""

    decision_id: UUID7
    manifest_hash: SHA256Hash
    validator_version: NonBlankStr
    validator_implementation_hash: SHA256Hash
    validation_profile_id: NonBlankStr
    validation_profile_hash: SHA256Hash
    checked_at: UTCDateTime
    validation_scope: ValidationScope
    result: ValidationResult
    validated_artifact_hashes: tuple[SHA256Hash, ...]
    validated_record_hashes: tuple[SHA256Hash, ...] = ()
    checked_contracts: tuple[NonBlankStr, ...]
    findings: tuple[ValidationFindingV1, ...]

    @model_validator(mode="after")
    def validate_exact_decision(self) -> DatasetValidationDecisionV1:
        """Keep result, scope, and exact checked-object sets self-consistent."""
        for label, hashes in (
            ("artifact", self.validated_artifact_hashes),
            ("record", self.validated_record_hashes),
        ):
            if hashes != tuple(sorted(set(hashes))):
                msg = f"validated {label} hashes must be sorted and unique"
                raise ValueError(msg)
        if self.checked_contracts != tuple(sorted(set(self.checked_contracts))):
            msg = "checked contracts must be sorted and unique"
            raise ValueError(msg)

        has_errors = any(
            finding.severity is FindingSeverity.ERROR for finding in self.findings
        )
        if self.result is ValidationResult.PASS and has_errors:
            msg = "a passing decision cannot contain error findings"
            raise ValueError(msg)
        if self.result is ValidationResult.FAIL and not has_errors:
            msg = "a failed decision requires an error finding"
            raise ValueError(msg)

        if self.validation_scope is ValidationScope.MANIFEST_ONLY:
            if self.validated_record_hashes:
                msg = "manifest-only validation cannot contain record hashes"
                raise ValueError(msg)
        elif not self.validated_record_hashes:
            msg = "records validation requires nonempty record hashes"
            raise ValueError(msg)
        if (
            self.validation_scope is ValidationScope.RECORDS
            and "record-temporal-v1" not in self.checked_contracts
        ):
            msg = "records validation requires the record-temporal-v1 contract"
            raise ValueError(msg)
        if "dataset-manifest-v1" not in self.checked_contracts:
            msg = "validation requires the dataset-manifest-v1 contract"
            raise ValueError(msg)
        return self


class DatasetValidationDecisionV2(FrozenModel):
    """Exact V2 manifest, role, schema, contract, and object validation evidence."""

    decision_schema_version: Literal["2"]
    decision_id: UUID7
    manifest_hash: SHA256Hash
    manifest_schema_version: Literal["2"]
    dataset_role_hash: SHA256Hash
    schema_hash: SHA256Hash
    temporal_contract_kind: TemporalContractKindV2
    temporal_contract_version: Literal["1"]
    temporal_contract_hash: SHA256Hash
    validator_version: NonBlankStr
    validator_implementation_hash: SHA256Hash
    validation_profile_id: NonBlankStr
    validation_profile_hash: SHA256Hash
    checked_at: UTCDateTime
    validation_scope: ValidationScope
    result: ValidationResult
    validated_artifact_hashes: tuple[SHA256Hash, ...]
    validated_record_hashes: tuple[SHA256Hash, ...] = ()
    checked_contracts: tuple[NonBlankStr, ...]
    findings: tuple[ValidationFindingV1, ...]

    @model_validator(mode="after")
    def validate_exact_decision(self) -> DatasetValidationDecisionV2:
        for label, hashes in (
            ("artifact", self.validated_artifact_hashes),
            ("record", self.validated_record_hashes),
        ):
            if hashes != tuple(sorted(set(hashes))):
                msg = f"validated {label} hashes must be sorted and unique"
                raise ValueError(msg)
        if self.checked_contracts != tuple(sorted(set(self.checked_contracts))):
            msg = "checked contracts must be sorted and unique"
            raise ValueError(msg)
        if self.findings != tuple(
            sorted(
                self.findings,
                key=lambda item: (
                    item.code,
                    item.severity.value,
                    item.message,
                    tuple(ref.content_hash for ref in item.artifact_references),
                ),
            )
        ):
            msg = "validation findings must be in canonical order"
            raise ValueError(msg)

        has_errors = any(
            finding.severity is FindingSeverity.ERROR for finding in self.findings
        )
        if self.result is ValidationResult.PASS and has_errors:
            msg = "a passing decision cannot contain error findings"
            raise ValueError(msg)
        if self.result is ValidationResult.FAIL and not has_errors:
            msg = "a failed decision requires an error finding"
            raise ValueError(msg)
        if self.validation_scope is ValidationScope.MANIFEST_ONLY:
            if self.validated_record_hashes:
                msg = "manifest-only validation cannot contain record hashes"
                raise ValueError(msg)
        elif not self.validated_record_hashes:
            msg = "records validation requires nonempty record hashes"
            raise ValueError(msg)
        required_contract = self.temporal_contract_kind.value.replace("_", "-")
        if "dataset-manifest-v2" not in self.checked_contracts:
            msg = "V2 validation requires the dataset-manifest-v2 contract"
            raise ValueError(msg)
        if required_contract not in self.checked_contracts:
            msg = "V2 validation requires its actual temporal contract"
            raise ValueError(msg)
        return self


class ValidatedDatasetMemberV1(FrozenModel):
    """One role manifest and the exact passing decision that validated it."""

    dataset_role: DatasetRoleV1
    manifest_hash: SHA256Hash
    validation_decision_hash: SHA256Hash


class ValidatedDatasetBundleV1(FrozenModel):
    """Content-addressable set of independently validated role datasets."""

    schema_version: Literal["1"]
    bundle_id: UUID7
    bundle_version: NonBlankStr
    members: tuple[ValidatedDatasetMemberV1, ...]
    created_at: UTCDateTime

    @field_validator("members")
    @classmethod
    def canonicalize_members(
        cls, members: tuple[ValidatedDatasetMemberV1, ...]
    ) -> tuple[ValidatedDatasetMemberV1, ...]:
        if not members:
            msg = "validated dataset bundle members must not be empty"
            raise ValueError(msg)
        role_names = tuple(member.dataset_role.name for member in members)
        if len(set(role_names)) != len(role_names):
            msg = "validated dataset bundle roles must be unique"
            raise ValueError(msg)
        manifest_hashes = tuple(member.manifest_hash for member in members)
        if len(set(manifest_hashes)) != len(manifest_hashes):
            msg = "validated dataset bundle manifest hashes must be unique"
            raise ValueError(msg)
        return tuple(
            sorted(
                members,
                key=lambda member: (
                    member.dataset_role.name,
                    member.manifest_hash,
                ),
            )
        )


class DatasetValidationError(DriftError):
    """Raised when an input has one or more fail-closed validation findings."""

    def __init__(self, findings: Sequence[ValidationFindingV1]) -> None:
        self.findings = tuple(findings)
        super().__init__("; ".join(finding.code for finding in self.findings))

    @classmethod
    def single(cls, code: str) -> DatasetValidationError:
        """Build a one-finding error for a named validation failure."""
        return cls(
            (
                ValidationFindingV1(
                    code=code,
                    severity=FindingSeverity.ERROR,
                    message=code.replace("_", " "),
                ),
            )
        )
