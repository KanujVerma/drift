"""Closed-world corporate-action coverage: stamping, verification and the rule.

Issue 76 (owner ruling, option A; decisions D1 to D9). This module is the one
seed of the dedicated ``m1c-corporate-action-coverage-v1`` closure (decision
D5-b), so its own bytes, and the record module it reads, are the identity
every ``ClosedWorldCorporateActionCoverageV1`` binds as ``implementation_hash``.
It is in no other closure: no M1c outcome, selection or projection, and no
M1d evidence, stales when this code changes.

* ``build_corporate_action_coverage`` is the only function that stamps the
  record's ``implementation_hash``. It also states the covered interval by the
  V1 rule (D2-a and its addition) and seals the record.
* ``verify_corporate_action_coverage`` re-validates a record through its own
  contract, requires the running identity (V10) and, given the retained
  artifacts, requires the response bytes and every bound artifact to be
  present and exact (V4). Every failure raises
  ``CorporateActionCoverageError`` with its code; none is downgraded.
* ``corporate_action_window_status`` is the derivation rule (section 3.3):
  over an inclusive window of local dates a security is
  ``evidenced_no_action``, ``actions_present`` or ``indeterminate``, and
  ``indeterminate`` never defaults to no action.
* ``native_outcome_covers_window`` is M1c-native coverage (section 3.4): the
  promotion-grade form, read from an outcome resolution whose three coverage
  results are complete over the whole action vocabulary.

Nothing here opens a connection or reads a provider format; re-parsing the
retained response bytes is the provider bridge's job (V5, V6).
"""

from collections.abc import Iterable, Mapping
from datetime import date
from hashlib import sha256
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError

from drift.domain.assertions import TemporalBoundaryClaimV1
from drift.domain.economic_closed_world import (
    CORPORATE_ACTION_COVERAGE_DOMAIN_CODES,
    CORPORATE_ACTION_SNAPSHOT_LIMITATION,
    ClosedWorldCorporateActionCoverageV1,
    CorporateActionCompletenessAssertionV1,
    ReturnedCorporateActionV1,
    corporate_action_covered_interval,
    corporate_action_derivation_algorithm_hash,
    corporate_action_record_hash,
)
from drift.domain.economic_common import ActionKind
from drift.domain.economic_queries import market_horizon
from drift.domain.economic_results import EconomicOutcomeResolutionV1
from drift.domain.semantic_attestation import (
    m1c_corporate_action_coverage_attestation_hash,
)
from drift.errors import DriftError

type CorporateActionWindowStatus = Literal[
    "evidenced_no_action", "actions_present", "indeterminate"
]

_NATIVE_FAMILIES = ("effect", "settlement", "terms")
_HIDING_REASONS = frozenset(
    {"source_revision_selection_unresolved", "economic_time_indeterminate"}
)
"""M1c outcome reasons either of which can hide an action (section 3.4, iv)."""


class CorporateActionCoverageError(DriftError, ValueError):
    """An integrity failure of corporate-action coverage, refused by its code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def _domain_code(error: ValidationError) -> str:
    text = str(error)
    for code in CORPORATE_ACTION_COVERAGE_DOMAIN_CODES:
        if code in text:
            return code
    return "ca_coverage_record_invalid"


def build_corporate_action_coverage(
    *,
    source_id: str,
    security_id: UUID,
    queried_symbol: str,
    requested_start_date: date,
    requested_end_date: date,
    requested_action_classes: tuple[str, ...],
    request_binding_hash: str,
    response_sha256: str,
    response_byte_size: int,
    origin_observation_hash: str,
    returned_actions: tuple[ReturnedCorporateActionV1, ...],
    completeness: CorporateActionCompletenessAssertionV1,
    snapshot_as_of: TemporalBoundaryClaimV1,
    acknowledged_limitations: tuple[str, ...] = (CORPORATE_ACTION_SNAPSHOT_LIMITATION,),
) -> ClosedWorldCorporateActionCoverageV1:
    """Stamp, state and seal one record; the only stamper of its identity.

    The covered interval is never taken from the caller: it is the requested
    interval clipped to the evidence floor and the snapshot date, or nothing.
    A value that fails the record's contract is refused with its code.
    """
    try:
        covered = (
            corporate_action_covered_interval(
                requested_start_date, requested_end_date, snapshot_as_of
            )
            if requested_start_date <= requested_end_date
            else None
        )
        body: dict[str, Any] = {
            "schema_version": "1",
            "source_id": source_id,
            "security_id": security_id,
            "queried_symbol": queried_symbol,
            "requested_start_date": requested_start_date,
            "requested_end_date": requested_end_date,
            "requested_action_classes": requested_action_classes,
            "request_binding_hash": request_binding_hash,
            "response_sha256": response_sha256,
            "response_byte_size": response_byte_size,
            "origin_observation_hash": origin_observation_hash,
            "returned_actions": returned_actions,
            "completeness": completeness,
            "covered_start_date": None if covered is None else covered[0],
            "covered_end_date": None if covered is None else covered[1],
            "snapshot_as_of": snapshot_as_of,
            "revision_support": "current_only",
            "evidence_grade": "exploratory",
            "acknowledged_limitations": acknowledged_limitations,
            "derivation_algorithm_hash": corporate_action_derivation_algorithm_hash(),
            "implementation_hash": m1c_corporate_action_coverage_attestation_hash(),
        }
        draft = ClosedWorldCorporateActionCoverageV1.model_construct(
            **(body | {"record_hash": "0" * 64})
        )
        return ClosedWorldCorporateActionCoverageV1.model_validate(
            body | {"record_hash": corporate_action_record_hash(draft)}
        )
    except ValidationError as error:
        raise CorporateActionCoverageError(
            _domain_code(error), "the record does not satisfy its contract"
        ) from error
    except ValueError as error:
        raise CorporateActionCoverageError(
            "ca_coverage_record_invalid", str(error)
        ) from error


def _revalidated(
    record: object,
) -> ClosedWorldCorporateActionCoverageV1:
    """Rebuild one record through its own contract, or refuse it by code."""
    if not isinstance(record, ClosedWorldCorporateActionCoverageV1):
        raise CorporateActionCoverageError(
            "ca_coverage_record_invalid",
            f"expected a ClosedWorldCorporateActionCoverageV1, got "
            f"{type(record).__name__}",
        )
    try:
        return ClosedWorldCorporateActionCoverageV1.model_validate(
            record.model_dump(mode="python", warnings=False)
        )
    except ValidationError as error:
        raise CorporateActionCoverageError(
            _domain_code(error), "the record does not revalidate"
        ) from error
    except (TypeError, ValueError) as error:
        raise CorporateActionCoverageError(
            "ca_coverage_record_invalid", "the record does not revalidate"
        ) from error


def _require_retained(
    support: Mapping[str, Any],
    digest: str,
    code: str,
    what: str,
    *,
    byte_size: int | None = None,
) -> None:
    artifact = support.get(digest)
    if artifact is None:
        raise CorporateActionCoverageError(code, f"the {what} {digest} is not retained")
    data = artifact.data
    if sha256(data).hexdigest() != digest or (
        byte_size is not None and len(data) != byte_size
    ):
        mismatch = (
            "ca_coverage_response_hash_mismatch"
            if code == "ca_coverage_response_bytes_unavailable"
            else code
        )
        raise CorporateActionCoverageError(
            mismatch, f"the retained {what} does not hash to {digest}"
        )


def verify_corporate_action_coverage(
    record: ClosedWorldCorporateActionCoverageV1,
    supporting_artifacts: Mapping[str, Any] | None = None,
) -> ClosedWorldCorporateActionCoverageV1:
    """Re-verify one record (V1 to V3, V7, V8 again, V10, and V4 when given).

    ``supporting_artifacts`` is a content-addressed mapping of retained bytes.
    Given it, the response bytes must be retained under the record's digest
    with its exact size, and the request declaration, the measured origin
    record and the completeness policy statement must be retained too.
    Returns the revalidated record.
    """
    checked = _revalidated(record)
    if checked.implementation_hash != m1c_corporate_action_coverage_attestation_hash():
        raise CorporateActionCoverageError(
            "ca_coverage_implementation_identity_mismatch",
            "the record was derived under an m1c-corporate-action-coverage-v1 "
            "identity other than the running one",
        )
    if supporting_artifacts is not None:
        _require_retained(
            supporting_artifacts,
            checked.response_sha256,
            "ca_coverage_response_bytes_unavailable",
            "corporate-action response",
            byte_size=checked.response_byte_size,
        )
        _require_retained(
            supporting_artifacts,
            checked.request_binding_hash,
            "ca_coverage_request_binding_mismatch",
            "request declaration",
        )
        _require_retained(
            supporting_artifacts,
            checked.origin_observation_hash,
            "ca_coverage_origin_unavailable",
            "measured origin record",
        )
        _require_retained(
            supporting_artifacts,
            checked.completeness.policy_statement_hash,
            "ca_coverage_policy_statement_unavailable",
            "closed-world policy statement",
        )
    return checked


# --- section 3.3: the derivation rule -------------------------------------------


def _in_window(action: ReturnedCorporateActionV1, start: date, end: date) -> bool:
    return any(start <= day <= end for day in action.dates)


def _covers(
    record: ClosedWorldCorporateActionCoverageV1, start: date, end: date
) -> bool:
    return (
        record.completeness.positive
        and record.covered_start_date is not None
        and record.covered_end_date is not None
        and record.covered_start_date <= start
        and end <= record.covered_end_date
    )


def _conflicts(
    first: ClosedWorldCorporateActionCoverageV1,
    second: ClosedWorldCorporateActionCoverageV1,
    start: date,
    end: date,
) -> bool:
    """V9: whether two records disagree on an overlap this window touches."""
    if (
        first.covered_start_date is None
        or first.covered_end_date is None
        or second.covered_start_date is None
        or second.covered_end_date is None
    ):
        return False
    low = max(first.covered_start_date, second.covered_start_date, start)
    high = min(first.covered_end_date, second.covered_end_date, end)
    if low > high:
        return False
    overlap_low = max(first.covered_start_date, second.covered_start_date)
    overlap_high = min(first.covered_end_date, second.covered_end_date)

    def projected(
        record: ClosedWorldCorporateActionCoverageV1,
    ) -> frozenset[ReturnedCorporateActionV1]:
        return frozenset(
            action
            for action in record.returned_actions
            if not action.dates or _in_window(action, overlap_low, overlap_high)
        )

    return projected(first) != projected(second)


def _candidates(
    records: Iterable[ClosedWorldCorporateActionCoverageV1], security_id: UUID
) -> tuple[ClosedWorldCorporateActionCoverageV1, ...] | None:
    """Every valid record of the security, or ``None`` if any record is invalid."""
    valid: list[ClosedWorldCorporateActionCoverageV1] = []
    for record in records:
        try:
            checked = _revalidated(record)
        except CorporateActionCoverageError:
            return None
        if checked.security_id == security_id:
            valid.append(checked)
    return tuple(valid)


def corporate_action_window_status(
    records: Iterable[ClosedWorldCorporateActionCoverageV1],
    security_id: UUID,
    start: date,
    end: date,
) -> CorporateActionWindowStatus:
    """Derive one security's corporate-action status over ``[start, end]``.

    ``start`` and ``end`` are inclusive local dates. The window is
    ``indeterminate`` when any record fails its own contract; when the
    security's records come from more than one source or grade; when two of
    its records disagree on an overlap the window touches (V9, never resolved
    by preference); when any of its returned actions carries no date, since an
    undated action can lie in any window; or when no single record with a
    positive assertion covers the whole window. Otherwise it is
    ``actions_present`` when any returned action has any date inside the
    window (D4-a), and ``evidenced_no_action`` only when none does. There is
    no default "no action".
    """
    first, last = (
        date.fromordinal(date.toordinal(start)),
        date.fromordinal(date.toordinal(end)),
    )
    if first > last:
        return "indeterminate"
    candidates = _candidates(records, security_id)
    if not candidates:
        return "indeterminate"
    if len({(item.source_id, item.evidence_grade) for item in candidates}) != 1:
        return "indeterminate"
    if any(
        _conflicts(one, other, first, last)
        for index, one in enumerate(candidates)
        for other in candidates[index + 1 :]
    ):
        return "indeterminate"
    actions = tuple(action for item in candidates for action in item.returned_actions)
    if any(not action.dates for action in actions):
        return "indeterminate"
    if not any(_covers(item, first, last) for item in candidates):
        return "indeterminate"
    if any(_in_window(action, first, last) for action in actions):
        return "actions_present"
    return "evidenced_no_action"


def window_returned_actions(
    records: Iterable[ClosedWorldCorporateActionCoverageV1],
    security_id: UUID,
    start: date,
    end: date,
) -> tuple[ReturnedCorporateActionV1, ...]:
    """Every distinct returned action of the security dated inside the window.

    For naming what halts a run; ordered by native kind, native id and dates.
    """
    found = {
        action
        for record in records
        if record.security_id == security_id
        for action in record.returned_actions
        if _in_window(action, start, end)
    }
    return tuple(
        sorted(
            found,
            key=lambda item: (
                item.native_kind,
                item.native_id,
                tuple(day.isoformat() for day in item.dates),
            ),
        )
    )


# --- section 3.4: M1c-native coverage -------------------------------------------


def native_outcome_covers_window(
    resolution: EconomicOutcomeResolutionV1, start: date, end: date
) -> bool:
    """Whether an M1c outcome resolution covers ``[start, end]`` closed-world.

    All four conditions of section 3.4 must hold: (i) exactly one coverage
    result for each of terms, effect and settlement, each ``complete``; (ii)
    the query asks for the whole action vocabulary, because coverage for
    splits is not coverage for spin-offs; (iii) the query's history start is
    before ``start`` and its horizon after ``end``, a one-day margin that
    absorbs the offset between UTC instants and local session dates; and (iv)
    no reason that can hide an action.
    """
    families = sorted(item.family for item in resolution.coverage_results)
    if families != list(_NATIVE_FAMILIES):
        return False
    if any(item.status != "complete" for item in resolution.coverage_results):
        return False
    query = resolution.query
    if set(query.action_kinds) != set(ActionKind):
        return False
    if not (query.history_start.date() < start and market_horizon(query).date() > end):
        return False
    return not _HIDING_REASONS & set(resolution.reasons)


def native_outcome_is_empty(resolution: EconomicOutcomeResolutionV1) -> bool:
    """Whether a resolution carries no effect or settlement evidence at all.

    Under M1c-native coverage (section 3.4) such an outcome is evidenced no
    action (C4), not unsupported evidence.
    """
    return not (
        resolution.effect_projections
        or resolution.delivery_groups
        or resolution.unknown_effect_hashes
        or resolution.uncomposed_settlement_hashes
    )
