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
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

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
    account_id: str
    arm_id: str
    state_hash: str
    is_paused: bool
    has_pending_orders: bool
    observed_at: datetime
    state_verified: bool = False
    verification_ref: ArtifactReference | None = None


class PlatformExecutionRequest(ImmutableModel):
    """Validated execution dispatch request presented to platform executors."""

    request_id: str
    candidate_id: str
    attempt_id: str
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
        candidate.completed_at.tzinfo is None
        or candidate.completed_at.utcoffset() is None
        or portfolio_state.observed_at.tzinfo is None
        or portfolio_state.observed_at.utcoffset() is None
    ):
        raise ValueError("INDETERMINATE_TIMEZONE: input evidence timestamp has no offset")
    curr_utc = current_time.astimezone(UTC)
    cand_comp_utc = candidate.completed_at.astimezone(UTC)
    actual_request_id = request_id or str(
        uuid5(
            NAMESPACE_URL,
            compute_record_hash({
                "candidate_id": candidate.candidate_id,
                "candidate_hash": candidate.record_hash,
                "portfolio_state_hash": portfolio_state.state_hash,
                "mandate_hash": portfolio_state.mandate_ref.sha256,
                "current_time": curr_utc,
            }),
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
            "cash_weight": candidate.cash_weight,
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
            "cash_weight": candidate.cash_weight,
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
        cand_exp_utc = (
            candidate.valid_until.astimezone(UTC)
            if candidate.valid_until.tzinfo
            else candidate.valid_until.replace(tzinfo=UTC)
        )
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
                "cash_weight": candidate.cash_weight,
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
            "refusal_reason": "UNVERIFIED_PORTFOLIO_STATE: platform verification required",
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
            "refusal_reason": "STALE_OR_FUTURE_STATE: account evidence unavailable at dispatch",
            "dispatched_at": curr_utc,
        }
        raw_dict["record_hash"] = compute_record_hash(raw_dict)
        return PlatformExecutionRequest.model_validate(raw_dict)

    # 4. Portfolio state hash change check (T08)
    if (
        candidate.portfolio_ref.sha256 != portfolio_state.portfolio_ref.sha256
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
            "cash_weight": candidate.cash_weight,
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
    if candidate.mandate_ref.sha256 != portfolio_state.mandate_ref.sha256:
        raw_dict = {
            "request_id": actual_request_id,
            "candidate_id": candidate.candidate_id,
            "attempt_id": candidate.attempt_id,
            "scope": candidate.scope.model_dump(mode="python"),
            "portfolio_ref": candidate.portfolio_ref.model_dump(mode="python"),
            "mandate_ref": candidate.mandate_ref.model_dump(mode="python"),
            "disposition": candidate.disposition,
            "target_allocations": [],
            "cash_weight": candidate.cash_weight,
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
            "cash_weight": candidate.cash_weight,
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
            "cash_weight": candidate.cash_weight,
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
            "cash_weight": candidate.cash_weight,
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
            "cash_weight": candidate.cash_weight,
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
        "target_allocations": target_allocs,
        "cash_weight": candidate.cash_weight,
        "session_target": sess_target,
        "status": status_val,
        "refusal_reason": reason_val,
        "dispatched_at": curr_utc,
    }
    raw_dict["record_hash"] = compute_record_hash(raw_dict)
    return PlatformExecutionRequest.model_validate(raw_dict)
