"""Closed-world session coverage derivation, materialization and verification.

Issue 71 (ruling Q18 of #62, decisions D1 to D9). This module is a seed of the
``m1d-evidence-v1`` closure (D5-a): it derives M1d evidence from a
``ClosedWorldSessionCoverageV1`` and checks the record against the M1d context
it sits in, so its own bytes are part of the identity every record binds.

* ``evidenced_session_date_status`` is the derivation rule: a returned date is
  ``scheduled_open`` (schedule evidence only, never a realized open); a covered
  date that was not returned is ``evidenced_non_trading`` under a positive
  assertion; anything else, including a conflict between two records of one
  source, is ``indeterminate``. INDETERMINATE never defaults to closed.
* ``expand_closed_world_coverage`` is the D4-A materialization: one explicit
  ``state="closed"`` ``ScheduledSessionVersionV1`` per evidenced non-trading
  date, bound to the record's canonical bytes, so the existing supporting
  closure forces the record into every context that carries a row.
* ``verify_closed_world_session_coverage`` re-verifies every record a context
  carries (V4, V6, V8, V10 of the contract): its bound bytes are retained and
  hash to what it names, it was derived under the running M1d evidence
  identity, and the context's schedule rows over its covered interval are
  exactly its returned dates and exactly its expansion.

The plain M1d validators cannot tell a derived closed row from one a provider
printed, so the enforcement points that need a definite session answer call
the verifier: the Alpaca bridge at intake (R1) and the M2 reconstructed lane
(R7). Nothing here opens a connection or reads a provider format.
"""

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import ValidationError

from drift.datasets.hashing import assertion_version_payload, manifest_hash
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.assertions import (
    BoundaryShape,
    HistoryCompleteness,
    RevisionEnvelopeV1,
    TemporalBoundaryClaimV1,
)
from drift.domain.observation_query import m1d_implementation_hash
from drift.domain.revisions import RevisionKind
from drift.domain.session_closed_world import (
    CLOSED_WORLD_DOMAIN_CODES,
    CLOSED_WORLD_RECORD_KIND,
    ClosedWorldSessionCoverageV1,
)
from drift.domain.sessions import (
    ScheduledSessionVersionV1,
    SessionCoverageVersionV1,
    SessionKeyV1,
)
from drift.domain.temporal import (
    AvailabilityBasis,
    AvailabilityEvidenceV1,
    AvailabilityShape,
    SourcePrecision,
)
from drift.errors import DriftError
from drift.markets.observation_validation import M1dResolutionContext
from drift.serialization.canonical import canonical_json, content_hash

type ClosedWorldDateStatus = Literal[
    "scheduled_open", "evidenced_non_trading", "indeterminate"
]

_UUID_NAMESPACE = "drift.markets.session_closed_world.v1"
_OPEN_STATES = frozenset({"regular", "early_close"})


class ClosedWorldCoverageError(DriftError, ValueError):
    """An integrity failure of closed-world coverage, refused by its code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def closed_world_record_bytes(record: ClosedWorldSessionCoverageV1) -> bytes:
    """Return the exact canonical bytes every derived row is bound to."""
    return canonical_json(record)


def closed_world_record_digest(record: ClosedWorldSessionCoverageV1) -> str:
    """Return the content address of the record's canonical bytes."""
    return sha256(closed_world_record_bytes(record)).hexdigest()


def _dates(start: date, end: date) -> tuple[date, ...]:
    """Every calendar date from ``start`` through ``end``, inclusive."""
    first, last = date.toordinal(start), date.toordinal(end)
    return tuple(date.fromordinal(ordinal) for ordinal in range(first, last + 1))


def evidenced_closed_dates(
    record: ClosedWorldSessionCoverageV1,
) -> tuple[date, ...]:
    """The covered dates the record did not return, when its assertion holds."""
    if not record.completeness.positive:
        return ()
    returned = frozenset(record.returned_dates)
    return tuple(
        day
        for day in _dates(record.covered_start_date, record.covered_end_date)
        if day not in returned
    )


def _revalidated(
    records: Iterable[ClosedWorldSessionCoverageV1],
) -> tuple[ClosedWorldSessionCoverageV1, ...]:
    """Only records that validate through their own contract count."""
    valid: list[ClosedWorldSessionCoverageV1] = []
    for record in records:
        try:
            valid.append(
                ClosedWorldSessionCoverageV1.model_validate(
                    record.model_dump(mode="python", warnings=False)
                )
            )
        except TypeError, ValueError, ValidationError:
            continue
    return tuple(valid)


def evidenced_session_date_status(
    records: Iterable[ClosedWorldSessionCoverageV1],
    mic: str,
    local_date: date,
) -> ClosedWorldDateStatus:
    """Derive one regular-session date's status from closed-world coverage.

    Records are unioned only within one source, MIC and grade: records of two
    sources for one venue answer nothing. Where two records disagree on the
    date, one returning it and one evidencing it closed, the date is
    ``indeterminate``; a conflict is never resolved by preference.
    """
    day = date.fromordinal(date.toordinal(local_date))
    candidates = tuple(
        record
        for record in _revalidated(records)
        if record.mic == mic and record.session_scope == "regular"
    )
    if len({(item.source_id, item.evidence_grade) for item in candidates}) != 1:
        return "indeterminate"
    claims: set[ClosedWorldDateStatus] = set()
    for record in candidates:
        if day in record.returned_dates:
            claims.add("scheduled_open")
        elif day in evidenced_closed_dates(record):
            claims.add("evidenced_non_trading")
    if len(claims) != 1:
        return "indeterminate"
    return claims.pop()


def _derived_uuid7(*parts: str) -> UUID:
    """Derive a stable RFC 4122 version 7 identifier from exact inputs."""
    digest = sha256("\u0000".join((_UUID_NAMESPACE, *parts)).encode("utf-8")).digest()
    raw = bytearray(digest[:16])
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


def _reference(digest: str, seed: str) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=_derived_uuid7("artifact", seed, digest),
        kind=ArtifactKind.OTHER,
        content_hash=digest,
        location=f"drift+sha256://{digest}",
    )


def _closed_row(
    record: ClosedWorldSessionCoverageV1, digest: str, day: date
) -> ScheduledSessionVersionV1:
    instant = record.snapshot_as_of.upper_bound
    assert instant is not None
    seed = f"{record.source_id}:{record.mic}:{day.isoformat()}"
    availability = AvailabilityEvidenceV1(
        channel=record.availability_channel,
        shape=AvailabilityShape.EXACT,
        lower_bound=instant,
        upper_bound=instant,
        precision=SourcePrecision.SECOND,
        source_time_label=instant.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_timezone=None,
        basis=AvailabilityBasis.SOURCE_OBSERVED,
        evidence_reference=_reference(digest, f"{seed}:available"),
        rule_derivation=None,
    )
    revision = RevisionEnvelopeV1(
        schema_version="1",
        logical_record_id=_derived_uuid7("logical", seed),
        record_version_id=_derived_uuid7("version", seed, digest),
        revision_kind=RevisionKind.INITIAL,
        supersedes_record_version_id=None,
        source_sequence=0,
        availability=(availability,),
        history_completeness=HistoryCompleteness.UNKNOWN,
        source_native_revision_label=None,
        source_artifact=_reference(digest, f"{seed}:source"),
        payload_hash="0" * 64,
    )
    lower = datetime(day.year, day.month, day.day, tzinfo=UTC)
    values: dict[str, object] = {
        "schema_version": "1",
        "revision": revision,
        "source_id": record.source_id,
        "session_key": SessionKeyV1(
            mic=record.mic, session_scope="regular", local_date=day
        ),
        "source_temporal_evidence": TemporalBoundaryClaimV1(
            schema_version="1",
            shape=BoundaryShape.BOUNDED,
            lower_bound=lower,
            upper_bound=lower + timedelta(days=1),
            source_precision=SourcePrecision.INTERVAL,
            source_time_label=day.isoformat(),
            source_timezone=None,
            evidence_reference=_reference(digest, f"{seed}:temporal"),
        ),
        "state": "closed",
        "local_open": None,
        "local_close": None,
        "timezone_identifier": record.timezone_identifier,
        "open_fold": None,
        "close_fold": None,
        "historical_boundary_offsets": (),
        "source_methodology_hash": record.source_methodology_hash,
    }
    provisional = ScheduledSessionVersionV1.model_construct(
        _fields_set=None, **cast(Any, values)
    )
    values["revision"] = revision.model_copy(
        update={"payload_hash": content_hash(assertion_version_payload(provisional))}
    )
    return ScheduledSessionVersionV1.model_validate(values)


def expand_closed_world_coverage(
    record: ClosedWorldSessionCoverageV1,
) -> tuple[ScheduledSessionVersionV1, ...]:
    """Materialize every evidenced non-trading date as an explicit closed row.

    Each row carries the record's source, venue, scope, timezone and source
    methodology, no boundaries, folds or offsets, and names the record's
    canonical bytes as its source artifact, its temporal evidence and its
    availability evidence. It is available exactly at the acquisition instant.
    """
    digest = closed_world_record_digest(record)
    return tuple(
        _closed_row(record, digest, day) for day in evidenced_closed_dates(record)
    )


def _domain_code(error: ValidationError) -> str:
    text = str(error)
    for code in CLOSED_WORLD_DOMAIN_CODES:
        if code in text:
            return code
    return "closed_world_record_invalid"


def parse_closed_world_record(data: bytes) -> ClosedWorldSessionCoverageV1 | None:
    """Return the record these bytes claim to be, or ``None`` if they claim none.

    Bytes claim to be a record only by carrying its ``kind``. Once they do, any
    failure to be exactly one valid record in canonical form is an integrity
    failure, never a reason to ignore them.
    """
    try:
        document = json.loads(data)
    except ValueError:
        return None
    if not isinstance(document, dict) or document.get("kind") != (
        CLOSED_WORLD_RECORD_KIND
    ):
        return None
    try:
        record = ClosedWorldSessionCoverageV1.model_validate_json(data)
    except ValidationError as error:
        raise ClosedWorldCoverageError(
            _domain_code(error), "the retained bytes are not a valid record"
        ) from error
    if closed_world_record_bytes(record) != data:
        raise ClosedWorldCoverageError(
            "closed_world_record_hash_mismatch",
            "the retained bytes are not the record's canonical encoding",
        )
    return record


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
        raise ClosedWorldCoverageError(code, f"{what} {digest} is not retained")
    data = artifact.data
    if sha256(data).hexdigest() != digest or (
        byte_size is not None and len(data) != byte_size
    ):
        mismatch = (
            "closed_world_response_hash_mismatch"
            if code == "closed_world_response_bytes_unavailable"
            else code
        )
        raise ClosedWorldCoverageError(
            mismatch, f"the retained {what} does not hash to {digest}"
        )


def _verify_record(
    record: ClosedWorldSessionCoverageV1, support: Mapping[str, Any]
) -> None:
    """V4, the M1d half of V6, the bound statement and origin, and V10."""
    _require_retained(
        support,
        record.response_sha256,
        "closed_world_response_bytes_unavailable",
        "calendar response",
        byte_size=record.response_byte_size,
    )
    _require_retained(
        support,
        record.request_binding_hash,
        "closed_world_request_binding_mismatch",
        "request declaration",
    )
    _require_retained(
        support,
        record.origin_observation_hash,
        "closed_world_origin_unavailable",
        "measured origin record",
    )
    _require_retained(
        support,
        record.completeness.policy_statement_hash,
        "closed_world_policy_statement_unavailable",
        "closed-world policy statement",
    )
    if record.implementation_hash != m1d_implementation_hash():
        raise ClosedWorldCoverageError(
            "closed_world_implementation_identity_mismatch",
            "the record was derived under an M1d evidence identity other than "
            "the running one",
        )


def _mismatch(detail: str) -> ClosedWorldCoverageError:
    return ClosedWorldCoverageError("closed_world_expansion_mismatch", detail)


def _verify_coverage_binding(
    record: ClosedWorldSessionCoverageV1,
    coverage: SessionCoverageVersionV1,
    context: M1dResolutionContext,
) -> frozenset[str]:
    """V8: the coverage claim and its schedule rows are exactly the record's.

    Returns the content hashes of the closed rows this binding accounts for.
    """
    if (
        coverage.source_id != record.source_id
        or coverage.mic != record.mic
        or coverage.session_scope != record.session_scope
        or coverage.methodology_hash != record.source_methodology_hash
    ):
        raise _mismatch("the coverage row describes another source or venue")
    if (coverage.start_date, coverage.end_date) != (
        record.covered_start_date,
        record.covered_end_date,
    ):
        raise _mismatch(
            "the coverage row does not cover exactly the record's covered "
            f"interval {record.covered_start_date.isoformat()} to "
            f"{record.covered_end_date.isoformat()}"
        )
    by_manifest = {
        manifest_hash(item.manifest): item for item in context.session_datasets
    }
    targets = []
    for digest in coverage.covered_dataset_hashes:
        target = by_manifest.get(digest)
        if target is None:
            raise _mismatch(f"the covered schedule dataset {digest} is absent")
        targets.append(target)
    rows = tuple(
        row
        for target in targets
        for row in target.records
        if isinstance(row, ScheduledSessionVersionV1)
        and row.source_id == record.source_id
        and row.session_key.mic == record.mic
        and record.covered_start_date
        <= row.session_key.local_date
        <= record.covered_end_date
    )
    opened = tuple(
        sorted(row.session_key.local_date for row in rows if row.state in _OPEN_STATES)
    )
    if opened != record.returned_dates:
        raise _mismatch(
            "the open schedule rows over the covered interval are not exactly the "
            "returned dates"
        )
    for row in rows:
        if row.state in _OPEN_STATES and (
            row.timezone_identifier != record.timezone_identifier
            or row.source_methodology_hash != record.source_methodology_hash
        ):
            raise _mismatch(
                f"the open row on {row.session_key.local_date.isoformat()} does "
                "not share the record's timezone and methodology"
            )
    expected = tuple(
        sorted(content_hash(row) for row in expand_closed_world_coverage(record))
    )
    actual = tuple(
        sorted(content_hash(row) for row in rows if row.state not in _OPEN_STATES)
    )
    if actual != expected:
        raise _mismatch(
            "the closed schedule rows over the covered interval are not exactly "
            "the record's expansion"
        )
    return frozenset(expected)


def verify_closed_world_session_coverage(
    context: M1dResolutionContext,
) -> tuple[ClosedWorldSessionCoverageV1, ...]:
    """Re-verify every closed-world record an M1d context carries.

    A record is found wherever a session coverage row or a scheduled row names
    bytes that claim to be one. Each is checked against the retained artifacts
    and the running M1d evidence identity, every coverage row it backs must
    cover exactly its interval over exactly its returned dates and its
    expansion, and every scheduled row that names it must be one of the rows a
    coverage binding accounted for. Any failure raises
    ``ClosedWorldCoverageError`` with its code. Returns the verified records,
    ordered by record hash.
    """
    support = context.supporting_artifacts
    parsed: dict[str, ClosedWorldSessionCoverageV1 | None] = {}

    def claimed(digest: str, *, strict: bool) -> ClosedWorldSessionCoverageV1 | None:
        """The verified record ``digest`` names, if its bytes claim to be one.

        A coverage row's source bytes are read strictly: bytes that do not hash
        to their name cannot even say whether they claim to be a record, so
        they are refused. A schedule row's are read leniently, because an open
        row names the raw provider bytes, whose mapping the M1d context
        validator owns; a record that only such a row names is still held to
        the coverage bindings below.
        """
        if digest in parsed:
            return parsed[digest]
        artifact = support.get(digest)
        if artifact is None:
            return None
        if sha256(artifact.data).hexdigest() != digest:
            if not strict:
                return None
            raise ClosedWorldCoverageError(
                "closed_world_record_hash_mismatch",
                f"the retained bytes named {digest} do not hash to it",
            )
        record = parse_closed_world_record(artifact.data)
        if record is not None:
            _verify_record(record, support)
        parsed[digest] = record
        return record

    accounted: set[str] = set()
    for dataset in context.session_datasets:
        for row in dataset.records:
            if isinstance(row, SessionCoverageVersionV1):
                record = claimed(row.revision.source_artifact.content_hash, strict=True)
                if record is not None:
                    accounted.update(_verify_coverage_binding(record, row, context))
    bound_rows = tuple(
        row
        for dataset in context.session_datasets
        for row in dataset.records
        if isinstance(row, ScheduledSessionVersionV1)
        and claimed(row.revision.source_artifact.content_hash, strict=False) is not None
    )
    for row in bound_rows:
        if content_hash(row) not in accounted:
            raise _mismatch(
                f"the schedule row on {row.session_key.local_date.isoformat()} "
                "names a closed-world record no coverage row of this context "
                "expands to it"
            )
    records = {
        record.record_hash: record for record in parsed.values() if record is not None
    }
    return tuple(records[key] for key in sorted(records))
