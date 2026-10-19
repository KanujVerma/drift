"""Deterministic strategy-switch eligibility preflight for Stage 1 (Issue 422).

Evaluates whether a proposed Stage 1 strategy selection (B3, B4, or B5) is
eligible to proceed toward portfolio target staging. Operates as a pure,
non-mutating preflight component that enforces historical observation
completeness, fixed universe integrity, price validity, and incumbent
portfolio safety before any candidate targets can reach the evaluator.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import model_validator

from drift.analysis.analytical_returns import (
    CorporateActionAdjustment,
    SessionObservationRecord,
    build_analytical_return_series,
)
from drift.baselines.b3_monthly_equal_weight_rebalance import (
    B3MonthlyEqualWeightRebalanceStrategy,
)
from drift.baselines.b4_momentum import (
    B4_STRATEGY_HASH,
)
from drift.baselines.b5_low_volatility import (
    B5_STRATEGY_HASH,
)
from drift.baselines.common import (
    deterministic_baseline_uuid7,
    extract_security_history,
    get_admitted_securities,
)
from drift.domain.common import (
    UUID7,
    FrozenModel,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)
from drift.domain.evaluator_exploratory_strategy import (
    ExploratoryReconstructedDecisionViewV1,
    ExploratoryStrategyDecisionContextV1,
)
from drift.domain.evaluator_portfolio import PortfolioStateV2
from drift.domain.evaluator_reconstruction import (
    ExploratoryReconstructedSessionObservationV1,
)
from drift.domain.evaluator_strategy import (
    StrategyDecisionContextV1,
    StrategyDecisionViewV1,
)
from drift.domain.normalization import DerivedObservationViewV1
from drift.domain.sessions import SessionKeyV1
from drift.domain.strategies import StrategyReference
from drift.serialization.canonical import content_hash

STAGE1_ETF_SYMBOLS: tuple[str, ...] = (
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
STAGE1_EXPECTED_UNIVERSE_SIZE = len(STAGE1_ETF_SYMBOLS)

B3_STRATEGY_NAMES = frozenset(
    {"b3", "b3_monthly_equal_weight_rebalance", "b3_equal_weight"}
)
B4_STRATEGY_NAMES = frozenset({"b4", "b4_momentum"})
B5_STRATEGY_NAMES = frozenset({"b5", "b5_low_volatility"})

STAGE1_ADMITTED_STRATEGIES = B3_STRATEGY_NAMES | B4_STRATEGY_NAMES | B5_STRATEGY_NAMES

B3_MIN_SESSIONS = 1
B4_MIN_SESSIONS = 253
B5_MIN_SESSIONS = 61

B3_CANONICAL_HASH: SHA256Hash = B3MonthlyEqualWeightRebalanceStrategy()._strategy_hash
B4_CANONICAL_HASH: SHA256Hash = B4_STRATEGY_HASH
B5_CANONICAL_HASH: SHA256Hash = B5_STRATEGY_HASH

B3_CANONICAL_ID: UUID = deterministic_baseline_uuid7(
    "drift.baselines.b3_monthly_equal_weight_rebalance"
)
B4_CANONICAL_ID: UUID = deterministic_baseline_uuid7("drift.baselines.b4_momentum")
B5_CANONICAL_ID: UUID = deterministic_baseline_uuid7(
    "drift.baselines.b5_low_volatility"
)

B3_CANONICAL_LOCATION = "drift/baselines/b3_monthly_equal_weight_rebalance.py"
B4_CANONICAL_LOCATION = "drift/baselines/b4_momentum.py"
B5_CANONICAL_LOCATION = "drift/baselines/b5_low_volatility.py"


class PreflightStatus(StrEnum):
    """Categorical outcomes of the Stage 1 switch preflight evaluation."""

    ELIGIBLE = "eligible"
    UNAVAILABLE = "unavailable"
    ABSTAIN = "abstain"
    REJECTED = "rejected"
    INDETERMINATE_SAFETY = "indeterminate_safety"


class Stage1SwitchPreflightResult(FrozenModel):
    """Immutable, tamper-evident preflight verdict for Stage 1 strategy switching."""

    schema_version: Literal["1"] = "1"
    status: PreflightStatus
    reason: NonBlankStr
    proposed_strategy: str
    current_strategy: str | None
    effective_strategy: str | None
    is_tradeable: bool
    hold_incumbent: bool
    requires_containment: bool
    session_key: SessionKeyV1 | None = None
    decision_cutoff: UTCDateTime | None = None
    cohort_hash: SHA256Hash | None = None
    admitted_universe: tuple[UUID7, ...] = ()
    portfolio_state_hash: SHA256Hash | None = None
    account_id: str | None = None
    mandate: str | None = None
    preflight_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_preflight_verdict(self) -> Self:
        """Self-validate status/flag coherence and cryptographic content hash."""
        if self.status == PreflightStatus.ELIGIBLE:
            if not self.is_tradeable:
                raise ValueError("ELIGIBLE status requires is_tradeable=True")
            if self.hold_incumbent:
                raise ValueError("ELIGIBLE status requires hold_incumbent=False")
            if self.requires_containment:
                raise ValueError("ELIGIBLE status requires requires_containment=False")
            if self.effective_strategy != self.proposed_strategy:
                raise ValueError(
                    "ELIGIBLE status requires effective_strategy == proposed_strategy"
                )
            if self.session_key is None:
                raise ValueError("ELIGIBLE status requires bound session_key")
            if self.decision_cutoff is None:
                raise ValueError("ELIGIBLE status requires bound decision_cutoff")
            if not self.admitted_universe:
                raise ValueError("ELIGIBLE status requires non-empty admitted_universe")
            if self.portfolio_state_hash is None:
                raise ValueError("ELIGIBLE status requires bound portfolio_state_hash")
            if self.account_id is None or not self.account_id.strip():
                raise ValueError("ELIGIBLE status requires non-empty account_id")
            if self.mandate is None or not self.mandate.strip():
                raise ValueError("ELIGIBLE status requires non-empty mandate")

        elif self.status == PreflightStatus.ABSTAIN:
            if self.is_tradeable:
                raise ValueError("ABSTAIN status requires is_tradeable=False")
            if self.hold_incumbent:
                if self.requires_containment:
                    raise ValueError(
                        "safe hold_incumbent requires requires_containment=False"
                    )
                if self.effective_strategy != self.current_strategy:
                    raise ValueError(
                        "safe hold_incumbent requires "
                        "effective_strategy == current_strategy"
                    )
            else:
                if not self.requires_containment:
                    raise ValueError(
                        "failed hold_incumbent requires requires_containment=True"
                    )
                if self.effective_strategy is not None:
                    raise ValueError(
                        "failed hold_incumbent requires effective_strategy=None"
                    )

        elif self.status in (PreflightStatus.UNAVAILABLE, PreflightStatus.REJECTED):
            if self.is_tradeable:
                raise ValueError(f"{self.status} status requires is_tradeable=False")
            if self.hold_incumbent:
                if self.requires_containment:
                    raise ValueError(
                        "safe hold_incumbent requires requires_containment=False"
                    )
                if self.effective_strategy != self.current_strategy:
                    raise ValueError(
                        "safe hold_incumbent requires "
                        "effective_strategy == current_strategy"
                    )
            else:
                if not self.requires_containment:
                    raise ValueError(
                        "failed hold_incumbent requires requires_containment=True"
                    )
                if self.effective_strategy is not None:
                    raise ValueError(
                        "failed hold_incumbent requires effective_strategy=None"
                    )

        elif self.status == PreflightStatus.INDETERMINATE_SAFETY:
            if self.is_tradeable:
                raise ValueError(
                    "INDETERMINATE_SAFETY status requires is_tradeable=False"
                )
            if self.hold_incumbent:
                raise ValueError(
                    "INDETERMINATE_SAFETY status requires hold_incumbent=False"
                )
            if not self.requires_containment:
                raise ValueError(
                    "INDETERMINATE_SAFETY status requires requires_containment=True"
                )
            if self.effective_strategy is not None:
                raise ValueError(
                    "INDETERMINATE_SAFETY status requires effective_strategy=None"
                )

        expected_hash = compute_preflight_hash(
            status=self.status,
            reason=self.reason,
            proposed_strategy=self.proposed_strategy,
            current_strategy=self.current_strategy,
            effective_strategy=self.effective_strategy,
            is_tradeable=self.is_tradeable,
            hold_incumbent=self.hold_incumbent,
            requires_containment=self.requires_containment,
            session_key=self.session_key,
            decision_cutoff=self.decision_cutoff,
            cohort_hash=self.cohort_hash,
            admitted_universe=self.admitted_universe,
            portfolio_state_hash=self.portfolio_state_hash,
            account_id=self.account_id,
            mandate=self.mandate,
        )
        if self.preflight_hash != expected_hash:
            raise ValueError(
                f"preflight hash mismatch: expected {expected_hash}, "
                f"got {self.preflight_hash}"
            )
        return self


def compute_preflight_hash(
    *,
    status: PreflightStatus,
    reason: str,
    proposed_strategy: str,
    current_strategy: str | None,
    effective_strategy: str | None,
    is_tradeable: bool,
    hold_incumbent: bool,
    requires_containment: bool,
    session_key: SessionKeyV1 | None,
    decision_cutoff: datetime | None,
    cohort_hash: str | None,
    admitted_universe: Sequence[UUID7],
    portfolio_state_hash: str | None,
    account_id: str | None,
    mandate: str | None,
) -> SHA256Hash:
    """Compute the deterministic cryptographic SHA-256 hash of a preflight result."""
    payload = {
        "status": status.value,
        "reason": reason,
        "proposed_strategy": proposed_strategy,
        "current_strategy": current_strategy,
        "effective_strategy": effective_strategy,
        "is_tradeable": is_tradeable,
        "hold_incumbent": hold_incumbent,
        "requires_containment": requires_containment,
        "session_key": (
            {
                "mic": session_key.mic,
                "session_scope": session_key.session_scope,
                "local_date": str(session_key.local_date),
            }
            if session_key is not None
            else None
        ),
        "decision_cutoff": (
            decision_cutoff.isoformat() if decision_cutoff is not None else None
        ),
        "cohort_hash": cohort_hash,
        "admitted_universe": [str(u) for u in admitted_universe],
        "portfolio_state_hash": portfolio_state_hash,
        "account_id": account_id,
        "mandate": mandate,
    }
    return content_hash(payload)


def _make_result(
    *,
    status: PreflightStatus,
    reason: str,
    proposed_strategy: str,
    current_strategy: str | None,
    effective_strategy: str | None,
    is_tradeable: bool,
    hold_incumbent: bool,
    requires_containment: bool,
    session_key: SessionKeyV1 | None = None,
    decision_cutoff: datetime | None = None,
    cohort_hash: str | None = None,
    admitted_universe: tuple[UUID7, ...] = (),
    portfolio_state_hash: str | None = None,
    account_id: str | None = None,
    mandate: str | None = None,
) -> Stage1SwitchPreflightResult:
    """Helper to construct a self-hashed Stage1SwitchPreflightResult."""
    p_hash = compute_preflight_hash(
        status=status,
        reason=reason,
        proposed_strategy=proposed_strategy,
        current_strategy=current_strategy,
        effective_strategy=effective_strategy,
        is_tradeable=is_tradeable,
        hold_incumbent=hold_incumbent,
        requires_containment=requires_containment,
        session_key=session_key,
        decision_cutoff=decision_cutoff,
        cohort_hash=cohort_hash,
        admitted_universe=admitted_universe,
        portfolio_state_hash=portfolio_state_hash,
        account_id=account_id,
        mandate=mandate,
    )
    return Stage1SwitchPreflightResult(
        schema_version="1",
        status=status,
        reason=reason,
        proposed_strategy=proposed_strategy,
        current_strategy=current_strategy,
        effective_strategy=effective_strategy,
        is_tradeable=is_tradeable,
        hold_incumbent=hold_incumbent,
        requires_containment=requires_containment,
        session_key=session_key,
        decision_cutoff=decision_cutoff,
        cohort_hash=cohort_hash,
        admitted_universe=admitted_universe,
        portfolio_state_hash=portfolio_state_hash,
        account_id=account_id,
        mandate=mandate,
        preflight_hash=p_hash,
    )


def validate_strategy_identity(
    strategy: str | StrategyReference | None,
) -> tuple[str | None, str | None]:
    """Validate strategy identity against Stage 1 admitted references.

    Returns (canonical_name, rejection_reason).
    canonical_name is one of 'B3', 'B4', 'B5', 'ABSTAIN', or None.
    If rejection_reason is not None, validation failed.
    """
    if strategy is None:
        return None, None
    if isinstance(strategy, StrategyReference):
        if strategy.strategy_version != "1":
            return (
                None,
                f"unsupported_strategy_version: expected '1', "
                f"got {strategy.strategy_version!r}",
            )
        if strategy.strategy_id == B3_CANONICAL_ID:
            if strategy.code_hash != B3_CANONICAL_HASH:
                return (
                    None,
                    f"strategy_code_hash_mismatch: B3 code hash {strategy.code_hash} "
                    f"does not match canonical {B3_CANONICAL_HASH}",
                )
            if strategy.artifact_reference.location != B3_CANONICAL_LOCATION:
                return (
                    None,
                    "strategy_location_mismatch: B3 location "
                    f"{strategy.artifact_reference.location!r} "
                    "does not match canonical",
                )
            if strategy.artifact_reference.content_hash != strategy.code_hash:
                return (
                    None,
                    "strategy_artifact_hash_mismatch: artifact content hash "
                    "does not match strategy code hash",
                )
            return "B3", None

        if strategy.strategy_id == B4_CANONICAL_ID:
            if strategy.code_hash != B4_CANONICAL_HASH:
                return (
                    None,
                    f"strategy_code_hash_mismatch: B4 code hash {strategy.code_hash} "
                    f"does not match canonical {B4_CANONICAL_HASH}",
                )
            if strategy.artifact_reference.location != B4_CANONICAL_LOCATION:
                return (
                    None,
                    "strategy_location_mismatch: B4 location "
                    f"{strategy.artifact_reference.location!r} "
                    "does not match canonical",
                )
            if strategy.artifact_reference.content_hash != strategy.code_hash:
                return (
                    None,
                    "strategy_artifact_hash_mismatch: artifact content hash "
                    "does not match strategy code hash",
                )
            return "B4", None

        if strategy.strategy_id == B5_CANONICAL_ID:
            if strategy.code_hash != B5_CANONICAL_HASH:
                return (
                    None,
                    f"strategy_code_hash_mismatch: B5 code hash {strategy.code_hash} "
                    f"does not match canonical {B5_CANONICAL_HASH}",
                )
            if strategy.artifact_reference.location != B5_CANONICAL_LOCATION:
                return (
                    None,
                    "strategy_location_mismatch: B5 location "
                    f"{strategy.artifact_reference.location!r} "
                    "does not match canonical",
                )
            if strategy.artifact_reference.content_hash != strategy.code_hash:
                return (
                    None,
                    "strategy_artifact_hash_mismatch: artifact content hash "
                    "does not match strategy code hash",
                )
            return "B5", None

        return (
            None,
            f"unrecognized_strategy_id: strategy_id {strategy.strategy_id} "
            "is not an approved Stage 1 baseline",
        )

    norm = strategy.strip().lower()
    if norm in B3_STRATEGY_NAMES or norm == "b3":
        return "B3", None
    if norm in B4_STRATEGY_NAMES or norm == "b4":
        return "B4", None
    if norm in B5_STRATEGY_NAMES or norm == "b5":
        return "B5", None
    if norm == "abstain":
        return "ABSTAIN", None
    return (
        None,
        f"unsupported_stage1_strategy: proposed strategy {strategy!r} "
        "is not an admitted Stage 1 candidate (admitted: B3, B4, B5, ABSTAIN)",
    )


def check_portfolio_safety(
    *,
    current_portfolio_state: PortfolioStateV2 | None,
    decision_context: (
        StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1 | None
    ),
    open_orders: Sequence[object] | None,
    mandate_verified: bool | None,
    risk_verified: bool | None,
    account_id: str | None,
    mandate: str | None,
) -> tuple[bool, str | None]:
    """Reconcile complete portfolio book and context safety evidence.

    Returns (is_safe, failure_reason). Shared identically by positive candidate
    eligibility and safe-hold fallback resolution.
    """
    if account_id is None or not account_id.strip():
        return False, "missing_account_id: explicit account_id is required"
    if mandate is None or not mandate.strip():
        return False, "missing_mandate: explicit mandate identifier is required"
    if mandate_verified is not True:
        return (
            False,
            "unverified_mandate: affirmative mandate verification evidence is required",
        )
    if risk_verified is not True:
        return (
            False,
            "unverified_risk: affirmative risk verification evidence is required",
        )
    if open_orders is None:
        return (
            False,
            "unknown_open_orders_status: open_orders must be explicitly queried; "
            "missing status cannot assume zero obligations",
        )
    if len(open_orders) > 0:
        return (
            False,
            f"pending_orders_present: portfolio has {len(open_orders)} "
            "open or pending orders",
        )
    if current_portfolio_state is None:
        return (
            False,
            "missing_portfolio_state: current_portfolio_state is required "
            "to establish safe trading or holding",
        )
    if current_portfolio_state.cash_balance < Decimal("0"):
        return False, "negative_cash: current portfolio cash balance is negative"

    for h in current_portfolio_state.holdings:
        if h.basis_status == "indeterminate":
            return (
                False,
                f"indeterminate_holding_basis: holding {h.security_id} "
                "has indeterminate cost basis",
            )

    # Mandatory decision context verification
    if decision_context is None:
        return (
            False,
            "missing_decision_context: strategy decision context is required "
            "for portfolio safety verification",
        )
    if decision_context.session_key is None:
        return (
            False,
            "missing_decision_session: decision context lacks session_key",
        )
    if decision_context.decision_cutoff is None:
        return (
            False,
            "missing_decision_cutoff: decision context lacks decision_cutoff timestamp",
        )

    if current_portfolio_state.session_key != decision_context.session_key:
        return (
            False,
            "portfolio_context_session_mismatch: portfolio session "
            f"{current_portfolio_state.session_key} does not match "
            f"context {decision_context.session_key}",
        )
    if decision_context.portfolio_nav <= Decimal("0"):
        return False, "non_positive_nav: context portfolio_nav is non-positive"
    if abs(
        current_portfolio_state.net_asset_value - decision_context.portfolio_nav
    ) > Decimal("0.01"):
        return (
            False,
            "portfolio_context_nav_mismatch: portfolio NAV "
            f"{current_portfolio_state.net_asset_value} does not match "
            f"context NAV {decision_context.portfolio_nav}",
        )
    if (
        hasattr(decision_context, "current_cash")
        and decision_context.current_cash is not None
    ):
        if abs(
            current_portfolio_state.cash_balance - decision_context.current_cash
        ) > Decimal("0.01"):
            return (
                False,
                "portfolio_context_cash_mismatch: portfolio cash "
                f"{current_portfolio_state.cash_balance} does not match "
                f"context cash {decision_context.current_cash}",
            )
    if (
        hasattr(decision_context, "current_holdings")
        and decision_context.current_holdings is not None
    ):
        ctx_holdings = {
            h.security_id: h.quantity for h in decision_context.current_holdings
        }
        port_holdings = {
            h.security_id: h.quantity for h in current_portfolio_state.holdings
        }
        if ctx_holdings != port_holdings:
            return (
                False,
                "portfolio_context_holdings_mismatch: "
                "portfolio holdings do not match context holdings",
            )

    return True, None


def validate_universe(
    *,
    required_universe: Sequence[UUID7] | None,
    expected_universe_hash: SHA256Hash | None,
    context_cohort: tuple[UUID7, ...],
    cohort_hash: SHA256Hash | None,
    universe_manifest: Mapping[UUID7, str] | Mapping[str, UUID7] | None,
) -> tuple[bool, str | None, tuple[UUID7, ...]]:
    """Validate 12-ETF universe completeness, hash match, and manifest."""
    if required_universe is None or len(required_universe) == 0:
        return (
            False,
            "missing_required_universe: required_universe must be an explicit, "
            "nonempty sequence of admitted security IDs",
            (),
        )

    if len(required_universe) != len(set(required_universe)):
        return (
            False,
            "duplicate_security_in_required_universe: required_universe contains "
            "duplicate security IDs",
            (),
        )

    if len(required_universe) != STAGE1_EXPECTED_UNIVERSE_SIZE:
        return (
            False,
            "mismatched_universe_size: expected exactly "
            f"{STAGE1_EXPECTED_UNIVERSE_SIZE} Stage 1 ETFs, "
            f"got {len(required_universe)}",
            (),
        )

    req_set = set(required_universe)
    ctx_set = set(context_cohort)

    if len(context_cohort) != len(ctx_set):
        return (
            False,
            "duplicate_security_in_context_cohort: context admitted securities "
            "contain duplicates",
            (),
        )

    if req_set != ctx_set:
        missing_in_ctx = req_set - ctx_set
        extra_in_ctx = ctx_set - req_set
        if missing_in_ctx:
            return (
                False,
                f"missing_securities_in_context: context lacks required securities: "
                f"{missing_in_ctx}",
                (),
            )
        if extra_in_ctx:
            return (
                False,
                f"extra_securities_in_context: context contains extra securities: "
                f"{extra_in_ctx}",
                (),
            )

    if expected_universe_hash is None:
        return (
            False,
            "missing_expected_universe_hash: "
            "expected_universe_hash must be explicitly provided",
            (),
        )

    if cohort_hash is not None and cohort_hash != expected_universe_hash:
        return (
            False,
            f"universe_hash_mismatch: expected {expected_universe_hash}, "
            f"got {cohort_hash}",
            (),
        )

    if universe_manifest is None:
        return (
            False,
            "missing_universe_manifest: explicit trusted universe manifest "
            "mapping required to authenticate security identities",
            (),
        )

    normalized_manifest: dict[UUID7, str] = {}
    for k, v in universe_manifest.items():
        if isinstance(k, UUID) and isinstance(v, str):
            normalized_manifest[k] = v.upper()
        elif isinstance(k, str) and isinstance(v, UUID):
            normalized_manifest[v] = k.upper()
        else:
            return (
                False,
                f"invalid_universe_manifest_entry: manifest entry {k!r}: {v!r} "
                "must map UUID to symbol",
                (),
            )

    mapped_symbols: list[str] = []
    for sec_id in req_set:
        if sec_id not in normalized_manifest:
            return (
                False,
                f"unmapped_universe_security: security {sec_id} not present in "
                "trusted universe manifest",
                (),
            )
        sym = normalized_manifest[sec_id]
        if sym not in STAGE1_ETF_SYMBOLS:
            return (
                False,
                f"unrecognized_universe_symbol: security {sec_id} mapped to "
                f"symbol {sym!r}, which is not an admitted Stage 1 ETF",
                (),
            )
        mapped_symbols.append(sym)

    if len(set(mapped_symbols)) != STAGE1_EXPECTED_UNIVERSE_SIZE:
        return (
            False,
            f"mismatched_universe_symbols: manifest does not contain all "
            f"{STAGE1_EXPECTED_UNIVERSE_SIZE} distinct Stage 1 ETF symbols",
            (),
        )

    sorted_universe = tuple(sorted(req_set, key=lambda u: u.bytes))
    return True, None, sorted_universe


def _get_raw_observations(
    context: StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1 | None,
    sec_id: UUID7,
) -> Sequence[object]:
    """Retrieve raw historical observation objects for a security."""
    if context is None:
        return ()

    if isinstance(context, StrategyDecisionContextV1):
        for group in context.decision_views:
            if not isinstance(group, StrategyDecisionViewV1):
                raise ValueError(
                    "cross_lane_evidence_detected: StrategyDecisionContextV1 "
                    f"contains non-StrategyDecisionViewV1 group {type(group)}"
                )
            if group.security_id == sec_id:
                for view in group.views:
                    if not isinstance(view, DerivedObservationViewV1):
                        raise ValueError(
                            "cross_lane_evidence_detected: StrategyDecisionViewV1 "
                            f"contains non-DerivedObservationViewV1 view {type(view)}"
                        )
                return group.views
        return ()

    if isinstance(context, ExploratoryStrategyDecisionContextV1):
        if context.lane != "exploratory":
            raise ValueError(
                "invalid_exploratory_lane: expected lane 'exploratory', "
                f"got {context.lane!r}"
            )
        for recon_group in context.reconstructed_decision_views:
            if not isinstance(recon_group, ExploratoryReconstructedDecisionViewV1):
                raise ValueError(
                    "cross_lane_evidence_detected: "
                    "ExploratoryStrategyDecisionContextV1 "
                    f"contains non-group {type(recon_group)}"
                )
            if recon_group.security_id == sec_id:
                for obs in recon_group.observations:
                    if not isinstance(
                        obs, ExploratoryReconstructedSessionObservationV1
                    ):
                        raise ValueError(
                            "cross_lane_evidence_detected: "
                            "ExploratoryReconstructedDecisionViewV1 contains "
                            f"non-observation record {type(obs)}"
                        )
                return recon_group.observations
        return ()

    raise ValueError(
        "unsupported_context_type: unrecognized strategy decision context "
        f"type {type(context)}"
    )


def validate_observations_and_adjustments(
    *,
    decision_context: (
        StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1 | None
    ),
    eval_universe: tuple[UUID7, ...],
    prop_name: str,
    decision_cutoff: datetime,
    session_key: SessionKeyV1,
    adjustments_by_security: (
        Mapping[UUID7, Sequence[CorporateActionAdjustment]] | None
    ),
    completed_sessions: (Iterable[date | SessionKeyV1] | None) = None,
) -> tuple[bool, PreflightStatus, str | None]:
    """Validate observation ordering, timestamps, calendar, and adjustments."""
    if decision_context is None:
        return (
            False,
            PreflightStatus.UNAVAILABLE,
            "missing_decision_context: strategy decision context is required",
        )

    if completed_sessions is None:
        return (
            False,
            PreflightStatus.UNAVAILABLE,
            "missing_trading_calendar_evidence: completed trading session schedule "
            "is required to verify session count and exchange status",
        )

    completed_keys: set[SessionKeyV1] = set()
    completed_dates: set[date] = set()
    for item in completed_sessions:
        if isinstance(item, SessionKeyV1):
            completed_keys.add(item)
            completed_dates.add(item.local_date)
        elif isinstance(item, date):
            completed_dates.add(item)

    if prop_name == "B3":
        min_required_sessions = B3_MIN_SESSIONS
    elif prop_name == "B4":
        min_required_sessions = B4_MIN_SESSIONS
    elif prop_name == "B5":
        min_required_sessions = B5_MIN_SESSIONS
    else:
        min_required_sessions = 1

    if prop_name in {"B4", "B5"} and adjustments_by_security is None:
        return (
            False,
            PreflightStatus.UNAVAILABLE,
            "missing_adjustments_manifest: corporate action adjustments "
            "manifest is required for analytical strategies B4/B5; absent "
            "manifest cannot be inferred as zero adjustments",
        )

    cutoff_date = session_key.local_date
    eligible_momentum_securities: list[UUID7] = []
    eligible_volatility_securities: list[UUID7] = []

    for sec_id in eval_universe:
        try:
            raw_obs = _get_raw_observations(decision_context, sec_id)
        except ValueError as exc:
            return False, PreflightStatus.REJECTED, str(exc)

        if not raw_obs:
            return (
                False,
                PreflightStatus.UNAVAILABLE,
                f"missing_observations: security {sec_id} has no observations",
            )

        seen_raw_sessions = set()
        for raw_item in raw_obs:
            raw_s_key = getattr(raw_item, "source_session", None) or getattr(
                raw_item, "session_key", None
            )
            if raw_s_key is None:
                return (
                    False,
                    PreflightStatus.REJECTED,
                    f"malformed_observation: observation for security {sec_id} "
                    "lacks session key",
                )

            if raw_s_key.local_date > cutoff_date:
                return (
                    False,
                    PreflightStatus.UNAVAILABLE,
                    f"future_observation_detected: observation for "
                    f"security {sec_id} dated {raw_s_key.local_date} "
                    f"exceeds cutoff {cutoff_date}",
                )
            if raw_s_key.local_date.weekday() >= 5:
                return (
                    False,
                    PreflightStatus.REJECTED,
                    f"weekend_observation_detected: observation for "
                    f"security {sec_id} dated {raw_s_key.local_date} "
                    "occurs on a weekend",
                )
            if (
                raw_s_key not in completed_keys
                and raw_s_key.local_date not in completed_dates
            ):
                return (
                    False,
                    PreflightStatus.REJECTED,
                    f"closed_session_observation_detected: session "
                    f"{raw_s_key.local_date} is not an evidenced open trading session",
                )
            if raw_s_key in seen_raw_sessions:
                return (
                    False,
                    PreflightStatus.REJECTED,
                    f"duplicate_session_observation: security {sec_id} "
                    f"has duplicate observation for session {raw_s_key}",
                )
            seen_raw_sessions.add(raw_s_key)

            # Check time availability
            if isinstance(raw_item, DerivedObservationViewV1):
                if raw_item.role != "decision":
                    return (
                        False,
                        PreflightStatus.REJECTED,
                        f"invalid_observation_role: derived view for security {sec_id} "
                        f"has role {raw_item.role!r}, expected 'decision'",
                    )
                query_obs = getattr(raw_item.query, "observation", None)
                if query_obs is None:
                    return (
                        False,
                        PreflightStatus.UNAVAILABLE,
                        f"missing_observation_availability_evidence: derived view for "
                        f"security {sec_id} lacks observation query",
                    )
                d_time = getattr(query_obs, "decision_time", None)
                k_cutoff = getattr(query_obs, "knowledge_cutoff", None)
                e_cutoff = getattr(query_obs, "effective_cutoff", None)
                if d_time is None and k_cutoff is None and e_cutoff is None:
                    return (
                        False,
                        PreflightStatus.UNAVAILABLE,
                        f"missing_observation_availability_evidence: observation query "
                        f"for security {sec_id} lacks temporal cutoff evidence",
                    )
                for t_name, t_val in (
                    ("decision_time", d_time),
                    ("knowledge_cutoff", k_cutoff),
                    ("effective_cutoff", e_cutoff),
                ):
                    if t_val is not None and t_val > decision_cutoff:
                        return (
                            False,
                            PreflightStatus.UNAVAILABLE,
                            f"late_available_observation_detected: observation for "
                            f"security {sec_id} {t_name} {t_val.isoformat()} exceeds "
                            f"decision cutoff {decision_cutoff.isoformat()}",
                        )
            elif isinstance(raw_item, ExploratoryReconstructedSessionObservationV1):
                t_val = raw_item.evidence_vintage_cutoff
                if t_val is None:
                    return (
                        False,
                        PreflightStatus.UNAVAILABLE,
                        f"missing_observation_availability_evidence: observation "
                        f"for security {sec_id} lacks evidence_vintage_cutoff",
                    )
                if t_val > decision_cutoff:
                    return (
                        False,
                        PreflightStatus.UNAVAILABLE,
                        "late_available_observation_detected: observation for "
                        f"security {sec_id} evidence_vintage_cutoff "
                        f"{t_val.isoformat()} exceeds decision cutoff "
                        f"{decision_cutoff.isoformat()}",
                    )
            else:
                candidate_t = None
                for attr_name in (
                    "evidence_vintage_cutoff",
                    "available_at",
                    "closed_at",
                ):
                    cand = getattr(raw_item, attr_name, None)
                    if isinstance(cand, datetime):
                        candidate_t = cand
                        break
                if candidate_t is None:
                    return (
                        False,
                        PreflightStatus.UNAVAILABLE,
                        f"missing_observation_availability_evidence: observation "
                        f"for security {sec_id} lacks availability timestamp",
                    )
                if candidate_t > decision_cutoff:
                    return (
                        False,
                        PreflightStatus.UNAVAILABLE,
                        f"late_available_observation_detected: observation for "
                        f"security {sec_id} timestamp exceeds decision cutoff",
                    )

        history = extract_security_history(decision_context, sec_id)
        if not history:
            return (
                False,
                PreflightStatus.UNAVAILABLE,
                f"missing_extracted_history: security {sec_id} "
                "has no extracted history",
            )

        # Check chronological order, non-empty, and valid price marks
        prev_date = None
        has_current_session_close = False
        valid_history_sessions: list[SessionObservationRecord] = []
        for obs in history:
            if obs.session_key.local_date > cutoff_date:
                return (
                    False,
                    PreflightStatus.UNAVAILABLE,
                    f"future_observation_detected: observation for security "
                    f"{sec_id} dated {obs.session_key.local_date} exceeds "
                    f"decision cutoff {cutoff_date}",
                )
            if obs.session_key.local_date.weekday() >= 5:
                return (
                    False,
                    PreflightStatus.REJECTED,
                    f"weekend_observation_detected: observation for security "
                    f"{sec_id} dated {obs.session_key.local_date} occurs on a weekend",
                )
            if (
                obs.session_key not in completed_keys
                and obs.session_key.local_date not in completed_dates
            ):
                return (
                    False,
                    PreflightStatus.REJECTED,
                    "closed_session_observation_detected: session "
                    f"{obs.session_key.local_date} is not an evidenced "
                    "open trading session",
                )
            if prev_date is not None and obs.session_key.local_date < prev_date:
                return (
                    False,
                    PreflightStatus.REJECTED,
                    f"out_of_order_observations: observations for security {sec_id} "
                    "are not strictly chronologically ordered",
                )
            prev_date = obs.session_key.local_date

            if obs.close_price <= Decimal("0"):
                return (
                    False,
                    PreflightStatus.REJECTED,
                    f"invalid_close_price: security {sec_id} has non-positive "
                    f"close price {obs.close_price}",
                )

            vol = getattr(obs, "volume", None)
            if vol is not None and vol < 0:
                return (
                    False,
                    PreflightStatus.REJECTED,
                    f"invalid_volume: security {sec_id} has negative volume {vol}",
                )

            if obs.session_key == session_key:
                has_current_session_close = True

            valid_history_sessions.append(obs)

        if not has_current_session_close:
            return (
                False,
                PreflightStatus.UNAVAILABLE,
                f"missing_current_session_close: security {sec_id} lacks explicit "
                f"closing mark for decision session {session_key}",
            )

        # Corporate action adjustments verification
        sec_adjs: Sequence[CorporateActionAdjustment] = ()
        if adjustments_by_security is not None:
            if sec_id not in adjustments_by_security:
                return (
                    False,
                    PreflightStatus.UNAVAILABLE,
                    f"incomplete_adjustments_manifest: security {sec_id} missing "
                    "from corporate action adjustments manifest",
                )
            sec_adjs = adjustments_by_security[sec_id]

        for adj in sec_adjs:
            if adj.split_ratio <= Decimal("0"):
                return (
                    False,
                    PreflightStatus.REJECTED,
                    f"invalid_corporate_action_adjustment: security {sec_id} "
                    f"split ratio {adj.split_ratio} must be strictly positive",
                )
            if adj.cash_distribution < Decimal("0"):
                return (
                    False,
                    PreflightStatus.REJECTED,
                    f"invalid_corporate_action_adjustment: security {sec_id} "
                    f"cash distribution {adj.cash_distribution} cannot be negative",
                )
            if adj.effective_date > session_key.local_date:
                return (
                    False,
                    PreflightStatus.UNAVAILABLE,
                    f"future_corporate_action_adjustment: adjustment for security "
                    f"{sec_id} dated {adj.effective_date} exceeds decision session "
                    f"date {session_key.local_date}",
                )

        # Analytical return series verification for B4 and B5
        if prop_name in {"B4", "B5"}:
            series_grade: Literal["exploratory", "promotion"] = (
                "promotion"
                if isinstance(decision_context, StrategyDecisionContextV1)
                else "exploratory"
            )
            try:
                series = build_analytical_return_series(
                    security_id=sec_id,
                    grade=series_grade,
                    observations=valid_history_sessions,
                    adjustments=sec_adjs,
                )
            except Exception as exc:
                return (
                    False,
                    PreflightStatus.UNAVAILABLE,
                    f"analytical_series_error: security {sec_id} cannot build "
                    f"analytical return series: {exc}",
                )

            if len(series.sessions) < min_required_sessions:
                return (
                    False,
                    PreflightStatus.UNAVAILABLE,
                    f"insufficient_history: security {sec_id} "
                    f"produced {len(series.sessions)} analytical sessions; "
                    f"minimum {min_required_sessions} required",
                )

            if prop_name == "B4":
                t = len(series.sessions) - 1
                close_skip = series.sessions[t - 21].analytical_close
                close_form = series.sessions[t - 252].analytical_close
                if close_form > Decimal("0") and close_skip > Decimal("0"):
                    eligible_momentum_securities.append(sec_id)
            elif prop_name == "B5":
                valid_returns = [
                    s.return_from_prior
                    for s in series.sessions[-60:]
                    if s.return_from_prior is not None
                ]
                if len(valid_returns) >= 60:
                    eligible_volatility_securities.append(sec_id)

    # Check minimum eligible securities for B4 and B5 (accidental liquidation safeguard)
    if prop_name == "B4" and len(eligible_momentum_securities) < 2:
        return (
            False,
            PreflightStatus.UNAVAILABLE,
            f"insufficient_eligible_securities: only "
            f"{len(eligible_momentum_securities)} securities have valid momentum; "
            "minimum 2 required for B4",
        )

    if prop_name == "B5" and len(eligible_volatility_securities) < 2:
        return (
            False,
            PreflightStatus.UNAVAILABLE,
            f"insufficient_eligible_securities: only "
            f"{len(eligible_volatility_securities)} securities have valid "
            "volatility; minimum 2 required for B5",
        )

    return True, PreflightStatus.ELIGIBLE, None


def _resolve_non_eligible_outcome(
    *,
    status: PreflightStatus,
    reason: str,
    prop_name: str | None = None,
    curr_name: str | None,
    decision_context: (
        StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1 | None
    ),
    required_universe: Sequence[UUID7] | None = None,
    expected_universe_hash: SHA256Hash | None = None,
    universe_manifest: Mapping[UUID7, str] | Mapping[str, UUID7] | None = None,
    current_portfolio_state: PortfolioStateV2 | None,
    allow_incumbent_continuation: bool,
    account_id: str | None = None,
    mandate: str | None = None,
    portfolio_state_hash: str | None = None,
    open_orders: Sequence[object] | None = None,
    mandate_verified: bool | None = None,
    risk_verified: bool | None = None,
) -> Stage1SwitchPreflightResult:
    """Resolve whether an unavailable/rejected switch can safely hold incumbent."""
    candidate_strategy = prop_name if prop_name is not None else "UNKNOWN"
    session_key = decision_context.session_key if decision_context else None
    decision_cutoff = decision_context.decision_cutoff if decision_context else None

    context_cohort = (
        get_admitted_securities(decision_context)
        if decision_context is not None
        else ()
    )
    context_cohort_hash = (
        getattr(decision_context, "cohort_hash", None)
        if decision_context is not None
        else None
    )

    is_valid_u, u_reason, eval_universe = validate_universe(
        required_universe=required_universe,
        expected_universe_hash=expected_universe_hash,
        context_cohort=context_cohort,
        cohort_hash=context_cohort_hash,
        universe_manifest=universe_manifest,
    )

    cohort_hash = (
        (context_cohort_hash or expected_universe_hash) if is_valid_u else None
    )
    admitted_universe = eval_universe if is_valid_u else ()

    if not is_valid_u:
        status = PreflightStatus.INDETERMINATE_SAFETY
        reason = f"{reason}; {u_reason or 'cohort_binding_unavailable'}"

    if status == PreflightStatus.INDETERMINATE_SAFETY:
        return _make_result(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=reason,
            proposed_strategy=candidate_strategy,
            current_strategy=curr_name,
            effective_strategy=None,
            is_tradeable=False,
            hold_incumbent=False,
            requires_containment=True,
            session_key=session_key,
            decision_cutoff=decision_cutoff,
            cohort_hash=cohort_hash,
            admitted_universe=admitted_universe,
            portfolio_state_hash=portfolio_state_hash,
            account_id=account_id,
            mandate=mandate,
        )

    if not allow_incumbent_continuation:
        return _make_result(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=f"{reason}; incumbent continuation disabled",
            proposed_strategy=candidate_strategy,
            current_strategy=curr_name,
            effective_strategy=None,
            is_tradeable=False,
            hold_incumbent=False,
            requires_containment=True,
            session_key=session_key,
            decision_cutoff=decision_cutoff,
            cohort_hash=cohort_hash,
            admitted_universe=admitted_universe,
            portfolio_state_hash=portfolio_state_hash,
            account_id=account_id,
            mandate=mandate,
        )

    # Reconcile complete portfolio book safety before granting safe hold
    is_safe, port_err = check_portfolio_safety(
        current_portfolio_state=current_portfolio_state,
        decision_context=decision_context,
        open_orders=open_orders,
        mandate_verified=mandate_verified,
        risk_verified=risk_verified,
        account_id=account_id,
        mandate=mandate,
    )
    if not is_safe:
        return _make_result(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=f"{reason}; {port_err}",
            proposed_strategy=candidate_strategy,
            current_strategy=curr_name,
            effective_strategy=None,
            is_tradeable=False,
            hold_incumbent=False,
            requires_containment=True,
            session_key=session_key,
            decision_cutoff=decision_cutoff,
            cohort_hash=cohort_hash,
            admitted_universe=admitted_universe,
            portfolio_state_hash=portfolio_state_hash,
            account_id=account_id,
            mandate=mandate,
        )

    # Verify incumbent strategy identity
    if curr_name is None or curr_name not in {"B3", "B4", "B5"}:
        return _make_result(
            status=PreflightStatus.INDETERMINATE_SAFETY,
            reason=(
                f"{reason}; unknown or unadmitted incumbent strategy {curr_name!r}, "
                "cannot establish safe hold"
            ),
            proposed_strategy=candidate_strategy,
            current_strategy=curr_name,
            effective_strategy=None,
            is_tradeable=False,
            hold_incumbent=False,
            requires_containment=True,
            session_key=session_key,
            decision_cutoff=decision_cutoff,
            cohort_hash=cohort_hash,
            admitted_universe=admitted_universe,
            portfolio_state_hash=portfolio_state_hash,
            account_id=account_id,
            mandate=mandate,
        )

    # Safe hold of incumbent verified
    return _make_result(
        status=status,
        reason=f"{reason}; incumbent strategy {curr_name} safely retained",
        proposed_strategy=candidate_strategy,
        current_strategy=curr_name,
        effective_strategy=curr_name,
        is_tradeable=False,
        hold_incumbent=True,
        requires_containment=False,
        session_key=session_key,
        decision_cutoff=decision_cutoff,
        cohort_hash=cohort_hash,
        admitted_universe=admitted_universe,
        portfolio_state_hash=portfolio_state_hash,
        account_id=account_id,
        mandate=mandate,
    )


def verify_stage1_switch_preflight_result(
    result: Stage1SwitchPreflightResult,
    *,
    expected_account_id: str,
    expected_mandate: str,
    expected_session_key: SessionKeyV1,
    expected_cohort_hash: SHA256Hash,
    expected_decision_cutoff: datetime,
    current_portfolio_state: PortfolioStateV2 | None = None,
    expected_universe: Sequence[UUID7] | None = None,
) -> bool:
    """Cryptographically revalidate a preflight verdict for consumers (Issue 423).

    Verifies deterministic local integrity, recomputed content hash, status/flag
    coherence, and context binding against live caller state. A return value of
    True confirms the verdict is intact, mathematically self-consistent, and
    bound to the active context; it does NOT constitute trading authorization
    or replace downstream M0 risk-engine evaluation.

    Raises ValueError if any binding fails, or returns True on success.
    """
    if not expected_account_id or not expected_account_id.strip():
        raise ValueError("expected_account_id is required for verification")
    if not expected_mandate or not expected_mandate.strip():
        raise ValueError("expected_mandate is required for verification")
    if expected_session_key is None:
        raise ValueError("expected_session_key is required for verification")
    if not expected_cohort_hash or not expected_cohort_hash.strip():
        raise ValueError("expected_cohort_hash is required for verification")
    if expected_decision_cutoff is None:
        raise ValueError("expected_decision_cutoff is required for verification")

    # 1. Revalidate model coherence (catches model_copy tampering)
    try:
        Stage1SwitchPreflightResult.model_validate(result.model_dump(mode="python"))
    except Exception as exc:
        raise ValueError(
            f"verdict failed model validation / coherence check: {exc}"
        ) from exc

    # 2. Recompute canonical content hash and compare
    expected_hash = compute_preflight_hash(
        status=result.status,
        reason=result.reason,
        proposed_strategy=result.proposed_strategy,
        current_strategy=result.current_strategy,
        effective_strategy=result.effective_strategy,
        is_tradeable=result.is_tradeable,
        hold_incumbent=result.hold_incumbent,
        requires_containment=result.requires_containment,
        session_key=result.session_key,
        decision_cutoff=result.decision_cutoff,
        cohort_hash=result.cohort_hash,
        admitted_universe=result.admitted_universe,
        portfolio_state_hash=result.portfolio_state_hash,
        account_id=result.account_id,
        mandate=result.mandate,
    )
    if result.preflight_hash != expected_hash:
        raise ValueError(
            f"verdict preflight hash mismatch: recomputed {expected_hash}, "
            f"got {result.preflight_hash}"
        )

    # 3. Verify context bindings
    if result.session_key != expected_session_key:
        raise ValueError(
            f"verdict session key mismatch: expected {expected_session_key}, "
            f"got {result.session_key}"
        )

    if result.account_id != expected_account_id:
        raise ValueError(
            f"verdict account_id mismatch: expected {expected_account_id!r}, "
            f"got {result.account_id!r}"
        )

    if result.mandate != expected_mandate:
        raise ValueError(
            f"verdict mandate mismatch: expected {expected_mandate!r}, "
            f"got {result.mandate!r}"
        )

    if result.cohort_hash != expected_cohort_hash:
        raise ValueError(
            f"verdict cohort_hash mismatch: expected {expected_cohort_hash!r}, "
            f"got {result.cohort_hash!r}"
        )

    if result.decision_cutoff != expected_decision_cutoff:
        raise ValueError(
            f"verdict decision_cutoff mismatch: expected {expected_decision_cutoff}, "
            f"got {result.decision_cutoff}"
        )

    if expected_universe is not None:
        if tuple(result.admitted_universe) != tuple(expected_universe):
            raise ValueError(
                f"verdict admitted_universe mismatch: expected {expected_universe}, "
                f"got {result.admitted_universe}"
            )

    # 4. Verify portfolio state binding
    if current_portfolio_state is not None:
        state_hash = content_hash(current_portfolio_state.model_dump(mode="python"))
        if result.portfolio_state_hash != state_hash:
            raise ValueError(
                f"portfolio state changed: preflight evaluated "
                f"{result.portfolio_state_hash}, live state is {state_hash}"
            )
    elif result.portfolio_state_hash is not None:
        raise ValueError(
            "preflight result binds a portfolio state, but live "
            "current_portfolio_state was not provided"
        )

    if result.is_tradeable and current_portfolio_state is None:
        raise ValueError(
            "tradeable verdict requires live current_portfolio_state "
            "for authorization verification"
        )

    return True


def evaluate_stage1_switch_preflight(
    *,
    proposed_strategy: str | StrategyReference,
    current_strategy: str | StrategyReference | None,
    decision_context: (
        StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1 | None
    ),
    required_universe: Sequence[UUID7] | None = None,
    expected_universe_hash: SHA256Hash | None = None,
    universe_manifest: Mapping[UUID7, str] | Mapping[str, UUID7] | None = None,
    current_portfolio_state: PortfolioStateV2 | None = None,
    allow_incumbent_continuation: bool = True,
    adjustments_by_security: (
        Mapping[UUID7, Sequence[CorporateActionAdjustment]] | None
    ) = None,
    account_id: str | None = None,
    mandate: str | None = None,
    open_orders: Sequence[object] | None = None,
    mandate_verified: bool | None = None,
    risk_verified: bool | None = None,
    completed_sessions: (Iterable[date | SessionKeyV1] | None) = None,
) -> Stage1SwitchPreflightResult:
    """Evaluate whether a proposed switch is eligible for Stage 1 target staging.

    Distinguishes:
    - ELIGIBLE: Proposed strategy has sufficient, valid evidence to compute targets.
    - UNAVAILABLE: Required data/history is missing; trade generation is blocked.
    - ABSTAIN: Deliberate hold; incumbent strategy continues if safe.
    - REJECTED: Proposed strategy or configuration fails deterministic validation.
    - INDETERMINATE_SAFETY: Portfolio or risk state is unknown; containment needed.
    """
    port_state_hash = (
        content_hash(current_portfolio_state.model_dump(mode="python"))
        if current_portfolio_state is not None
        else None
    )

    # 1. Strategy identity validation
    prop_name, prop_err = validate_strategy_identity(proposed_strategy)
    curr_name, curr_err = validate_strategy_identity(current_strategy)

    def fail(status: PreflightStatus, reason: str) -> Stage1SwitchPreflightResult:
        return _resolve_non_eligible_outcome(
            status=status,
            reason=reason,
            prop_name=prop_name or str(proposed_strategy),
            curr_name=curr_name,
            decision_context=decision_context,
            required_universe=required_universe,
            expected_universe_hash=expected_universe_hash,
            universe_manifest=universe_manifest,
            current_portfolio_state=current_portfolio_state,
            allow_incumbent_continuation=allow_incumbent_continuation,
            account_id=account_id,
            mandate=mandate,
            portfolio_state_hash=port_state_hash,
            open_orders=open_orders,
            mandate_verified=mandate_verified,
            risk_verified=risk_verified,
        )

    if prop_err is not None or prop_name is None:
        return fail(
            PreflightStatus.REJECTED,
            prop_err or "unsupported_strategy: proposed strategy cannot be None",
        )

    if current_strategy is None:
        return fail(
            PreflightStatus.INDETERMINATE_SAFETY,
            "missing_current_strategy: current incumbent strategy is required",
        )
    if curr_name is None or curr_err is not None or curr_name not in {"B3", "B4", "B5"}:
        return fail(
            PreflightStatus.INDETERMINATE_SAFETY,
            f"unadmitted_incumbent_strategy: incumbent strategy {current_strategy!r} "
            "is not an admitted Stage 1 baseline",
        )

    # 2. Portfolio and context safety verification
    is_safe, port_err = check_portfolio_safety(
        current_portfolio_state=current_portfolio_state,
        decision_context=decision_context,
        open_orders=open_orders,
        mandate_verified=mandate_verified,
        risk_verified=risk_verified,
        account_id=account_id,
        mandate=mandate,
    )
    if not is_safe:
        assert port_err is not None
        return fail(PreflightStatus.INDETERMINATE_SAFETY, port_err)

    assert current_portfolio_state is not None

    # 3. Deliberate ABSTAIN outcome
    if prop_name == "ABSTAIN":
        return fail(
            PreflightStatus.ABSTAIN,
            "deliberate_abstain: strategy explicitly opted out of trading",
        )

    # 4. Context existence & decision cutoff
    if decision_context is None:
        return fail(
            PreflightStatus.UNAVAILABLE,
            "missing_decision_context: strategy decision context is required",
        )

    session_key = decision_context.session_key
    decision_cutoff = decision_context.decision_cutoff
    cohort_hash = getattr(decision_context, "cohort_hash", None)
    context_cohort = get_admitted_securities(decision_context)

    if decision_cutoff is None:
        return fail(
            PreflightStatus.UNAVAILABLE,
            "missing_decision_cutoff: decision context lacks decision_cutoff timestamp",
        )

    # 5. Universe completeness and identity verification
    is_valid_u, u_reason, eval_universe = validate_universe(
        required_universe=required_universe,
        expected_universe_hash=expected_universe_hash,
        context_cohort=context_cohort,
        cohort_hash=cohort_hash,
        universe_manifest=universe_manifest,
    )
    if not is_valid_u:
        assert u_reason is not None
        u_status = (
            PreflightStatus.UNAVAILABLE
            if u_reason.startswith("missing_required_universe")
            else PreflightStatus.REJECTED
        )
        return fail(u_status, u_reason)

    # 6. Observations, timestamps, calendar, and corporate action adjustments
    is_valid_obs, obs_status, obs_reason = validate_observations_and_adjustments(
        decision_context=decision_context,
        eval_universe=eval_universe,
        prop_name=prop_name,
        decision_cutoff=decision_cutoff,
        session_key=session_key,
        adjustments_by_security=adjustments_by_security,
        completed_sessions=completed_sessions,
    )
    if not is_valid_obs:
        assert obs_reason is not None
        return fail(obs_status, obs_reason)

    # 7. All checks passed: Candidate strategy is ELIGIBLE
    assert prop_name is not None
    min_required_sessions = (
        B3_MIN_SESSIONS
        if prop_name == "B3"
        else B4_MIN_SESSIONS
        if prop_name == "B4"
        else B5_MIN_SESSIONS
    )
    reason = (
        f"eligible: proposed strategy {prop_name} satisfied all evidence, "
        f"history ({len(eval_universe)} names >= {min_required_sessions} sessions), "
        "portfolio safety, and fixed universe completeness requirements"
    )
    return _make_result(
        status=PreflightStatus.ELIGIBLE,
        reason=reason,
        proposed_strategy=prop_name,
        current_strategy=curr_name,
        effective_strategy=prop_name,
        is_tradeable=True,
        hold_incumbent=False,
        requires_containment=False,
        session_key=session_key,
        decision_cutoff=decision_cutoff,
        cohort_hash=cohort_hash or expected_universe_hash,
        admitted_universe=eval_universe,
        portfolio_state_hash=port_state_hash,
        account_id=account_id,
        mandate=mandate,
    )
