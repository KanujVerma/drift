"""M2 runtime strategy boundary: causal decision context and target intent.

The strategy boundary is deliberately narrow. A strategy sees a causal,
point-in-time information set and answers with whole-share target positions on
economic securities. It never names an execution venue, never sees ex-post
evidence, and never reads a clock: the evaluator supplies the decision cutoff
and the evaluator resolves the execution listing at the next open.
"""

from decimal import Decimal
from typing import Literal, Protocol, Self, runtime_checkable
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from drift.domain.common import UUID7, FrozenModel, UTCDateTime
from drift.domain.evaluator_portfolio import SecurityHoldingV1, decimal_context
from drift.domain.normalization import DerivedObservationViewV1
from drift.domain.sessions import SessionKeyV1
from drift.domain.strategies import StrategyReference
from drift.errors import DriftError
from drift.serialization.canonical import content_hash

DECISION_TIME_MISMATCH = (
    "decision intent decision_time must strictly match context.decision_cutoff"
)


class StrategyIntentRejectedError(DriftError, ValueError):
    """Raised when a strategy intent violates the long-only target contract.

    Also a ValueError so that callers relying on the documented fail-closed
    ``ValueError`` contract keep working, while M2 code can catch the narrower
    Drift error and classify the run as REJECTED.
    """


def _security_order(security_id: UUID) -> bytes:
    """Canonical collection order for securities: raw UUID bytes."""
    return security_id.bytes


class PositionViewV1(FrozenModel):
    """Causal, point-in-time view of one existing portfolio holding."""

    schema_version: Literal["1"] = "1"
    security_id: UUID7
    quantity: int = Field(gt=0)
    cost_basis: Decimal
    average_cost_per_share: Decimal

    @model_validator(mode="after")
    def validate_position_view(self) -> Self:
        with decimal_context():
            return self._validate_under_pinned_context()

    def _validate_under_pinned_context(self) -> Self:
        if self.cost_basis < Decimal("0"):
            raise ValueError("cost basis must be non-negative")
        # A view that disagrees with its own basis would let a strategy see a
        # per-share cost no holding supports, so the two are bound here.
        expected = self.cost_basis / self.quantity
        if self.average_cost_per_share != expected:
            raise ValueError(
                f"average cost per share must equal {expected}, "
                f"got {self.average_cost_per_share}"
            )
        return self


def position_view(holding: SecurityHoldingV1) -> PositionViewV1:
    """Project one holding into its strategy-facing position view."""
    return PositionViewV1(
        security_id=holding.security_id,
        quantity=holding.quantity,
        cost_basis=holding.cost_basis,
        average_cost_per_share=holding.average_cost_per_share,
    )


class StrategyDecisionViewV1(FrozenModel):
    """Canonical, causally anchored decision evidence for one security."""

    schema_version: Literal["1"] = "1"
    security_id: UUID7
    views: tuple[DerivedObservationViewV1, ...]

    @field_validator("views")
    @classmethod
    def canonicalize_views(
        cls, values: tuple[DerivedObservationViewV1, ...]
    ) -> tuple[DerivedObservationViewV1, ...]:
        if not values:
            raise ValueError("decision view requires at least one derived view")
        paired = tuple((content_hash(view), view) for view in values)
        digests = tuple(digest for digest, _ in paired)
        if len(set(digests)) != len(digests):
            raise ValueError("decision view members must be unique")
        return tuple(view for _, view in sorted(paired, key=lambda pair: pair[0]))

    @model_validator(mode="after")
    def validate_decision_view(self) -> Self:
        for view in self.views:
            if view.security_id != self.security_id:
                raise ValueError("decision view members must share the security")
            # An outcome-role view is ex-post information. Letting one reach a
            # strategy would be a lookahead channel.
            if view.role != "decision":
                raise ValueError(
                    "decision view members require decision-role evidence, "
                    f"got role {view.role}"
                )
        return self


class StrategyDecisionContextV1(FrozenModel):
    """Causal, point-in-time information set handed to a runtime strategy."""

    schema_version: Literal["1"] = "1"
    session_key: SessionKeyV1
    decision_cutoff: UTCDateTime
    admitted_universe: tuple[UUID7, ...]
    current_holdings: tuple[PositionViewV1, ...]
    current_cash: Decimal
    portfolio_nav: Decimal
    decision_views: tuple[StrategyDecisionViewV1, ...]

    @field_validator("admitted_universe")
    @classmethod
    def canonicalize_universe(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(set(values)) != len(values):
            raise ValueError("admitted universe members must be unique")
        return tuple(sorted(values, key=_security_order))

    @field_validator("current_holdings")
    @classmethod
    def canonicalize_holdings(
        cls, values: tuple[PositionViewV1, ...]
    ) -> tuple[PositionViewV1, ...]:
        securities = tuple(item.security_id for item in values)
        if len(set(securities)) != len(securities):
            raise ValueError("holdings must be unique by security")
        return tuple(sorted(values, key=lambda item: _security_order(item.security_id)))

    @field_validator("decision_views")
    @classmethod
    def canonicalize_decision_views(
        cls, values: tuple[StrategyDecisionViewV1, ...]
    ) -> tuple[StrategyDecisionViewV1, ...]:
        securities = tuple(item.security_id for item in values)
        if len(set(securities)) != len(securities):
            raise ValueError("decision views must be unique by security")
        return tuple(sorted(values, key=lambda item: _security_order(item.security_id)))

    @model_validator(mode="after")
    def validate_context(self) -> Self:
        if self.current_cash < Decimal("0"):
            raise ValueError("current cash must be non-negative")
        if self.portfolio_nav < Decimal("0"):
            raise ValueError("portfolio net asset value must be non-negative")
        for group in self.decision_views:
            for view in group.views:
                self._validate_causality(view)
        return self

    def _validate_causality(self, view: DerivedObservationViewV1) -> None:
        # A decision taken at the close of session S may only read sessions up
        # to S. A later source session is plain lookahead.
        if view.source_session.local_date > self.session_key.local_date:
            raise ValueError(
                "decision evidence sourced after its decision session: "
                f"{view.source_session.local_date} follows "
                f"{self.session_key.local_date}"
            )
        # Split normalization against a future anchor leaks the future split
        # schedule into a past bar, so the anchor is pinned to this session.
        if view.basis_mode == "split_normalized" and view.anchor_session != (
            self.session_key
        ):
            raise ValueError(
                "split normalized decision evidence must be anchored to its "
                f"decision session {self.session_key.local_date}"
            )


class SecurityTargetPositionV1(FrozenModel):
    """Whole-share target position intent for one economic security.

    Deliberately carries no execution listing: the strategy targets the
    economic security and the evaluator resolves the active historical primary
    execution listing at the execution session.
    """

    schema_version: Literal["1"] = "1"
    security_id: UUID7
    target_quantity: int = Field(ge=0)


class StrategyDecisionIntentV1(FrozenModel):
    """Complete portfolio intent emitted by a strategy at a decision cutoff."""

    schema_version: Literal["1"] = "1"
    session_key: SessionKeyV1
    decision_time: UTCDateTime
    targets: tuple[SecurityTargetPositionV1, ...]

    @field_validator("targets")
    @classmethod
    def canonicalize_targets(
        cls, values: tuple[SecurityTargetPositionV1, ...]
    ) -> tuple[SecurityTargetPositionV1, ...]:
        securities = tuple(item.security_id for item in values)
        if len(set(securities)) != len(securities):
            raise ValueError("targets must be unique by security")
        return tuple(sorted(values, key=lambda item: _security_order(item.security_id)))


@runtime_checkable
class RuntimeStrategy(Protocol):
    """Pure strategy interface invoked by the evaluator engine."""

    @property
    def strategy_reference(self) -> StrategyReference:
        """Provenance reference for the executing strategy version."""
        ...

    def decide(self, context: StrategyDecisionContextV1) -> StrategyDecisionIntentV1:
        """Answer a causal decision context with a complete target intent."""
        ...


def stage_decision_targets(
    intent: StrategyDecisionIntentV1,
    context: StrategyDecisionContextV1,
) -> tuple[SecurityTargetPositionV1, ...]:
    """Validate one decision intent and stage the complete target set.

    Applies the explicit complete target set rule: any held security absent
    from the intent is staged at zero, which liquidates it. Phase 5 does not
    check solvency, because the next open price is a future unknown.
    """
    if intent.session_key != context.session_key:
        raise StrategyIntentRejectedError(
            "decision intent session_key must match the decision context session"
        )
    if intent.decision_time != context.decision_cutoff:
        raise StrategyIntentRejectedError(DECISION_TIME_MISMATCH)

    staged: dict[UUID, SecurityTargetPositionV1] = {}
    admitted = frozenset(context.admitted_universe)
    for target in intent.targets:
        if target.target_quantity < 0:
            raise StrategyIntentRejectedError(
                "target quantity must be non-negative, got "
                f"{target.target_quantity} for {target.security_id}"
            )
        if target.security_id in staged:
            raise StrategyIntentRejectedError(
                f"targets must be unique by security: {target.security_id}"
            )
        # Holding or entering a security the universe does not admit is an
        # unadmitted position. Only liquidating one is allowed.
        if target.target_quantity > 0 and target.security_id not in admitted:
            raise StrategyIntentRejectedError(
                f"a positive target requires an admitted security: {target.security_id}"
            )
        staged[target.security_id] = target

    for holding in context.current_holdings:
        if holding.security_id not in staged:
            staged[holding.security_id] = SecurityTargetPositionV1(
                security_id=holding.security_id, target_quantity=0
            )
    return tuple(
        sorted(staged.values(), key=lambda item: _security_order(item.security_id))
    )
