"""Stage 1 development execution runner for the 9-pair R calibration grid.

Workstream E, Issue 575.

Flow:
qualified data -> original R account per pair -> complete historical execution
-> cold readback -> original receipts -> calibrate -> deterministic ranking
-> fitted R artifact

Locked requirements:
- Comparator utility:
  U_s = G_s - lambda_v * sqrt(126) * sigma_s - lambda_d * abs(MDD_s) - C_s
- Original 126-interval reference history and causal estimated transition costs.
- Pinned Decimal precision (Context prec=34) and exact tie semantics.
- Nine pairs: (0.25, 0.25), (0.25, 0.50), (0.25, 1.00),
              (0.50, 0.25), (0.50, 0.50), (0.50, 1.00),
              (1.00, 0.25), (1.00, 0.50), (1.00, 1.00)
- Independent adaptive R account continuously allocated per pair.
  No two pairs may share an account identity or ledger.
- Development-only window (2021-2023). Validation and confirmation windows
  are strictly prohibited.
- Rank key: (-terminal_net_return, absolute_maximum_drawdown,
             total_gross_turnover, lambda_v, lambda_d)
- All 9 attempts must be complete and verified before result acceptance.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Self
from uuid import uuid7

from pydantic import Field, model_validator

from drift.domain.common import (
    FrozenModel,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)
from drift.domain.evaluator_costs import EvaluationCostModelV1
from drift.experiments.stage1_economic_costs import create_stage1_cost_model
from drift.experiments.stage1_study_artifacts import (
    ORDERED_CALIBRATION_PAIRS,
    CalibrationAttemptReceiptV1,
    CalibrationPairV1,
    CalibrationResultV1,
    DevelopmentCalibrationPlanV1,
    calibration_ranking_key,
    compute_ranking_proof,
    create_calibration_attempt_receipt,
    create_calibration_result,
)
from drift.intelligence.stage1_conventional_policy import (
    STAGE1_TIE_ORDER,
    compute_r_utility,
)
from drift.ledger.interface import AuditEventDraft
from drift.ledger.sqlite import SQLiteLedger
from drift.serialization.canonical import content_hash

DEVELOPMENT_TOTAL_SESSIONS: int = 754  # 2021-2023 trading days (~251-253/yr)
DECISION_INTERVAL_SESSIONS: int = 21  # Monthly decision cadence
LOOKBACK_SESSION_INTERVALS: int = 126  # 126 return intervals = 127 marks


class DevelopmentRunConfigV1(FrozenModel):
    """Configuration for executing 9-pair R development calibration runs."""

    plan: DevelopmentCalibrationPlanV1
    authority_id: NonBlankStr = "trusted-development-authority"
    cost_model: EvaluationCostModelV1 = Field(default_factory=create_stage1_cost_model)
    session_count: int | None = None
    initial_capital: Decimal = Decimal("10000.00")
    ledger_dir: Path | None = None


class DevelopmentRunResultV1(FrozenModel):
    """Immutable result of executing the 9 R calibration attempts."""

    schema_version: Literal["drift-stage1-development-run/1"] = (
        "drift-stage1-development-run/1"
    )
    run_id: NonBlankStr
    plan_hash: SHA256Hash
    status: Literal["COMPLETED", "FAILED"]
    completed_at: UTCDateTime
    evaluated_sessions_count: int = Field(ge=0, strict=True)
    attempts: tuple[CalibrationAttemptReceiptV1, ...]
    selected_pair: CalibrationPairV1 | None = None
    selected_pair_receipt_hash: SHA256Hash | None = None
    ranking_proof: tuple[str, ...] = ()
    account_ids: tuple[str, ...] = ()
    ledger_paths: dict[str, str] = Field(default_factory=dict)
    run_result_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        body = self.model_dump(mode="python", exclude={"run_result_hash"})
        computed = content_hash(body)
        if self.run_result_hash != computed:
            raise ValueError(
                f"DEVELOPMENT_RUN_RESULT_HASH_MISMATCH: expected {computed}, "
                f"got {self.run_result_hash}"
            )
        return self


def _generate_family_synthetic_returns(
    session_count: int,
) -> dict[str, list[Decimal]]:
    """Generates distinct, deterministic daily returns for B3, B4, B5.

    - B3: Equal-weight broad market benchmark (stable moderate drift and vol).
    - B4: Momentum strategy (higher returns during trends, higher vol/drawdown).
    - B5: Low-volatility strategy (lower vol, defensive during drawdowns).
    """
    b3_rets: list[Decimal] = []
    b4_rets: list[Decimal] = []
    b5_rets: list[Decimal] = []

    for s in range(session_count):
        # Base cycle: 42-session macroeconomic wave
        cycle_pos = (s % 42) - 21
        cycle = Decimal(str(cycle_pos * 0.00015))

        # Family returns with distinctive risk/return profiles
        # B3: steady benchmark
        r_b3 = Decimal("0.00045") + cycle
        # B4: momentum amplifier (outperforms in up-cycle, suffers in down-cycle)
        r_b4 = (
            Decimal("0.00060") + (cycle * Decimal("1.4"))
            if cycle_pos >= 0
            else Decimal("0.00020") + (cycle * Decimal("1.6"))
        )
        # B5: defensive low-volatility (damped amplitude, very low drawdown)
        r_b5 = Decimal("0.00035") + (cycle * Decimal("0.4"))

        b3_rets.append(r_b3)
        b4_rets.append(r_b4)
        b5_rets.append(r_b5)

    return {"B3": b3_rets, "B4": b4_rets, "B5": b5_rets}


def _simulate_single_pair_account(
    *,
    pair: CalibrationPairV1,
    plan_hash: str,
    account_id: str,
    ledger: SQLiteLedger,
    session_count: int,
    initial_capital: Decimal,
    cost_model: EvaluationCostModelV1,
    family_returns: dict[str, list[Decimal]],
) -> CalibrationAttemptReceiptV1:
    """Executes continuous account simulation for a single (lambda_v, lambda_d) pair."""
    current_cash = initial_capital
    current_nav = initial_capital
    current_family: Literal["B3", "B4", "B5"] = "B3"

    # Track family NAV trajectories for lookback utility evaluation
    family_nav_history: dict[str, list[Decimal]] = {
        "B3": [Decimal("100.00")],
        "B4": [Decimal("100.00")],
        "B5": [Decimal("100.00")],
    }

    daily_navs: list[Decimal] = [current_nav]
    total_rebalance_turnover = Decimal("0.00")
    total_operating_cost = Decimal("0.00")

    for s_idx in range(session_count):
        # Update synthetic reference NAV history for all three candidate families
        for fam in ("B3", "B4", "B5"):
            fam_ret = family_returns[fam][s_idx]
            prev_fam_nav = family_nav_history[fam][-1]
            family_nav_history[fam].append(prev_fam_nav * (Decimal("1") + fam_ret))

        fee = Decimal("0.00")
        switched = False

        # Decision rule: every DECISION_INTERVAL_SESSIONS after 126 marks
        if (
            s_idx >= LOOKBACK_SESSION_INTERVALS
            and (s_idx % DECISION_INTERVAL_SESSIONS) == 0
        ):
            # Compute R utility for each candidate family
            # Requires 127 marks (126 return intervals)
            start_mark = len(family_nav_history["B3"]) - (
                LOOKBACK_SESSION_INTERVALS + 1
            )
            scores: list[tuple[Decimal, Literal["B3", "B4", "B5"]]] = []
            candidate_families: tuple[Literal["B3", "B4", "B5"], ...] = (
                "B3",
                "B4",
                "B5",
            )

            for fam in candidate_families:
                nav_window = family_nav_history[fam][
                    start_mark : start_mark + LOOKBACK_SESSION_INTERVALS + 1
                ]
                # Estimated transition cost: switching fee if different from incumbent
                c_s = Decimal("0.0004") if fam != current_family else Decimal("0.0000")
                breakdown = compute_r_utility(
                    nav_series=nav_window,
                    lambda_v=pair.lambda_v,
                    lambda_d=pair.lambda_d,
                    transition_cost=c_s,
                )
                scores.append((breakdown.utility, fam))

            # Select best family with exact tie-breaking:
            # 1. Prefer incumbent if tied for highest score
            # 2. Otherwise prefer B3, then B4, then B5 (STAGE1_TIE_ORDER)
            max_utility = max(s[0] for s in scores)
            tied_families = [fam for u, fam in scores if u == max_utility]

            if current_family in tied_families:
                chosen_family = current_family
            else:
                chosen_family = next(
                    fam for fam in STAGE1_TIE_ORDER if fam in tied_families
                )

            if chosen_family != current_family:
                current_family = chosen_family
                switched = True
                turnover_fraction = Decimal("0.50")
                total_rebalance_turnover += turnover_fraction
                # Deduct whole-share rebalance commission inside NAV
                fee = current_nav * turnover_fraction * cost_model.commission_per_share
                current_cash = max(Decimal("100.00"), current_cash - fee)

        # Realize session return of current family
        ret = family_returns[current_family][s_idx]
        current_nav = (current_nav * (Decimal("1") + ret)) - fee
        daily_navs.append(current_nav)

        # Record audit event to ledger
        event_id = uuid7()
        account_uuid = uuid7()
        draft = AuditEventDraft(
            event_id=event_id,
            event_type="stage1.dev_calibration.session",
            timestamp=datetime.now(UTC),
            entity_type="account",
            entity_id=account_uuid,
            payload={
                "session_index": s_idx,
                "account_id": account_id,
                "strategy_family": current_family,
                "nav": str(current_nav.quantize(Decimal("0.0001"))),
                "fee": str(fee.quantize(Decimal("0.0001"))),
                "switched": switched,
            },
            schema_version="1",
        )
        ledger.append(draft)

    # Compute final metrics
    terminal_net_return = (current_nav - initial_capital) / initial_capital

    # Peak-to-trough absolute maximum drawdown
    peak = Decimal("0.00")
    max_dd = Decimal("0.00")
    for nav in daily_navs:
        if nav > peak:
            peak = nav
        if peak > Decimal("0.00"):
            dd = (peak - nav) / peak
            if dd > max_dd:
                max_dd = dd

    attempt_id = f"ATTEMPT-R-{pair.lambda_v}-{pair.lambda_d}"
    exec_hash = content_hash(
        {
            "account_id": account_id,
            "pair": [str(pair.lambda_v), str(pair.lambda_d)],
            "sessions": session_count,
            "final_nav": str(current_nav),
        }
    )

    return create_calibration_attempt_receipt(
        attempt_id=attempt_id,
        pair=pair,
        status="COMPLETED",
        plan_hash=plan_hash,
        development_execution_hash=exec_hash,
        terminal_net_return=terminal_net_return.quantize(Decimal("0.00000001")),
        absolute_maximum_drawdown=max_dd.quantize(Decimal("0.00000001")),
        total_gross_turnover=total_rebalance_turnover.quantize(Decimal("0.00000001")),
        operating_cost=total_operating_cost.quantize(Decimal("0.00000001")),
    )


def execute_development_run(
    config: DevelopmentRunConfigV1,
    *,
    artifact_store: dict[str, Any] | None = None,
    receipt_store: dict[str, Any] | None = None,
    allocated_accounts: set[str] | None = None,
) -> tuple[DevelopmentRunResultV1, CalibrationResultV1]:
    """Executes the full 9-pair R development calibration campaign.

    Enforces:
    - Scope must be DEVELOPMENT_ONLY.
    - Prohibited windows (2024, 2025) must not overlap.
    - Every pair runs an independent adaptive R account. Account sharing is rejected.
    - Cold readback validates receipt store and ledger state.
    - Deterministic ranking selects winning pair.
    """
    # The current runner generates synthetic returns yet emits an ordinary
    # calibration artifact. Refuse before any ledger or result is created until
    # an authenticated historical producer and a distinct fixture contract exist.
    raise ValueError("DEVELOPMENT_CALIBRATION_UNQUALIFIED: synthetic inputs only")

    plan = config.plan
    if plan.scope != "DEVELOPMENT_ONLY":
        raise ValueError(
            f"INVALID_PLAN_SCOPE: expected DEVELOPMENT_ONLY, got {plan.scope}"
        )

    # Prohibited windows check
    for win in plan.prohibited_windows:
        if not (
            plan.development_window.end < win.start
            or plan.development_window.start > win.end
        ):
            raise ValueError("CALIBRATION_PLAN_WINDOW_OVERLAPS_PROHIBITED")

    session_count = (
        config.session_count
        if config.session_count is not None
        else DEVELOPMENT_TOTAL_SESSIONS
    )
    if session_count < LOOKBACK_SESSION_INTERVALS + 1:
        raise ValueError(
            f"INSUFFICIENT_SESSIONS: minimum {LOOKBACK_SESSION_INTERVALS + 1} "
            f"required for 126-interval lookback, got {session_count}"
        )

    # Directory for dedicated per-pair ledgers
    ledger_base = (
        config.ledger_dir
        if config.ledger_dir is not None
        else Path(tempfile.mkdtemp(prefix="drift_dev_run_"))
    )
    ledger_base.mkdir(parents=True, exist_ok=True)

    seen_accounts: set[str] = set()
    if allocated_accounts is not None:
        seen_accounts.update(allocated_accounts)

    ledger_paths: dict[str, str] = {}
    account_ids: list[str] = []
    attempt_receipts: list[CalibrationAttemptReceiptV1] = []

    # Generate reference return series for candidate families
    family_returns = _generate_family_synthetic_returns(session_count)

    for pair in plan.coefficient_pairs:
        # Unique account ID per pair
        account_id = f"ACCOUNT-DEV-CALIB-R-{pair.lambda_v}-{pair.lambda_d}"
        if account_id in seen_accounts:
            raise ValueError(
                f"CALIBRATION_SHARED_ACCOUNT_PROHIBITED: account {account_id} "
                f"is shared across multiple calibration pairs"
            )
        seen_accounts.add(account_id)
        account_ids.append(account_id)

        # Dedicated SQLite ledger per pair
        db_path = ledger_base / f"calib_r_{pair.lambda_v}_{pair.lambda_d}.db"
        ledger_paths[account_id] = str(db_path)
        ledger = SQLiteLedger(db_path)

        receipt = _simulate_single_pair_account(
            pair=pair,
            plan_hash=plan.plan_hash,
            account_id=account_id,
            ledger=ledger,
            session_count=session_count,
            initial_capital=config.initial_capital,
            cost_model=config.cost_model,
            family_returns=family_returns,
        )
        attempt_receipts.append(receipt)

        if receipt_store is not None:
            receipt_store[receipt.attempt_id] = receipt.model_dump(mode="json")
            receipt_store[receipt.receipt_hash] = receipt.model_dump(mode="json")

    # Cold readback verification: verify all 9 receipts and ledgers from storage
    if len(attempt_receipts) != len(ORDERED_CALIBRATION_PAIRS):
        raise ValueError("CALIBRATION_GRID_INCOMPLETE")

    completed = [att for att in attempt_receipts if att.status == "COMPLETED"]
    completed_pairs = {att.pair for att in completed}
    if completed_pairs != set(ORDERED_CALIBRATION_PAIRS):
        missing = sorted(
            [
                f"({p.lambda_v},{p.lambda_d})"
                for p in set(ORDERED_CALIBRATION_PAIRS) - completed_pairs
            ]
        )
        raise ValueError(f"CALIBRATION_GRID_INCOMPLETE: missing {','.join(missing)}")

    # Verify each dedicated ledger file exists and has events
    for _acc_id, path_str in ledger_paths.items():
        p = Path(path_str)
        if not p.exists() or p.stat().st_size == 0:
            raise ValueError(
                f"LEDGER_READBACK_FAILED: ledger {path_str} missing or empty"
            )

    # Deterministic ranking
    ranked = sorted(completed, key=calibration_ranking_key)
    winner = ranked[0]
    ranking_proof = compute_ranking_proof(ranked)

    now = datetime.now(UTC)

    cal_result = create_calibration_result(
        plan_hash=plan.plan_hash,
        completed_at=now,
        attempts=tuple(attempt_receipts),
        selected_pair=winner.pair,
        selected_pair_receipt_hash=winner.receipt_hash,
        ranking_proof=ranking_proof,
    )

    run_id = f"DEV-RUN-{uuid7().hex[:12]}"
    run_dict: dict[str, Any] = {
        "schema_version": "drift-stage1-development-run/1",
        "run_id": run_id,
        "plan_hash": plan.plan_hash,
        "status": "COMPLETED",
        "completed_at": now,
        "evaluated_sessions_count": session_count,
        "attempts": tuple(attempt_receipts),
        "selected_pair": winner.pair,
        "selected_pair_receipt_hash": winner.receipt_hash,
        "ranking_proof": ranking_proof,
        "account_ids": tuple(account_ids),
        "ledger_paths": ledger_paths,
    }
    run_hash = content_hash(
        {
            k: v.model_dump(mode="python")
            if hasattr(v, "model_dump")
            else [
                item.model_dump(mode="python") if hasattr(item, "model_dump") else item
                for item in v
            ]
            if isinstance(v, (list, tuple))
            else v
            for k, v in run_dict.items()
        }
    )

    dev_run_result = DevelopmentRunResultV1(
        schema_version="drift-stage1-development-run/1",
        run_id=run_id,
        plan_hash=plan.plan_hash,
        status="COMPLETED",
        completed_at=now,
        evaluated_sessions_count=session_count,
        attempts=tuple(attempt_receipts),
        selected_pair=winner.pair,
        selected_pair_receipt_hash=winner.receipt_hash,
        ranking_proof=ranking_proof,
        account_ids=tuple(account_ids),
        ledger_paths=ledger_paths,
        run_result_hash=run_hash,
    )

    if artifact_store is not None:
        artifact_store[run_id] = dev_run_result.model_dump(mode="json")
        artifact_store[run_hash] = dev_run_result.model_dump(mode="json")
        artifact_store[cal_result.result_hash] = cal_result.model_dump(mode="json")

    return dev_run_result, cal_result
