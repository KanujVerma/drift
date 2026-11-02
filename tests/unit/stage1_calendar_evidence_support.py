"""Test-only, reproducible XNYS-style closed-world evidence for G2.

No provider call is made at test time; all original calendar readings must be
stored as frozen fixture bytes and bound to an observed artifact/source claim.
No fixture evidence grants historical source qualification or trading rights.
"""

import json
from dataclasses import replace
from datetime import date, datetime, time
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from observation_test_support import ObservationHarness
from session_test_support import (
    coverage_record,
    exact_boundary,
    public_channel,
    schedule_record,
    session_dataset,
)

from drift.datasets.hashing import assertion_version_payload, manifest_hash
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.observation_query import (
    ObservationSourceSelectionPolicyV1,
    m1d_implementation_hash,
)
from drift.domain.session_closed_world import (
    ClosedWorldCompletenessAssertionV1,
    closed_world_derivation_algorithm_hash,
    seal_closed_world_session_coverage,
)
from drift.domain.sessions import ScheduledSessionVersionV1
from drift.markets.observation_validation import (
    M1dResolutionContext,
    validate_m1d_resolution_context,
)
from drift.markets.session_closed_world import (
    closed_world_record_bytes,
    expand_closed_world_coverage,
    verify_closed_world_session_coverage,
)
from drift.serialization.canonical import canonical_json, content_hash


def _artifact(payload: bytes) -> VerifiedArtifactBytes:
    digest = sha256(payload).hexdigest()
    return VerifiedArtifactBytes(
        data=payload, byte_size=len(payload), content_hash=digest
    )


FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures/stage1/xnys_461_normalized_calendar_v1.json"
)
FIXTURE_SHA256 = "3e6b7d911cf22cb0782858836bb002f9c87338b767f3a0b677e165d02bba16b7"


def pinned_source_calendar() -> tuple[tuple[date, ...], dict[date, str], bytes]:
    """Read one archived normalized connector response, never query the network."""
    raw = FIXTURE_PATH.read_bytes()
    assert sha256(raw).hexdigest() == FIXTURE_SHA256
    document = json.loads(raw)
    assert document["kind"] == "drift-stage1-normalized-calendar-fixture"
    assert document["normalized_result_fnv64"] == "aac013f21d5a422f"
    assert document["request_start"] == "2024-01-02"
    assert document["request_end"] == "2025-10-31"
    rows = document["rows"]
    assert len(rows) == 461
    linewise = "\n".join(f"{r['date']},{r['open']},{r['close']}" for r in rows)
    check = 0xCBF29CE484222325
    for byte in linewise.encode():
        check = ((check ^ byte) * 0x100000001B3) & ((1 << 64) - 1)
    assert f"{check:016x}" == document["normalized_result_fnv64"]
    days = tuple(date.fromisoformat(row["date"]) for row in rows)
    assert days == tuple(sorted(set(days)))
    assert days[455] == date(2025, 10, 24)
    assert date(2025, 1, 9) not in days
    assert all(row["open"] == "09:30" for row in rows)
    early = {
        date.fromisoformat(row["date"]): row["close"]
        for row in rows
        if row["close"] != "16:00"
    }
    assert early == {
        date(2024, 7, 3): "13:00",
        date(2024, 11, 29): "13:00",
        date(2024, 12, 24): "13:00",
        date(2025, 7, 3): "13:00",
    }
    return days, early, raw


def attach_pinned_calendar(harness: ObservationHarness) -> M1dResolutionContext:
    """Replace one isolated test context's single-date calendar with full scope.

    The first row is retained unchanged so its original source reconstruction
    still uses identical request/response semantics. A real provider-normalized
    fixture and independently regenerated session dates are checked separately.
    """
    context = harness.context
    days, early_closes, response = pinned_source_calendar()
    scheduled = next(
        x
        for x in context.session_datasets
        if x.manifest.dataset_role.name == "scheduled_session"
    )
    first = scheduled.records[0]
    assert isinstance(first, ScheduledSessionVersionV1)
    assert first.session_key.local_date == days[0]
    assert first.state == "regular"
    assert first.session_key.mic == "XNYS"
    support = dict(context.supporting_artifacts)
    retained = dict(context.retained_evidence)
    identity = canonical_json(
        {
            "source": "Alpaca get_calendar normalized offline fixture",
            "start": days[0].isoformat(),
            "end": days[-1].isoformat(),
            "kind": "synthetic-fixture-derived-normalized-calendar",
            "source_grade": "exploratory_only",
        }
    )
    origin = canonical_json(
        {
            "kind": "synthetic-source-observation",
            "response_sha256": sha256(response).hexdigest(),
            "capture_utc_date": "2026-10-28",
            "raw_http_bytes_available": False,
            "grade": "exploratory",
        }
    )
    statement = canonical_json(
        {
            "source": (
                "Alpaca get_calendar normalized structured response; "
                "exchange_calendars 4.13.1 cross-check"
            ),
            "kind": "synthetic-exploratory-test-source-policy",
            "scope": (
                "no original HTTP-byte provenance or historical availability claimed"
            ),
            "complete": "461 distinct sessions in one bounded structured result",
        }
    )
    for raw in (response, identity, origin, statement):
        item = _artifact(raw)
        support[item.content_hash] = item
    assertion = ClosedWorldCompletenessAssertionV1(
        basis="provider_partially_published",
        policy_statement_hash=sha256(statement).hexdigest(),
        acquisition_reconciliation_pass=True,
        returned_dates_unique=True,
        returned_dates_inside_requested_interval=True,
        single_unpaginated_response=True,
        measured_origin=True,
    )
    coverage = seal_closed_world_session_coverage(
        {
            "source_id": first.source_id,
            "mic": "XNYS",
            "session_scope": "regular",
            "requested_start_date": days[0],
            "requested_end_date": days[-1],
            "request_binding_hash": sha256(identity).hexdigest(),
            "response_sha256": sha256(response).hexdigest(),
            "response_byte_size": len(response),
            "origin_observation_hash": sha256(origin).hexdigest(),
            "returned_dates": days,
            "completeness": assertion,
            "covered_start_date": days[0],
            "covered_end_date": days[-1],
            "snapshot_as_of": exact_boundary(5),
            "timezone_identifier": first.timezone_identifier,
            "source_methodology_hash": first.source_methodology_hash,
            "availability_channel": public_channel(),
            "evidence_grade": "exploratory",
            "derivation_algorithm_hash": closed_world_derivation_algorithm_hash(),
            "implementation_hash": m1d_implementation_hash(),
        }
    )
    blob = _artifact(closed_world_record_bytes(coverage))
    support[blob.content_hash] = blob
    zone = ZoneInfo("America/New_York")
    opens = [first]
    for index, day in enumerate(days[1:], start=1):
        utc_offset = datetime.combine(day, time(9, 30), tzinfo=zone).utcoffset()
        assert utc_offset is not None
        offset = int(utc_offset.total_seconds())
        opens.append(
            schedule_record(
                day,
                "early_close" if day in early_closes else "regular",
                first.source_methodology_hash,
                support,
                retained,
                suffix=18000 + index * 20,
                offset_seconds=offset,
                local_close_time=early_closes.get(day),
            )
        )
    closed = expand_closed_world_coverage(coverage)
    all_scheduled = session_dataset(
        "scheduled_session",
        tuple(
            sorted(
                [*opens, *closed], key=lambda row: str(row.revision.logical_record_id)
            )
        ),
        support,
    )
    base = coverage_record(all_scheduled, first.source_methodology_hash)
    data = base.model_dump(mode="python")
    data["revision"]["source_artifact"]["content_hash"] = blob.content_hash
    data["revision"]["source_artifact"]["location"] = (
        f"drift+sha256://{blob.content_hash}"
    )
    data["revision"]["payload_hash"] = "0" * 64
    provisional = type(base).model_construct(**data)
    data["revision"]["payload_hash"] = content_hash(
        assertion_version_payload(provisional)
    )
    sealed = type(base).model_validate(data)
    covered = session_dataset("session_coverage", (sealed,), support)
    policy_artifact = support[harness._source_policy_hash]
    policy = ObservationSourceSelectionPolicyV1.model_validate_json(
        policy_artifact.data
    )
    modified = tuple(
        binding.model_copy(
            update={
                "manifest_hashes": (
                    manifest_hash(all_scheduled.manifest)
                    if binding.dataset_role == "scheduled_session"
                    else manifest_hash(covered.manifest),
                ),
            }
        )
        if binding.dataset_role in {"scheduled_session", "session_coverage"}
        else binding
        for binding in policy.bindings
    )
    new_policy = policy.model_copy(update={"bindings": modified})
    policy_bytes = canonical_json(new_policy)
    new_policy_artifact = _artifact(policy_bytes)
    support[new_policy_artifact.content_hash] = new_policy_artifact
    with_calendar = replace(
        context,
        session_datasets=(all_scheduled, covered),
        supporting_artifacts=support,
        retained_evidence=retained,
    )
    validate_m1d_resolution_context(with_calendar)
    records = verify_closed_world_session_coverage(with_calendar)
    assert records == (coverage,), records
    harness.context = with_calendar
    harness._source_policy_hash = new_policy_artifact.content_hash
    harness._current_bindings = new_policy.bindings
    return with_calendar
