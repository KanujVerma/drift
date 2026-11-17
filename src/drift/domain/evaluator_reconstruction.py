"""M2 exploratory cohort authorization and scheduled source-basis reconstruction.

These contracts are deliberately exploratory-only. An
``ExploratoryCohortAuthorizationV1`` is experiment SCOPE evidence: it records
which securities a specific exploratory run is authorized to consider. It is NOT
proof of universe membership, survivorship-free selection, structural listing
eligibility, primary listing, or historical availability of any record. An
``ExploratoryReconstructedSessionObservationV1`` is a source-basis retrospective
projection under scheduled-session reconstruction. It is NOT a
``DerivedObservationViewV1``, not an ``ObservationDecisionReferenceV1`` or
``ObservationOutcomeReferenceV1``, not an M1d ``NormalizationResultV1``, not proof
of a realized session, not proof of historical publication availability, not
proof of the absence of halts, and never promotion-grade evidence.
"""

from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from functools import wraps
from typing import Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ValidationInfo,
    field_validator,
    model_validator,
)

from drift.domain.common import (
    UUID7,
    FrozenModel,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_BOUNDED_COHORT,
    ALPACA_LIMITATION_COHORT_LISTING_ROLE,
    ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
    ALPACA_LIMITATION_UNVERSIONED_BARS,
)
from drift.domain.securities import ListingVenue
from drift.domain.sessions import SessionKeyV1
from drift.serialization.canonical import content_hash

REQUIRED_RECONSTRUCTION_FIELDS: tuple[str, ...] = (
    "close",
    "high",
    "low",
    "open",
    "volume",
)
"""Canonical required exploratory fields for scheduled source-basis reconstruction."""

_COHORT_SORT_KEY = str


class _ObservationValidationReuse:
    """One call's bounded exact-preimage hash computations, never validation."""

    def __init__(self) -> None:
        self.max_entries = 8192
        self.max_bytes = 128 * 1024 * 1024
        self.retained_bytes = 0
        self.entries: OrderedDict[tuple[object, ...], tuple[str, int]] = OrderedDict()

    def retain(self, key: tuple[object, ...], result: str, cost: int) -> None:
        if cost > self.max_bytes or self.max_entries <= 0:
            return
        while self.entries and (
            len(self.entries) >= self.max_entries
            or self.retained_bytes + cost > self.max_bytes
        ):
            _, (_, old_cost) = self.entries.popitem(last=False)
            self.retained_bytes -= old_cost
        self.entries[key] = (result, cost)
        self.retained_bytes += cost


def _exact_reconstruction_value(value: object) -> tuple[object, int] | None:
    """Lossless typed key; no caller equality or claimed digest is trusted."""
    cls = type(value)
    if cls is str:
        return (str, value), 128 + 4 * len(value)  # type: ignore[arg-type]
    if cls in (type(None), bool, int):
        return (cls, value), 192
    if cls is Decimal:
        assert isinstance(value, Decimal)
        if not value.is_finite():
            return None
        triple = value.as_tuple()
        return (Decimal, triple), 256 + 16 * len(triple.digits)
    if cls is UUID:
        assert isinstance(value, UUID)
        return (UUID, value.int), 192
    if cls is datetime:
        assert isinstance(value, datetime)
        # Domain timestamps are already strictly validated/normalized to UTC.
        return (datetime, value.isoformat(), value.fold), 256
    if cls is date:
        assert isinstance(value, date)
        return (date, value.isoformat()), 192
    if cls is ListingVenue:
        assert isinstance(value, Enum)
        return (ListingVenue, value.value), 192
    if cls is tuple:
        assert isinstance(value, tuple)
        parts = [_exact_reconstruction_value(item) for item in value]
        if any(part is None for part in parts):
            return None
        checked = [part for part in parts if part is not None]
        return tuple(part[0] for part in checked), 128 + sum(p[1] for p in checked)
    if cls in (
        SessionKeyV1,
        ExploratoryReconstructedFieldV1,
        ExploratoryReconstructedSessionObservationV1,
    ):
        assert isinstance(value, BaseModel)
        parts = [
            _exact_reconstruction_value(getattr(value, name))
            for name in type(value).model_fields
        ]
        if any(part is None for part in parts):
            return None
        checked = [part for part in parts if part is not None]
        return (cls, tuple(p[0] for p in checked)), 192 + sum(p[1] for p in checked)
    return None


_OBSERVATION_VALIDATION_REUSE: ContextVar[_ObservationValidationReuse | None] = (
    ContextVar("drift_private_observation_validation_reuse", default=None)
)


@contextmanager
def _reconstruction_validation_scope() -> Iterator[_ObservationValidationReuse]:
    """Never share successes across independent roots, arms, reads or failures."""
    cache = _ObservationValidationReuse()
    token = _OBSERVATION_VALIDATION_REUSE.set(cache)
    try:
        yield cache
    finally:
        _OBSERVATION_VALIDATION_REUSE.reset(token)
        cache.entries.clear()
        cache.retained_bytes = 0


def _with_reconstruction_validation_reuse[**P, T](
    function: Callable[P, T],
) -> Callable[P, T]:
    @wraps(function)
    def scoped(*args: P.args, **kwargs: P.kwargs) -> T:
        with _reconstruction_validation_scope():
            return function(*args, **kwargs)

    return scoped


def cohort_authorization_hash(cohort: ExploratoryCohortAuthorizationV1) -> SHA256Hash:
    """Compute the canonical content hash for ExploratoryCohortAuthorizationV1."""
    dump = cohort.model_dump(mode="python")
    dump.pop("cohort_hash", None)
    return content_hash(dump)


def reconstruction_policy_hash(policy: ExploratoryReconstructionPolicyV1) -> SHA256Hash:
    """Compute the canonical content hash for ExploratoryReconstructionPolicyV1."""
    dump = policy.model_dump(mode="python")
    dump.pop("policy_hash", None)
    return content_hash(dump)


def exploratory_reconstruction_semantic_hash() -> SHA256Hash:
    """Return the fixed semantic identity of the V1 scheduled source-basis policy."""
    return content_hash(
        {
            "algorithm_id": "drift.exploratory-source-basis-scheduled-reconstruction",
            "version": "1",
            "mode": "source_basis_scheduled_session_reconstruction_v1",
            "required_fields": list(REQUIRED_RECONSTRUCTION_FIELDS),
            "required_basis": "unadjusted",
            "field_meanings": {
                "open": "price",
                "high": "price",
                "low": "price",
                "close": "price",
                "volume": "share_volume",
            },
            "rule": (
                "interpret exact retained current-vintage source fields through "
                "the selected authenticated observation contract without any "
                "adjustment, split factor, or derived normalization"
            ),
        }
    )


class ExploratoryCohortAuthorizationV1(FrozenModel):
    """Predeclared bounded security cohort authorizing exploratory runs.

    Scope only: any input built on this cohort requires
    ``ALPACA_LIMITATION_BOUNDED_COHORT`` to be acknowledged by the exploratory
    admission. This contract makes no universe-membership, listing-history, or
    historical-availability claim.
    """

    schema_version: Literal["1"] = "1"
    kind: Literal["predeclared_bounded_security_cohort"] = (
        "predeclared_bounded_security_cohort"
    )
    cohort_id: NonBlankStr
    cohort_version: NonBlankStr
    security_ids: tuple[UUID7, ...]
    cohort_hash: SHA256Hash

    @field_validator("security_ids")
    @classmethod
    def canonicalize_security_ids(cls, values: tuple[UUID7, ...]) -> tuple[UUID7, ...]:
        if not values:
            raise ValueError("cohort requires at least one security")
        if len(set(values)) != len(values):
            raise ValueError("cohort security IDs must be unique")
        return tuple(sorted(values, key=_COHORT_SORT_KEY))

    @model_validator(mode="after")
    def validate_cohort(self) -> Self:
        expected = cohort_authorization_hash(self)
        if self.cohort_hash != expected:
            raise ValueError(
                f"cohort hash mismatch: expected {expected}, got {self.cohort_hash}"
            )
        return self


class ExploratoryReconstructionPolicyV1(FrozenModel):
    """Fixed source-basis reconstruction policy for scheduled exploratory inputs."""

    schema_version: Literal["1"] = "1"
    policy_id: NonBlankStr
    policy_version: NonBlankStr
    mode: Literal["source_basis_scheduled_session_reconstruction_v1"] = (
        "source_basis_scheduled_session_reconstruction_v1"
    )
    required_fields: tuple[str, ...] = REQUIRED_RECONSTRUCTION_FIELDS
    required_basis: Literal["unadjusted"] = "unadjusted"
    semantic_policy_hash: SHA256Hash
    policy_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if tuple(self.required_fields) != REQUIRED_RECONSTRUCTION_FIELDS:
            raise ValueError(
                "reconstruction policy requires exactly the canonical fields"
            )
        if self.semantic_policy_hash != exploratory_reconstruction_semantic_hash():
            raise ValueError("reconstruction semantic policy hash mismatch")
        expected = reconstruction_policy_hash(self)
        if self.policy_hash != expected:
            raise ValueError(
                f"reconstruction policy hash mismatch: expected {expected}, "
                f"got {self.policy_hash}"
            )
        return self


class ExploratoryReconstructedFieldV1(FrozenModel):
    """One exact source-basis field projected from a source record field."""

    schema_version: Literal["1"] = "1"
    field_name: NonBlankStr
    source_value: Decimal
    method_id: NonBlankStr
    meaning: Literal["price", "share_volume"]
    source_field_hash: SHA256Hash

    @field_validator("source_value", mode="before")
    @classmethod
    def require_exact_decimal(cls, value: object, info: ValidationInfo) -> Decimal:
        if info.mode == "json" and isinstance(value, str):
            try:
                parsed = Decimal(value)
            except (ArithmeticError, ValueError) as error:
                raise ValueError(
                    "reconstructed field requires an exact decimal string"
                ) from error
            if parsed.is_finite():
                return parsed
        elif info.mode == "python" and isinstance(value, Decimal):
            if value.is_finite():
                return value
        raise ValueError("reconstructed field requires an exact decimal value")

    @model_validator(mode="after")
    def validate_field(self) -> Self:
        if self.field_name not in REQUIRED_RECONSTRUCTION_FIELDS:
            raise ValueError(f"unsupported reconstruction field: {self.field_name}")
        expected_meaning = "share_volume" if self.field_name == "volume" else "price"
        if self.meaning != expected_meaning:
            raise ValueError(
                f"reconstructed field {self.field_name} requires meaning "
                f"'{expected_meaning}'"
            )
        return self


class ExploratoryReconstructedSessionObservationV1(FrozenModel):
    """Exploratory-only scheduled source-basis reconstruction of one session.

    This artifact deliberately binds weaker evidence than strict M1d views. It
    carries no realized-session claim, no historical publication-time proof, no
    universe or structural eligibility proof, and no split normalization.
    """

    schema_version: Literal["1"] = "1"
    kind: Literal["exploratory_reconstructed_session_observation"] = (
        "exploratory_reconstructed_session_observation"
    )
    session_key: SessionKeyV1
    security_id: UUID7
    listing_id: UUID7
    venue: ListingVenue
    cohort_hash: SHA256Hash
    source_observation_hash: SHA256Hash
    observation_contract_hash: SHA256Hash
    observation_selection_proof_hash: SHA256Hash
    contract_selection_proof_hash: SHA256Hash
    scheduled_session_hash: SHA256Hash
    scheduled_selection_proof_hash: SHA256Hash
    schedule_artifact_hash: SHA256Hash
    generated_session_row_hash: SHA256Hash
    outcome_query_hash: SHA256Hash
    source_context_hash: SHA256Hash
    evidence_vintage_cutoff: UTCDateTime
    reconstruction_policy_hash: SHA256Hash
    currency: NonBlankStr
    fields: tuple[ExploratoryReconstructedFieldV1, ...]
    acknowledged_limitations: tuple[NonBlankStr, ...]
    reconstruction_hash: SHA256Hash

    @field_validator("fields")
    @classmethod
    def canonicalize_fields(
        cls, fields: tuple[ExploratoryReconstructedFieldV1, ...]
    ) -> tuple[ExploratoryReconstructedFieldV1, ...]:
        names = tuple(item.field_name for item in fields)
        if len(set(names)) != len(names):
            raise ValueError("reconstructed fields must not repeat a name")
        if set(names) != set(REQUIRED_RECONSTRUCTION_FIELDS):
            raise ValueError("reconstruction requires exactly the five OHLCV fields")
        return tuple(sorted(fields, key=lambda item: item.field_name))

    @field_validator("acknowledged_limitations")
    @classmethod
    def canonicalize_limitations(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("reconstruction limitations must be unique")
        required = (
            ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
            ALPACA_LIMITATION_UNVERSIONED_BARS,
        )
        if not set(required).issubset(values):
            raise ValueError("reconstruction requires its retrospective limitations")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_reconstruction(self, info: ValidationInfo) -> Self:
        # Ordinary strict field and model validation has already executed.
        # Reuse only the pure canonical hash computation for an identical full
        # typed body. Return this newly parsed object, never a cached model.
        cache = _OBSERVATION_VALIDATION_REUSE.get()
        key: tuple[object, ...] | None = None
        cost = 0
        if (
            cache is not None
            and info.mode == "json"
            and info.context is None
            and type(self) is ExploratoryReconstructedSessionObservationV1
        ):
            exact = _exact_reconstruction_value(self)
            if exact is not None:
                key = (
                    type(self),
                    type(self).__pydantic_serializer__,
                    exploratory_reconstruction_hash,
                    content_hash,
                    exact[0],
                )
                cost = exact[1]
        cached = cache.entries.get(key) if cache is not None and key else None
        if cached is None:
            expected = exploratory_reconstruction_hash(self)
        else:
            expected = cached[0]
            assert cache is not None and key is not None
            cache.entries.move_to_end(key)
        if self.reconstruction_hash != expected:
            raise ValueError(
                f"reconstruction hash mismatch: expected {expected}, "
                f"got {self.reconstruction_hash}"
            )
        if cached is None and cache is not None and key is not None:
            cache.retain(key, expected, cost)
        return self


def exploratory_reconstruction_hash(
    observation: ExploratoryReconstructedSessionObservationV1,
) -> SHA256Hash:
    """Compute the canonical hash of an exploratory reconstructed observation."""
    dump = observation.model_dump(mode="python")
    dump.pop("reconstruction_hash", None)
    return content_hash(dump)


def cohort_required_limitations(
    cohort: ExploratoryCohortAuthorizationV1,
) -> tuple[NonBlankStr, ...]:
    """Return the limitation any exploratory run over this cohort must bind."""
    return (ALPACA_LIMITATION_BOUNDED_COHORT,)


def exploratory_required_limitations(
    observation: ExploratoryReconstructedSessionObservationV1,
) -> tuple[NonBlankStr, ...]:
    """Return the limitations the exploratory reconstruction always binds."""
    return observation.acknowledged_limitations


class ExploratoryCohortListingRoleV1(FrozenModel):
    """Exploratory-grade execution listing role derived from a predeclared cohort.

    Issue 77, Option A. Binds each cohort member's declared listing and venue
    as its execution listing for the duration of an exploratory run. It is
    NOT an M1b ListingRoleVersionV1, makes no claim of historical primary
    status or survivorship-free listing identity, and is refused by the
    promotion lane.
    """

    schema_version: Literal["1"] = "1"
    kind: Literal["exploratory_cohort_listing_role"] = "exploratory_cohort_listing_role"
    cohort_hash: SHA256Hash
    security_id: UUID7
    listing_id: UUID7
    venue: ListingVenue
    role: Literal["primary"] = "primary"
    acknowledged_limitations: tuple[NonBlankStr, ...] = (
        ALPACA_LIMITATION_COHORT_LISTING_ROLE,
    )
    record_hash: SHA256Hash

    @field_validator("acknowledged_limitations")
    @classmethod
    def validate_limitations(
        cls, values: tuple[NonBlankStr, ...]
    ) -> tuple[NonBlankStr, ...]:
        if ALPACA_LIMITATION_COHORT_LISTING_ROLE not in values:
            raise ValueError(
                "exploratory cohort listing role requires "
                f"'{ALPACA_LIMITATION_COHORT_LISTING_ROLE}'"
            )
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        expected = exploratory_cohort_listing_role_hash(self)
        if self.record_hash != expected:
            raise ValueError(
                f"exploratory cohort listing role hash mismatch: expected {expected}, "
                f"got {self.record_hash}"
            )
        return self


def exploratory_cohort_listing_role_hash(
    record: ExploratoryCohortListingRoleV1,
) -> SHA256Hash:
    """Compute canonical content hash for ExploratoryCohortListingRoleV1."""
    dump = record.model_dump(mode="python")
    dump.pop("record_hash", None)
    return content_hash(dump)


def build_exploratory_cohort_listing_role(
    *,
    cohort: ExploratoryCohortAuthorizationV1,
    security_id: UUID7,
    listing_id: UUID7,
    venue: ListingVenue,
) -> ExploratoryCohortListingRoleV1:
    """Mint one ExploratoryCohortListingRoleV1 bound to the cohort hash."""
    draft = ExploratoryCohortListingRoleV1.model_construct(
        schema_version="1",
        kind="exploratory_cohort_listing_role",
        cohort_hash=cohort.cohort_hash,
        security_id=security_id,
        listing_id=listing_id,
        venue=venue,
        role="primary",
        acknowledged_limitations=(ALPACA_LIMITATION_COHORT_LISTING_ROLE,),
        record_hash="0" * 64,
    )
    candidate = draft.model_copy(
        update={"record_hash": exploratory_cohort_listing_role_hash(draft)}
    )
    return ExploratoryCohortListingRoleV1.model_validate(candidate.model_dump())
