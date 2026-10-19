"""Deterministic validation and normalization engine for adaptive research.

Implements candidate validation, raw choice extraction, and N01-N12 semantic
and tamper rejection under the 'drift-research/1-draft' wire profile.
"""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from drift.intelligence.contracts import (
    SUPPORTED_PROFILES,
    ArtifactReference,
    CandidateStrategy,
    CostReceipt,
    AttemptRecord,
    ModelReplayRecord,
    ImmutableModel,
    RawChoice,
    ResearchCandidate,
    ResearchContext,
    StrategySelection,
    TargetWeight,
    TrustedInvocationBinding,
    compute_record_hash,
)
from drift.serialization.canonical import content_hash


class StrategyRegistration(ImmutableModel):
    """Inert metadata envelope for an allowed strategy family."""

    family_id: str
    strategy_ref: ArtifactReference
    envelope_ref: ArtifactReference
    eligibility_ref: ArtifactReference
    allowed_parameters: Mapping[str, type] = {}


class ResolvedDependencies(ImmutableModel):
    """Caller-injected read-only resolver for environment dependencies."""

    portfolio_ref: ArtifactReference
    mandate_ref: ArtifactReference
    universe_ref: ArtifactReference
    registry_ref: ArtifactReference
    method_ref: ArtifactReference
    admitted_securities: tuple[str, ...] = ()
    strategy_registry: Mapping[str, StrategyRegistration] = {}
    current_selection: StrategySelection | None = None


class ValidationResult(ImmutableModel):
    """Result of candidate validation and normalization."""

    is_valid: bool
    status: str  # "VALID", "REJECTED", "INVALID", "REFUSED"
    reason: str
    candidate: ResearchCandidate | None = None
    rejection_receipt: Mapping[str, Any] | None = None


def validate_raw_choice(data: Mapping[str, Any]) -> RawChoice:
    """Parse and validate unadorned RawChoice data, rejecting floats and extra keys."""
    if isinstance(data.get("cash_weight"), float):
        raise ValueError("invalid: JSON float is not Weight")
    targets = data.get("targets", ())
    if isinstance(targets, (list, tuple)):
        for t in targets:
            if isinstance(t, Mapping) and isinstance(t.get("weight"), float):
                raise ValueError("invalid: JSON float is not Weight")
    return RawChoice.model_validate(data)


def validate_candidate(
    *,
    raw_choice: RawChoice | Mapping[str, Any],
    context: ResearchContext,
    resolved_dependencies: ResolvedDependencies,
    trusted_invocation: TrustedInvocationBinding,
) -> ValidationResult:
    """Validate a raw candidate choice into an immutable ResearchCandidate.

    Returns a ValidationResult with status VALID and the normalized candidate,
    or a non-valid status with the specific reason.
    """
    if isinstance(raw_choice, Mapping):
        try:
            choice = validate_raw_choice(raw_choice)
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                status="INVALID",
                reason=f"invalid raw choice: {e}",
            )
    else:
        choice = raw_choice

    # The producer's claimed raw-output reference must bind the actual
    # untrusted choice bytes after canonical parsing. A self-hashed candidate
    # is not enough to prove which output the producer validated.
    observed_output_hash = content_hash(choice.model_dump(mode="python"))
    if trusted_invocation.raw_output_ref.sha256 != observed_output_hash:
        return ValidationResult(
            is_valid=False,
            status="REJECTED",
            reason="RAW_OUTPUT_BINDING_MISMATCH: retained choice digest differs",
        )

    # 1. Profile support
    if context.profile not in SUPPORTED_PROFILES:
        return ValidationResult(
            is_valid=False,
            status="REFUSED",
            reason=f"refuse unknown version: {context.profile}",
        )

    # 2. Timing invariants
    if (
        trusted_invocation.completed_at.tzinfo is None
        or trusted_invocation.checked_at.tzinfo is None
        or trusted_invocation.completed_at.utcoffset() is None
        or trusted_invocation.checked_at.utcoffset() is None
    ):
        return ValidationResult(
            is_valid=False,
            status="INVALID",
            reason="INDETERMINATE_TIMEZONE: research timestamps need an offset",
        )
    if trusted_invocation.completed_at > trusted_invocation.checked_at:
        return ValidationResult(
            is_valid=False,
            status="INVALID",
            reason="FUTURE_COMPLETION_AT_VALIDATION",
        )
    if trusted_invocation.completed_at < context.review_started_at:
        return ValidationResult(
            is_valid=False,
            status="INVALID",
            reason="invalid: completion precedes review start",
        )

    if (
        trusted_invocation.valid_until is not None
        and trusted_invocation.valid_until < trusted_invocation.checked_at
    ):
        return ValidationResult(
            is_valid=False,
            status="REJECTED",
            reason=(
                f"rejected: already expired at validation at "
                f"{trusted_invocation.checked_at.isoformat()}"
            ),
        )

    # 3. Context state and mandate binding verification
    if context.portfolio_ref != resolved_dependencies.portfolio_ref:
        return ValidationResult(
            is_valid=False,
            status="REJECTED",
            reason="rejected: candidate state binding differs from context",
        )
    if context.mandate_ref != resolved_dependencies.mandate_ref:
        return ValidationResult(
            is_valid=False,
            status="REJECTED",
            reason="rejected: candidate mandate binding differs from context",
        )

    for label, actual, expected in (
        ("universe", resolved_dependencies.universe_ref, context.universe_ref),
        ("registry", resolved_dependencies.registry_ref, context.registry_ref),
        ("method", resolved_dependencies.method_ref, context.method_ref),
    ):
        if actual != expected:
            return ValidationResult(
                is_valid=False,
                status="REJECTED",
                reason=f"RESEARCH_CONTEXT_BINDING_MISMATCH: {label}",
            )

    # 4. Disposition semantics
    disposition = choice.disposition
    if disposition in ("abstain", "unavailable"):
        if (
            choice.targets
            or choice.cash_weight is not None
            or choice.selection is not None
        ):
            return ValidationResult(
                is_valid=False,
                status="INVALID",
                reason="invalid: abstention cannot retain strategy/targets/cash",
            )
        candidate_strategy = None
        targets_tuple: tuple[TargetWeight, ...] = ()
        cash_weight_val = None

    elif disposition == "hold":
        if choice.targets or choice.cash_weight is not None:
            return ValidationResult(
                is_valid=False,
                status="INVALID",
                reason="invalid: hold cannot specify target weights or cash weight",
            )
        if resolved_dependencies.current_selection is None:
            return ValidationResult(
                is_valid=False,
                status="REJECTED",
                reason=(
                    "rejected: hold disposition requires valid "
                    "current selection in dependencies"
                ),
            )
        if choice.selection != resolved_dependencies.current_selection:
            return ValidationResult(
                is_valid=False,
                status="REJECTED",
                reason="rejected: hold selection does not match current selection",
            )
        candidate_strategy = None
        targets_tuple = ()
        cash_weight_val = None

    elif disposition == "propose":
        if choice.selection is None:
            return ValidationResult(
                is_valid=False,
                status="INVALID",
                reason="invalid: propose disposition requires non-null selection",
            )
        reg = resolved_dependencies.strategy_registry.get(choice.selection.family_id)
        if reg is None:
            return ValidationResult(
                is_valid=False,
                status="REJECTED",
                reason=(
                    f"rejected: undeclared strategy family {choice.selection.family_id}"
                ),
            )

        if choice.selection.strategy_version != reg.strategy_ref.version:
            return ValidationResult(
                is_valid=False,
                status="REJECTED",
                reason="STRATEGY_VERSION_MISMATCH",
            )

        # Check parameter envelope
        for param_name, param_val in choice.selection.parameters.items():
            if param_name not in reg.allowed_parameters:
                return ValidationResult(
                    is_valid=False,
                    status="REJECTED",
                    reason=(
                        "rejected: undeclared parameter; a separate "
                        "declared-integer-envelope variant rejects "
                        f"boolean type: {param_name}"
                    ),
                )
            expected_type = reg.allowed_parameters[param_name]
            if not isinstance(param_val, expected_type) or (
                expected_type is int and isinstance(param_val, bool)
            ):
                return ValidationResult(
                    is_valid=False,
                    status="REJECTED",
                    reason=(
                        f"rejected: parameter {param_name} expected "
                        f"{expected_type.__name__}, got {type(param_val).__name__}"
                    ),
                )

        # Check admitted securities and weights sum
        if choice.cash_weight is None:
            return ValidationResult(
                is_valid=False,
                status="INVALID",
                reason="invalid: propose disposition requires non-null cash_weight",
            )

        total_weight = Decimal(choice.cash_weight)
        seen_security_ids: set[str] = set()
        for tw in choice.targets:
            if tw.security_id in seen_security_ids:
                return ValidationResult(
                    is_valid=False,
                    status="REJECTED",
                    reason="DUPLICATE_TARGET_SECURITY",
                )
            seen_security_ids.add(tw.security_id)
            if tw.security_id not in resolved_dependencies.admitted_securities:
                return ValidationResult(
                    is_valid=False,
                    status="REJECTED",
                    reason=(
                        f"rejected: security {tw.security_id} not in admitted universe"
                    ),
                )
            total_weight += Decimal(tw.weight)

        if total_weight != Decimal("1.0"):
            return ValidationResult(
                is_valid=False,
                status="INVALID",
                reason=f"invalid: weights sum to {total_weight}",
            )

        params_hash = content_hash(choice.selection.parameters)
        candidate_strategy = CandidateStrategy(
            family_id=reg.family_id,
            strategy_ref=reg.strategy_ref,
            envelope_ref=reg.envelope_ref,
            parameters=choice.selection.parameters,
            parameters_hash=params_hash,
            eligibility_ref=reg.eligibility_ref,
        )
        targets_tuple = tuple(choice.targets)
        cash_weight_val = choice.cash_weight

    else:
        return ValidationResult(
            is_valid=False,
            status="INVALID",
            reason=f"unsupported disposition: {disposition}",
        )

    # Build candidate model preserving raw datetime objects for canonical normalization
    candidate_data: dict[str, Any] = {
        "profile": context.profile,
        "kind": "candidate",
        "candidate_id": trusted_invocation.candidate_id,
        "attempt_id": trusted_invocation.attempt_id,
        "scope": context.scope.model_dump(mode="python"),
        "context_ref": {
            "id": context.context_id,
            "version": context.profile,
            "sha256": context.record_hash,
        },
        "portfolio_ref": context.portfolio_ref.model_dump(mode="python"),
        "mandate_ref": context.mandate_ref.model_dump(mode="python"),
        "universe_ref": context.universe_ref.model_dump(mode="python"),
        "registry_ref": context.registry_ref.model_dump(mode="python"),
        "method_ref": context.method_ref.model_dump(mode="python"),
        "producer": trusted_invocation.producer,
        "completed_at": trusted_invocation.completed_at,
        "valid_until": trusted_invocation.valid_until,
        "disposition": disposition,
        "strategy": (
            candidate_strategy.model_dump(mode="python") if candidate_strategy else None
        ),
        "targets": [t.model_dump(mode="python") for t in targets_tuple],
        "cash_weight": cash_weight_val,
        "evidence_refs": [],
        "rationale": choice.rationale,
        "reason_codes": list(choice.reason_codes),
        "model_replay_ref": (
            trusted_invocation.model_replay_ref.model_dump(mode="python")
            if trusted_invocation.model_replay_ref
            else None
        ),
        "cost_receipt_ids": list(trusted_invocation.cost_receipt_ids),
    }

    rec_hash = content_hash(candidate_data)
    candidate_data["record_hash"] = rec_hash
    candidate_model = ResearchCandidate.model_validate(candidate_data)

    return ValidationResult(
        is_valid=True,
        status="VALID",
        reason="candidate valid and normalized",
        candidate=candidate_model,
    )


def validate_retained_record(
    record: Mapping[str, Any],
    *,
    expected_kind: str,
    context_cutoff: datetime | None = None,
    checked_at: datetime | None = None,
    context: ResearchContext | None = None,
) -> None:
    """Validate a retained JSON record, enforcing all semantic and tamper invariants.

    Covers N01-N12.
    Raises ValueError with the exact rejection or invalidity string.
    """
    profile = record.get("profile")
    if profile not in SUPPORTED_PROFILES:
        raise ValueError(f"refuse unknown version: {profile}")

    kind = record.get("kind")
    if kind != expected_kind:
        raise ValueError(f"invalid record kind: expected {expected_kind}, got {kind}")

    # Check record_hash integrity
    stated_hash = record.get("record_hash")
    if not stated_hash:
        raise ValueError("invalid: missing record_hash")
    calc_hash = compute_record_hash(record)
    if stated_hash != calc_hash:
        raise ValueError("invalid: record_hash mismatch")

    # Kind-specific semantic checks
    if kind == "context":
        if "mandate_ref" not in record or record["mandate_ref"] is None:
            raise ValueError(
                "invalid context shape: required mandate binding missing; "
                "builder emits unavailable preflight attempt, no candidate"
            )
        # Check causal inputs
        cutoff_str = record.get("decision_cutoff")
        if cutoff_str:
            cutoff = datetime.fromisoformat(cutoff_str)
            for inp in record.get("inputs", []):
                avail_str = inp.get("available_at")
                if avail_str and datetime.fromisoformat(avail_str) > cutoff:
                    raise ValueError(
                        "refuse: input availability after "
                        f"{cutoff.strftime('%H:%M')} cutoff; "
                        "late observation cannot enter causal context"
                    )

    elif kind == "candidate":
        # Check floats in weights
        cash_weight = record.get("cash_weight")
        if isinstance(cash_weight, float):
            raise ValueError("invalid: JSON float is not Weight")
        targets = record.get("targets", [])
        for t in targets:
            if isinstance(t.get("weight"), float):
                raise ValueError("invalid: JSON float is not Weight")

        # Disposition check
        disp = record.get("disposition")
        if disp in ("abstain", "unavailable"):
            if targets or cash_weight is not None or record.get("strategy") is not None:
                raise ValueError(
                    "invalid: abstention cannot retain strategy/targets/cash"
                )
        elif disp == "propose":
            total = (
                Decimal(str(cash_weight)) if cash_weight is not None else Decimal("0")
            )
            for t in targets:
                total += Decimal(str(t["weight"]))
            if total != Decimal("1.0"):
                raise ValueError(f"invalid: weights sum to {total}")

        # Check undeclared parameters if strategy present
        strategy = record.get("strategy")
        if strategy:
            params = strategy.get("parameters", {})
            for p_key, p_val in params.items():
                if isinstance(p_val, bool):
                    raise ValueError(
                        "rejected: undeclared parameter; a separate "
                        "declared-integer-envelope variant rejects boolean "
                        f"type: {p_key}"
                    )

        # State binding checks
        port_ref = record.get("portfolio_ref", {})
        if context is not None and port_ref != context.portfolio_ref.model_dump(
            mode="python"
        ):
            raise ValueError(
                "rejected: candidate state binding differs from context; "
                "use resolvable matching fixture digest to isolate state check"
            )

        # Timing checks
        completed_str = record.get("completed_at")
        if context is not None and completed_str:
            completed = datetime.fromisoformat(completed_str)
            if completed < context.review_started_at:
                raise ValueError("invalid: completion precedes review start")

        valid_until_str = record.get("valid_until")
        if valid_until_str and checked_at:
            if datetime.fromisoformat(valid_until_str) < checked_at:
                raise ValueError(
                    f"rejected: already expired at validation at "
                    f"{checked_at.isoformat()}"
                )

        # Check cross-arm scope
        scope = record.get("scope", {})
        if context is not None:
            if scope != context.scope.model_dump(mode="python"):
                raise ValueError("reject cross-arm scope or campaign/account mismatch")
            for ref_field in (
                "portfolio_ref",
                "mandate_ref",
                "universe_ref",
                "registry_ref",
                "method_ref",
            ):
                if record.get(ref_field) != context.model_dump(mode="python")[ref_field]:
                    raise ValueError(f"rejected: context binding differs: {ref_field}")
            expected_context = {
                "id": context.context_id,
                "version": context.profile,
                "sha256": context.record_hash,
            }
            if record.get("context_ref") != expected_context:
                raise ValueError("rejected: wrong research context")

    elif kind == "raw_cost":
        basis = record.get("amount_basis")
        if basis == "verified_zero":
            evidence = record.get("raw_evidence_ref")
            curr = record.get("currency")
            if not evidence or not curr:
                raise ValueError(
                    "rejected: missing evidence of verified zero "
                    "and currency remains null"
                )

    # Structural schema validation is always necessary, even when the caller
    # cannot supply an authoritative context for referential validation.
    # A valid hash is only tamper detection, never independent source proof.
    typed_records = {
        "context": ResearchContext,
        "candidate": ResearchCandidate,
        "attempt": AttemptRecord,
        "raw_cost": CostReceipt,
        "model_replay": ModelReplayRecord,
    }
    record_type = typed_records.get(kind)
    if record_type is None:
        raise ValueError(f"unsupported retained research record kind: {kind}")
    record_type.model_validate(dict(record))
