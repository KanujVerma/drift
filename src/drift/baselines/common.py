"""Shared baseline strategy helpers and context observation extractors (Issue 166).

Provides uniform access to closing prices, session history, and portfolio
targets across both Realized and Exploratory decision lanes.
"""

import hashlib
from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from drift.analysis.analytical_returns import SessionObservationRecord
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.common import UUID7
from drift.domain.evaluator_exploratory_strategy import (
    ExploratoryStrategyDecisionContextV1,
)
from drift.domain.evaluator_portfolio import decimal_context
from drift.domain.evaluator_strategy import (
    SecurityTargetPositionV1,
    StrategyDecisionContextV1,
    StrategyDecisionIntentV1,
)
from drift.domain.strategies import StrategyReference


def deterministic_baseline_uuid7(seed: str) -> UUID:
    """Derive a deterministic UUIDv7 value from a seed string."""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    raw = int(digest[:32], 16)
    # Set version bits (bits 48-51 from MSB) to 7
    raw &= ~(0xF << 76)
    raw |= 0x7 << 76
    # Set variant bits (bits 64-65 from MSB) to 0b10 (RFC 4122 / RFC 9562)
    raw &= ~(0x3 << 62)
    raw |= 0x2 << 62
    return UUID(int=raw)


def make_baseline_reference(
    name: str,
    version: str = "1",
    custom_hash: str | None = None,
) -> StrategyReference:
    """Create a validated StrategyReference for a reference baseline strategy."""
    strategy_id = deterministic_baseline_uuid7(f"drift.baselines.{name}")
    code_hash = (
        custom_hash
        or hashlib.sha256(f"drift.baselines.{name}:{version}".encode()).hexdigest()
    )
    artifact_seed = f"drift.baselines.artifact.{name}:{version}"
    artifact_id = deterministic_baseline_uuid7(artifact_seed)
    artifact_ref = ArtifactReference(
        artifact_id=artifact_id,
        kind=ArtifactKind.STRATEGY,
        content_hash=code_hash,
        location=f"drift/baselines/{name}.py",
    )
    return StrategyReference(
        strategy_id=strategy_id,
        strategy_version=version,
        code_hash=code_hash,
        artifact_reference=artifact_ref,
    )


def security_order_key(security_id: UUID) -> bytes:
    """Canonical collection order for securities: raw UUID bytes."""
    return security_id.bytes


def extract_security_history(
    context: StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1,
    security_id: UUID7,
) -> tuple[SessionObservationRecord, ...]:
    """Extract chronological session observations for one security up to cutoff."""
    cutoff_date = context.session_key.local_date
    if isinstance(context, StrategyDecisionContextV1):
        for view_group in context.decision_views:
            if view_group.security_id == security_id:
                records = []
                for v in view_group.views:
                    if v.source_session.local_date <= cutoff_date:
                        rf = next(f for f in v.fields if f.field_name == "close")
                        price = (
                            rf.quantized_value
                            if rf.quantized_value is not None
                            else rf.source_value
                        )
                        records.append(
                            SessionObservationRecord(
                                session_key=v.source_session,
                                close_price=price,
                                observation_hash=v.output_hash,
                            )
                        )
                return tuple(records)
        return ()

    # Exploratory reconstructed lane
    for recon_group in context.reconstructed_decision_views:
        if recon_group.security_id == security_id:
            recon_records = []
            for obs in recon_group.observations:
                if obs.session_key.local_date <= cutoff_date:
                    ef = next(f for f in obs.fields if f.field_name == "close")
                    recon_records.append(
                        SessionObservationRecord(
                            session_key=obs.session_key,
                            close_price=ef.source_value,
                            observation_hash=obs.reconstruction_hash,
                        )
                    )
            return tuple(recon_records)
    return ()


def extract_current_close_price(
    context: StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1,
    security_id: UUID7,
) -> Decimal | None:
    """Extract the closing mark of the current decision session for one security."""
    history = extract_security_history(context, security_id)
    if not history:
        return None
    for obs in reversed(history):
        if obs.session_key == context.session_key:
            return obs.close_price
    return history[-1].close_price


def get_admitted_securities(
    context: StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1,
) -> tuple[UUID7, ...]:
    """Return the canonically sorted admitted security set for either lane."""
    if isinstance(context, StrategyDecisionContextV1):
        return context.admitted_universe
    return context.admitted_cohort


def build_decision_intent(
    context: StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1,
    targets: Sequence[SecurityTargetPositionV1],
) -> StrategyDecisionIntentV1:
    """Construct a validated StrategyDecisionIntentV1 bound to the context cutoff."""
    return StrategyDecisionIntentV1(
        session_key=context.session_key,
        decision_time=context.decision_cutoff,
        targets=tuple(targets),
    )


def compute_equal_weight_quantities(
    budget: Decimal,
    securities: Sequence[UUID7],
    prices: dict[UUID7, Decimal],
) -> dict[UUID7, int]:
    """Compute whole-share positions allocating budget equally across securities."""
    if not securities or budget <= Decimal("0"):
        return {sec: 0 for sec in securities}

    n = len(securities)
    quantities: dict[UUID7, int] = {}
    with decimal_context():
        dollars_per_security = budget / Decimal(str(n))
        for sec in securities:
            price = prices.get(sec)
            if price is not None and price > Decimal("0"):
                qty = int(dollars_per_security // price)
                quantities[sec] = max(0, qty)
            else:
                quantities[sec] = 0
    return quantities
