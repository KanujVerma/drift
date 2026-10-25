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
    """Callbacks for a canonical twin of the actual engine-owned opening book.

    The evaluator creates exactly one internal original portfolio from its
    validated admission, calendar and cash. A callback may retain a reference
    indefinitely, or mutate a frozen model via object.__setattr__; therefore
    the private original used for accounting is NEVER exposed. All callbacks
    receive the SAME separately validated twin of those exact original
    bytes. The evaluator consumes its own single original, without recrediting
    or swapping a caller-defined book into the accounting loop.

    PR B provides a local origin ledger, but acceptance of the original
    issuer trust root is a separate Matthew decision, not implied by calling
    this observer.
    """

    def retain_original_book(
        self,
        *,
        opening_book: PortfolioStateV2,
        admission: EvaluationAdmissionV1,
        protocol: EvaluationProtocolV1,
        currency_code: str,
    ) -> None:
        """Retain a detached canonical witness of the original book bytes."""
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
        """Observe consumption using the original witness, not engine state."""
        ...
