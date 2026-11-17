"""Canonical Stage 1 study report serialization and fresh-process rebuild.

Rebuilds from retained artifacts without contacting models or altering outcomes.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

from pydantic import model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash
from drift.experiments.stage1_study_outcomes import StudyOutcomeClassificationV1
from drift.experiments.stage1_uncertainty import PairedUncertaintyArtifactV1
from drift.serialization.canonical import canonical_json, content_hash


class StudyReportArtifactV1(FrozenModel):
    schema_version: Literal["drift-stage1-study-report/1"] = (
        "drift-stage1-study-report/1"
    )
    study_id: NonBlankStr
    protocol_hash: SHA256Hash
    mode: NonBlankStr
    scheduled_sessions: int
    observed_sessions: int
    primary_economic_advantage: Decimal | None
    uncertainty: PairedUncertaintyArtifactV1 | None = None
    outcome_classification: StudyOutcomeClassificationV1
    limitations: tuple[str, ...] = ()
    evidence_inventory: tuple[str, ...] = ()
    report_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        body = self.model_dump(mode="python", exclude={"report_hash"})
        if self.report_hash != content_hash(body):
            raise ValueError("STUDY_REPORT_HASH_MISMATCH")
        return self


def create_study_report(
    *,
    study_id: str,
    protocol_hash: str,
    mode: str,
    scheduled_sessions: int,
    observed_sessions: int,
    outcome_classification: StudyOutcomeClassificationV1,
    primary_economic_advantage: Decimal | None = None,
    uncertainty: PairedUncertaintyArtifactV1 | None = None,
    limitations: tuple[str, ...] = (),
    evidence_inventory: tuple[str, ...] = (),
) -> StudyReportArtifactV1:
    body = {
        "schema_version": "drift-stage1-study-report/1",
        "study_id": study_id,
        "protocol_hash": protocol_hash,
        "mode": mode,
        "scheduled_sessions": scheduled_sessions,
        "observed_sessions": observed_sessions,
        "primary_economic_advantage": primary_economic_advantage,
        "uncertainty": uncertainty,
        "outcome_classification": outcome_classification,
        "limitations": limitations,
        "evidence_inventory": evidence_inventory,
    }
    h = content_hash(body)
    return StudyReportArtifactV1.model_validate_json(
        canonical_json(body | {"report_hash": h})
    )
