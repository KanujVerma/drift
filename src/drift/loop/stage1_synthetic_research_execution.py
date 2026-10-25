"""Offline research -> installed strategy -> original M0 evidence candidate.

This coordinator is a local synthetic integration, NOT the accepted #513 grant
issuer, a numerical mandate, the scientific R policy, or E6B TrialRecordV1.
The host and installed Python are trusted; model choices are inert typed data.
All durable records use the existing SQLite ledger. Readers never create or
repair a ledger. G2/scientific/operational authority is deliberately not issued.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import zlib
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Literal, cast
from uuid import UUID, uuid7

from pydantic import BaseModel, Field, model_validator

from drift.baselines import (
    B3MonthlyEqualWeightRebalanceStrategy,
    B4MomentumStrategy,
    B5LowVolatilityStrategy,
)
from drift.baselines.common import extract_current_close_price
from drift.baselines.runner import (
    build_canonical_run_identity,
    build_canonical_specification,
    make_bundle_dataset_reference,
)
from drift.domain.common import ImmutableJSONValue
from drift.domain.evaluator_bundles import (
    EvaluationRunIdentityV2,
    strategy_parameters_hash,
)
from drift.domain.evaluator_exploratory_strategy import (
    ExploratoryStrategyDecisionContextV1,
)
from drift.domain.evaluator_portfolio import decimal_context
from drift.domain.evaluator_strategy import (
    StrategyDecisionContextV1,
    StrategyDecisionIntentV1,
    StrategyIntentRejectedError,
)
from drift.domain.evaluator_trace import (
    ExploratoryStrategyDecisionTraceEventV1,
    StrategyDecisionTraceEventV1,
)
from drift.domain.events import AuditEvent
from drift.domain.observation_query import drift_source_inventory_hash
from drift.domain.strategies import StrategyReference
from drift.evaluator.engine import SessionEvaluatorEngine
from drift.evaluator.experiment_runner import (
    ExperimentRunnerContext,
    execute_experiment_run,
)
from drift.evaluator.opening_book_lifecycle import (
    OpeningBookLifecycleError,
    parse_original_invocation_binding,
)
from drift.experiments.stage1_campaign_config import (
    ArmSpecV1,
    CampaignSpecV1,
    RunAccountBindingV1,
)
from drift.experiments.stage1_trial_provenance import (
    Stage1TrialProvenanceSnapshotV1,
    verify_stage1_trial_provenance_snapshot,
)
from drift.intelligence.contracts import (
    ArtifactReference,
    ImmutableModel,
    RawChoice,
    ResearchCandidate,
    ResearchContext,
)
from drift.intelligence.conventional_selector import (
    ConventionalSelectorResult,
    select_conventional_candidate,
)
from drift.intelligence.proposal_producer import (
    FakeTransport,
    ProducerResult,
    produce_proposal,
)
from drift.intelligence.receipts import ResearchReceiptStore
from drift.intelligence.validation import ResolvedDependencies, StrategyRegistration
from drift.ledger.interface import AuditEventDraft
from drift.ledger.sqlite import SQLiteLedger
from drift.ledger.stage1_synthetic_account_receipts import (
    BOUND_PROFILE,
    CLAIM,
    CONSUMED,
    AccountAllocationFieldsV1,
    ConfiguredLocalSyntheticOriginV1,
    LocalEventReferenceV1,
    LocalSyntheticAccountReceiptStoreV1,
    OriginalLocalAccountReadbackV1,
)
from drift.ledger.stage1_synthetic_account_receipts import (
    ENTITY as ACCOUNT_ENTITY,
)
from drift.loop.stage1_original_result_association import (
    LocalOriginalResultReadbackV1,
    Stage1OriginalResultAssociationV1,
    read_original_result,
)
from drift.loop.stage1_synthetic_account_lifecycle import (
    Stage1SyntheticAccountLifecycleV1,
)
from drift.serialization.canonical import canonical_json, content_hash

PROFILE = "drift-synthetic-research-execution/1-candidate"
ENTITY = "stage1_synthetic_research_execution"
OPPORTUNITY = "stage1.synthetic_research.opportunity"
RESEARCH = "stage1.synthetic_research.original_output"
RESERVATION = "stage1.synthetic_research.m0_reservation"
OUTCOME = "stage1.synthetic_research.outcome"
MAX_RECORD_BYTES = 1_048_576
MAX_DECISION_CONTEXT_BYTES = 33_554_432
_INLINE_CONTEXT_BYTES = MAX_RECORD_BYTES // 2
_PROOF_METADATA_RESERVE = 16_384
_PHASES = (OPPORTUNITY, RESEARCH, RESERVATION, OUTCOME)
_PAYLOAD_KEYS = frozenset({"profile", "issuer_instance_id", "body_utf8", "body_hash"})
_FAMILIES = ("B3", "B4", "B5")


def _stamp(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("SYNTHETIC_CLOCK_REQUIRES_AWARE_DATETIME")
    return value.astimezone(UTC)


def _clone[T: BaseModel](cls: type[T], value: T) -> T:
    if type(value) is not cls:
        raise ValueError(f"EXACT_TYPED_INPUT_REQUIRED:{cls.__name__}")
    return cls.model_validate_json(canonical_json(value.model_dump(mode="python")))


def _finite_score(value: str) -> Decimal:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or "e" in value.lower()
    ):
        raise ValueError("FIXTURE_SCORE_REQUIRES_PLAIN_DECIMAL")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("INVALID_FIXTURE_SCORE") from error
    if not result.is_finite():
        raise ValueError("INVALID_FIXTURE_SCORE")
    return result


class OfflineResearchRequestV1(ImmutableModel):
    """Explicit scripted inputs, not a provider adapter or approved R formula."""

    mode: Literal["scripted_fixture", "conventional_fixture"]
    deadline: datetime
    scripted_choice: RawChoice | None = None
    candidate_pool: tuple[RawChoice, ...] = ()
    fixture_scores: Mapping[str, str] = Field(default_factory=dict)
    should_timeout: bool = Field(default=False, strict=True)
    malformed_output: str | None = None
    synthetic_cost_amount: str = "0"

    @model_validator(mode="after")
    def validate_request(self) -> OfflineResearchRequestV1:
        _stamp(self.deadline)
        if self.mode == "scripted_fixture":
            if self.candidate_pool or self.fixture_scores:
                raise ValueError("SCRIPTED_REQUEST_CANNOT_HAVE_COMPARATOR")
        else:
            if (
                self.scripted_choice is not None
                or self.should_timeout
                or self.malformed_output is not None
            ):
                raise ValueError("COMPARATOR_REQUEST_CANNOT_HAVE_TRANSPORT")
            if self.synthetic_cost_amount != "0":
                raise ValueError("COMPARATOR_HAS_NO_SCRIPTED_TRANSPORT_BILL")
            for family, score in self.fixture_scores.items():
                if family not in _FAMILIES:
                    raise ValueError("UNSUPPORTED_FIXTURE_SCORE_FAMILY")
                _finite_score(score)
        return self


type _InstalledStrategy = (
    B3MonthlyEqualWeightRebalanceStrategy | B4MomentumStrategy | B5LowVolatilityStrategy
)


def _installed(family: str) -> _InstalledStrategy:
    if type(family) is not str:
        raise ValueError("UNSUPPORTED_INSTALLED_STRATEGY")
    if family == "B3":
        return B3MonthlyEqualWeightRebalanceStrategy()
    if family == "B4":
        return B4MomentumStrategy()
    if family == "B5":
        return B5LowVolatilityStrategy()
    raise ValueError("UNSUPPORTED_INSTALLED_STRATEGY")


def installed_strategy_registration(family: str) -> StrategyRegistration:
    """Resolve only installed default constructors; never import a caller name."""
    strategy = _installed(family)
    reference = strategy.strategy_reference
    parameters = strategy_parameters_hash(strategy.strategy_parameters)
    return StrategyRegistration(
        family_id=family,
        strategy_ref=ArtifactReference(
            id=str(reference.strategy_id),
            version=reference.strategy_version,
            sha256=reference.code_hash,
        ),
        envelope_ref=ArtifactReference(
            id=f"synthetic:installed:{family}:parameters",
            version=PROFILE,
            sha256=parameters,
        ),
        eligibility_ref=ArtifactReference(
            id=f"synthetic:installed:{family}:not-source-qualified",
            version=PROFILE,
            sha256=content_hash({"family": family, "synthetic_only": True}),
        ),
        allowed_parameters={},
    )


def installed_registry_reference() -> ArtifactReference:
    return ArtifactReference(
        id="synthetic:installed-B3-B4-B5",
        version=PROFILE,
        sha256=content_hash(
            tuple(
                installed_strategy_registration(family).model_dump(mode="python")
                for family in _FAMILIES
            )
        ),
    )


def synthetic_universe_reference(securities: Sequence[UUID]) -> ArtifactReference:
    if type(securities) not in (tuple, list) or any(
        type(s) is not UUID for s in securities
    ):
        raise ValueError("SYNTHETIC_UNIVERSE_REQUIRES_EXACT_UUIDS")
    if not securities or len(set(securities)) != len(securities):
        raise ValueError("SYNTHETIC_UNIVERSE_NOT_UNIQUE")
    return ArtifactReference(
        id="synthetic:installed-evaluator-universe",
        version=PROFILE,
        sha256=content_hash(
            tuple(str(s) for s in sorted(securities, key=lambda s: s.bytes))
        ),
    )


def original_portfolio_reference(
    original: OriginalLocalAccountReadbackV1,
) -> ArtifactReference:
    return ArtifactReference(
        id=original.fields.portfolio_account_id,
        version=PROFILE,
        sha256=hashlib.sha256(original.original_book_bytes).hexdigest(),
    )


class _Opportunity(ImmutableModel):
    snapshot_fingerprint: str
    scope_fingerprint: str
    allocation_id: str
    allocation_event_id: str
    allocation_event_hash: str
    witness_event_id: str
    witness_event_hash: str
    account_fields: Mapping[str, str]
    context: ResearchContext
    request: OfflineResearchRequestV1
    input_bundle_hash: str
    protocol_hash: str
    admission_hash: str
    cost_model_hash: str
    evaluator_evidence_hash: str
    source_inventory_hash: str
    securities: tuple[str, ...]
    allowed_families: tuple[str, ...]


class _Research(ImmutableModel):
    opportunity_hash: str
    producer_at: datetime
    output_utf8: str
    receipt_journal_utf8: str


class _Reservation(ImmutableModel):
    research_hash: str
    candidate_hash: str
    family: Literal["B3", "B4", "B5"]
    strategy_hash: str
    parameter_hash: str
    m0_run_id: str
    m0_audit_event_id: str


class _Outcome(ImmutableModel):
    research_hash: str
    reservation_hash: str | None = None
    status: Literal["NO_DISPATCH", "M0_RETURNED", "M0_FAILED"]
    reason: str
    m0_run_id: str | None = None
    association_event_id: str | None = None
    association_event_hash: str | None = None
    first_context_kind: Literal["realized", "reconstructed"] | None = None
    first_context_utf8: str | None = None
    first_intent_utf8: str | None = None


class _CompressedDecisionContextV1(ImmutableModel):
    """Lossless bounded transport of original canonical decision-context bytes."""

    profile: Literal["drift-synthetic-decision-context/1"] = (
        "drift-synthetic-decision-context/1"
    )
    encoding: Literal["zlib-base64"] = "zlib-base64"
    uncompressed_size: int = Field(strict=True, gt=0, le=MAX_DECISION_CONTEXT_BYTES)
    sha256: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")
    data: str = Field(strict=True, min_length=1, max_length=MAX_RECORD_BYTES)


class _OutcomeV2(_Outcome):
    """Only large successful-return proofs use this additive outcome version."""

    first_context_artifact: _CompressedDecisionContextV1

    @model_validator(mode="after")
    def require_one_context(self) -> _OutcomeV2:
        if (
            self.status != "M0_RETURNED"
            or self.first_context_utf8 is not None
            or self.first_context_kind is None
            or self.first_intent_utf8 is None
        ):
            raise ValueError("COMPRESSED_CONTEXT_OUTCOME_INVALID")
        return self


def _encode_context(
    original: bytes,
) -> tuple[str | None, _CompressedDecisionContextV1 | None]:
    if not original or len(original) > MAX_DECISION_CONTEXT_BYTES:
        raise ValueError("DECISION_CONTEXT_DECODED_BOUND_EXCEEDED")
    if len(original) <= _INLINE_CONTEXT_BYTES:
        return original.decode("utf-8"), None
    artifact = _CompressedDecisionContextV1(
        uncompressed_size=len(original),
        sha256=hashlib.sha256(original).hexdigest(),
        data=base64.b64encode(zlib.compress(original, level=9)).decode("ascii"),
    )
    return None, artifact


def _decode_context(artifact: _CompressedDecisionContextV1) -> dict[str, object]:
    artifact = _clone(_CompressedDecisionContextV1, artifact)
    try:
        compressed = base64.b64decode(artifact.data, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("DECISION_CONTEXT_BASE64_INVALID") from error
    if base64.b64encode(compressed).decode("ascii") != artifact.data:
        raise ValueError("DECISION_CONTEXT_BASE64_NONCANONICAL")
    decoder = zlib.decompressobj()
    try:
        original = decoder.decompress(compressed, artifact.uncompressed_size + 1)
    except zlib.error as error:
        raise ValueError("DECISION_CONTEXT_ZLIB_INVALID") from error
    # No unbounded flush. Refuse truncated streams, trailing bytes, additional
    # streams and dishonest advertised sizes, even if a prefix looks genuine.
    if (
        len(original) != artifact.uncompressed_size
        or not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
    ):
        raise ValueError("DECISION_CONTEXT_STREAM_OR_LENGTH_INVALID")
    if hashlib.sha256(original).hexdigest() != artifact.sha256:
        raise ValueError("DECISION_CONTEXT_ORIGINAL_HASH_MISMATCH")
    return _json_object(
        original.decode("utf-8"), maximum_bytes=MAX_DECISION_CONTEXT_BYTES
    )


@dataclass(frozen=True, slots=True)
class SyntheticResearchExecutionReadback:
    """Locally verified mechanics only. Never a released scientific trial."""

    opportunity_ref: LocalEventReferenceV1
    trial_id: str
    state: str
    disposition: str | None
    reason: str
    research_receipt_hashes: tuple[str, ...]
    candidate_hash: str | None
    original_result: LocalOriginalResultReadbackV1 | None
    reported_research_cost_usd: Decimal | None

    @property
    def g2_accepted(self) -> bool:
        return False

    @property
    def scientifically_qualified(self) -> bool:
        return False

    @property
    def authorizes_trading(self) -> bool:
        return False


def _json_object(
    text: str, *, maximum_bytes: int = MAX_RECORD_BYTES
) -> dict[str, object]:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("DUPLICATE_EXECUTION_JSON_KEY")
            result[key] = value
        return result

    def invalid(value: str) -> object:
        raise ValueError(f"NONFINITE_EXECUTION_JSON:{value}")

    if type(text) is not str or len(text.encode("utf-8")) > maximum_bytes:
        raise ValueError("EXECUTION_RECORD_TOO_LARGE_OR_NOT_TEXT")
    decoded = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)
    if type(decoded) is not dict or canonical_json(decoded) != text.encode("utf-8"):
        raise ValueError("EXECUTION_RECORD_NOT_CANONICAL")
    return decoded


def _record[T: BaseModel](
    event: AuditEvent, cls: type[T], origin: ConfiguredLocalSyntheticOriginV1
) -> T:
    payload = event.payload
    if (
        not isinstance(payload, Mapping)
        or set(payload) != _PAYLOAD_KEYS
        or payload["profile"] != PROFILE
        or payload["issuer_instance_id"] != str(origin.issuer_instance_id)
        or event.entity_type != ENTITY
        or event.schema_version != ("2" if cls is _OutcomeV2 else "1")
        or (cls is _OutcomeV2 and event.event_type != OUTCOME)
    ):
        raise ValueError("EXECUTION_EVENT_OR_ORIGIN_MISMATCH")
    text = payload["body_utf8"]
    if type(text) is not str:
        raise ValueError("EXECUTION_RECORD_NOT_TEXT")
    decoded = _json_object(text)
    if payload["body_hash"] != content_hash(decoded):
        raise ValueError("EXECUTION_RECORD_HASH_MISMATCH")
    return cls.model_validate(decoded)


def _append(
    origin: ConfiguredLocalSyntheticOriginV1,
    *,
    phase: str,
    allocation_id: UUID,
    trial_id: str,
    body: BaseModel,
    timestamp: datetime,
) -> AuditEvent:
    encoded = canonical_json(body.model_dump(mode="python"))
    if len(encoded) > MAX_RECORD_BYTES:
        raise ValueError("EXECUTION_RECORD_TOO_LARGE")
    payload = {
        "profile": PROFILE,
        "issuer_instance_id": str(origin.issuer_instance_id),
        "body_utf8": encoded.decode("utf-8"),
        "body_hash": hashlib.sha256(encoded).hexdigest(),
    }
    if len(canonical_json(payload)) > MAX_RECORD_BYTES:
        raise ValueError("EXECUTION_RECORD_TOO_LARGE")
    # Only the writer may create its store. This root already has the prepared
    # account; read-only opening proves that it exists before the writer opens.
    origin.verified_events()
    return SQLiteLedger(origin.ledger_path).append(
        AuditEventDraft(
            event_id=uuid7(),
            event_type=phase,
            timestamp=_stamp(timestamp),
            entity_type=ENTITY,
            entity_id=allocation_id,
            payload=payload,
            deduplication_key=f"stage1:synthetic-research:{allocation_id}:{phase}",
            schema_version="2" if type(body) is _OutcomeV2 else "1",
        )
    )


def _resolved(plan: _Opportunity) -> ResolvedDependencies:
    context = plan.context
    return ResolvedDependencies(
        portfolio_ref=context.portfolio_ref,
        mandate_ref=context.mandate_ref,
        universe_ref=context.universe_ref,
        registry_ref=context.registry_ref,
        method_ref=context.method_ref,
        admitted_securities=plan.securities,
        strategy_registry={
            family: installed_strategy_registration(family)
            for family in plan.allowed_families
        },
        # A fresh book is not an executed incumbent. The arm's initial-family
        # label cannot authenticate a hold; the K1 validator must refuse it.
        current_selection=None,
    )


def _produce_unpinned(
    plan: _Opportunity, trial_id: str, at: datetime
) -> tuple[ProducerResult | ConventionalSelectorResult, ResearchReceiptStore]:
    request = plan.request
    context = plan.context
    recorder = ResearchReceiptStore()
    policy = ArtifactReference(
        id="synthetic:execution-validation",
        version=PROFILE,
        sha256=content_hash(PROFILE),
    )
    attempt_id = f"{trial_id}:K1-001"
    logical_id = f"{trial_id}:REQUEST-001"
    if request.mode == "scripted_fixture":
        output = produce_proposal(
            context=context,
            resolved_inputs=_resolved(plan),
            frozen_method=context.method_ref,
            validation_policy=policy,
            recorder=recorder,
            attempt_id=attempt_id,
            logical_request_id=logical_id,
            checked_at=at,
            valid_until=request.deadline,
            transport=FakeTransport(
                raw_choice=request.scripted_choice,
                should_timeout=request.should_timeout,
                malformed_json=request.malformed_output,
                cost_amount=request.synthetic_cost_amount,
            ),
        )
        return output, recorder

    def score(candidate: ResearchCandidate) -> Decimal:
        family = candidate.strategy.family_id if candidate.strategy else ""
        if family not in request.fixture_scores:
            raise ValueError("MISSING_EXPLICIT_FIXTURE_SCORE")
        return _finite_score(request.fixture_scores[family])

    comparison = select_conventional_candidate(
        context=context,
        resolved_inputs=_resolved(plan),
        candidate_pool=request.candidate_pool,
        objective_fn=score,
        method_ref=context.method_ref,
        validation_policy=policy,
        recorder=recorder,
        attempt_id=attempt_id,
        logical_request_id=logical_id,
        checked_at=at,
        valid_until=request.deadline,
    )
    return comparison, recorder


def _produce(
    plan: _Opportunity, trial_id: str, at: datetime
) -> tuple[ProducerResult | ConventionalSelectorResult, ResearchReceiptStore]:
    # Replaying the same retained fixture must not depend on ambient precision.
    with decimal_context():
        return _produce_unpinned(plan, trial_id, at)


def _candidate(
    output: ProducerResult | ConventionalSelectorResult,
) -> ResearchCandidate | None:
    return (
        output.candidate
        if isinstance(output, ProducerResult)
        else output.selected_candidate
    )


class _FirstDecisionGuard:
    """Preserve installed intents; refuse an incompatible first proposed target.

    The guard does not allocate weights or change an approved strategy's rules.
    It is NOT a mandate gate, a monthly-switch scheduler or hostile-code sandbox.
    """

    def __init__(self, candidate: ResearchCandidate, cutoff: datetime) -> None:
        self._candidate = _clone(ResearchCandidate, candidate)
        choice = self._candidate.strategy
        if choice is None or choice.parameters:
            raise ValueError("INSTALLED_SELECTION_REQUIRES_UNTUNED_STRATEGY")
        self._strategy = _installed(choice.family_id)
        registration = installed_strategy_registration(choice.family_id)
        if (
            choice.strategy_ref != registration.strategy_ref
            or choice.envelope_ref != registration.envelope_ref
            or choice.eligibility_ref != registration.eligibility_ref
        ):
            raise ValueError("INSTALLED_SELECTION_BINDING_MISMATCH")
        if (
            self._candidate.cash_weight is None
            or (
                Fraction(Decimal(self._candidate.cash_weight))
                + sum(
                    (
                        Fraction(Decimal(item.weight))
                        for item in self._candidate.targets
                    ),
                    Fraction(0),
                )
            )
            != 1
        ):
            raise ValueError("RESEARCH_EXACT_WEIGHT_SUM_MISMATCH")
        self._cutoff = _stamp(cutoff)
        self._checked = False
        self.first_context_kind: Literal["realized", "reconstructed"] | None = None
        self.first_context_utf8: str | None = None
        self.first_intent_utf8: str | None = None
        self.first_context_artifact: _CompressedDecisionContextV1 | None = None

    @property
    def strategy_reference(self) -> StrategyReference:
        return self._strategy.strategy_reference

    @property
    def strategy_parameters(self) -> ImmutableJSONValue:
        return self._strategy.strategy_parameters

    def _guard(
        self,
        context: StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1,
        intent: StrategyDecisionIntentV1,
    ) -> StrategyDecisionIntentV1:
        if self._checked:
            return intent
        if context.decision_cutoff != self._cutoff:
            raise StrategyIntentRejectedError("RESEARCH_EXECUTION_CUTOFF_MISMATCH")
        proposed: dict[UUID, int] = {}
        for target in self._candidate.targets:
            security = UUID(target.security_id)
            price = extract_current_close_price(context, security)
            if price is None or price <= 0:
                raise StrategyIntentRejectedError(
                    "RESEARCH_EXECUTION_PRICE_UNAVAILABLE"
                )
            quantity = int(
                Fraction(context.portfolio_nav)
                * Fraction(Decimal(target.weight))
                / Fraction(price)
            )
            if quantity:
                proposed[security] = quantity
        actual = {
            item.security_id: item.target_quantity
            for item in intent.targets
            if item.target_quantity > 0
        }
        if not actual or actual != proposed:
            raise StrategyIntentRejectedError("RESEARCH_INSTALLED_TARGET_MISMATCH")
        self.first_context_kind = (
            "realized"
            if type(context) is StrategyDecisionContextV1
            else "reconstructed"
        )
        self.first_context_utf8, self.first_context_artifact = _encode_context(
            canonical_json(context)
        )
        self.first_intent_utf8 = canonical_json(intent).decode("utf-8")
        proof = {
            "first_context_kind": self.first_context_kind,
            "first_context_utf8": self.first_context_utf8,
            "first_context_artifact": self.first_context_artifact,
            "first_intent_utf8": self.first_intent_utf8,
        }
        payload_size = len(
            canonical_json({"body_utf8": canonical_json(proof).decode("utf-8")})
        )
        if payload_size > MAX_RECORD_BYTES - _PROOF_METADATA_RESERVE:
            raise StrategyIntentRejectedError("FIRST_DECISION_PROOF_TOO_LARGE")
        self._checked = True
        return intent

    def decide(self, context: StrategyDecisionContextV1) -> StrategyDecisionIntentV1:
        return self._guard(context, self._strategy.decide(context))

    def decide_exploratory(
        self, context: ExploratoryStrategyDecisionContextV1
    ) -> StrategyDecisionIntentV1:
        return self._guard(context, self._strategy.decide_exploratory(context))


def _completed_outcome(
    *,
    research_hash: str,
    reservation_hash: str,
    m0_run_id: str,
    association: LocalEventReferenceV1,
    reason: str,
    guarded: _FirstDecisionGuard,
) -> _Outcome:
    legacy = _Outcome(
        research_hash=research_hash,
        reservation_hash=reservation_hash,
        status="M0_RETURNED",
        reason=reason,
        m0_run_id=m0_run_id,
        association_event_id=str(association.event_id),
        association_event_hash=association.event_hash,
        first_context_kind=guarded.first_context_kind,
        first_context_utf8=guarded.first_context_utf8,
        first_intent_utf8=guarded.first_intent_utf8,
    )
    if guarded.first_context_artifact is None:
        return legacy
    return _OutcomeV2.model_validate(
        legacy.model_dump(mode="python")
        | {"first_context_artifact": guarded.first_context_artifact}
    )


def _verify_context(
    plan: _Opportunity,
    *,
    provenance: Stage1TrialProvenanceSnapshotV1,
    original: OriginalLocalAccountReadbackV1,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
) -> None:
    scope, context = provenance.scope, plan.context
    arm = next(item for item in arms if item.arm_id == scope.arm_id)
    mode = {
        "ADAPTIVE_AI": "scripted_fixture",
        "DETERMINISTIC_COMPARATOR": "conventional_fixture",
    }.get(arm.selector_type)
    securities = tuple(UUID(item) for item in plan.securities)
    if (
        plan.request.mode != mode
        or plan.allowed_families
        != tuple(
            family
            for family in _FAMILIES
            if family in arm.eligible_strategy_references
            and family in campaign.allowed_strategy_families
        )
        or context.scope.experiment_id != campaign.campaign_id
        or context.scope.campaign_ref.version != campaign.schema_version
        or plan.protocol_hash != original.fields.protocol_hash
        or plan.admission_hash != original.fields.admission_hash
        or plan.snapshot_fingerprint != provenance.snapshot_fingerprint
        or plan.scope_fingerprint != content_hash(asdict(scope))
        or plan.allocation_id != str(original.allocation_id)
        or plan.account_fields != asdict(original.fields)
        or plan.allocation_event_id != str(original.allocation_ref.event_id)
        or plan.allocation_event_hash != original.allocation_ref.event_hash
        or plan.witness_event_id != str(original.witness_ref.event_id)
        or plan.witness_event_hash != original.witness_ref.event_hash
        or context.source_grade != "synthetic_fixture"
        or context.scope.account_id != scope.run_account_binding.portfolio_account_id
        or context.scope.arm_id != scope.arm_id
        or context.scope.campaign_ref.id != scope.campaign_id
        or context.scope.campaign_ref.sha256 != scope.campaign_spec_fingerprint
        or context.portfolio_ref != original_portfolio_reference(original)
        or context.universe_ref != synthetic_universe_reference(securities)
        or context.registry_ref != installed_registry_reference()
        or plan.source_inventory_hash != drift_source_inventory_hash()
    ):
        raise ValueError("RESEARCH_ORIGINAL_SCOPE_OR_SOURCE_MISMATCH")


def execute_synthetic_research(
    *,
    origin: ConfiguredLocalSyntheticOriginV1,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
    provenance: Stage1TrialProvenanceSnapshotV1,
    account: Stage1SyntheticAccountLifecycleV1,
    engine: SessionEvaluatorEngine,
    context: ResearchContext,
    request: OfflineResearchRequestV1,
    clock: Callable[[], datetime],
) -> SyntheticResearchExecutionReadback:
    """Run one offline opportunity once; uncertain appends never permit retry.

    ``origin``, engine/account and clock are the trusted synthetic host's
    configuration, not values resolved from an untrusted candidate. Accepted
    original issuer and risk/mandate authorization are still absent.
    """
    if (
        type(origin) is not ConfiguredLocalSyntheticOriginV1
        or type(engine) is not SessionEvaluatorEngine
    ):
        raise ValueError("EXACT_CONFIGURED_SYNTHETIC_HOST_REQUIRED")
    if type(account) is not Stage1SyntheticAccountLifecycleV1:
        raise ValueError("EXACT_PREPARED_ACCOUNT_REQUIRED")
    campaign = deepcopy(campaign)
    arms, bindings, runs = (
        deepcopy(tuple(arms)),
        deepcopy(tuple(bindings)),
        tuple(expected_run_ids),
    )
    provenance = deepcopy(provenance)
    if campaign.campaign_type != "SYNTHETIC_TEST":
        raise ValueError("SYNTHETIC_CAMPAIGN_ONLY")
    verify_stage1_trial_provenance_snapshot(
        snapshot=provenance,
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=runs,
    )
    context = _clone(ResearchContext, context)
    request = _clone(OfflineResearchRequestV1, request)
    original = account.verified_original()
    # Constructing the existing observer verifies the account/E1 identity before
    # any new research event. It does not make its issuer-authentication true.
    observer = Stage1OriginalResultAssociationV1(
        origin=origin,
        account=account,
        provenance=provenance,
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=runs,
        clock=clock,
    )
    securities = tuple(
        str(item.security_id) for item in engine.bundle.security_identities
    )
    plan = _Opportunity(
        snapshot_fingerprint=provenance.snapshot_fingerprint,
        scope_fingerprint=content_hash(asdict(provenance.scope)),
        allocation_id=str(original.allocation_id),
        allocation_event_id=str(original.allocation_ref.event_id),
        allocation_event_hash=original.allocation_ref.event_hash,
        witness_event_id=str(original.witness_ref.event_id),
        witness_event_hash=original.witness_ref.event_hash,
        account_fields=asdict(original.fields),
        context=context,
        request=request,
        input_bundle_hash=engine.bundle.bundle_hash,
        protocol_hash=engine.protocol.protocol_hash,
        admission_hash=engine.admission.admission_hash,
        cost_model_hash=engine.cost_model.cost_model_hash,
        evaluator_evidence_hash=engine.evaluator_evidence_hash,
        source_inventory_hash=drift_source_inventory_hash(),
        securities=securities,
        allowed_families=tuple(
            family
            for family in _FAMILIES
            if family
            in next(
                arm for arm in arms if arm.arm_id == provenance.scope.arm_id
            ).eligible_strategy_references
            and family in campaign.allowed_strategy_families
        ),
    )
    _verify_context(
        plan, provenance=provenance, original=original, campaign=campaign, arms=arms
    )
    at = _stamp(clock())
    if (
        at < original.receipt_observed_available_by_at
        or at < context.review_started_at
        or at >= request.deadline
    ):
        raise ValueError("INVALID_OPPORTUNITY_CHRONOLOGY")
    trial = provenance.scope.trial_id
    opportunity = _append(
        origin,
        phase=OPPORTUNITY,
        allocation_id=original.allocation_id,
        trial_id=trial,
        body=plan,
        timestamp=at,
    )
    producer_at = _stamp(clock())
    if not at <= producer_at < request.deadline:
        raise ValueError("INVALID_RESEARCH_START_CHRONOLOGY")
    output, recorder = _produce(plan, trial, producer_at)
    research_at = _stamp(clock())
    if research_at < producer_at:
        raise ValueError("RESEARCH_RETENTION_PRECEDES_INVOCATION")
    research = _append(
        origin,
        phase=RESEARCH,
        allocation_id=original.allocation_id,
        trial_id=trial,
        timestamp=research_at,
        body=_Research(
            opportunity_hash=opportunity.event_hash,
            producer_at=producer_at,
            output_utf8=canonical_json(output.model_dump(mode="python")).decode(
                "utf-8"
            ),
            receipt_journal_utf8=recorder.export_canonical_jsonl().decode("utf-8"),
        ),
    )
    choice = _candidate(output)
    reason = None
    if not output.is_success or choice is None:
        reason = output.reason or output.status
    elif choice.disposition != "propose":
        reason = f"NON_DISPATCH_DISPOSITION:{choice.disposition}"
    elif research_at > request.deadline:
        reason = "RESEARCH_READY_AFTER_DEADLINE"
    if reason is not None:
        _append(
            origin,
            phase=OUTCOME,
            allocation_id=original.allocation_id,
            trial_id=trial,
            timestamp=research_at,
            body=_Outcome(
                research_hash=research.event_hash,
                status="NO_DISPATCH",
                reason=reason,
            ),
        )
    else:
        assert choice is not None and choice.strategy is not None
        guarded = _FirstDecisionGuard(choice, context.decision_cutoff)
        run_id, audit_id = uuid7(), uuid7()
        started_at = _stamp(clock())
        if started_at < research_at or started_at > request.deadline:
            raise ValueError("DISPATCH_OUTSIDE_RESEARCH_VALIDITY")
        reservation = _append(
            origin,
            phase=RESERVATION,
            allocation_id=original.allocation_id,
            trial_id=trial,
            timestamp=started_at,
            body=_Reservation(
                research_hash=research.event_hash,
                candidate_hash=choice.record_hash,
                family=cast(Literal["B3", "B4", "B5"], choice.strategy.family_id),
                strategy_hash=guarded.strategy_reference.code_hash,
                parameter_hash=strategy_parameters_hash(guarded.strategy_parameters),
                m0_run_id=str(run_id),
                m0_audit_event_id=str(audit_id),
            ),
        )
        identity = build_canonical_run_identity(
            strategy_hash=guarded.strategy_reference.code_hash,
            strategy_parameters_hash=strategy_parameters_hash(
                guarded.strategy_parameters
            ),
            protocol_hash=engine.protocol.protocol_hash,
            cost_model_hash=engine.cost_model.cost_model_hash,
            admission=engine.admission,
            bundle=engine.bundle,
            evaluator_evidence_hash=engine.evaluator_evidence_hash,
        )
        specification = build_canonical_specification(
            strategy=guarded,
            bundle=engine.bundle,
            dataset_reference=make_bundle_dataset_reference(
                engine.bundle,
                source=(
                    "Synthetic research-selected installed strategy; "
                    "not qualified market data"
                ),
            ),
        )
        run = execute_experiment_run(
            specification,
            ExperimentRunnerContext(
                run_id=run_id,
                started_at=started_at,
                completed_at=started_at,
                engine=engine,
                strategy=guarded,
                run_identity=identity,
                result_artifact_id=uuid7(),
                trace_artifact_id=uuid7(),
                result_artifact_location=f"synthetic://{trial}/result",
                trace_artifact_location=f"synthetic://{trial}/trace",
                ledger=SQLiteLedger(origin.ledger_path),
                audit_event_id=audit_id,
                original_result_observer=observer,
                completion_clock=clock,
            ),
        )
        if run.status.value == "failed":
            finished_at = _stamp(clock())
            if run.completed_at is None or finished_at < run.completed_at:
                raise ValueError("RESULT_RETENTION_CHRONOLOGY_INVALID")
            _append(
                origin,
                phase=OUTCOME,
                allocation_id=original.allocation_id,
                trial_id=trial,
                timestamp=finished_at,
                body=_Outcome(
                    research_hash=research.event_hash,
                    reservation_hash=reservation.event_hash,
                    status="M0_FAILED",
                    reason=run.error_details or "M0_FAILED",
                    m0_run_id=str(run.run_id),
                ),
            )
        else:
            observed = observer.readback()
            finished_at = _stamp(clock())
            if finished_at < observed.observed_readback_at or finished_at < started_at:
                raise ValueError("RESULT_RETENTION_CHRONOLOGY_INVALID")
            _append(
                origin,
                phase=OUTCOME,
                allocation_id=original.allocation_id,
                trial_id=trial,
                timestamp=finished_at,
                body=_completed_outcome(
                    research_hash=research.event_hash,
                    reservation_hash=reservation.event_hash,
                    m0_run_id=str(run.run_id),
                    association=observed.association_ref,
                    reason=run.status.value,
                    guarded=guarded,
                ),
            )
    return read_synthetic_research_execution(
        origin=origin,
        opportunity_ref=LocalEventReferenceV1(
            opportunity.event_id, opportunity.event_hash
        ),
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=runs,
        provenance=provenance,
        clock=clock,
    )


def read_synthetic_research_execution(
    *,
    origin: ConfiguredLocalSyntheticOriginV1,
    opportunity_ref: LocalEventReferenceV1,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
    provenance: Stage1TrialProvenanceSnapshotV1,
    clock: Callable[[], datetime],
) -> SyntheticResearchExecutionReadback:
    """Cold verify originals, deterministic offline producer replay, and M0.

    Local replay validates the synthetic computation. It is NOT authentication
    of an external AI response or proof of an independently accepted issuer.
    """
    if (
        type(origin) is not ConfiguredLocalSyntheticOriginV1
        or type(opportunity_ref) is not LocalEventReferenceV1
    ):
        raise ValueError("INVALID_RESEARCH_ORIGIN_OR_REFERENCE")
    if (
        type(opportunity_ref.event_id) is not UUID
        or type(opportunity_ref.event_hash) is not str
    ):
        raise ValueError("INVALID_RESEARCH_ORIGIN_OR_REFERENCE")
    if (
        opportunity_ref.event_id.version != 7
        or len(opportunity_ref.event_hash) != 64
        or any(c not in "0123456789abcdef" for c in opportunity_ref.event_hash)
    ):
        raise ValueError("INVALID_RESEARCH_ORIGIN_OR_REFERENCE")
    campaign, provenance = deepcopy(campaign), deepcopy(provenance)
    arms, bindings, runs = (
        deepcopy(tuple(arms)),
        deepcopy(tuple(bindings)),
        tuple(expected_run_ids),
    )
    if campaign.campaign_type != "SYNTHETIC_TEST":
        raise ValueError("SYNTHETIC_CAMPAIGN_ONLY")
    verify_stage1_trial_provenance_snapshot(
        snapshot=provenance,
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=runs,
    )
    events = origin.verified_events()
    selected = [event for event in events if event.event_id == opportunity_ref.event_id]
    if (
        len(selected) != 1
        or selected[0].event_hash != opportunity_ref.event_hash
        or selected[0].event_type != OPPORTUNITY
    ):
        raise ValueError("ORIGINAL_OPPORTUNITY_NOT_FOUND")
    opportunity = selected[0]
    trial = provenance.scope.trial_id
    plan = _record(opportunity, _Opportunity, origin)
    phases: dict[str, AuditEvent] = {}
    for event in events:
        if event.entity_id != opportunity.entity_id or event.event_type not in _PHASES:
            continue
        if event.event_type in phases:
            raise ValueError("DUPLICATE_RESEARCH_PHASE")
        if (
            event.deduplication_key
            != f"stage1:synthetic-research:{opportunity.entity_id}:{event.event_type}"
        ):
            raise ValueError("RESEARCH_PHASE_SCOPE_MISMATCH")
        phases[event.event_type] = event
    if phases.get(OPPORTUNITY) != opportunity:
        raise ValueError("RESEARCH_OPPORTUNITY_SCOPE_MISMATCH")
    ordered = [phases[phase] for phase in _PHASES if phase in phases]
    indexes = {event.event_id: index for index, event in enumerate(events)}
    if [indexes[e.event_id] for e in ordered] != sorted(
        indexes[e.event_id] for e in ordered
    ):
        raise ValueError("RESEARCH_PHASE_ORDER_INVALID")
    if any(
        a.timestamp > b.timestamp for a, b in zip(ordered, ordered[1:], strict=False)
    ):
        raise ValueError("RESEARCH_PHASE_CLOCK_ORDER_INVALID")
    now = _stamp(clock())
    if any(event.timestamp > now for event in ordered):
        raise ValueError("RESEARCH_EVIDENCE_AFTER_READBACK")
    store = LocalSyntheticAccountReceiptStoreV1.open_existing(
        origin=origin, clock=clock
    )
    original = store.readback_allocation(
        allocation_id=UUID(plan.allocation_id),
        allocation_ref=LocalEventReferenceV1(
            UUID(plan.allocation_event_id), plan.allocation_event_hash
        ),
        witness_ref=LocalEventReferenceV1(
            UUID(plan.witness_event_id), plan.witness_event_hash
        ),
        expected_fields=AccountAllocationFieldsV1(**dict(plan.account_fields)),
    )
    _verify_context(
        plan, provenance=provenance, original=original, campaign=campaign, arms=arms
    )
    if (
        opportunity.entity_id != original.allocation_id
        or not original.receipt_observed_available_by_at
        <= opportunity.timestamp
        < plan.request.deadline
        or opportunity.timestamp < plan.context.review_started_at
    ):
        raise ValueError("OPPORTUNITY_ACCOUNT_OR_CLOCK_MISMATCH")
    reference = LocalEventReferenceV1(opportunity.event_id, opportunity.event_hash)
    if RESEARCH not in phases:
        if RESERVATION in phases or OUTCOME in phases:
            raise ValueError("ORPHAN_EXECUTION_WITHOUT_RESEARCH")
        return SyntheticResearchExecutionReadback(
            reference,
            trial,
            "UNRESOLVED",
            None,
            "RESEARCH_NOT_RETAINED",
            (),
            None,
            None,
            None,
        )
    research_event = phases[RESEARCH]
    research = _record(research_event, _Research, origin)
    if (
        research.opportunity_hash != opportunity.event_hash
        or not opportunity.timestamp <= research.producer_at <= research_event.timestamp
        or research.producer_at >= plan.request.deadline
    ):
        raise ValueError("RESEARCH_ORIGINAL_LINK_OR_CLOCK_MISMATCH")
    output, replayed = _produce(plan, trial, research.producer_at)
    expected_output = canonical_json(output.model_dump(mode="python")).decode("utf-8")
    if (
        research.output_utf8 != expected_output
        or research.receipt_journal_utf8.encode("utf-8")
        != replayed.export_canonical_jsonl()
    ):
        raise ValueError("RESEARCH_ORIGINAL_REPLAY_MISMATCH")
    restored = ResearchReceiptStore()
    restored.load_canonical_jsonl(research.receipt_journal_utf8.encode("utf-8"))
    choice = _candidate(output)
    costs = restored.get_cost_receipts_for_attempt(f"{trial}:K1-001")
    hashes = tuple(
        event.record_hash for event in restored.get_attempt_events(f"{trial}:K1-001")
    ) + tuple(cost.record_hash for cost in costs)
    amount: Decimal | None = None
    if costs and all(
        cost.amount_basis == "verified_zero" and cost.currency == "USD"
        for cost in costs
    ):
        amount = Decimal("0")
    disposition = choice.disposition if choice else output.status
    candidate_hash = choice.record_hash if choice else None
    if OUTCOME not in phases:
        return SyntheticResearchExecutionReadback(
            reference,
            trial,
            "UNRESOLVED",
            disposition,
            "EXECUTION_NOT_FINALIZED",
            hashes,
            candidate_hash,
            None,
            amount,
        )
    outcome = (
        _record(phases[OUTCOME], _OutcomeV2, origin)
        if phases[OUTCOME].schema_version == "2"
        else _record(phases[OUTCOME], _Outcome, origin)
    )
    if outcome.research_hash != research_event.event_hash:
        raise ValueError("OUTCOME_RESEARCH_LINK_MISMATCH")
    if outcome.status == "NO_DISPATCH":
        expected_reason = (
            (output.reason or output.status)
            if not output.is_success or choice is None
            else (
                f"NON_DISPATCH_DISPOSITION:{choice.disposition}"
                if choice.disposition != "propose"
                else (
                    "RESEARCH_READY_AFTER_DEADLINE"
                    if research_event.timestamp > plan.request.deadline
                    else None
                )
            )
        )
        if (
            expected_reason is None
            or outcome.reason != expected_reason
            or RESERVATION in phases
            or any(
                value is not None
                for value in (
                    outcome.reservation_hash,
                    outcome.m0_run_id,
                    outcome.association_event_id,
                    outcome.association_event_hash,
                    outcome.first_context_kind,
                    outcome.first_context_utf8,
                    outcome.first_intent_utf8,
                )
            )
        ):
            raise ValueError("FALSE_NO_DISPATCH_OUTCOME")
        return SyntheticResearchExecutionReadback(
            reference,
            trial,
            "NO_DISPATCH",
            disposition,
            outcome.reason,
            hashes,
            candidate_hash,
            None,
            amount,
        )
    if (
        RESERVATION not in phases
        or choice is None
        or choice.strategy is None
        or choice.disposition != "propose"
        or not output.is_success
    ):
        raise ValueError("EXECUTION_WITHOUT_ORIGINAL_SELECTION")
    reservation_event = phases[RESERVATION]
    reservation = _record(reservation_event, _Reservation, origin)
    installed = _FirstDecisionGuard(choice, plan.context.decision_cutoff)
    if (
        reservation.research_hash != research_event.event_hash
        or reservation.candidate_hash != choice.record_hash
        or reservation.family != choice.strategy.family_id
        or reservation.strategy_hash != installed.strategy_reference.code_hash
        or reservation.parameter_hash
        != strategy_parameters_hash(installed.strategy_parameters)
        or reservation_event.timestamp > plan.request.deadline
        or outcome.reservation_hash != reservation_event.event_hash
        or outcome.m0_run_id != reservation.m0_run_id
    ):
        raise ValueError("EXECUTION_RESERVATION_OR_STRATEGY_MISMATCH")
    if outcome.status == "M0_FAILED":
        failed = [
            event
            for event in events
            if str(event.event_id) == reservation.m0_audit_event_id
        ]
        claims = [
            event
            for event in events
            if event.entity_id == original.allocation_id and event.event_type == CLAIM
        ]
        # Failed M0 has no successful financial artifact. Verify its original
        # invocation through the actual bound account claim, never assume fills
        # were zero simply because the engine failed before returning a trace.
        if len(failed) != 1 or len(claims) != 1:
            raise ValueError("FAILED_M0_ORIGINAL_EVIDENCE_MISSING")
        event, claim = failed[0], claims[0]
        data, claimed = event.payload, claim.payload
        if not isinstance(data, Mapping) or not isinstance(claimed, Mapping):
            raise ValueError("FAILED_M0_ORIGINAL_EVIDENCE_MISSING")
        # Matching payload dictionaries do not establish an original claim.
        # Validate its producer envelope and canonical invocation identity from
        # this same verified event snapshot, before attributing a failed run.
        try:
            binding = parse_original_invocation_binding(data.get("invocation_binding"))
            claim_binding = parse_original_invocation_binding(
                claimed.get("invocation_binding")
            )
        except OpeningBookLifecycleError as error:
            raise ValueError("FAILED_M0_ORIGINAL_CLAIM_MISMATCH") from error
        identity_hash = claimed.get("identity_hash")
        if (
            claim.entity_type != ACCOUNT_ENTITY
            or claim.schema_version != "2"
            or claimed.get("profile") != BOUND_PROFILE
            or claimed.get("issuer_instance_id") != str(origin.issuer_instance_id)
            or claim.deduplication_key != f"stage1:invocation:{original.allocation_id}"
            or binding != claim_binding
            or claim.event_id != binding.invocation_id
            or binding.m0_run_id != UUID(reservation.m0_run_id)
            or binding.m0_audit_event_id != UUID(reservation.m0_audit_event_id)
            or claimed.get("witness_event_hash") != original.witness_ref.event_hash
            or type(identity_hash) is not str
            or len(identity_hash) != 64
            or any(c not in "0123456789abcdef" for c in identity_hash)
            or not reservation_event.timestamp <= claim.timestamp <= event.timestamp
        ):
            raise ValueError("FAILED_M0_ORIGINAL_CLAIM_MISMATCH")
        # Failure may precede book consumption. Do not invent consumption, but
        # verify every consumption record that does exist, including lineage,
        # identity, original book bytes and causal order. A valid hash chain
        # alone does not make a contradictory producer event acceptable.
        consumptions = [
            item
            for item in events
            if item.entity_id == original.allocation_id and item.event_type == CONSUMED
        ]
        if len(consumptions) > 1:
            raise ValueError("FAILED_M0_DUPLICATE_CONSUMPTION")
        if consumptions:
            consumption = consumptions[0]
            consumed = consumption.payload
            if not isinstance(consumed, Mapping):
                raise ValueError("FAILED_M0_CONSUMPTION_MISMATCH")
            try:
                consumed_binding = parse_original_invocation_binding(
                    consumed.get("invocation_binding")
                )
            except OpeningBookLifecycleError as error:
                raise ValueError("FAILED_M0_CONSUMPTION_MISMATCH") from error
            if (
                consumption.entity_type != ACCOUNT_ENTITY
                or consumption.schema_version != "2"
                or consumed.get("profile") != BOUND_PROFILE
                or consumed.get("issuer_instance_id") != str(origin.issuer_instance_id)
                or consumption.deduplication_key
                != f"stage1:consumed:{original.allocation_id}"
                or consumed_binding != binding
                or consumed.get("claim_event_id") != str(claim.event_id)
                or consumed.get("claim_event_hash") != claim.event_hash
                or consumed.get("allocation_event_hash")
                != original.allocation_ref.event_hash
                or consumed.get("identity_hash") != identity_hash
                or consumed.get("original_book_sha256")
                != hashlib.sha256(original.original_book_bytes).hexdigest()
                or not indexes[claim.event_id]
                < indexes[consumption.event_id]
                < indexes[event.event_id]
                or not claim.timestamp <= consumption.timestamp <= event.timestamp
            ):
                raise ValueError("FAILED_M0_CONSUMPTION_MISMATCH")
        if (
            event.event_type != "m2.evaluation.run.recorded"
            or event.entity_id != UUID(reservation.m0_run_id)
            or event.entity_type != "experiment_run"
            or event.schema_version != "3"
            or data.get("status") != "failed"
            or data.get("artifact_hashes") != ()
            or data.get("metrics") != {}
            or "original_final_book_hash" in data
            or data.get("error_details") != outcome.reason
            or claimed.get("allocation_event_hash")
            != original.allocation_ref.event_hash
            or not indexes[reservation_event.event_id]
            < indexes[claim.event_id]
            < indexes[event.event_id]
            < indexes[phases[OUTCOME].event_id]
            or event.timestamp > phases[OUTCOME].timestamp
            or outcome.association_event_id is not None
            or outcome.association_event_hash is not None
            or outcome.first_context_kind is not None
            or outcome.first_context_utf8 is not None
            or outcome.first_intent_utf8 is not None
        ):
            raise ValueError("FAILED_M0_ORIGINAL_EVIDENCE_MISMATCH")
        return SyntheticResearchExecutionReadback(
            reference,
            trial,
            "EXECUTION_FAILED",
            disposition,
            outcome.reason,
            hashes,
            candidate_hash,
            None,
            amount,
        )
    if outcome.association_event_id is None or outcome.association_event_hash is None:
        raise ValueError("ORIGINAL_RESULT_REFERENCE_MISSING")
    retained = read_original_result(
        origin=origin,
        original_account=original,
        association_ref=LocalEventReferenceV1(
            UUID(outcome.association_event_id), outcome.association_event_hash
        ),
        provenance=provenance,
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=runs,
        clock=clock,
    )
    identity = retained.original_artifacts.result.run_identity
    if not isinstance(identity, EvaluationRunIdentityV2):
        raise ValueError("RESEARCH_REQUIRES_PARAMETER_BOUND_V2_IDENTITY")
    m0 = [
        event
        for event in events
        if str(event.event_id) == reservation.m0_audit_event_id
    ]
    if (
        retained.operational_m0_run_id != UUID(reservation.m0_run_id)
        or identity.strategy_hash != reservation.strategy_hash
        or identity.strategy_parameters_hash != reservation.parameter_hash
        or identity.bundle_hash != plan.input_bundle_hash
        or identity.protocol_hash != plan.protocol_hash
        or identity.cost_model_hash != plan.cost_model_hash
        or identity.admission_hash != plan.admission_hash
        or identity.evaluator_evidence_hash != plan.evaluator_evidence_hash
        or identity.code_version_hash != plan.source_inventory_hash
        or len(m0) != 1
        or m0[0].event_type != "m2.evaluation.run.recorded"
        or indexes[m0[0].event_id] <= indexes[reservation_event.event_id]
        or indexes[retained.association_ref.event_id] <= indexes[m0[0].event_id]
        or indexes[retained.association_ref.event_id]
        >= indexes[phases[OUTCOME].event_id]
    ):
        raise ValueError("RESEARCH_TO_ORIGINAL_M0_MISMATCH")
    # Independently reconstruct the first actual target decision. A correct
    # result hash is not evidence that it executed the retained proposal.
    if (
        outcome.first_context_kind is None
        or (outcome.first_context_utf8 is None and not isinstance(outcome, _OutcomeV2))
        or outcome.first_intent_utf8 is None
    ):
        raise ValueError("ORIGINAL_FIRST_DECISION_PROOF_MISSING")
    if isinstance(outcome, _OutcomeV2):
        context_data = _decode_context(outcome.first_context_artifact)
    else:
        assert outcome.first_context_utf8 is not None
        context_data = _json_object(outcome.first_context_utf8)
    intent_data = _json_object(outcome.first_intent_utf8)
    first_intent = StrategyDecisionIntentV1.model_validate_json(
        canonical_json(intent_data)
    )
    with decimal_context():
        if outcome.first_context_kind == "realized":
            first_context = StrategyDecisionContextV1.model_validate_json(
                canonical_json(context_data)
            )
            replay_intent = installed.decide(first_context)
        else:
            reconstructed = ExploratoryStrategyDecisionContextV1.model_validate_json(
                canonical_json(context_data)
            )
            replay_intent = installed.decide_exploratory(reconstructed)
    decisions = [
        event
        for event in retained.original_artifacts.trace.events
        if isinstance(
            event,
            (StrategyDecisionTraceEventV1, ExploratoryStrategyDecisionTraceEventV1),
        )
    ]
    if (
        not decisions
        or canonical_json(replay_intent) != canonical_json(first_intent)
        or decisions[0].context_hash != content_hash(context_data)
        or decisions[0].intent_hash != content_hash(first_intent)
        or decisions[0].decision_cutoff != plan.context.decision_cutoff
        or (
            isinstance(decisions[0], StrategyDecisionTraceEventV1)
            != (outcome.first_context_kind == "realized")
        )
    ):
        raise ValueError("RESEARCH_TO_FIRST_DECISION_PROOF_MISMATCH")
    state = (
        "LOCAL_EXECUTION_COMPLETE"
        if retained.classification == "complete"
        else "LOCAL_EXECUTION_NOT_COMPLETE"
    )
    return SyntheticResearchExecutionReadback(
        reference,
        trial,
        state,
        disposition,
        retained.classification,
        hashes,
        candidate_hash,
        retained,
        amount,
    )
