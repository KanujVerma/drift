"""Shared typed findings for fail-closed dataset validation."""

from collections.abc import Sequence
from enum import StrEnum

from drift.domain.artifacts import ArtifactReference
from drift.domain.common import FrozenModel, NonBlankStr
from drift.errors import DriftError


class FindingSeverity(StrEnum):
    """Severity assigned to one immutable validation finding."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ValidationFindingV1(FrozenModel):
    """One deterministic finding emitted by a dataset validator."""

    code: NonBlankStr
    severity: FindingSeverity
    message: NonBlankStr
    artifact_references: tuple[ArtifactReference, ...] = ()


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
