"""Immutable G3 protocol freeze with explicit, independently verified inputs.

A protocol hash proves identity, not source qualification or study efficacy.
Historical readiness requires a trusted host-selected original-evidence verifier;
no receipt-selected resolver, mutable defaults or silently pristine holdout.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol, Self

from pydantic import Field, model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.serialization.canonical import canonical_json, content_hash

STAGE1_UNIVERSE = (
    "VOO",
    "IJH",
    "IJR",
    "QQQ",
    "VEA",
    "VWO",
    "SHY",
    "IEF",
    "TLT",
    "TIP",
    "LQD",
    "GLD",
)
EvidenceRole = Literal[
    "g2_integration",
    "dataset_qualification",
    "mandate_review",
    "comparator_review",
    "cost_review",
    "model_replay",
    "scientific_protocol_review",
    "holdout_audit",
]
REQUIRED_ROLES: tuple[EvidenceRole, ...] = (
    "g2_integration",
    "dataset_qualification",
    "mandate_review",
    "comparator_review",
    "cost_review",
    "model_replay",
    "scientific_protocol_review",
    "holdout_audit",
)


class StudyDateWindowV1(FrozenModel):
    start: date
    end: date

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.start > self.end:
            raise ValueError("G3_WINDOW_REVERSED")
        return self


class StudyMandateV1(FrozenModel):
    maximum_etf_fraction: Decimal = Field(gt=0, le=1)
    maximum_equity_fraction: Decimal = Field(gt=0, le=1)
    maximum_bond_fraction: Decimal = Field(gt=0, le=1)
    maximum_gold_fraction: Decimal = Field(gt=0, le=1)
    maximum_gross_fraction: Decimal = Field(gt=0, le=1)
    maximum_turnover_fraction: Decimal = Field(gt=0, le=2)
    no_shorting: Literal[True] = True
    no_leverage: Literal[True] = True
    incoming_policy: Literal["REJECT"] = "REJECT"
    existing_breach_policy_hash: SHA256Hash
    feasibility_report_hash: SHA256Hash


class ConventionalSelectorPolicyV1(FrozenModel):
    formula: Literal["R:return-risk-drawdown-switchcost/1"]
    history_sessions: Literal[126] = 126
    volatility_penalty: Decimal = Field(ge=0, allow_inf_nan=False)
    drawdown_penalty: Decimal = Field(ge=0, allow_inf_nan=False)
    switching_cost_penalty: Decimal = Field(ge=0, allow_inf_nan=False)
    development_fit_hash: SHA256Hash
    executable_formula_hash: SHA256Hash
    tie_order: tuple[Literal["B3", "B4", "B5"], ...] = ("B3", "B4", "B5")

    @model_validator(mode="after")
    def exact_ties(self) -> Self:
        if self.tie_order != ("B3", "B4", "B5"):
            raise ValueError("G3_COMPARATOR_TIE_POLICY_CHANGED")
        return self


class StudyModelPolicyV1(FrozenModel):
    provider: NonBlankStr
    immutable_model_revision: NonBlankStr
    model_record_hash: SHA256Hash
    prompt_hash: SHA256Hash
    tools_policy_hash: SHA256Hash
    context_policy_hash: SHA256Hash
    feedback_policy_hash: SHA256Hash
    decoding_policy_hash: SHA256Hash
    seed: int = Field(strict=True, ge=0)
    known_training_cutoff: date | None = None


class StudyCostPolicyV1(FrozenModel):
    trading_model_hash: SHA256Hash
    dated_cost_evidence_hash: SHA256Hash
    operating_costs: Literal["ORIGINAL_RECEIPTS_NO_UNKNOWN_ZERO"] = (
        "ORIGINAL_RECEIPTS_NO_UNKNOWN_ZERO"
    )
    accounting: Literal["TRADING_IN_NAV_OPERATING_ATTRIBUTED_ONCE"] = (
        "TRADING_IN_NAV_OPERATING_ATTRIBUTED_ONCE"
    )


class StudyStatisticalPolicyV1(FrozenModel):
    primary_endpoint: Literal["PAIRED_NET_TERMINAL_RETURN_B_MINUS_R"] = (
        "PAIRED_NET_TERMINAL_RETURN_B_MINUS_R"
    )
    alpha: Decimal = Field(gt=0, lt=1)
    minimum_economic_advantage_fraction: Decimal = Field(ge=0, allow_inf_nan=False)
    uncertainty_method: Literal["STATIONARY_BLOCK_BOOTSTRAP"]
    bootstrap_repetitions: int = Field(strict=True, gt=0)
    bootstrap_seed: int = Field(strict=True, ge=0)
    block_length_policy_hash: SHA256Hash
    multiplicity_policy_hash: SHA256Hash
    stopping_policy_hash: SHA256Hash
    risk_free_policy_hash: SHA256Hash


class Stage1StudyDraftV1(FrozenModel):
    schema_version: Literal["drift-stage1-study/1"] = "drift-stage1-study/1"
    study_id: NonBlankStr
    created_at: UTCDateTime
    mode: Literal["RETROSPECTIVE_DISCOVERY", "CONFIRMATORY_HISTORICAL"]
    universe: tuple[str, ...] = STAGE1_UNIVERSE
    warmup_sessions: Literal[253] = 253
    observation_sessions: Literal[126] = 126
    families: tuple[Literal["B3", "B4", "B5"], ...] = ("B3", "B4", "B5")
    initial_family: Literal["B3"] = "B3"
    initial_capital: Literal["10000"] = "10000"
    currency: Literal["USD"] = "USD"
    schedule: Literal["MONTH_END_CLOSE_NEXT_ELIGIBLE_OPEN"] = (
        "MONTH_END_CLOSE_NEXT_ELIGIBLE_OPEN"
    )
    abstention: Literal["RETAIN_VALID_INCUMBENT"] = "RETAIN_VALID_INCUMBENT"
    development: StudyDateWindowV1
    validation: StudyDateWindowV1
    scoring: StudyDateWindowV1
    prior_holdout_exposure: Literal["UNKNOWN", "EXPOSED", "AUDITED_UNEXPOSED"]
    installed_source_hash: SHA256Hash | None = None
    dataset_manifest_hash: SHA256Hash | None = None
    calendar_and_universe_hash: SHA256Hash | None = None
    decision_cutoff_policy_hash: SHA256Hash | None = None
    seed_and_replication_policy_hash: SHA256Hash | None = None
    mandate: StudyMandateV1 | None = None
    comparator: ConventionalSelectorPolicyV1 | None = None
    model: StudyModelPolicyV1 | None = None
    costs: StudyCostPolicyV1 | None = None
    statistics: StudyStatisticalPolicyV1 | None = None

    @model_validator(mode="after")
    def validate_protocol(self) -> Self:
        if self.universe != STAGE1_UNIVERSE or self.families != ("B3", "B4", "B5"):
            raise ValueError("G3_PRIMARY_UNIVERSE_OR_ACTION_MENU_CHANGED")
        if not (
            self.development.end < self.validation.start
            and self.validation.end < self.scoring.start
        ):
            raise ValueError("G3_CHRONOLOGICAL_SPLITS_OVERLAP")
        return self

    @property
    def protocol_hash(self) -> str:
        return content_hash(self)


class StudyEvidenceReferenceV1(FrozenModel):
    role: EvidenceRole
    receipt_id: NonBlankStr
    receipt_hash: SHA256Hash
    protocol_hash: SHA256Hash
    accepted_at: UTCDateTime


class OriginalStudyEvidenceVerifier(Protocol):
    """Host-configured adapter to original, independently accepted receipts.

    Implementations must check the original issuer, signed or host-appointed
    trust root, exact receipt bytes, scope and assessor independence. A string
    or a caller's accepted=True field is not a conforming implementation.
    """

    def verify(self, reference: StudyEvidenceReferenceV1) -> bool: ...


class StudyReadinessV1(FrozenModel):
    protocol_hash: SHA256Hash
    status: Literal[
        "BLOCKED", "READY_FOR_HISTORICAL_DISCOVERY", "READY_FOR_CONFIRMATORY_SCORING"
    ]
    blockers: tuple[str, ...]
    verified_roles: tuple[EvidenceRole, ...]

    @property
    def authorizes_trading(self) -> bool:
        return False

    @property
    def establishes_efficacy(self) -> bool:
        return False


def assess_study_readiness(
    draft: Stage1StudyDraftV1,
    *,
    evidence: tuple[StudyEvidenceReferenceV1, ...] = (),
    verifier: OriginalStudyEvidenceVerifier | None = None,
    as_of: datetime | None = None,
) -> StudyReadinessV1:
    draft = Stage1StudyDraftV1.model_validate_json(canonical_json(draft))
    refs = tuple(
        StudyEvidenceReferenceV1.model_validate_json(canonical_json(ref))
        for ref in evidence
    )
    cutoff = draft.created_at if as_of is None else as_of
    if cutoff.tzinfo is None or cutoff.utcoffset() is None or cutoff < draft.created_at:
        raise ValueError("G3_INVALID_ACCEPTANCE_CUTOFF")
    blockers: set[str] = set()
    required = (
        "installed_source_hash",
        "dataset_manifest_hash",
        "calendar_and_universe_hash",
        "decision_cutoff_policy_hash",
        "seed_and_replication_policy_hash",
        "mandate",
        "comparator",
        "model",
        "costs",
        "statistics",
    )
    for field in required:
        if getattr(draft, field) is None:
            blockers.add("MISSING_CONFIGURATION:" + field)
    if draft.mode == "CONFIRMATORY_HISTORICAL":
        if draft.prior_holdout_exposure != "AUDITED_UNEXPOSED":
            blockers.add("HOLDOUT_NOT_AUDITED_UNEXPOSED")
        if (
            draft.model is None
            or draft.model.known_training_cutoff is None
            or draft.model.known_training_cutoff >= draft.scoring.start
        ):
            blockers.add("MODEL_PRETRAINING_CUTOFF_NOT_ELIGIBLE")
    verified: list[EvidenceRole] = []
    for role in REQUIRED_ROLES:
        matches = [ref for ref in refs if ref.role == role]
        if len(matches) != 1:
            blockers.add("MISSING_OR_DUPLICATE_ORIGINAL_EVIDENCE:" + role)
            continue
        ref = matches[0]
        if ref.protocol_hash != draft.protocol_hash:
            blockers.add("EVIDENCE_FOR_DIFFERENT_PROTOCOL:" + role)
            continue
        if ref.accepted_at > cutoff:
            blockers.add("ACCEPTANCE_NOT_YET_AVAILABLE:" + role)
            continue
        if verifier is None:
            blockers.add("ORIGINAL_VERIFIER_UNAVAILABLE:" + role)
            continue
        try:
            accepted = verifier.verify(ref)
        except Exception:
            # Provider outage or verifier failure is unavailability, never PASS.
            blockers.add("ORIGINAL_VERIFIER_FAILED:" + role)
            continue
        if accepted is not True:
            blockers.add("ORIGINAL_EVIDENCE_NOT_ACCEPTED:" + role)
            continue
        verified.append(role)
    status: Literal[
        "BLOCKED", "READY_FOR_HISTORICAL_DISCOVERY", "READY_FOR_CONFIRMATORY_SCORING"
    ] = "BLOCKED"
    if not blockers:
        status = (
            "READY_FOR_HISTORICAL_DISCOVERY"
            if draft.mode == "RETROSPECTIVE_DISCOVERY"
            else "READY_FOR_CONFIRMATORY_SCORING"
        )
    return StudyReadinessV1(
        protocol_hash=draft.protocol_hash,
        status=status,
        blockers=tuple(sorted(blockers)),
        verified_roles=tuple(verified),
    )


class FrozenStage1StudyV1(FrozenModel):
    schema_version: Literal["drift-stage1-freeze/1"] = "drift-stage1-freeze/1"
    protocol: Stage1StudyDraftV1
    frozen_at: UTCDateTime
    evidence: tuple[StudyEvidenceReferenceV1, ...]
    freeze_hash: SHA256Hash

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        if self.frozen_at < self.protocol.created_at:
            raise ValueError("G3_FREEZE_PRECEDES_PROTOCOL")
        body = self.model_dump(mode="python", exclude={"freeze_hash"})
        if self.freeze_hash != content_hash(body):
            raise ValueError("G3_FREEZE_HASH_MISMATCH")
        return self


def freeze_study(
    draft: Stage1StudyDraftV1,
    *,
    frozen_at: datetime,
    evidence: tuple[StudyEvidenceReferenceV1, ...],
    verifier: OriginalStudyEvidenceVerifier,
) -> FrozenStage1StudyV1:
    draft = Stage1StudyDraftV1.model_validate_json(canonical_json(draft))
    refs = tuple(
        sorted(
            (
                StudyEvidenceReferenceV1.model_validate_json(canonical_json(ref))
                for ref in evidence
            ),
            key=lambda ref: ref.role,
        )
    )
    readiness = assess_study_readiness(
        draft, evidence=refs, verifier=verifier, as_of=frozen_at
    )
    if readiness.status == "BLOCKED":
        raise ValueError("G3_FREEZE_BLOCKED:" + ";".join(readiness.blockers))
    body = {
        "schema_version": "drift-stage1-freeze/1",
        "protocol": draft,
        "frozen_at": frozen_at,
        "evidence": refs,
    }
    return FrozenStage1StudyV1.model_validate_json(
        canonical_json(body | {"freeze_hash": content_hash(body)})
    )


def verify_frozen_study(
    frozen: FrozenStage1StudyV1, *, verifier: OriginalStudyEvidenceVerifier
) -> StudyReadinessV1:
    """A deserialized freeze still needs its original acceptance receipts."""
    frozen = FrozenStage1StudyV1.model_validate_json(canonical_json(frozen))
    report = assess_study_readiness(
        frozen.protocol,
        evidence=frozen.evidence,
        verifier=verifier,
        as_of=frozen.frozen_at,
    )
    if report.status == "BLOCKED":
        raise ValueError("G3_FROZEN_EVIDENCE_UNAVAILABLE:" + ";".join(report.blockers))
    return report
