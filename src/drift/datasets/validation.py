"""Dataset-level validation entry points shared by M1a consumers."""

from collections.abc import Sequence

from drift.domain.dataset_validation import ValidationFindingV1
from drift.domain.revisions import FactVersionV1, validate_revision_chain


def validate_fact_versions(
    versions: Sequence[FactVersionV1],
) -> tuple[ValidationFindingV1, ...]:
    """Validate an immutable fact-revision chain without selecting a cutoff."""
    return validate_revision_chain(versions)
