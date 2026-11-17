"""Optional detached observations and pre-commit authorization for installed hosts.

This is an evaluator interface, not a research/mandate implementation. Observers
are trusted installed code. They receive detached values and cannot mutate the
accounting outcome the engine will commit. An exception prevents execution; it
is never permission to retry a consumed original account.
"""

from typing import Literal, Protocol, Self, runtime_checkable

from pydantic import Field, model_validator

from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash
from drift.domain.evaluator_clock import EvaluationSessionV1, SessionClockV1
from drift.domain.evaluator_costs import EvaluationCostModelV1
from drift.domain.evaluator_execution import ListingOpenPriceV1, RebalanceOutcomeV2
from drift.domain.evaluator_portfolio import PortfolioStateV2
from drift.domain.evaluator_strategy import SecurityTargetPositionV1
from drift.domain.evaluator_trace import EvaluatorTraceEventV2
from drift.domain.securities import ListingV1
from drift.domain.synthetic_execution import (
    SyntheticExecutionReceiptV1,
    SyntheticExecutionSelectionV1,
)
from drift.evaluator.opening_book_lifecycle import OriginalInvocationBindingV1
from drift.serialization.canonical import content_hash


class SessionObservationV1(FrozenModel):
    """Actual marked book and original session trace prefix, before a decision."""

    schema_version: Literal["1"] = "1"
    session_index: int = Field(ge=0, strict=True)
    session: EvaluationSessionV1
    state: PortfolioStateV2
    trace_prefix: tuple[EvaluatorTraceEventV2, ...]
    invocation_binding: OriginalInvocationBindingV1 | None = None

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        if (
            self.state.session_key != self.session.session_key
            or not self.state.is_marked
        ):
            raise ValueError("SESSION_OBSERVATION_REQUIRES_CURRENT_MARK")
        if not self.trace_prefix or any(
            event.session_index != self.session_index
            or event.session_key != self.session.session_key
            for event in self.trace_prefix
        ):
            raise ValueError("SESSION_OBSERVATION_TRACE_SCOPE")
        return self


class OpenSecurityPriceV1(FrozenModel):
    security_id: UUID7
    quote: ListingOpenPriceV1


class ExecutionSecurityListingV1(FrozenModel):
    security_id: UUID7
    listing: ListingV1


class RebalancePreviewV1(FrozenModel):
    """Canonical accounting outcome, not yet assigned to the engine's book."""

    schema_version: Literal["1"] = "1"
    session_index: int = Field(ge=0, strict=True)
    session: EvaluationSessionV1
    decision_session: EvaluationSessionV1
    before_state: PortfolioStateV2
    outcome: RebalanceOutcomeV2
    open_prices: tuple[OpenSecurityPriceV1, ...]
    invocation_binding: OriginalInvocationBindingV1 | None = None

    @model_validator(mode="after")
    def validate_preview(self) -> Self:
        key = self.session.session_key
        if (
            self.before_state.session_key != key
            or self.outcome.state.session_key != key
        ):
            raise ValueError("REBALANCE_PREVIEW_SESSION_SCOPE")
        keys = tuple(item.security_id.bytes for item in self.open_prices)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("REBALANCE_PREVIEW_PRICE_IDENTITIES")
        return self

    @property
    def financial_hash(self) -> str:
        """Operational invocation IDs must not enter deterministic trace hashes."""
        payload = self.model_dump(mode="python")
        payload.pop("invocation_binding")
        return content_hash(payload)


class ExecutionAuthorizationV1(FrozenModel):
    """An exact-preview installed-host verdict; not external issuer proof."""

    schema_version: Literal["1"] = "1"
    preview_hash: SHA256Hash
    policy_hash: SHA256Hash
    verdict: Literal["approve", "reject", "contain"]
    reason: NonBlankStr


class ProtectiveExecutionContextV1(FrozenModel):
    """Actual pre-open state and evidence for an explicit protective planner."""

    schema_version: Literal["1"] = "1"
    session_index: int = Field(ge=0, strict=True)
    session: EvaluationSessionV1
    decision_session: EvaluationSessionV1 | None
    before_state: PortfolioStateV2
    staged_targets: tuple[SecurityTargetPositionV1, ...]
    open_prices: tuple[OpenSecurityPriceV1, ...]
    execution_listings: tuple[ExecutionSecurityListingV1, ...]
    cost_model: EvaluationCostModelV1
    session_clock: SessionClockV1
    invocation_binding: OriginalInvocationBindingV1 | None = None

    @model_validator(mode="after")
    def validate_context(self) -> Self:
        if (
            self.before_state.session_key != self.session.session_key
            or self.before_state.mark is not None
            or self.session_index >= len(self.session_clock.sessions)
            or self.session_clock.sessions[self.session_index] != self.session
        ):
            raise ValueError("PROTECTIVE_EXECUTION_CONTEXT_SESSION")
        required = {holding.security_id for holding in self.before_state.holdings}
        required.update(target.security_id for target in self.staged_targets)
        prices = tuple(item.security_id.bytes for item in self.open_prices)
        listings = tuple(item.security_id.bytes for item in self.execution_listings)
        expected = tuple(sorted(item.bytes for item in required))
        if prices != expected or listings != expected:
            raise ValueError("PROTECTIVE_EXECUTION_CONTEXT_EVIDENCE_INVENTORY")
        return self

    @property
    def financial_hash(self) -> str:
        payload = self.model_dump(mode="python")
        payload.pop("invocation_binding")
        return content_hash(payload)


class ProtectiveTargetProposalV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    context_hash: SHA256Hash
    policy_hash: SHA256Hash
    targets: tuple[SecurityTargetPositionV1, ...]
    reason: NonBlankStr

    @model_validator(mode="after")
    def validate_targets(self) -> Self:
        identities = tuple(target.security_id.bytes for target in self.targets)
        if identities != tuple(sorted(set(identities))):
            raise ValueError("PROTECTIVE_TARGET_IDENTITIES")
        return self


class SyntheticExecutionObservationV1(FrozenModel):
    """Postcommit original outcome; a partial receipt is never a full switch."""

    schema_version: Literal["1"] = "1"
    session_index: int = Field(ge=0, strict=True)
    session: EvaluationSessionV1
    decision_session: EvaluationSessionV1
    preview_hash: SHA256Hash
    purpose: Literal["strategy", "protective"]
    protective_policy_hash: SHA256Hash | None
    receipt: SyntheticExecutionReceiptV1
    invocation_binding: OriginalInvocationBindingV1 | None = None

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        if (
            self.receipt.selection.preview_hash != self.preview_hash
            or self.receipt.requested_plan.session_key != self.session.session_key
            or self.decision_session.closed_at >= self.session.opened_at
            or (self.purpose == "protective")
            != (self.protective_policy_hash is not None)
            or self.receipt.selection.invocation_id
            != (
                self.invocation_binding.invocation_id
                if self.invocation_binding is not None
                else None
            )
        ):
            raise ValueError("SYNTHETIC_EXECUTION_OBSERVATION_SCOPE")
        return self


@runtime_checkable
class SessionEvidenceObserverV1(Protocol):
    def observe_session(self, observation: SessionObservationV1) -> None:
        """Retain actual marked state before the installed strategy decides."""
        ...

    def authorize_rebalance(
        self, preview: RebalancePreviewV1
    ) -> ExecutionAuthorizationV1:
        """Approve, reject the incoming change, or halt before any fill commits."""
        ...


@runtime_checkable
class SyntheticExecutionObserverV1(Protocol):
    def select_execution(
        self, preview: RebalancePreviewV1
    ) -> SyntheticExecutionSelectionV1:
        """Select simulated quantities after approval, before actual commitment."""
        ...

    def observe_execution(self, observation: SyntheticExecutionObservationV1) -> None:
        """Retain actual committed fills and unresolved requested quantities."""
        ...


@runtime_checkable
class ProtectiveExecutionObserverV1(Protocol):
    def requires_protective_execution(
        self, session_index: int, session: EvaluationSessionV1
    ) -> bool:
        """Request the next-open evidence for a previously detected breach."""
        ...

    def propose_protective_targets(
        self, context: ProtectiveExecutionContextV1
    ) -> ProtectiveTargetProposalV1 | None:
        """Return sell-only targets, no correction, or raise to contain uncertainty."""
        ...
