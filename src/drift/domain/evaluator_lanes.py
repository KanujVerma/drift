"""Domain models for M2 evaluation lanes, admission, and limitations."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash
from drift.domain.economic_closed_world import CORPORATE_ACTION_SNAPSHOT_LIMITATION
from drift.serialization.canonical import content_hash

LIMITATION_CA_ABSENCE_FROM_CURRENT_SNAPSHOT = CORPORATE_ACTION_SNAPSHOT_LIMITATION
"""Issue 76, decision D3-b: an exploratory closed-world corporate-action record
reads the absence of an action from one current provider snapshot. Every such
record carries this limitation, so every bundle carrying one requires it and
the promotion gate refuses it. The string is defined once, beside the record,
in ``drift.domain.economic_closed_world``; this is its lane-side name."""

ALPACA_LIMITATION_TRUNCATED_CA = (
    "corporate-action-mutation-replay-truncated-to-approx-72-days"
)
ALPACA_LIMITATION_UNVERSIONED_BARS = (
    "derived-bars-unversioned-without-provider-vintages"
)
ALPACA_LIMITATION_ABSENT_HALTS = "trading-halt-telemetry-absent-from-api"
ALPACA_LIMITATION_BOUNDED_COHORT = "evaluation-restricted-to-declared-bounded-cohort"
ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION = (
    "session-clock-reconstructed-from-scheduled-calendar-"
    "without-independent-realized-history"
)
ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION = (
    "strategy-inputs-retrospectively-reconstructed-from-audit-vintage-bars"
)
ALPACA_LIMITATION_COHORT_LISTING_ROLE = (
    "execution-listing-declared-by-cohort-not-historical-role-evidence"
)
ALPACA_LIMITATION_CALENDAR_CLOSED_WORLD = (
    "calendar-absence-read-as-closure-under-closed-world-assumption"
)


def exploratory_evaluation_admission_hash(
    admission: ExploratoryEvaluationAdmissionV1,
) -> SHA256Hash:
    """Compute canonical content hash for ExploratoryEvaluationAdmissionV1."""
    dump = admission.model_dump(mode="python")
    dump.pop("admission_hash", None)
    return content_hash(dump)


def promotion_evaluation_admission_hash(
    admission: PromotionEvaluationAdmissionV1,
) -> SHA256Hash:
    """Compute canonical content hash for PromotionEvaluationAdmissionV1."""
    dump = admission.model_dump(mode="python")
    dump.pop("admission_hash", None)
    return content_hash(dump)


class ExploratoryEvaluationAdmissionV1(FrozenModel):
    """Admission record gating evaluation in the exploratory lane."""

    schema_version: Literal["1"] = "1"
    lane: Literal["exploratory"] = "exploratory"
    input_bundle_hash: SHA256Hash
    acknowledged_limitations: tuple[NonBlankStr, ...]
    admission_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_admission(self) -> Self:
        if not self.acknowledged_limitations:
            raise ValueError("acknowledged_limitations must not be empty")
        if len(set(self.acknowledged_limitations)) != len(
            self.acknowledged_limitations
        ):
            raise ValueError("acknowledged_limitations entries must be unique")
        if (
            tuple(sorted(self.acknowledged_limitations))
            != self.acknowledged_limitations
        ):
            raise ValueError("acknowledged_limitations must be canonically sorted")
        expected = exploratory_evaluation_admission_hash(self)
        if self.admission_hash != expected:
            raise ValueError(
                f"admission hash mismatch: expected {expected}, "
                f"got {self.admission_hash}"
            )
        return self


class PromotionEvaluationAdmissionV1(FrozenModel):
    """Admission record gating evaluation in the promotion-grade lane.

    `provenance_proof_hash` binds the admission to the `BundleProvenanceProofV1`
    minted by replay verification. It is required, so a promotion-grade claim
    can never be made without an accepted provenance proof behind it.
    """

    schema_version: Literal["1"] = "1"
    lane: Literal["promotion"] = "promotion"
    m1e_completion_record_hash: SHA256Hash
    m1e_profile_set_hash: SHA256Hash
    decision_handoff_hash: SHA256Hash
    audit_handoff_hash: SHA256Hash
    input_bundle_hash: SHA256Hash
    provenance_proof_hash: SHA256Hash
    admission_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_admission(self) -> Self:
        expected = promotion_evaluation_admission_hash(self)
        if self.admission_hash != expected:
            raise ValueError(
                f"admission hash mismatch: expected {expected}, "
                f"got {self.admission_hash}"
            )
        return self


type EvaluationAdmissionV1 = Annotated[
    ExploratoryEvaluationAdmissionV1 | PromotionEvaluationAdmissionV1,
    Field(discriminator="lane"),
]
