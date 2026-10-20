"""Platform execution bridge runtime.

Translates validated research proposals and candidates into Matthew's platform
execution request wrappers under DP-R2, DP-R5, and research acceptance criteria:
- State and permission enforcement (T08): stale candidates, expired TTLs,
  changed portfolio states, mandate changes, paused accounts, and pending orders
  refuse dispatch fail-closed.
- Hold/abstain handling (T08): admitted without order dispatch; does not cancel
  in-flight orders.
- Causal execution timing checks (T14): submission before completion refuses;
  unsupported intraday capability falls back cleanly to next open under A09 or
  refuses as unsupported.
- Strict scope and arm isolation (A12).
"""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, model_validator

from drift.intelligence.contracts import (
    ArtifactReference,
    ImmutableModel,
    ResearchCandidate,
    Scope,
    TargetWeight,
    compute_record_hash,
)

SessionTarget = Literal["intraday", "next_open", "none"]
BridgeStatus = Literal["admitted", "refused", "unsupported"]


class PortfolioStateBinding(ImmutableModel):
    """Snapshot binding of the current operational portfolio and mandate state."""

    portfolio_ref: ArtifactReference
    mandate_ref: ArtifactReference
    account_id: str = Field(min_length=1)
    arm_id: str = Field(min_length=1)
    state_hash: str = Field(min_length=64, max_length=64)
    is_paused: bool = Field(strict=True)
    has_pending_orders: bool = Field(strict=True)
    observed_at: datetime
    state_verified: bool = Field(default=False, strict=True)
    verification_ref: ArtifactReference | None = None


class PlatformExecutionRequest(ImmutableModel):
    """Validated execution dispatch request presented to platform executors."""

    request_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    scope: Scope
    portfolio_ref: ArtifactReference
    mandate_ref: ArtifactReference
    disposition: Literal["propose", "hold", "abstain", "unavailable"]
    target_allocations: tuple[TargetWeight, ...] = ()
    cash_weight: str | None = None
    session_target: SessionTarget
    status: BridgeStatus
    refusal_reason: str | None = None
    dispatched_at: datetime
    record_hash: str

    @model_validator(mode="after")
    def verify_request_identity(self) -> "PlatformExecutionRequest":
        """Even a caller-rehashed request must be intrinsically non-actionable
        unless its entire proposed allocation and disposition are coherent.
        """
        if self.record_hash != compute_record_hash(self):
            raise ValueError("PLATFORM_REQUEST_HASH_MISMATCH")
        if self.dispatched_at.tzinfo is None or self.dispatched_at.utcoffset() is None:
            raise ValueError("INDETERMINATE_TIMEZONE: request dispatch")
        if self.status != "admitted":
            if (
                self.session_target != "none"
                or self.target_allocations
                or self.cash_weight is not None
            ):
                raise ValueError("NON_ACTIONABLE_PLATFORM_REQUEST_HAS_TARGETS")
            if not self.refusal_reason:
                raise ValueError("UNREASONED_PLATFORM_REFUSAL")
            return self
        if self.refusal_reason is not None or self.disposition == "unavailable":
            raise ValueError("INVALID_ADMITTED_PLATFORM_REQUEST")
        if self.disposition in ("hold", "abstain"):
            if (
                self.target_allocations
                or self.cash_weight is not None
                or self.session_target != "none"
            ):
                raise ValueError("NON_TRADING_REQUEST_HAS_TARGETS")
            return self
        if (
            self.session_target == "none"
            or not self.target_allocations
            or self.cash_weight is None
        ):
            raise ValueError("UNSAFE_EMPTY_STAGE1_DISPATCH")
        if len({target.security_id for target in self.target_allocations}) != len(
            self.target_allocations
        ):
            raise ValueError("DUPLICATE_PLATFORM_TARGET")
        try:
            amounts = [
                Decimal(self.cash_weight),
                *(Decimal(target.weight) for target in self.target_allocations),
            ]
        except (InvalidOperation, TypeError) as error:
            raise ValueError("INVALID_PLATFORM_TARGET_WEIGHTS") from error
        texts = [self.cash_weight, *(t.weight for t in self.target_allocations)]
        if (
            any(
                not isinstance(value, str)
                or value != value.strip()
                or "e" in value.lower()
                for value in texts
            )
            or any(
                not value.is_finite() or not Decimal("0") <= value <= Decimal("1")
                for value in amounts
            )
            or sum(amounts, Decimal("0")) != Decimal("1")
        ):
            raise ValueError("INVALID_PLATFORM_TARGET_WEIGHTS")
        return self

def bridge_candidate_to_execution(
    *,
    candidate: ResearchCandidate,
    portfolio_state: PortfolioStateBinding,
    current_time: datetime,
    intraday_supported: bool = False,
    allow_next_open_fallback: bool = True,
    request_id: str | None = None,
) -> PlatformExecutionRequest:
    """Bridge a research candidate into a PlatformExecutionRequest.

    Enforces:
    - Arm and account boundary alignment (A12).
    - Causal timing: current_time must be >= candidate.completed_at (T14).
    - Candidate TTL expiry: current_time must be <= candidate.valid_until (T08, DP-R2).
    - Stale state detection: portfolio hash and mandate must match candidate (T08).
    - Safety halts: account paused or pending orders refuse dispatch (T08).
    - Clean next-session fallback when intraday execution is unavailable (A09, T14).
    """
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("INDETERMINATE_TIMEZONE: current time has no offset")
    if (
        type(intraday_supported) is not bool
        or type(allow_next_open_fallback) is not bool
    ):
        raise ValueError("INVALID_SESSION_CAPABILITY: expected strict booleans")
    # Refuse model_copy(update=...) forgery before accessing nested timestamps
    # or treating caller-provided account flags as authority.
    candidate = ResearchCandidate.model_validate(candidate.model_dump(mode="python"))
    portfolio_state = PortfolioStateBinding.model_validate(
        portfolio_state.model_dump(mode="python")
    )
    if (
        candidate.completed_at.tzinfo is None
        or candidate.completed_at.utcoffset() is None
        or portfolio_state.observed_at.tzinfo is None
        or portfolio_state.observed_at.utcoffset() is None
    ):
        raise ValueError(
            "INDETERMINATE_TIMEZONE: input evidence timestamp has no offset"
        )
    curr_utc = current_time.astimezone(UTC)
    cand_comp_utc = candidate.completed_at.astimezone(UTC)
    actual_request_id = request_id or str(
        uuid5(
            NAMESPACE_URL,
            compute_record_hash(
                {
                    "candidate_id": candidate.candidate_id,
                    "candidate_hash": candidate.record_hash,
                    "portfolio_state": portfolio_state.model_dump(mode="python"),
                    "current_time": curr_utc,
                    "intraday_supported": intraday_supported,
                    "allow_next_open_fallback": allow_next_open_fallback,
                }
            ),
        )
    )
    raw_dict: dict[str, Any]

    # 1. Arm and account scope alignment (A12)
    if (
        candidate.scope.account_id != portfolio_state.account_id
        or candidate.scope.arm_id != portfolio_state.arm_id
    ):
        raw_dict = {
            "request_id": actual_request_id,
            "candidate_id": candidate.candidate_id,
            "attempt_id": candidate.attempt_id,
            "scope": candidate.scope.model_dump(mode="python"),
            "portfolio_ref": candidate.portfolio_ref.model_dump(mode="python"),
            "mandate_ref": candidate.mandate_ref.model_dump(mode="python"),
            "disposition": candidate.disposition,
            "target_allocations": [],
            "cash_weight": None,
            "session_target": "none",
            "status": "refused",
            "refusal_reason": (
                f"SCOPE_MISMATCH: candidate scope ({candidate.scope.arm_id}, "
                f"{candidate.scope.account_id}) does not match portfolio state "
                f"({portfolio_state.arm_id}, {portfolio_state.account_id})"
            ),
            "dispatched_at": curr_utc,
        }
        raw_dict["record_hash"] = compute_record_hash(raw_dict)
        return PlatformExecutionRequest.model_validate(raw_dict)

    # 2. Causal execution timing check (T14)
    if curr_utc < cand_comp_utc:
        raw_dict = {
            "request_id": actual_request_id,
            "candidate_id": candidate.candidate_id,
            "attempt_id": candidate.attempt_id,
            "scope": candidate.scope.model_dump(mode="python"),
            "portfolio_ref": candidate.portfolio_ref.model_dump(mode="python"),
            "mandate_ref": candidate.mandate_ref.model_dump(mode="python"),
            "disposition": candidate.disposition,
            "target_allocations": [],
            "cash_weight": None,
            "session_target": "none",
            "status": "refused",
            "refusal_reason": (
                "LOOKAHEAD_VIOLATION: execution requested before decision completion"
            ),
            "dispatched_at": curr_utc,
        }
        raw_dict["record_hash"] = compute_record_hash(raw_dict)
        return PlatformExecutionRequest.model_validate(raw_dict)

    # 3. Decision TTL expiration check (T08, DP-R2)
    if candidate.valid_until is not None:
        if (
            candidate.valid_until.tzinfo is None
            or candidate.valid_until.utcoffset() is None
        ):
            raise ValueError("INDETERMINATE_TIMEZONE: candidate expiry")
        cand_exp_utc = candidate.valid_until.astimezone(UTC)
        if curr_utc > cand_exp_utc:
            raw_dict = {
                "request_id": actual_request_id,
                "candidate_id": candidate.candidate_id,
                "attempt_id": candidate.attempt_id,
                "scope": candidate.scope.model_dump(mode="python"),
                "portfolio_ref": candidate.portfolio_ref.model_dump(mode="python"),
                "mandate_ref": candidate.mandate_ref.model_dump(mode="python"),
                "disposition": candidate.disposition,
                "target_allocations": [],
                "cash_weight": None,
                "session_target": "none",
                "status": "refused",
                "refusal_reason": (
                    "STALE_CANDIDATE_EXPIRED: decision validity window expired"
                ),
                "dispatched_at": curr_utc,
            }
            raw_dict["record_hash"] = compute_record_hash(raw_dict)
            return PlatformExecutionRequest.model_validate(raw_dict)

    # A caller assertion cannot authorize execution. A trusted platform
    # producer must attest to the complete observed state; this remains a
    # synthetic bridge, not a broker/mandate admission or an order.
    if not portfolio_state.state_verified or portfolio_state.verification_ref is None:
        raw_dict = {
            "request_id": actual_request_id,
            "candidate_id": candidate.candidate_id,
            "attempt_id": candidate.attempt_id,
            "scope": candidate.scope.model_dump(mode="python"),
            "portfolio_ref": candidate.portfolio_ref.model_dump(mode="python"),
            "mandate_ref": candidate.mandate_ref.model_dump(mode="python"),
            "disposition": candidate.disposition,
            "target_allocations": [],
            "cash_weight": None,
            "session_target": "none",
            "status": "refused",
            "refusal_reason": (
                "UNVERIFIED_PORTFOLIO_STATE: platform verification required"
            ),
            "dispatched_at": curr_utc,
        }
        raw_dict["record_hash"] = compute_record_hash(raw_dict)
        return PlatformExecutionRequest.model_validate(raw_dict)

    observed_utc = portfolio_state.observed_at.astimezone(UTC)
    if observed_utc < cand_comp_utc or observed_utc > curr_utc:
        raw_dict = {
            "request_id": actual_request_id,
            "candidate_id": candidate.candidate_id,
            "attempt_id": candidate.attempt_id,
            "scope": candidate.scope.model_dump(mode="python"),
            "portfolio_ref": candidate.portfolio_ref.model_dump(mode="python"),
            "mandate_ref": candidate.mandate_ref.model_dump(mode="python"),
            "disposition": candidate.disposition,
            "target_allocations": [],
            "cash_weight": None,
            "session_target": "none",
            "status": "refused",
            "refusal_reason": (
                "STALE_OR_FUTURE_STATE: account evidence unavailable at dispatch"
            ),
            "dispatched_at": curr_utc,
        }
        raw_dict["record_hash"] = compute_record_hash(raw_dict)
        return PlatformExecutionRequest.model_validate(raw_dict)

    # 4. Portfolio state hash change check (T08)
    if (
        candidate.portfolio_ref != portfolio_state.portfolio_ref
        or portfolio_state.state_hash != candidate.portfolio_ref.sha256
    ):
        raw_dict = {
            "request_id": actual_request_id,
            "candidate_id": candidate.candidate_id,
            "attempt_id": candidate.attempt_id,
            "scope": candidate.scope.model_dump(mode="python"),
            "portfolio_ref": candidate.portfolio_ref.model_dump(mode="python"),
            "mandate_ref": candidate.mandate_ref.model_dump(mode="python"),
            "disposition": candidate.disposition,
            "target_allocations": [],
            "cash_weight": None,
            "session_target": "none",
            "status": "refused",
            "refusal_reason": (
                "STALE_PORTFOLIO_STATE: underlying portfolio state has changed "
                "since review"
            ),
            "dispatched_at": curr_utc,
        }
        raw_dict["record_hash"] = compute_record_hash(raw_dict)
        return PlatformExecutionRequest.model_validate(raw_dict)

    # 5. Mandate reference change check (T08)
    if candidate.mandate_ref != portfolio_state.mandate_ref:
        raw_dict = {
            "request_id": actual_request_id,
            "candidate_id": candidate.candidate_id,
            "attempt_id": candidate.attempt_id,
            "scope": candidate.scope.model_dump(mode="python"),
            "portfolio_ref": candidate.portfolio_ref.model_dump(mode="python"),
            "mandate_ref": candidate.mandate_ref.model_dump(mode="python"),
            "disposition": candidate.disposition,
            "target_allocations": [],
            "cash_weight": None,
            "session_target": "none",
            "status": "refused",
            "refusal_reason": (
                "MANDATE_MISMATCH: mandate reference changed since review"
            ),
            "dispatched_at": curr_utc,
        }
        raw_dict["record_hash"] = compute_record_hash(raw_dict)
        return PlatformExecutionRequest.model_validate(raw_dict)

    # 6. Account paused check (T08)
    if portfolio_state.is_paused:
        raw_dict = {
            "request_id": actual_request_id,
            "candidate_id": candidate.candidate_id,
            "attempt_id": candidate.attempt_id,
            "scope": candidate.scope.model_dump(mode="python"),
            "portfolio_ref": candidate.portfolio_ref.model_dump(mode="python"),
            "mandate_ref": candidate.mandate_ref.model_dump(mode="python"),
            "disposition": candidate.disposition,
            "target_allocations": [],
            "cash_weight": None,
            "session_target": "none",
            "status": "refused",
            "refusal_reason": "ACCOUNT_PAUSED: trading paused for target account",
            "dispatched_at": curr_utc,
        }
        raw_dict["record_hash"] = compute_record_hash(raw_dict)
        return PlatformExecutionRequest.model_validate(raw_dict)

    # 7. Unresolved in-flight orders conflict check (T08, A07)
    if portfolio_state.has_pending_orders:
        raw_dict = {
            "request_id": actual_request_id,
            "candidate_id": candidate.candidate_id,
            "attempt_id": candidate.attempt_id,
            "scope": candidate.scope.model_dump(mode="python"),
            "portfolio_ref": candidate.portfolio_ref.model_dump(mode="python"),
            "mandate_ref": candidate.mandate_ref.model_dump(mode="python"),
            "disposition": candidate.disposition,
            "target_allocations": [],
            "cash_weight": None,
            "session_target": "none",
            "status": "refused",
            "refusal_reason": (
                "PENDING_ORDERS_CONFLICT: unresolved in-flight orders present"
            ),
            "dispatched_at": curr_utc,
        }
        raw_dict["record_hash"] = compute_record_hash(raw_dict)
        return PlatformExecutionRequest.model_validate(raw_dict)

    # 8. Disposition and session capability evaluation
    if candidate.disposition == "unavailable":
        raw_dict = {
            "request_id": actual_request_id,
            "candidate_id": candidate.candidate_id,
            "attempt_id": candidate.attempt_id,
            "scope": candidate.scope.model_dump(mode="python"),
            "portfolio_ref": candidate.portfolio_ref.model_dump(mode="python"),
            "mandate_ref": candidate.mandate_ref.model_dump(mode="python"),
            "disposition": candidate.disposition,
            "target_allocations": [],
            "cash_weight": None,
            "session_target": "none",
            "status": "refused",
            "refusal_reason": (
                "UNAVAILABLE_DISPOSITION: candidate disposition is unavailable"
            ),
            "dispatched_at": curr_utc,
        }
        raw_dict["record_hash"] = compute_record_hash(raw_dict)
        return PlatformExecutionRequest.model_validate(raw_dict)

    if candidate.disposition in ("hold", "abstain"):
        # Hold/abstain produces admitted request with session_target="none";
        # does NOT submit trade orders or cancel existing orders (T08)
        raw_dict = {
            "request_id": actual_request_id,
            "candidate_id": candidate.candidate_id,
            "attempt_id": candidate.attempt_id,
            "scope": candidate.scope.model_dump(mode="python"),
            "portfolio_ref": candidate.portfolio_ref.model_dump(mode="python"),
            "mandate_ref": candidate.mandate_ref.model_dump(mode="python"),
            "disposition": candidate.disposition,
            "target_allocations": [],
            "cash_weight": None,
            "session_target": "none",
            "status": "admitted",
            "refusal_reason": None,
            "dispatched_at": curr_utc,
        }
        raw_dict["record_hash"] = compute_record_hash(raw_dict)
        return PlatformExecutionRequest.model_validate(raw_dict)

    # Never turn missing Stage 1 targets into a discretionary all-cash order.
    # The existing M2 complete-target liquidation rule must remain unchanged.
    if not candidate.targets or candidate.cash_weight is None:
        raw_dict = {
            "request_id": actual_request_id,
            "candidate_id": candidate.candidate_id,
            "attempt_id": candidate.attempt_id,
            "scope": candidate.scope.model_dump(mode="python"),
            "portfolio_ref": candidate.portfolio_ref.model_dump(mode="python"),
            "mandate_ref": candidate.mandate_ref.model_dump(mode="python"),
            "disposition": candidate.disposition,
            "target_allocations": [],
            "cash_weight": None,
            "session_target": "none",
            "status": "refused",
            "refusal_reason": "EMPTY_STAGE1_TARGETS: cannot infer a liquidation intent",
            "dispatched_at": curr_utc,
        }
        raw_dict["record_hash"] = compute_record_hash(raw_dict)
        return PlatformExecutionRequest.model_validate(raw_dict)

    # An independently re-hashed ResearchCandidate is not proof that its
    # proposed weights were validated against a coherent allocation. Never
    # emit an actionable Stage 1 request with an invalid cash/target total.
    try:
        cash_text = candidate.cash_weight or ""
        cash_amount = Decimal(cash_text)
        target_amounts = [Decimal(target.weight) for target in candidate.targets]
        allocation_valid = (
            cash_amount.is_finite()
            and Decimal("0") <= cash_amount <= Decimal("1")
            and "e" not in cash_text.lower()
            and all(
                amount.is_finite() and Decimal("0") <= amount <= Decimal("1")
                for amount in target_amounts
            )
            and sum(target_amounts, cash_amount) == Decimal("1")
        )
    except (InvalidOperation, TypeError):
        allocation_valid = False
    if not allocation_valid:
        raw_dict = {
            "request_id": actual_request_id,
            "candidate_id": candidate.candidate_id,
            "attempt_id": candidate.attempt_id,
            "scope": candidate.scope.model_dump(mode="python"),
            "portfolio_ref": candidate.portfolio_ref.model_dump(mode="python"),
            "mandate_ref": candidate.mandate_ref.model_dump(mode="python"),
            "disposition": candidate.disposition,
            "target_allocations": [],
            "cash_weight": None,
            "session_target": "none",
            "status": "refused",
            "refusal_reason": "INVALID_STAGE1_TARGET_WEIGHTS",
            "dispatched_at": curr_utc,
        }
        raw_dict["record_hash"] = compute_record_hash(raw_dict)
        return PlatformExecutionRequest.model_validate(raw_dict)

    # Propose disposition: return a *candidate* request for separate M0
    # admission. The status here never authorizes a broker or a fill.
    target_allocs = [t.model_dump(mode="python") for t in candidate.targets]
    if intraday_supported:
        sess_target: SessionTarget = "intraday"
        status_val: BridgeStatus = "admitted"
        reason_val = None
    elif allow_next_open_fallback:
        sess_target = "next_open"
        status_val = "admitted"
        reason_val = None
    else:
        sess_target = "none"
        status_val = "unsupported"
        reason_val = (
            "UNSUPPORTED_SESSION: intraday session not supported and fallback disabled"
        )

    raw_dict = {
        "request_id": actual_request_id,
        "candidate_id": candidate.candidate_id,
        "attempt_id": candidate.attempt_id,
        "scope": candidate.scope.model_dump(mode="python"),
        "portfolio_ref": candidate.portfolio_ref.model_dump(mode="python"),
        "mandate_ref": candidate.mandate_ref.model_dump(mode="python"),
        "disposition": candidate.disposition,
        "target_allocations": target_allocs if status_val == "admitted" else [],
        "cash_weight": candidate.cash_weight if status_val == "admitted" else None,
        "session_target": sess_target,
        "status": status_val,
        "refusal_reason": reason_val,
        "dispatched_at": curr_utc,
    }
    raw_dict["record_hash"] = compute_record_hash(raw_dict)
    return PlatformExecutionRequest.model_validate(raw_dict)
