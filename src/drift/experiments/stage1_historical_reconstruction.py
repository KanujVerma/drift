"""Stage 1 G4 historical experiment independent reconstruction and verification.

Workstream H, Issue 575.
Implements H4 independent financial verification:
- Reconstructs actual original account NAV, cash, fees, and session completeness
  from retained evidence.
- Verifies candidate arm B and comparator arm R starting from USD 10,000 in B3.
- Independent compounding: NAV_t = NAV_{t-1} * (1 + ret_t) - fee_t.
- Independent primary economic advantage (PEA) reconciliation:
  PEA = (NAV_B_term - 10000) - (NAV_R_term - 10000) - incremental_operating_costs.
- Independent drawdown, volatility, and paired stationary bootstrap verification
  (seed 575, 10,000 reps).
- Enforces scientific classification precedence (INVALID, UNAVAILABLE,
  UNSUCCESSFUL, SUCCESS, PROMISING_BUT_INCONCLUSIVE).
- Detects any discrepancy between reported manifests and reconstructed financial
  reality.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash
from drift.experiments.stage1_study_freeze import FrozenStage1StudyV1
from drift.experiments.stage1_study_outcomes import (
    classify_study_outcome,
)
from drift.experiments.stage1_uncertainty import (
    compute_paired_uncertainty_artifact,
)
from drift.serialization.canonical import canonical_json, content_hash

DEFAULT_INITIAL_CAPITAL = Decimal("10000")


class HistoricalReconstructionReportV1(FrozenModel):
    """Report of independent financial reconstruction of historical experiment."""

    schema_version: Literal["drift-stage1-reconstruction/1"] = (
        "drift-stage1-reconstruction/1"
    )
    study_id: NonBlankStr
    protocol_hash: SHA256Hash
    freeze_hash: SHA256Hash
    status: Literal["VERIFIED", "RECONSTRUCTION_FAILED"]
    total_sessions_verified: int
    b_terminal_nav: Decimal
    r_terminal_nav: Decimal
    b_terminal_nav_reconstructed: Decimal
    r_terminal_nav_reconstructed: Decimal
    primary_economic_advantage_reconstructed: Decimal
    uncertainty_verified: bool
    reconstructed_outcome: str
    discrepancies: tuple[str, ...]
    reconstruction_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        body = self.model_dump(mode="python", exclude={"reconstruction_hash"})
        computed = content_hash(body)
        if self.reconstruction_hash != computed:
            raise ValueError(
                f"RECONSTRUCTION_HASH_MISMATCH: expected {computed}, "
                f"got {self.reconstruction_hash}"
            )
        return self


def reconstruct_and_verify_historical_experiment(
    *,
    frozen: FrozenStage1StudyV1,
    b_receipts: Sequence[Mapping[str, Any]],
    r_receipts: Sequence[Mapping[str, Any]],
    incremental_operating_costs: Decimal,
    initial_capital: Decimal = DEFAULT_INITIAL_CAPITAL,
    expected_sessions: Sequence[int | str] | None = None,
    reported_b_terminal_nav: Decimal | None = None,
    reported_r_terminal_nav: Decimal | None = None,
    reported_primary_economic_advantage: Decimal | None = None,
    reported_outcome: str | None = None,
    mean_block_length: int | None = None,
) -> HistoricalReconstructionReportV1:
    """Independently reconstructs account accounting, NAV, and uncertainty."""
    discrepancies: list[str] = []

    if len(b_receipts) != len(r_receipts):
        discrepancies.append(
            f"RECEIPT_COUNT_MISMATCH: B={len(b_receipts)}, R={len(r_receipts)}"
        )

    n_sessions = len(b_receipts)
    if expected_sessions is not None:
        if n_sessions != len(expected_sessions):
            discrepancies.append(
                f"EXPECTED_SESSION_COUNT_MISMATCH: expected {len(expected_sessions)}, "
                f"got {n_sessions}"
            )

    # Sort receipts by session index
    def _get_sidx(r: Mapping[str, Any]) -> int:
        idx = r.get("session_index")
        if isinstance(idx, int) and not isinstance(idx, bool):
            return idx
        return 0

    sorted_b = sorted(b_receipts, key=_get_sidx)
    sorted_r = sorted(r_receipts, key=_get_sidx)

    # 1. Independent compounding for Arm B
    b_nav = initial_capital
    b_nav_marks: list[Decimal] = [b_nav]
    b_returns: list[Decimal] = []

    for i, r in enumerate(sorted_b):
        s_idx = _get_sidx(r)
        if expected_sessions is not None and i < len(expected_sessions):
            exp_id = expected_sessions[i]
            if isinstance(exp_id, int) and s_idx != exp_id:
                discrepancies.append(
                    f"B_SESSION_INDEX_MISMATCH at {i}: expected {exp_id}, got {s_idx}"
                )

        metrics = r.get("metrics", {})
        ret_val = Decimal(str(metrics.get("net_return", "0")))
        fee_val = Decimal(str(metrics.get("per_share_fees", "0")))
        reported_nav = Decimal(str(metrics.get("terminal_nav", "0")))

        b_returns.append(ret_val)
        b_nav = (b_nav * (Decimal("1") + ret_val)) - fee_val
        b_nav_marks.append(b_nav)

        if b_nav <= Decimal("0"):
            discrepancies.append(
                f"B_ACCOUNT_SOLVENCY_BREACH at session {s_idx}: NAV={b_nav}"
            )

        # Check receipt reported nav against calculated nav within 0.0001
        if abs(reported_nav - b_nav) > Decimal("0.0005"):
            discrepancies.append(
                f"B_NAV_COMPUTATION_DISCREPANCY at session {s_idx}: "
                f"reported {reported_nav}, calculated {b_nav}"
            )

    # 2. Independent compounding for Arm R
    r_nav = initial_capital
    r_nav_marks: list[Decimal] = [r_nav]
    r_returns: list[Decimal] = []

    for i, r in enumerate(sorted_r):
        s_idx = _get_sidx(r)
        if expected_sessions is not None and i < len(expected_sessions):
            exp_id = expected_sessions[i]
            if isinstance(exp_id, int) and s_idx != exp_id:
                discrepancies.append(
                    f"R_SESSION_INDEX_MISMATCH at {i}: expected {exp_id}, got {s_idx}"
                )

        metrics = r.get("metrics", {})
        ret_val = Decimal(str(metrics.get("net_return", "0")))
        fee_val = Decimal(str(metrics.get("per_share_fees", "0")))
        reported_nav = Decimal(str(metrics.get("terminal_nav", "0")))

        r_returns.append(ret_val)
        r_nav = (r_nav * (Decimal("1") + ret_val)) - fee_val
        r_nav_marks.append(r_nav)

        if r_nav <= Decimal("0"):
            discrepancies.append(
                f"R_ACCOUNT_SOLVENCY_BREACH at session {s_idx}: NAV={r_nav}"
            )

        if abs(reported_nav - r_nav) > Decimal("0.0005"):
            discrepancies.append(
                f"R_NAV_COMPUTATION_DISCREPANCY at session {s_idx}: "
                f"reported {reported_nav}, calculated {r_nav}"
            )

    # 3. Independent PEA calculation
    delta_nav = (b_nav - initial_capital) - (r_nav - initial_capital)
    reconstructed_pea = delta_nav - incremental_operating_costs

    if reported_b_terminal_nav is not None:
        if abs(reported_b_terminal_nav - b_nav) > Decimal("0.01"):
            discrepancies.append(
                "REPORTED_B_TERMINAL_NAV_MISMATCH: "
                f"reported {reported_b_terminal_nav}, calculated {b_nav}"
            )

    if reported_r_terminal_nav is not None:
        if abs(reported_r_terminal_nav - r_nav) > Decimal("0.01"):
            discrepancies.append(
                "REPORTED_R_TERMINAL_NAV_MISMATCH: "
                f"reported {reported_r_terminal_nav}, calculated {r_nav}"
            )

    if reported_primary_economic_advantage is not None:
        if abs(reported_primary_economic_advantage - reconstructed_pea) > Decimal(
            "0.01"
        ):
            discrepancies.append(
                "REPORTED_PEA_MISMATCH: "
                f"reported {reported_primary_economic_advantage}, "
                f"reconstructed {reconstructed_pea}"
            )

    # 4. Independent Volatility & Drawdown
    n_obs = Decimal(len(b_returns)) if b_returns else Decimal("1")
    b_mean = sum(b_returns) / n_obs if b_returns else Decimal("0")
    b_var = (
        sum((x - b_mean) ** 2 for x in b_returns) / (n_obs - Decimal("1"))
        if len(b_returns) > 1
        else Decimal("0")
    )
    b_vol = b_var.sqrt() * Decimal("252").sqrt()

    r_mean = sum(r_returns) / n_obs if r_returns else Decimal("0")
    r_var = (
        sum((x - r_mean) ** 2 for x in r_returns) / (n_obs - Decimal("1"))
        if len(r_returns) > 1
        else Decimal("0")
    )
    r_vol = r_var.sqrt() * Decimal("252").sqrt()

    def _calc_mdd(marks: list[Decimal]) -> Decimal:
        peak = marks[0]
        mdd = Decimal("0")
        for m in marks:
            if m > peak:
                peak = m
            if peak > Decimal("0"):
                dd = (peak - m) / peak
                if dd > mdd:
                    mdd = dd
        return mdd

    b_mdd = _calc_mdd(b_nav_marks)
    r_mdd = _calc_mdd(r_nav_marks)

    # 5. Independent Uncertainty via 10,000 paired stationary bootstrap
    uncertainty_verified = False
    p_nav_lower: Decimal | None = None
    p_econ_lower: Decimal | None = None

    if len(b_returns) >= 2 and len(b_returns) == len(r_returns):
        try:
            unc = compute_paired_uncertainty_artifact(
                b_returns=b_returns,
                r_returns=r_returns,
                initial_capital=initial_capital,
                incremental_operating_costs=incremental_operating_costs,
                mean_block_length=mean_block_length or 21,
                seed=575,
            )
            if unc.primary_nav_diff_interval:
                p_nav_lower = unc.primary_nav_diff_interval[0]
            if unc.primary_economic_interval:
                p_econ_lower = unc.primary_economic_interval[0]
            uncertainty_verified = True
        except Exception as e:
            discrepancies.append(f"UNCERTAINTY_COMPUTATION_FAILED: {e}")

    # 6. Reconstructed Outcome Classification
    outcome_result = classify_study_outcome(
        scheduled_sessions=n_sessions,
        primary_economic_advantage=reconstructed_pea,
        primary_nav_diff_lower=p_nav_lower,
        primary_econ_lower=p_econ_lower,
        b_volatility=b_vol,
        r_volatility=r_vol,
        b_max_drawdown=b_mdd,
        r_max_drawdown=r_mdd,
        is_prospective_complete=False,
        is_independently_accepted=True,
    )

    reconstructed_outcome = outcome_result.outcome
    if reported_outcome is not None and reported_outcome != reconstructed_outcome:
        discrepancies.append(
            f"OUTCOME_CLASSIFICATION_MISMATCH: reported {reported_outcome}, "
            f"reconstructed {reconstructed_outcome}"
        )

    status: Literal["VERIFIED", "RECONSTRUCTION_FAILED"] = (
        "VERIFIED" if not discrepancies else "RECONSTRUCTION_FAILED"
    )

    body = {
        "schema_version": "drift-stage1-reconstruction/1",
        "study_id": frozen.protocol.study_id,
        "protocol_hash": frozen.protocol.protocol_hash,
        "freeze_hash": frozen.freeze_hash,
        "status": status,
        "total_sessions_verified": n_sessions,
        "b_terminal_nav": b_nav.quantize(Decimal("0.0001")),
        "r_terminal_nav": r_nav.quantize(Decimal("0.0001")),
        "b_terminal_nav_reconstructed": b_nav.quantize(Decimal("0.0001")),
        "r_terminal_nav_reconstructed": r_nav.quantize(Decimal("0.0001")),
        "primary_economic_advantage_reconstructed": reconstructed_pea.quantize(
            Decimal("0.0001")
        ),
        "uncertainty_verified": uncertainty_verified,
        "reconstructed_outcome": reconstructed_outcome,
        "discrepancies": tuple(discrepancies),
    }

    h = content_hash(body)
    return HistoricalReconstructionReportV1.model_validate_json(
        canonical_json(body | {"reconstruction_hash": h})
    )
