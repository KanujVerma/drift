"""M2 portfolio state, whole-share holdings, and deterministic cash claims."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Annotated, Literal, Self

from pydantic import (
    BeforeValidator,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash
from drift.domain.economic_common import ActionKind, validate_canonical_cash
from drift.domain.sessions import SessionKeyV1
from drift.errors import DriftError
from drift.serialization.canonical import content_hash

# Version 2 of the preimage: identity became source-scoped and date-independent.
# A v1 id and a v2 id for the same occurrence must never be mistaken for one
# another, so the profile string moves with the preimage shape.
CLAIM_ID_PROFILE = "drift-pending-cash-claim-v2"

# Proportional basis relief can produce a non-terminating quotient, so the
# arithmetic context must be pinned rather than inherited. Without this an
# unrelated dependency touching getcontext() would silently change recorded
# books and break replay reproducibility.
PORTFOLIO_DECIMAL_PRECISION = 34
PORTFOLIO_DECIMAL_ROUNDING = ROUND_HALF_EVEN

type EvaluationLane = Literal["exploratory", "promotion"]
"""The ADR 0012 lane a portfolio book is admitted under."""

type MarkEvidenceGrade = Literal["promotion_grade", "exploratory", "indeterminate"]
"""Three-valued grade of the evidence behind one close price.

``indeterminate`` is a distinct answer from ``exploratory``: it means the mark
cannot name the evidence it came from at all. Collapsing the two into a boolean
would make an unbound price indistinguishable from an honestly exploratory one.
"""

LANE_ADMISSIBLE_MARK_GRADES: dict[EvaluationLane, frozenset[MarkEvidenceGrade]] = {
    # ADR 0012: the exploratory lane must stay fully usable, so it admits
    # exploratory evidence. The absolute non-upgrade rule means the promotion
    # lane admits nothing weaker than promotion-grade. Neither lane admits an
    # indeterminate binding: unknown provenance fails closed everywhere.
    "exploratory": frozenset({"promotion_grade", "exploratory"}),
    "promotion": frozenset({"promotion_grade"}),
}


@contextmanager
def decimal_context() -> Iterator[None]:
    """Pin the decimal context used for all portfolio arithmetic."""
    with localcontext(
        Context(prec=PORTFOLIO_DECIMAL_PRECISION, rounding=PORTFOLIO_DECIMAL_ROUNDING)
    ):
        yield


class IndeterminateValuationError(DriftError):
    """Raised when a held position cannot be marked from authorized evidence."""


class LaneAdmissibilityError(DriftError):
    """Raised when evidence is refused by the lane the book is admitted under."""


def canonical_money(value: Decimal) -> Decimal:
    """Re-spell an exact monetary Decimal in the M1c canonical cash form.

    ``content_hash`` renders Decimals with ``str()``, so ``Decimal("100000")``
    and ``Decimal("100000.00")`` are one amount with two hashes. M1c already
    settled this for source cash text with ``CanonicalCash``, so portfolio money
    reuses that exact spelling rule instead of inventing a second one; the
    magnitude is handed straight to ``validate_canonical_cash``. Note that
    ``decimal_context()`` pins arithmetic, not spelling, so it does not address
    this at all. The sign is carried separately because portfolio realized PnL
    may be negative while M1c source cash may not.
    """
    with decimal_context():
        magnitude = abs(value).normalize()
        text = format(magnitude, "f")
    validate_canonical_cash(text)
    return Decimal(f"-{text}") if value < Decimal("0") else Decimal(text)


def validate_canonical_money(value: object, info: ValidationInfo) -> Decimal:
    """Accept only an exact finite decimal and store its canonical spelling."""
    if info.mode == "json" and isinstance(value, str):
        try:
            parsed = Decimal(value)
        except (ArithmeticError, ValueError) as error:
            raise ValueError(
                "monetary amount requires an exact decimal string"
            ) from error
    elif info.mode == "python" and isinstance(value, Decimal):
        parsed = value
    else:
        raise ValueError("monetary amount requires an exact decimal value")
    if not parsed.is_finite():
        raise ValueError("monetary amount requires a finite decimal value")
    return canonical_money(parsed)


type CanonicalMoney = Annotated[Decimal, BeforeValidator(validate_canonical_money)]
"""An exact monetary Decimal normalized to one canonical spelling."""


def pending_cash_claim_id(
    *,
    source_id: str,
    security_id: UUID7,
    action_kind: ActionKind,
    occurrence_id: str,
    component_id: str,
) -> SHA256Hash:
    """Derive the deterministic identity of one occurrence-bound cash claim.

    Identity is source-scoped because M1c occurrence identity is source-scoped:
    ``EconomicDeliveryGroupV1`` keys a delivered occurrence on ``source_id``
    plus ``native_occurrence_id``, so two sources reusing one native occurrence
    id are two occurrences and must not collide onto a single claim.

    Identity is date-independent because M1c models payable and entitlement
    dates as revisable source claims (``EconomicDateFactV1`` role ``"payable"``
    inside a revision envelope). A date in the preimage would let a payable-date
    revision mint a second claim id for one economic entitlement, and both
    settled-claim guards are keyed on ``claim_id``, so neither would fire and
    the entitlement would pay twice. Dates are therefore attributes of the
    claim; a revision resolves by superseding the same identity.

    Component identity is part of the preimage so that several cash components
    of one action on one date remain distinct claims.
    """
    return content_hash(
        {
            "profile": CLAIM_ID_PROFILE,
            "source_id": source_id,
            "security_id": str(security_id),
            "action_kind": action_kind.value,
            "occurrence_id": occurrence_id,
            "component_id": component_id,
        }
    )


class SecurityHoldingV1(FrozenModel):
    """One long, whole-share position with its exact acquisition cost."""

    schema_version: Literal["1"] = "1"
    security_id: UUID7
    quantity: int = Field(gt=0)
    cost_basis: CanonicalMoney

    @model_validator(mode="after")
    def validate_holding(self) -> Self:
        if self.cost_basis < Decimal("0"):
            raise ValueError("cost basis must be non-negative")
        return self

    @property
    def average_cost_per_share(self) -> Decimal:
        """Per-share cost under the pinned Drift decimal context.

        Not exact in general: a basis that does not divide evenly by quantity
        has no finite decimal representation. The pinned context makes the
        rounding deterministic, not absent.
        """
        with decimal_context():
            return self.cost_basis / self.quantity


class PendingCashClaimV1(FrozenModel):
    """Cash owed to the portfolio by a corporate action but not yet delivered.

    ``entitlement_session`` and ``payable_session`` are revisable attributes,
    not identity. A revised payable date supersedes this claim under the same
    ``claim_id`` rather than creating a second claim for one entitlement.
    """

    schema_version: Literal["1"] = "1"
    claim_id: SHA256Hash
    source_id: NonBlankStr
    security_id: UUID7
    action_kind: ActionKind
    occurrence_id: NonBlankStr
    component_id: NonBlankStr
    entitled_quantity: int = Field(gt=0)
    cash_per_share: CanonicalMoney
    total_cash_expected: CanonicalMoney
    entitlement_session: date
    payable_session: date

    @model_validator(mode="after")
    def validate_claim(self) -> Self:
        with decimal_context():
            return self._validate_claim_under_pinned_context()

    def _validate_claim_under_pinned_context(self) -> Self:
        if self.cash_per_share < Decimal("0"):
            raise ValueError("cash per share must be non-negative")
        expected_total = self.cash_per_share * self.entitled_quantity
        if self.total_cash_expected != expected_total:
            raise ValueError(
                f"total cash expected must equal {expected_total}, "
                f"got {self.total_cash_expected}"
            )
        if self.payable_session < self.entitlement_session:
            raise ValueError("payable session cannot precede entitlement session")
        expected_id = pending_cash_claim_id(
            source_id=self.source_id,
            security_id=self.security_id,
            action_kind=self.action_kind,
            occurrence_id=self.occurrence_id,
            component_id=self.component_id,
        )
        if self.claim_id != expected_id:
            raise ValueError(
                f"claim id mismatch: expected {expected_id}, got {self.claim_id}"
            )
        return self


class PortfolioFillV1(FrozenModel):
    """One executed whole-share fill as the accounting kernel consumes it."""

    schema_version: Literal["1"] = "1"
    security_id: UUID7
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    fill_price: CanonicalMoney
    transaction_costs: CanonicalMoney = Decimal("0")

    @model_validator(mode="after")
    def validate_fill(self) -> Self:
        if self.fill_price <= Decimal("0"):
            raise ValueError("fill price must be strictly positive")
        if self.transaction_costs < Decimal("0"):
            raise ValueError("transaction costs must be non-negative")
        return self


class MarkEvidenceV1(FrozenModel):
    """Provenance binding for one close price used to mark a position.

    A mark that cannot name the exact evidence it came from is ``indeterminate``
    and names a reason instead of a hash. It is admissible in no lane, so an
    unbound price can never default into net asset value.
    """

    schema_version: Literal["1"] = "1"
    grade: MarkEvidenceGrade
    evidence_hash: SHA256Hash | None = None
    reason: NonBlankStr | None = None

    @model_validator(mode="after")
    def validate_union_shape(self) -> Self:
        if self.grade == "indeterminate":
            if self.evidence_hash is not None:
                raise ValueError(
                    "indeterminate mark evidence cannot name an evidence hash"
                )
            if self.reason is None:
                raise ValueError("indeterminate mark evidence requires a reason")
            return self
        if self.evidence_hash is None:
            raise ValueError(
                f"{self.grade} mark evidence requires a bound evidence hash"
            )
        if self.reason is not None:
            raise ValueError("bound mark evidence cannot carry an indeterminacy reason")
        return self


class MarkPriceV1(FrozenModel):
    """One exact unadjusted close price bound to the evidence that produced it."""

    schema_version: Literal["1"] = "1"
    security_id: UUID7
    close_price: CanonicalMoney
    evidence: MarkEvidenceV1

    @model_validator(mode="after")
    def validate_mark_price(self) -> Self:
        if self.close_price <= Decimal("0"):
            raise ValueError("close price must be strictly positive")
        return self


class PortfolioMarkV1(FrozenModel):
    """The evidence-bound mark taken for exactly one session in one lane.

    The mark carries the session it was taken in, so a mark can never survive
    rehydration into a different session: the state refuses a mark whose
    session key is not its own.
    """

    schema_version: Literal["1"] = "1"
    session_key: SessionKeyV1
    lane: EvaluationLane
    prices: tuple[MarkPriceV1, ...]

    @field_validator("prices")
    @classmethod
    def canonicalize_prices(
        cls, prices: tuple[MarkPriceV1, ...]
    ) -> tuple[MarkPriceV1, ...]:
        securities = tuple(price.security_id for price in prices)
        if len(set(securities)) != len(securities):
            raise ValueError("mark must carry at most one price per security")
        return tuple(sorted(prices, key=lambda price: str(price.security_id)))

    @model_validator(mode="after")
    def validate_mark(self) -> Self:
        admissible = LANE_ADMISSIBLE_MARK_GRADES[self.lane]
        for price in self.prices:
            if price.evidence.grade not in admissible:
                raise ValueError(
                    f"{self.lane} lane refuses {price.evidence.grade} mark "
                    f"evidence for security {price.security_id}"
                )
        return self


class PortfolioStateV1(FrozenModel):
    """Immutable portfolio state as of one evaluation session.

    The state names the lane it was produced under and the admission that
    authorized it, so a book can be shown promotion-grade rather than merely
    assumed to be.
    """

    schema_version: Literal["1"] = "1"
    lane: EvaluationLane
    admission_hash: SHA256Hash
    session_key: SessionKeyV1
    cash_balance: CanonicalMoney
    holdings: tuple[SecurityHoldingV1, ...]
    pending_cash_claims: tuple[PendingCashClaimV1, ...]
    settled_claim_ids: tuple[SHA256Hash, ...] = ()
    mark: PortfolioMarkV1 | None = None
    holdings_market_value: CanonicalMoney
    pending_claims_value: CanonicalMoney
    net_asset_value: CanonicalMoney
    realized_gross_pnl: CanonicalMoney
    realized_net_pnl: CanonicalMoney
    cumulative_transaction_costs: CanonicalMoney

    @property
    def is_marked(self) -> bool:
        """Whether this state carries a mark taken in its own session."""
        return self.mark is not None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        with decimal_context():
            return self._validate_under_pinned_context()

    def _validate_under_pinned_context(self) -> Self:
        _validate_book(self)
        return self


def _validate_book(state: PortfolioStateV1 | PortfolioStateV2) -> None:
    """Hold the cash, claim, mark and NAV invariants every book version shares.

    Called under the pinned decimal context. Both state versions validate
    through this one function, so V2 cannot drift from V1 on anything the
    two have in common.
    """
    if state.cash_balance < Decimal("0"):
        raise ValueError("cash balance must be non-negative")
    if state.holdings_market_value < Decimal("0"):
        raise ValueError("holdings market value must be non-negative")
    if state.cumulative_transaction_costs < Decimal("0"):
        raise ValueError("cumulative transaction costs must be non-negative")

    securities = tuple(holding.security_id for holding in state.holdings)
    if len(set(securities)) != len(securities):
        raise ValueError("holdings must carry at most one entry per security")
    claim_ids = tuple(claim.claim_id for claim in state.pending_cash_claims)
    if len(set(claim_ids)) != len(claim_ids):
        raise ValueError("pending claims must be unique by claim id")

    # A settled claim must never reappear as pending. Claim identity is
    # derived from the source-scoped economic occurrence and is independent
    # of every revisable date, so the same id is the same entitlement and
    # paying it twice creates cash from nothing.
    if len(set(state.settled_claim_ids)) != len(state.settled_claim_ids):
        raise ValueError("settled claim ids must be unique")
    if tuple(sorted(state.settled_claim_ids)) != state.settled_claim_ids:
        raise ValueError("settled claim ids must be canonically sorted")
    replayed = set(state.settled_claim_ids) & set(claim_ids)
    if replayed:
        raise ValueError(
            f"claim already settled cannot be pending again: {sorted(replayed)[0]}"
        )

    expected_claims = sum(
        (claim.total_cash_expected for claim in state.pending_cash_claims),
        Decimal("0"),
    )
    if state.pending_claims_value != expected_claims:
        raise ValueError(
            f"pending claims value must equal {expected_claims}, "
            f"got {state.pending_claims_value}"
        )

    _validate_book_mark(state)

    expected_nav = (
        state.cash_balance + state.holdings_market_value + state.pending_claims_value
    )
    if state.net_asset_value != expected_nav:
        raise ValueError(
            f"net asset value must reconcile to {expected_nav}, "
            f"got {state.net_asset_value}"
        )


def _validate_book_mark(state: PortfolioStateV1 | PortfolioStateV2) -> None:
    # A mark is only meaningful for the holdings it was taken against, in
    # the session it was taken in, under the lane that admitted it. Coupling
    # all three here stops a stale mark surviving a fill or a rehydration
    # into another session and inventing net asset value nothing backs. A
    # mark reads quantities and prices only, never a basis status.
    if not state.holdings and state.holdings_market_value != Decimal("0"):
        raise ValueError("state without holdings cannot carry a market value")
    if state.mark is None:
        if state.holdings_market_value != Decimal("0"):
            raise ValueError("unmarked state cannot carry a holdings market value")
        return
    if state.mark.session_key != state.session_key:
        raise ValueError(
            "mark belongs to session "
            f"{state.mark.session_key.mic}/{state.mark.session_key.local_date}, "
            f"state is session {state.session_key.mic}/{state.session_key.local_date}"
        )
    if state.mark.lane != state.lane:
        raise ValueError(
            f"mark was admitted under the {state.mark.lane} lane, "
            f"state is in the {state.lane} lane"
        )
    priced = {price.security_id: price.close_price for price in state.mark.prices}
    if set(priced) != set(holding.security_id for holding in state.holdings):
        raise ValueError("mark must price exactly the held securities")
    expected_value = sum(
        (priced[holding.security_id] * holding.quantity for holding in state.holdings),
        Decimal("0"),
    )
    if state.holdings_market_value != expected_value:
        raise ValueError(
            f"holdings market value must equal {expected_value}, "
            f"got {state.holdings_market_value}"
        )
    if state.holdings and state.holdings_market_value <= Decimal("0"):
        raise ValueError("marked holdings must carry a positive market value")


# ==========================================================================
# Version 2: applied-effect identity and basis status (issues 49, 103, 105)
# ==========================================================================
#
# The V1 models above are frozen (#50): every field is dumped by
# ``content_hash``, so even a defaulted field would move their bytes. The V2
# models are successors, not subclasses, and no function lifts a V1 book into
# V2: a V1 holding cannot say whether its basis is known, and a lift would
# launder the zero basis a V1 spin-off child carries (#103) as a known one.

# Version 1 of the applied-effect preimage. Revisable fields stay out of it:
# the effective time, the ratio and components, the record version and its
# hash, and the action kind. A revision that reclassifies an occurrence must
# not mint a fresh identity and re-apply, which is the double-pay defect of
# the claim identity (#4) in share form. The cost is that two share mutations
# of one occurrence on one security share an identity, and that collision
# fails closed.
APPLIED_EFFECT_ID_PROFILE = "drift-applied-economic-effect-v1"

type BasisStatus = Literal["known", "indeterminate"]
"""Whether a holding's cost basis is exactly known.

``indeterminate`` means no source evidence allocates the basis, so any
realized PnL computed from it would be invented. It is never zero.
"""


class EffectAlreadyAppliedError(IndeterminateValuationError):
    """Raised when a share-mutating effect the book already absorbed recurs.

    Re-applying a split to a book that already reflects it doubles the
    position. The book records every share-mutating effect it absorbed, so a
    replay is refused rather than applied twice (issue 49).
    """


class IndeterminateBasisError(IndeterminateValuationError):
    """Raised when realizing a holding whose cost basis is indeterminate.

    A sale or disposal relieves basis into realized PnL. With no proven
    basis there is no proven PnL, so the run fails closed (spec 12.5).
    """


def applied_economic_effect_id(
    *, source_id: str, security_id: UUID7, occurrence_id: str
) -> SHA256Hash:
    """Derive the identity of one economic effect a book absorbed.

    Source-scoped and date-independent, as claim identity is (spec 11.3).
    The action kind is excluded because it is revisable (see
    ``APPLIED_EFFECT_ID_PROFILE``).
    """
    return content_hash(
        {
            "profile": APPLIED_EFFECT_ID_PROFILE,
            "source_id": source_id,
            "security_id": str(security_id),
            "occurrence_id": occurrence_id,
        }
    )


def _require_canonical_ids(values: tuple[str, ...], label: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")
    if tuple(sorted(values)) != values:
        raise ValueError(f"{label} must be canonically sorted")


class SecurityHoldingV2(FrozenModel):
    """One long, whole-share position whose cost basis is known or not.

    A known basis is exact and non-negative. An indeterminate basis carries
    no amount at all, and names the applied effects that made it
    indeterminate, so the cause travels with the holding to the sale that
    would realize it.
    """

    schema_version: Literal["2"] = "2"
    security_id: UUID7
    quantity: int = Field(gt=0)
    basis_status: BasisStatus
    cost_basis: CanonicalMoney | None
    basis_indeterminate_by: tuple[SHA256Hash, ...] = ()

    @model_validator(mode="after")
    def validate_holding(self) -> Self:
        if self.basis_status == "known":
            if self.cost_basis is None:
                raise ValueError("a known basis requires an exact cost basis")
            if self.cost_basis < Decimal("0"):
                raise ValueError("cost basis must be non-negative")
            if self.basis_indeterminate_by:
                raise ValueError("a known basis cannot name an indeterminacy cause")
            return self
        if self.cost_basis is not None:
            raise ValueError("an indeterminate basis cannot carry a cost basis")
        if not self.basis_indeterminate_by:
            raise ValueError(
                "an indeterminate basis must name the effects that made it so"
            )
        _require_canonical_ids(self.basis_indeterminate_by, "indeterminacy causes")
        return self

    @property
    def average_cost_per_share(self) -> Decimal | None:
        """Per-share cost under the pinned decimal context, if the basis is known.

        Not exact in general, as for ``SecurityHoldingV1``. ``None`` exactly
        when the basis is indeterminate.
        """
        if self.cost_basis is None:
            return None
        with decimal_context():
            return self.cost_basis / self.quantity


class PortfolioStateV2(FrozenModel):
    """Immutable portfolio state carrying applied effects and basis status.

    ``applied_effect_ids`` records every share-mutating economic effect the
    book has absorbed, so a replay is detectable from the state alone (issue
    49), exactly as ``settled_claim_ids`` makes cash entitlements idempotent.
    Each indeterminate holding names only effects recorded here.
    """

    schema_version: Literal["2"] = "2"
    lane: EvaluationLane
    admission_hash: SHA256Hash
    session_key: SessionKeyV1
    cash_balance: CanonicalMoney
    holdings: tuple[SecurityHoldingV2, ...]
    pending_cash_claims: tuple[PendingCashClaimV1, ...]
    settled_claim_ids: tuple[SHA256Hash, ...] = ()
    applied_effect_ids: tuple[SHA256Hash, ...] = ()
    mark: PortfolioMarkV1 | None = None
    holdings_market_value: CanonicalMoney
    pending_claims_value: CanonicalMoney
    net_asset_value: CanonicalMoney
    realized_gross_pnl: CanonicalMoney
    realized_net_pnl: CanonicalMoney
    cumulative_transaction_costs: CanonicalMoney

    @property
    def is_marked(self) -> bool:
        """Whether this state carries a mark taken in its own session."""
        return self.mark is not None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        with decimal_context():
            _validate_book(self)
        _require_canonical_ids(self.applied_effect_ids, "applied effect ids")
        applied = frozenset(self.applied_effect_ids)
        for holding in self.holdings:
            unrecorded = sorted(set(holding.basis_indeterminate_by) - applied)
            if unrecorded:
                raise ValueError(
                    f"holding {holding.security_id} names an indeterminacy cause "
                    f"the book never applied: {unrecorded[0]}"
                )
        return self
