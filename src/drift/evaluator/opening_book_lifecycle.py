"""Optional evaluator-neutral opening-book lifecycle for a synthetic M0 proof.

This protocol is an integration boundary, not an authenticated account issuer.
Returning successfully from a callback does not establish that an event was
durably retained or that an arbitrary caller controls the permitted ledger.
Those properties require Matthew's independently verified #508 producer (PR B).

An evaluator using this interface does not import E1, research, a ledger,
credentials, a broker, or a policy/authorization service.
"""

from typing import Protocol

from drift.domain.evaluator_bundles import (
    EvaluationRunIdentityV1,
    EvaluationRunIdentityV2,
)
from drift.domain.evaluator_lanes import EvaluationAdmissionV1
from drift.domain.evaluator_portfolio import PortfolioStateV2
from drift.domain.evaluator_protocol import EvaluationProtocolV1
from drift.errors import DriftError


class OpeningBookLifecycleError(DriftError, RuntimeError):
    """An opening-book transition refused before another session can begin."""


class OpeningBookLifecycleV1(Protocol):
    """Only callbacks observing an engine-created fresh opening book.

    PR B will supply a Matthew-owned producer with a configured trust root,
    original-byte retention and verified durable acknowledgements. No
    caller-provided book is ever accepted into the engine.
    """

    def retain_original_book(
        self,
        *,
        opening_book: PortfolioStateV2,
        admission: EvaluationAdmissionV1,
        protocol: EvaluationProtocolV1,
        currency_code: str,
    ) -> None:
        """Retain the real original book before research or an invocation."""
        ...

    def claim_invocation(
        self,
        *,
        opening_book: PortfolioStateV2,
        run_identity: EvaluationRunIdentityV1 | EvaluationRunIdentityV2,
    ) -> None:
        """Record the irreversible invocation claim before any session step."""
        ...

    def observe_consumption(
        self,
        *,
        opening_book: PortfolioStateV2,
        run_identity: EvaluationRunIdentityV1 | EvaluationRunIdentityV2,
    ) -> None:
        """Observe the same book installed in the evaluator loop."""
        ...
