"""Optional evaluator-neutral opening-book lifecycle for a synthetic M0 proof.

This protocol is an integration boundary, not an authenticated account issuer.
Returning successfully from a callback does not establish that an event was
durably retained or that an arbitrary caller controls the permitted ledger.
Those properties require Matthew's independently verified #508 producer (PR B).

An evaluator using this interface does not import E1, research, a ledger,
credentials, a broker, or a policy/authorization service.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

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


def _copy_uuid7(value: object) -> UUID:
    """Detach exact UUID leaves, including their reflectively mutable integer."""
    if type(value) is not UUID:
        raise OpeningBookLifecycleError(
            "original invocation binding requires exact UUIDv7 identifiers"
        )
    try:
        bits = value.int
    except AttributeError as error:
        raise OpeningBookLifecycleError(
            "original invocation binding has an invalid UUIDv7 identifier"
        ) from error
    if type(bits) is not int or not 0 <= bits < 1 << 128:
        raise OpeningBookLifecycleError(
            "original invocation binding has an invalid UUIDv7 identifier"
        )
    copied = UUID(int=bits)
    if copied.version != 7:
        raise OpeningBookLifecycleError(
            "original invocation binding requires exact UUIDv7 identifiers"
        )
    return copied


@dataclass(frozen=True, slots=True)
class OriginalInvocationBindingV1:
    """Operational identity shared by one local M0 and prepared invocation.

    These identifiers never enter deterministic evaluator identity or artifact
    hashes. They identify one invocation under a configured trusted host; they
    do not authenticate an issuer or isolate hostile in-process Python code.
    """

    invocation_id: UUID
    m0_run_id: UUID
    m0_audit_event_id: UUID

    def __post_init__(self) -> None:
        # Frozen UUID objects, like frozen dataclasses, can still be changed
        # through object.__setattr__. Never retain a caller's UUID leaf.
        object.__setattr__(self, "invocation_id", _copy_uuid7(self.invocation_id))
        object.__setattr__(self, "m0_run_id", _copy_uuid7(self.m0_run_id))
        object.__setattr__(
            self, "m0_audit_event_id", _copy_uuid7(self.m0_audit_event_id)
        )


def copy_original_invocation_binding(
    binding: OriginalInvocationBindingV1,
) -> OriginalInvocationBindingV1:
    """Validate and detach a binding before retaining or exposing its values."""
    if type(binding) is not OriginalInvocationBindingV1:
        raise OpeningBookLifecycleError("original invocation binding has wrong type")
    try:
        return OriginalInvocationBindingV1(
            invocation_id=binding.invocation_id,
            m0_run_id=binding.m0_run_id,
            m0_audit_event_id=binding.m0_audit_event_id,
        )
    except AttributeError as error:
        raise OpeningBookLifecycleError(
            "original invocation binding has missing identifiers"
        ) from error


def invocation_binding_payload(
    binding: OriginalInvocationBindingV1,
) -> dict[str, str]:
    """Return exactly three canonical operational UUIDv7 strings."""
    captured = copy_original_invocation_binding(binding)
    return {
        "invocation_id": str(captured.invocation_id),
        "m0_run_id": str(captured.m0_run_id),
        "m0_audit_event_id": str(captured.m0_audit_event_id),
    }


def parse_original_invocation_binding(value: object) -> OriginalInvocationBindingV1:
    """Rebuild a strict binding from an original immutable event payload."""
    if not isinstance(value, Mapping):
        raise OpeningBookLifecycleError("original invocation binding is not a mapping")
    captured: dict[str, str] = {}
    for key, text in value.items():
        if type(key) is not str or type(text) is not str or key in captured:
            raise OpeningBookLifecycleError(
                "original invocation binding needs exact unique string keys and values"
            )
        captured[key] = text
    if set(captured) != {"invocation_id", "m0_run_id", "m0_audit_event_id"}:
        raise OpeningBookLifecycleError(
            "original invocation binding has missing or extra identifiers"
        )
    identifiers: dict[str, UUID] = {}
    for key, text in captured.items():
        try:
            identifier = UUID(text)
        except ValueError as error:
            raise OpeningBookLifecycleError(
                "original invocation binding has an invalid UUIDv7 identifier"
            ) from error
        if str(identifier) != text or identifier.version != 7:
            raise OpeningBookLifecycleError(
                "original invocation binding needs canonical UUIDv7 text"
            )
        identifiers[key] = identifier
    return OriginalInvocationBindingV1(
        invocation_id=identifiers["invocation_id"],
        m0_run_id=identifiers["m0_run_id"],
        m0_audit_event_id=identifiers["m0_audit_event_id"],
    )


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


@runtime_checkable
class BoundOpeningBookLifecycleV1(OpeningBookLifecycleV1, Protocol):
    """Additive local invocation-binding callbacks for prepared engine runs.

    Structural support for these methods is not issuer authentication. The
    configured trusted implementation must retain and verify original events.
    """

    def claim_bound_invocation(
        self,
        *,
        opening_book: PortfolioStateV2,
        run_identity: EvaluationRunIdentityV1 | EvaluationRunIdentityV2,
        binding: OriginalInvocationBindingV1,
    ) -> None:
        """Claim one prepared invocation under its captured operational binding."""
        ...

    def observe_bound_consumption(
        self,
        *,
        opening_book: PortfolioStateV2,
        run_identity: EvaluationRunIdentityV1 | EvaluationRunIdentityV2,
        binding: OriginalInvocationBindingV1,
    ) -> None:
        """Retain consumption under the exact binding of the original claim."""
        ...
