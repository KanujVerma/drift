"""Structural controls for fictional, explicitly associated venue sessions.

The source identities and proof hashes below are synthetic. A valid shape and
hash alone do not authenticate a source or admit a clock to the evaluator.
"""

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
import session_test_support
from test_session_closed_world import record as synthetic_coverage

import drift.domain.evaluator_clock as clock_contract
import drift.domain.observation_query as observation_query
from drift.datasets.hashing import assertion_version_payload
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_ABSENT_HALTS,
    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
)
from drift.domain.securities import ListingVenue
from drift.domain.sessions import SessionKeyV1
from drift.evaluator.clock import (
    _session_from_authority,
    build_scheduled_reconstruction_clock,
)
from drift.markets.observation_selection import select_observation_records
from drift.markets.observation_validation import m1d_context_hash
from drift.serialization.canonical import canonical_json, content_hash


def _member(
    mic: str,
    day: date,
    opened: datetime,
    closed: datetime,
    *,
    authority: str = "scheduled_reconstruction",
) -> dict[str, Any]:
    session = _session_from_authority(
        session_key=SessionKeyV1(mic=mic, session_scope="regular", local_date=day),
        opened_at=opened,
        closed_at=closed,
        authority=authority,
        record_hashes=("1" * 64,),
        proof_hashes=("2" * 64,),
    )
    return {
        "schema_version": "1",
        "session": session,
        "resolution_context_hash": "3" * 64,
        "selection_query_hash": ("4" if mic == "ARCX" else "5") * 64,
        "source_policy_hash": "6" * 64,
        "availability_evidence_hash": "7" * 64,
        "first_available_at": opened - timedelta(days=1),
    }


def _body(day: date, opened: datetime, closed: datetime) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "local_date": day,
        "opened_at": opened,
        "closed_at": closed,
        "authority": "scheduled_reconstruction",
        "expected_venues": ("ARCX", "XNAS"),
        "members": (
            _member("ARCX", day, opened, closed),
            _member("XNAS", day, opened, closed),
        ),
    }


def _association(body: dict[str, Any]) -> Any:
    association_type = getattr(clock_contract, "CommonSessionAssociationV1", None)
    assert association_type is not None, "common session association is not implemented"
    return association_type.model_validate(
        body | {"association_hash": content_hash(body)}
    )


def test_arcx_is_a_distinct_listing_venue() -> None:
    assert "ARCX" in {venue.value for venue in ListingVenue}
    assert ListingVenue("ARCX") != ListingVenue.XNAS


@pytest.mark.parametrize(
    ("day", "opened", "closed"),
    [
        (
            date(2023, 7, 3),
            datetime(2023, 7, 3, 13, 30, tzinfo=UTC),
            datetime(2023, 7, 3, 17, tzinfo=UTC),
        ),
        (
            date(2023, 11, 24),
            datetime(2023, 11, 24, 14, 30, tzinfo=UTC),
            datetime(2023, 11, 24, 18, tzinfo=UTC),
        ),
    ],
)
def test_aligned_synthetic_venue_members_form_one_association(
    day: date, opened: datetime, closed: datetime
) -> None:
    group = _association(_body(day, opened, closed))
    assert group.local_date == day
    assert (group.opened_at, group.closed_at) == (opened, closed)
    assert tuple(member.session.session_key.mic for member in group.members) == (
        "ARCX",
        "XNAS",
    )
    assert not hasattr(group, "mic")


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "extra",
        "wrong_date",
        "wrong_open",
        "wrong_close",
        "wrong_authority",
        "late_availability",
        "missing_availability",
    ],
)
def test_association_refuses_missing_conflicting_or_late_member(mutation: str) -> None:
    day = date(2023, 7, 3)
    opened = datetime(2023, 7, 3, 13, 30, tzinfo=UTC)
    closed = datetime(2023, 7, 3, 17, tzinfo=UTC)
    body = _body(day, opened, closed)
    a, b = body["members"]
    if mutation == "missing":
        body["members"] = (a,)
    elif mutation == "duplicate":
        body["members"] = (a, a)
    elif mutation == "extra":
        body["members"] = (a, b, _member("XNYS", day, opened, closed))
    elif mutation == "wrong_date":
        other = day + timedelta(days=1)
        body["members"] = (
            a,
            _member(
                "XNAS", other, opened + timedelta(days=1), closed + timedelta(days=1)
            ),
        )
    elif mutation == "wrong_open":
        body["members"] = (
            a,
            _member("XNAS", day, opened + timedelta(minutes=1), closed),
        )
    elif mutation == "wrong_close":
        body["members"] = (
            a,
            _member("XNAS", day, opened, closed + timedelta(minutes=1)),
        )
    elif mutation == "wrong_authority":
        body["members"] = (
            a,
            _member("XNAS", day, opened, closed, authority="realized"),
        )
    elif mutation == "late_availability":
        body["members"] = (a, b | {"first_available_at": closed + timedelta(seconds=1)})
    else:
        body["members"] = (a, b | {"availability_evidence_hash": None})
    with pytest.raises(ValueError):
        _association(body)


def _clock_body() -> dict[str, Any]:
    july3 = _association(
        _body(
            date(2023, 7, 3),
            datetime(2023, 7, 3, 13, 30, tzinfo=UTC),
            datetime(2023, 7, 3, 17, 0, tzinfo=UTC),
        )
    )
    july5 = _association(
        _body(
            date(2023, 7, 5),
            datetime(2023, 7, 5, 13, 30, tzinfo=UTC),
            datetime(2023, 7, 5, 20, 0, tzinfo=UTC),
        )
    )
    return {
        "schema_version": "1",
        "mode": "scheduled_session_reconstruction",
        "window_start": date(2023, 7, 3),
        "window_end": date(2023, 7, 5),
        "expected_venues": ("ARCX", "XNAS"),
        "expected_session_dates": (date(2023, 7, 3), date(2023, 7, 5)),
        "sessions": (july3, july5),
        "acknowledged_limitations": tuple(
            sorted(
                (
                    ALPACA_LIMITATION_ABSENT_HALTS,
                    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
                )
            )
        ),
    }


def _common_clock(body: dict[str, Any]) -> Any:
    clock_type = getattr(clock_contract, "CommonSessionClockV1", None)
    assert clock_type is not None, "common session clock is not implemented"
    return clock_type.model_validate(body | {"clock_hash": content_hash(body)})


def test_common_clock_has_one_step_per_expected_synthetic_date() -> None:
    clock = _common_clock(_clock_body())
    assert tuple(item.local_date for item in clock.sessions) == (
        date(2023, 7, 3),
        date(2023, 7, 5),
    )
    assert all(len(item.members) == 2 for item in clock.sessions)
    assert not hasattr(clock.sessions[0], "session_key")


@pytest.mark.parametrize(
    "mutation",
    [
        "omitted_date",
        "duplicate_date",
        "reverse",
        "wrong_venues",
        "outside_window",
        "wrong_mode",
        "missing_limitations",
    ],
)
def test_common_clock_refuses_inconsistent_frozen_inventory(mutation: str) -> None:
    body = _clock_body()
    first, second = body["sessions"]
    if mutation == "omitted_date":
        body["sessions"] = (first,)
    elif mutation == "duplicate_date":
        body["sessions"] = (first, first)
    elif mutation == "reverse":
        body["sessions"] = (second, first)
    elif mutation == "wrong_venues":
        body["expected_venues"] = ("ARCX", "XNYS")
    elif mutation == "outside_window":
        body["window_end"] = date(2023, 7, 4)
    elif mutation == "wrong_mode":
        body["mode"] = "realized_session_authority"
    else:
        body["acknowledged_limitations"] = ()
    with pytest.raises(ValueError):
        _common_clock(body)


def test_midnight_labels_match_for_distinct_equivalent_timezone_bytes() -> None:
    from drift.adapters.alpaca_exploratory import _diagnostic_midnight_labels

    data = session_test_support.timezone_bytes()
    changed = data.replace(b"EST", b"XYZ")
    assert data != changed
    dates = (date(2026, 1, 5), date(2026, 7, 6))
    assert _diagnostic_midnight_labels(dates, data) == _diagnostic_midnight_labels(
        dates, changed
    )


def _replay_inventory() -> Any:
    """Build synthetic query declarations; no source authority is asserted."""
    _, prototype, _ = session_test_support.generation_case()
    clock_body = _clock_body()
    requests = []
    groups = []
    for group in clock_body["sessions"]:
        members = []
        for member in group.members:
            query = prototype.model_copy(
                update={
                    "venue": ListingVenue(member.session.session_key.mic),
                    "session_date": group.local_date,
                    "decision_time": group.closed_at,
                    "knowledge_cutoff": group.closed_at,
                    "effective_cutoff": group.closed_at,
                }
            )
            values = member.model_dump(mode="python") | {
                "resolution_context_hash": query.input_context_hash,
                "selection_query_hash": content_hash(query),
                "source_policy_hash": query.source_selection_policy_hash,
            }
            members.append(clock_contract.CommonVenueSessionV1.model_validate(values))
            requests.append(query)
        group_body = group.model_dump(mode="python", exclude={"association_hash"})
        group_body["members"] = tuple(members)
        groups.append(_association(group_body))
    clock_body["sessions"] = tuple(groups)
    return _common_clock(clock_body), tuple(requests)


def test_replay_inventory_requires_each_member_exactly_once() -> None:
    from drift.evaluator.clock import require_common_replay_inventory

    clock, queries = _replay_inventory()
    assert require_common_replay_inventory(clock, queries) == queries


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "foreign"])
def test_replay_inventory_refuses_missing_duplicate_and_foreign_queries(
    mutation: str,
) -> None:
    from drift.evaluator.clock import require_common_replay_inventory

    clock, queries = _replay_inventory()
    if mutation == "missing":
        changed = queries[:-1]
    elif mutation == "duplicate":
        changed = (*queries, queries[0])
    else:
        changed = (*queries, queries[0].model_copy(update={"profile_hash": "9" * 64}))
    with pytest.raises(ValueError, match="replay inventory"):
        require_common_replay_inventory(clock, changed)


@pytest.mark.parametrize(
    "mutation", ["venue", "date", "context", "policy", "decision_time"]
)
def test_replay_inventory_refuses_rehashed_member_mismatch(mutation: str) -> None:
    from drift.evaluator.clock import require_common_replay_inventory

    clock, queries = _replay_inventory()
    query = queries[0]
    changes = {
        "venue": {"venue": ListingVenue.XNYS},
        "date": {"session_date": query.session_date + timedelta(days=1)},
        "context": {"input_context_hash": "a" * 64},
        "policy": {"source_selection_policy_hash": "b" * 64},
        "decision_time": {"decision_time": query.decision_time + timedelta(seconds=1)},
    }
    modified = query.model_copy(update=changes[mutation])
    first_group = clock.sessions[0]
    first_member = first_group.members[0]
    member_values = first_member.model_dump(mode="python") | {
        "selection_query_hash": content_hash(modified),
    }
    group_values = first_group.model_dump(mode="python", exclude={"association_hash"})
    group_values["members"] = (
        clock_contract.CommonVenueSessionV1.model_validate(member_values),
        *first_group.members[1:],
    )
    clock_values = clock.model_dump(mode="python", exclude={"clock_hash"})
    clock_values["sessions"] = (_association(group_values), *clock.sessions[1:])
    changed_clock = _common_clock(clock_values)
    with pytest.raises(ValueError, match="replay inventory"):
        require_common_replay_inventory(changed_clock, (modified, *queries[1:]))


def _synthetic_member_with_m1d_replay(venue: ListingVenue = ListingVenue.XNYS) -> Any:
    """Build real M1d-selected evidence from a fictional single-venue source."""
    close = datetime(2026, 1, 5, 21, tzinfo=UTC)
    if venue is ListingVenue.XNYS:
        context, query, policy = session_test_support.generation_case(
            knowledge_cutoff=close
        )
    else:
        # The existing builder is XNYS-only. Change its fictional source rows
        # and policy together, then let the unmodified M1d builders validate.
        original_schedule = session_test_support.schedule_record
        original_coverage = session_test_support.coverage_record
        original_boundary = session_test_support.boundary_authority_payload
        original_binding = observation_query.ObservationSourceBindingV1

        def reseal(record: Any, updates: Any) -> Any:
            values = {key: getattr(record, key) for key in type(record).model_fields}
            values.update(updates)
            draft = type(record).model_construct(**values)
            revision = draft.revision.model_copy(
                update={"payload_hash": content_hash(assertion_version_payload(draft))}
            )
            values["revision"] = revision
            return type(draft).model_validate(values)

        def schedule(*args: Any, **kwargs: Any) -> Any:
            original = original_schedule(*args, **kwargs)
            key = original.session_key.model_copy(update={"mic": venue.value})
            return reseal(original, {"session_key": key})

        def coverage(*args: Any, **kwargs: Any) -> Any:
            return reseal(original_coverage(*args, **kwargs), {"mic": venue.value})

        def binding(*args: Any, **kwargs: Any) -> Any:
            return original_binding(*args, **(kwargs | {"venue": venue}))

        def boundary(*args: Any, **kwargs: Any) -> Any:
            return original_boundary(*args, **kwargs) | {"mic": venue.value}

        with pytest.MonkeyPatch.context() as patcher:
            patcher.setattr(session_test_support, "schedule_record", schedule)
            patcher.setattr(session_test_support, "coverage_record", coverage)
            patcher.setattr(
                session_test_support, "boundary_authority_payload", boundary
            )
            patcher.setattr(observation_query, "ObservationSourceBindingV1", binding)
            context, query, policy = session_test_support.generation_case(
                knowledge_cutoff=close
            )
        query = query.model_copy(update={"venue": venue})
    policy_bytes = canonical_json(policy)
    policy_hash = sha256(policy_bytes).hexdigest()
    support = dict(context.supporting_artifacts)
    support[policy_hash] = VerifiedArtifactBytes(
        data=policy_bytes, byte_size=len(policy_bytes), content_hash=policy_hash
    )
    context = replace(
        context,
        supporting_artifacts=support,
        schedule_generation_policy_hash=policy_hash,
    )
    query = query.model_copy(
        update={
            "decision_time": close,
            "effective_cutoff": close,
            "input_context_hash": m1d_context_hash(context),
        }
    )
    selected = select_observation_records(query, "scheduled_session", context)
    session = build_scheduled_reconstruction_clock((query,), context).sessions[0]
    decision = selected.proof.availability_decisions[0]
    assert decision.evidence.upper_bound is not None
    member = clock_contract.CommonVenueSessionV1(
        session=session,
        resolution_context_hash=query.input_context_hash,
        selection_query_hash=content_hash(query),
        source_policy_hash=query.source_selection_policy_hash,
        availability_evidence_hash=decision.evidence_hash,
        first_available_at=decision.evidence.upper_bound,
    )
    return member, query, context


def test_member_replay_rederives_synthetic_m1d_evidence() -> None:
    from drift.evaluator.clock import replay_common_venue_session

    member, query, context = _synthetic_member_with_m1d_replay()
    assert replay_common_venue_session(member, query, context) == member.session


@pytest.mark.parametrize("venue", [ListingVenue.ARCX, ListingVenue.XNAS])
def test_member_replay_preserves_synthetic_source_venue(venue: ListingVenue) -> None:
    from drift.evaluator.clock import replay_common_venue_session

    member, query, context = _synthetic_member_with_m1d_replay(venue)
    result = replay_common_venue_session(member, query, context)
    assert result.session_key.mic == venue.value


def _synthetic_pair_with_m1d_replay() -> Any:
    items = tuple(
        _synthetic_member_with_m1d_replay(venue)
        for venue in (ListingVenue.ARCX, ListingVenue.XNAS)
    )
    members = tuple(item[0] for item in items)
    session = members[0].session
    group = _association(
        {
            "schema_version": "1",
            "local_date": session.session_key.local_date,
            "opened_at": session.opened_at,
            "closed_at": session.closed_at,
            "authority": "scheduled_reconstruction",
            "expected_venues": ("ARCX", "XNAS"),
            "members": members,
        }
    )
    body = {
        "schema_version": "1",
        "mode": "scheduled_session_reconstruction",
        "window_start": group.local_date,
        "window_end": group.local_date,
        "expected_venues": group.expected_venues,
        "expected_session_dates": (group.local_date,),
        "sessions": (group,),
        "acknowledged_limitations": tuple(
            sorted(
                (
                    ALPACA_LIMITATION_ABSENT_HALTS,
                    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
                )
            )
        ),
    }
    return _common_clock(body), tuple((item[1], item[2]) for item in items)


def test_associated_synthetic_sources_replay_both_original_venue_sessions() -> None:
    from drift.evaluator.clock import replay_common_session_members

    clock, requests = _synthetic_pair_with_m1d_replay()
    sessions = replay_common_session_members(clock, requests)
    assert tuple(item.session_key.mic for item in sessions) == ("ARCX", "XNAS")
    assert sessions == tuple(member.session for member in clock.sessions[0].members)


@pytest.mark.parametrize("mutation", ["missing", "swapped_contexts", "duplicate"])
def test_associated_replay_refuses_missing_or_swapped_sources(mutation: str) -> None:
    from drift.evaluator.clock import replay_common_session_members

    clock, requests = _synthetic_pair_with_m1d_replay()
    if mutation == "missing":
        changed = requests[:1]
    elif mutation == "duplicate":
        changed = (*requests, requests[0])
    else:
        changed = ((requests[0][0], requests[1][1]), (requests[1][0], requests[0][1]))
    with pytest.raises(ValueError):
        replay_common_session_members(clock, changed)


def _paired_coverage(clock: Any) -> Any:
    day = clock.sessions[0].local_date
    snapshot = session_test_support.exact_boundary(5)
    return tuple(
        synthetic_coverage(
            mic=venue,
            source_id="calendar-source",
            requested_start_date=day,
            requested_end_date=day,
            returned_dates=(day,),
            snapshot_as_of=snapshot,
            response_sha256=digest * 64,
            request_binding_hash=digest * 64,
            origin_observation_hash=digest * 64,
            availability_channel=session_test_support.public_channel(),
        )
        for venue, digest in (("ARCX", "a"), ("XNAS", "b"))
    )


def test_common_replay_combines_member_proofs_and_venue_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The coverage verifier is stubbed; source bytes remain synthetic."""
    import drift.evaluator.clock as clock_module

    clock, requests = _synthetic_pair_with_m1d_replay()
    coverage = _paired_coverage(clock)
    by_context = {
        m1d_context_hash(context): (record,)
        for (_, context), record in zip(requests, coverage, strict=True)
    }
    monkeypatch.setattr(
        clock_module,
        "verify_closed_world_session_coverage",
        lambda context: by_context[m1d_context_hash(context)],
    )
    monkeypatch.setattr(
        clock_module, "_coverage_binds_selected_session", lambda *args: True
    )
    authority = {
        query.venue.value: (query.source_selection_policy_hash, "calendar-source")
        for query, _ in requests
    }
    assert clock_module.verify_common_clock_replay(
        clock, requests, authority, _stub_verifiers()
    ) == tuple(member.session for member in clock.sessions[0].members)


def test_common_replay_refuses_an_interval_outside_source_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import drift.evaluator.clock as clock_module

    clock, requests = _synthetic_pair_with_m1d_replay()
    values = clock.model_dump(mode="python", exclude={"clock_hash"})
    values["window_end"] = clock.window_end + timedelta(days=1)
    clock = _common_clock(values)
    coverage = _paired_coverage(clock)
    by_context = {
        m1d_context_hash(context): (record,)
        for (_, context), record in zip(requests, coverage, strict=True)
    }
    monkeypatch.setattr(
        clock_module,
        "verify_closed_world_session_coverage",
        lambda context: by_context[m1d_context_hash(context)],
    )
    monkeypatch.setattr(
        clock_module, "_coverage_binds_selected_session", lambda *args: True
    )
    monkeypatch.setattr(
        clock_module, "require_common_interval_inventory", lambda *args: None
    )
    authority = {
        query.venue.value: (query.source_selection_policy_hash, "calendar-source")
        for query, _ in requests
    }
    with pytest.raises(ValueError, match="policy"):
        clock_module.verify_common_clock_replay(
            clock, requests, authority, _stub_verifiers()
        )


@pytest.mark.parametrize(
    "mutation",
    ["foreign_authority", "foreign_coverage", "late_snapshot", "unselected_coverage"],
)
def test_common_replay_refuses_untrusted_or_late_coverage(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    import drift.evaluator.clock as clock_module

    clock, requests = _synthetic_pair_with_m1d_replay()
    coverage = list(_paired_coverage(clock))
    authority = {
        query.venue.value: (query.source_selection_policy_hash, "calendar-source")
        for query, _ in requests
    }
    if mutation == "foreign_authority":
        authority["ARCX"] = ("f" * 64, "calendar-source")
    elif mutation == "foreign_coverage":
        body = coverage[0].model_dump(mode="python", exclude={"record_hash"})
        body["source_id"] = "foreign-source"
        from drift.domain.session_closed_world import seal_closed_world_session_coverage

        coverage[0] = seal_closed_world_session_coverage(body)
    elif mutation == "late_snapshot":
        day = clock.sessions[0].local_date
        coverage[0] = synthetic_coverage(
            mic="ARCX",
            source_id="calendar-source",
            requested_start_date=day,
            requested_end_date=day,
            returned_dates=(day,),
            response_sha256="a" * 64,
            availability_channel=session_test_support.public_channel(),
        )
    by_context = {
        m1d_context_hash(context): (record,)
        for (_, context), record in zip(requests, coverage, strict=True)
    }
    monkeypatch.setattr(
        clock_module,
        "verify_closed_world_session_coverage",
        lambda context: by_context[m1d_context_hash(context)],
    )
    monkeypatch.setattr(
        clock_module, "_coverage_binds_selected_session", lambda *args: True
    )
    if mutation == "unselected_coverage":
        from types import SimpleNamespace

        original_select = select_observation_records

        def select(query: Any, purpose: Any, context: Any) -> Any:
            if purpose == "session_coverage":
                return SimpleNamespace(
                    records=(), proof=SimpleNamespace(classification="absent")
                )
            return original_select(query, purpose, context)

        monkeypatch.setattr(clock_module, "select_observation_records", select)
    with pytest.raises(ValueError):
        clock_module.verify_common_clock_replay(
            clock, requests, authority, _stub_verifiers()
        )


@pytest.mark.parametrize("mutation", ["partial", "late_snapshot"])
def test_common_replay_rejects_selected_partial_coverage(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    from types import SimpleNamespace

    import drift.evaluator.clock as clock_module

    clock, requests = _synthetic_pair_with_m1d_replay()
    coverage = _paired_coverage(clock)
    by_context = {
        m1d_context_hash(context): (record,)
        for (_, context), record in zip(requests, coverage, strict=True)
    }
    monkeypatch.setattr(
        clock_module,
        "verify_closed_world_session_coverage",
        lambda context: by_context[m1d_context_hash(context)],
    )
    monkeypatch.setattr(
        clock_module, "_coverage_binds_selected_session", lambda *args: True
    )
    original_select = select_observation_records

    def select(query: Any, purpose: Any, context: Any) -> Any:
        result = original_select(query, purpose, context)
        if purpose != "session_coverage":
            return result
        row: Any = result.records[0]
        values = {key: getattr(row, key) for key in type(row).model_fields}
        if mutation == "partial":
            values["status"] = "partial"
        else:
            values["snapshot_as_of"] = session_test_support.exact_boundary(6)
        provisional = type(row).model_construct(**values)
        values["revision"] = row.revision.model_copy(
            update={
                "payload_hash": content_hash(assertion_version_payload(provisional))
            }
        )
        return SimpleNamespace(
            records=(type(row).model_validate(values),), proof=result.proof
        )

    monkeypatch.setattr(clock_module, "select_observation_records", select)
    authority = {
        query.venue.value: (query.source_selection_policy_hash, "calendar-source")
        for query, _ in requests
    }
    with pytest.raises(ValueError, match="coverage"):
        clock_module.verify_common_clock_replay(
            clock, requests, authority, _stub_verifiers()
        )


def test_coverage_binding_joins_the_selected_session_dataset(tmp_path: Path) -> None:
    from test_alpaca_exploratory_adapter import run_pinned_intake

    from drift.evaluator.clock import _coverage_binds_selected_session
    from drift.markets.session_closed_world import verify_closed_world_session_coverage

    intake = run_pinned_intake(tmp_path)
    query = intake.outcome_queries[0]
    selected = select_observation_records(query, "scheduled_session", intake.context)
    selected_coverage = select_observation_records(
        query, "session_coverage", intake.context
    )
    assert len(selected.records) == 1
    assert len(selected_coverage.records) == 1
    coverage = verify_closed_world_session_coverage(intake.context)
    assert coverage == (intake.closed_world_coverage,)
    assert _coverage_binds_selected_session(
        coverage[0],
        content_hash(selected_coverage.records[0]),
        content_hash(selected.records[0]),
        intake.context,
    )
    assert not _coverage_binds_selected_session(
        coverage[0],
        content_hash(selected_coverage.records[0]),
        "0" * 64,
        intake.context,
    )
    assert not _coverage_binds_selected_session(
        coverage[0], "0" * 64, content_hash(selected.records[0]), intake.context
    )
    assert not _coverage_binds_selected_session(
        synthetic_coverage(),
        content_hash(selected_coverage.records[0]),
        content_hash(selected.records[0]),
        intake.context,
    )


@pytest.mark.parametrize(
    "mutation", ["context", "query", "policy", "availability", "time", "session"]
)
def test_member_replay_rejects_rehashed_or_forged_binding(mutation: str) -> None:
    from drift.evaluator.clock import replay_common_venue_session

    member, query, context = _synthetic_member_with_m1d_replay()
    values = member.model_dump(mode="python")
    if mutation == "context":
        values["resolution_context_hash"] = "a" * 64
    elif mutation == "query":
        values["selection_query_hash"] = "b" * 64
    elif mutation == "policy":
        values["source_policy_hash"] = "c" * 64
    elif mutation == "availability":
        values["availability_evidence_hash"] = "d" * 64
    elif mutation == "time":
        values["first_available_at"] = member.first_available_at + timedelta(seconds=1)
    else:
        old = member.session
        values["session"] = _session_from_authority(
            session_key=old.session_key,
            opened_at=old.opened_at,
            closed_at=old.closed_at - timedelta(minutes=1),
            authority=old.authority,
            record_hashes=old.authority_record_hashes,
            proof_hashes=old.authority_proof_hashes,
        )
    changed = clock_contract.CommonVenueSessionV1.model_validate(values)
    with pytest.raises(ValueError):
        replay_common_venue_session(changed, query, context)


def _synthetic_interval_records() -> Any:
    dates = (date(2023, 7, 3), date(2023, 7, 5))
    return tuple(
        synthetic_coverage(
            mic=mic,
            source_id=f"synthetic-{mic}",
            requested_start_date=dates[0],
            requested_end_date=dates[-1],
            returned_dates=dates,
            response_sha256=digest * 64,
            request_binding_hash=digest * 64,
            origin_observation_hash=digest * 64,
        )
        for mic, digest in (("ARCX", "a"), ("XNAS", "b"))
    )


def test_venue_interval_inventory_covers_holiday_for_both_venues() -> None:
    from drift.evaluator.clock import require_common_interval_inventory

    require_common_interval_inventory(
        _common_clock(_clock_body()), _synthetic_interval_records()
    )


def test_identical_calendar_bytes_can_have_distinct_venue_requests() -> None:
    """Byte equality alone neither proves nor disproves venue authority."""
    from drift.evaluator.clock import require_common_interval_inventory

    original = _synthetic_interval_records()
    other = synthetic_coverage(
        mic="XNAS",
        source_id="synthetic-XNAS",
        requested_start_date=date(2023, 7, 3),
        requested_end_date=date(2023, 7, 5),
        returned_dates=(date(2023, 7, 3), date(2023, 7, 5)),
        response_sha256=original[0].response_sha256,
        request_binding_hash="e" * 64,
        origin_observation_hash="f" * 64,
    )
    require_common_interval_inventory(
        _common_clock(_clock_body()), (original[0], other)
    )


@pytest.mark.parametrize(
    "rows",
    [
        (
            (date(2023, 11, 22), 14, 30, 21),
            (date(2023, 11, 24), 14, 30, 18),
            (date(2023, 11, 27), 14, 30, 21),
        ),
        (
            (date(2023, 3, 10), 14, 30, 21),
            (date(2023, 3, 13), 13, 30, 20),
        ),
    ],
)
def test_synthetic_interval_keeps_early_close_holiday_and_dst_boundaries(
    rows: Any,
) -> None:
    from drift.evaluator.clock import require_common_interval_inventory

    days = tuple(row[0] for row in rows)
    groups = tuple(
        _association(
            _body(
                day,
                datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC),
                datetime(day.year, day.month, day.day, close, tzinfo=UTC),
            )
        )
        for day, hour, minute, close in rows
    )
    body = _clock_body()
    body.update(
        window_start=days[0],
        window_end=days[-1],
        expected_session_dates=days,
        sessions=groups,
    )
    records = tuple(
        synthetic_coverage(
            mic=mic,
            source_id=f"synthetic-{mic}",
            requested_start_date=days[0],
            requested_end_date=days[-1],
            returned_dates=days,
            response_sha256=digest * 64,
            request_binding_hash=digest * 64,
            origin_observation_hash=digest * 64,
        )
        for mic, digest in (("ARCX", "a"), ("XNAS", "b"))
    )
    require_common_interval_inventory(_common_clock(body), records)


def test_interval_refuses_an_omitted_terminal_month_end() -> None:
    from drift.evaluator.clock import require_common_interval_inventory

    days = (date(2023, 1, 30), date(2023, 1, 31))
    group = _association(
        _body(
            days[0],
            datetime(2023, 1, 30, 14, 30, tzinfo=UTC),
            datetime(2023, 1, 30, 21, tzinfo=UTC),
        )
    )
    body = _clock_body()
    body.update(
        window_start=days[0],
        window_end=days[-1],
        expected_session_dates=(days[0],),
        sessions=(group,),
    )
    records = tuple(
        synthetic_coverage(
            mic=mic,
            source_id=f"synthetic-{mic}",
            requested_start_date=days[0],
            requested_end_date=days[-1],
            returned_dates=days,
            response_sha256=digest * 64,
            request_binding_hash=digest * 64,
            origin_observation_hash=digest * 64,
        )
        for mic, digest in (("ARCX", "a"), ("XNAS", "b"))
    )
    with pytest.raises(ValueError, match="common interval"):
        require_common_interval_inventory(_common_clock(body), records)


@pytest.mark.parametrize(
    "mutation",
    ["missing_venue", "missing_end", "joint_omission", "conflict", "reused_request"],
)
def test_venue_interval_inventory_refuses_unproven_dates(mutation: str) -> None:
    from drift.evaluator.clock import require_common_interval_inventory

    body = _clock_body()
    records = _synthetic_interval_records()
    if mutation == "missing_venue":
        records = records[:1]
    elif mutation == "missing_end":
        body["window_end"] = date(2023, 7, 6)
    elif mutation == "joint_omission":
        # Both calendars report July 4 open, but the proposed clock omits it.
        records = tuple(
            synthetic_coverage(
                mic=record.mic,
                source_id=record.source_id,
                requested_start_date=date(2023, 7, 3),
                requested_end_date=date(2023, 7, 5),
                returned_dates=(date(2023, 7, 3), date(2023, 7, 4), date(2023, 7, 5)),
                request_binding_hash=record.request_binding_hash,
                origin_observation_hash=record.origin_observation_hash,
            )
            for record in records
        )
    elif mutation == "reused_request":
        records = (
            records[0],
            synthetic_coverage(
                mic="XNAS",
                source_id="synthetic-XNAS",
                requested_start_date=date(2023, 7, 3),
                requested_end_date=date(2023, 7, 5),
                returned_dates=(date(2023, 7, 3), date(2023, 7, 5)),
                response_sha256="b" * 64,
                request_binding_hash=records[0].request_binding_hash,
                origin_observation_hash="b" * 64,
            ),
        )
    else:
        records = (
            records[0],
            synthetic_coverage(
                mic="XNAS",
                source_id="synthetic-XNAS",
                requested_start_date=date(2023, 7, 3),
                requested_end_date=date(2023, 7, 5),
                returned_dates=(date(2023, 7, 3), date(2023, 7, 4), date(2023, 7, 5)),
            ),
        )
    with pytest.raises(ValueError, match="common interval"):
        require_common_interval_inventory(_common_clock(body), records)


def _attach_synthetic_closed_world(
    member: Any, query: Any, context: Any, *, contradict_response: bool = False
) -> Any:
    """Add fictional retained calendar evidence through actual M1d datasets."""
    from drift.datasets.hashing import manifest_hash
    from drift.domain.session_closed_world import seal_closed_world_session_coverage
    from drift.domain.sessions import ScheduledSessionVersionV1
    from drift.markets.session_closed_world import closed_world_record_bytes

    support = dict(context.supporting_artifacts)

    def retain(data: bytes) -> str:
        digest = sha256(data).hexdigest()
        support[digest] = VerifiedArtifactBytes(
            data=data, byte_size=len(data), content_hash=digest
        )
        return digest

    def rebind(row: Any, digest: str, **updates: Any) -> Any:
        values = {key: getattr(row, key) for key in type(row).model_fields}
        values.update(updates)
        revision = row.revision.model_copy(
            update={"source_artifact": session_test_support.reference(998, digest)}
        )
        values["revision"] = revision
        provisional = type(row).model_construct(**values)
        values["revision"] = revision.model_copy(
            update={
                "payload_hash": content_hash(assertion_version_payload(provisional))
            }
        )
        return type(row).model_validate(values)

    day = query.session_date
    raw_hash = retain(
        canonical_json(
            {
                "mic": query.venue.value,
                "dates": [] if contradict_response else [day.isoformat()],
            }
        )
    )
    request_hash = retain(
        canonical_json(
            {"mic": query.venue.value, "start": day.isoformat(), "end": day.isoformat()}
        )
    )
    origin_hash = retain(
        canonical_json({"request_sha256": request_hash, "response_sha256": raw_hash})
    )
    statement_hash = retain(f"fictional policy: {query.venue.value}".encode())
    source_row = next(
        row
        for dataset in context.session_datasets
        for row in dataset.records
        if isinstance(row, ScheduledSessionVersionV1)
    )
    source_row = rebind(source_row, raw_hash)
    schedule = session_test_support.session_dataset(
        "scheduled_session", (source_row,), support
    )
    base = synthetic_coverage()
    snapshot = session_test_support.exact_boundary(5)
    values = base.model_dump(mode="python", exclude={"record_hash"}) | {
        "source_id": source_row.source_id,
        "mic": query.venue.value,
        "requested_start_date": day,
        "requested_end_date": day,
        "request_binding_hash": request_hash,
        "response_sha256": raw_hash,
        "response_byte_size": len(support[raw_hash].data),
        "origin_observation_hash": origin_hash,
        "returned_dates": (day,),
        "covered_start_date": day,
        "covered_end_date": day,
        "snapshot_as_of": snapshot,
        "timezone_identifier": source_row.timezone_identifier,
        "source_methodology_hash": source_row.source_methodology_hash,
        "availability_channel": query.requested_channel,
        "completeness": base.completeness.model_copy(
            update={"policy_statement_hash": statement_hash}
        ),
    }
    closed = seal_closed_world_session_coverage(values)
    closed_hash = retain(closed_world_record_bytes(closed))
    coverage_row = session_test_support.coverage_record(
        schedule, source_row.source_methodology_hash, start_date=day, end_date=day
    )
    coverage_row = rebind(coverage_row, closed_hash, mic=query.venue.value)
    coverage_dataset = session_test_support.session_dataset(
        "session_coverage", (coverage_row,), support
    )
    source_policy = (
        observation_query.ObservationSourceSelectionPolicyV1.model_validate_json(
            support[query.source_selection_policy_hash].data
        )
    )
    bindings = tuple(
        binding.model_copy(
            update={
                "manifest_hashes": (
                    manifest_hash(
                        schedule.manifest
                        if binding.dataset_role == "scheduled_session"
                        else coverage_dataset.manifest
                    ),
                )
            }
        )
        for binding in source_policy.bindings
    )
    source_policy = source_policy.model_copy(update={"bindings": bindings})
    source_policy_hash = retain(canonical_json(source_policy))
    context = replace(
        context,
        session_datasets=(schedule, coverage_dataset),
        supporting_artifacts=support,
    )
    query = query.model_copy(
        update={
            "source_selection_policy_hash": source_policy_hash,
            "input_context_hash": m1d_context_hash(context),
        }
    )
    selected = select_observation_records(query, "scheduled_session", context)
    session = build_scheduled_reconstruction_clock((query,), context).sessions[0]
    availability = selected.proof.availability_decisions[0]
    assert availability.evidence.upper_bound is not None
    member = clock_contract.CommonVenueSessionV1(
        session=session,
        resolution_context_hash=query.input_context_hash,
        selection_query_hash=content_hash(query),
        source_policy_hash=source_policy_hash,
        availability_evidence_hash=availability.evidence_hash,
        first_available_at=availability.evidence.upper_bound,
    )
    return member, query, context


def _verify_fictional_calendar(coverage: Any, context: Any) -> None:
    """Synthetic source contract, never an Alpaca or venue authentication."""
    raw = json.loads(context.supporting_artifacts[coverage.response_sha256].data)
    request = json.loads(
        context.supporting_artifacts[coverage.request_binding_hash].data
    )
    origin = json.loads(
        context.supporting_artifacts[coverage.origin_observation_hash].data
    )
    if raw != {
        "mic": coverage.mic,
        "dates": [day.isoformat() for day in coverage.returned_dates],
    }:
        raise ValueError("synthetic source response does not match its dates")
    if request != {
        "mic": coverage.mic,
        "start": coverage.requested_start_date.isoformat(),
        "end": coverage.requested_end_date.isoformat(),
    }:
        raise ValueError("synthetic source request mismatch")
    if origin != {
        "request_sha256": coverage.request_binding_hash,
        "response_sha256": coverage.response_sha256,
    }:
        raise ValueError("synthetic source origin mismatch")


def _fictional_verifiers() -> Any:
    return {venue: _verify_fictional_calendar for venue in ("ARCX", "XNAS")}


def _stub_verifiers() -> Any:
    return {venue: lambda *_args: None for venue in ("ARCX", "XNAS")}


def test_common_clock_replays_two_unmocked_synthetic_venue_contexts() -> None:
    from drift.evaluator.clock import verify_common_clock_replay

    items = tuple(
        _attach_synthetic_closed_world(*_synthetic_member_with_m1d_replay(venue))
        for venue in (ListingVenue.ARCX, ListingVenue.XNAS)
    )
    members = tuple(item[0] for item in items)
    session = members[0].session
    body = {
        "schema_version": "1",
        "local_date": session.session_key.local_date,
        "opened_at": session.opened_at,
        "closed_at": session.closed_at,
        "authority": "scheduled_reconstruction",
        "expected_venues": ("ARCX", "XNAS"),
        "members": members,
    }
    group = _association(body)
    clock = _common_clock(
        {
            "schema_version": "1",
            "mode": "scheduled_session_reconstruction",
            "window_start": group.local_date,
            "window_end": group.local_date,
            "expected_venues": group.expected_venues,
            "expected_session_dates": (group.local_date,),
            "sessions": (group,),
            "acknowledged_limitations": tuple(
                sorted(
                    (
                        ALPACA_LIMITATION_ABSENT_HALTS,
                        ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
                    )
                )
            ),
        }
    )
    requests = tuple((query, context) for _, query, context in items)
    authority = {
        query.venue.value: (query.source_selection_policy_hash, "calendar-source")
        for query, _ in requests
    }
    assert verify_common_clock_replay(
        clock, requests, authority, _fictional_verifiers()
    ) == tuple(member.session for member in members)


def _twelve_synthetic_fixture(*, contradict_response: bool = False) -> Any:
    import json

    from drift.adapters.alpaca_exploratory import (
        AlpacaCohortMember,
        AlpacaDiagnosticBarPage,
        AlpacaMixedVenueDiagnosticInput,
    )

    items = tuple(
        _attach_synthetic_closed_world(
            *_synthetic_member_with_m1d_replay(venue),
            contradict_response=contradict_response and venue is ListingVenue.ARCX,
        )
        for venue in (ListingVenue.ARCX, ListingVenue.XNAS)
    )
    members = tuple(item[0] for item in items)
    session = members[0].session
    group = _association(
        {
            "schema_version": "1",
            "local_date": session.session_key.local_date,
            "opened_at": session.opened_at,
            "closed_at": session.closed_at,
            "authority": "scheduled_reconstruction",
            "expected_venues": ("ARCX", "XNAS"),
            "members": members,
        }
    )
    clock = _common_clock(
        {
            "schema_version": "1",
            "mode": "scheduled_session_reconstruction",
            "window_start": group.local_date,
            "window_end": group.local_date,
            "expected_venues": group.expected_venues,
            "expected_session_dates": (group.local_date,),
            "sessions": (group,),
            "acknowledged_limitations": tuple(
                sorted(
                    (
                        ALPACA_LIMITATION_ABSENT_HALTS,
                        ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
                    )
                )
            ),
        }
    )
    requests = tuple((query, context) for _, query, context in items)
    authority = {
        query.venue.value: (query.source_selection_policy_hash, "calendar-source")
        for query, _ in requests
    }
    nasdaq = {"QQQ", "SHY", "IEF", "TLT"}
    symbols = (
        "VOO",
        "IJH",
        "IJR",
        "QQQ",
        "VEA",
        "VWO",
        "SHY",
        "IEF",
        "TLT",
        "TIP",
        "LQD",
        "GLD",
    )
    stamp = datetime(2026, 1, 5, 5, tzinfo=UTC)
    inputs = []
    for index, symbol in enumerate(symbols):
        venue = ListingVenue.XNAS if symbol in nasdaq else ListingVenue.ARCX
        member = AlpacaCohortMember(
            symbol,
            session_test_support.uid(1100 + index),
            session_test_support.uid(1200 + index),
            venue,
        )
        parameters = {
            "symbols": symbol,
            "start": "2026-01-05",
            "end": "2026-01-05",
            "feed": "sip",
            "adjustment": "raw",
            "timeframe": "1Day",
            "asof": "-",
            "currency": "USD",
            "sort": "asc",
            "limit": "1000",
        }
        bar = {
            "t": stamp.isoformat(),
            "o": "100",
            "h": "101",
            "l": "99",
            "c": "100",
            "v": 1000,
            "n": 50,
        }
        page = AlpacaDiagnosticBarPage(
            None,
            json.dumps({"bars": {symbol: [bar]}, "next_page_token": None}).encode(),
        )
        inputs.append(
            AlpacaMixedVenueDiagnosticInput(
                member, parameters, (page,), {group.local_date: stamp}
            )
        )
    return clock, requests, authority, tuple(inputs)


def test_twelve_synthetic_symbols_prepare_against_one_common_clock() -> None:
    from drift.adapters.alpaca_exploratory import prepare_alpaca_mixed_venue_diagnostics

    clock, requests, authority, inputs = _twelve_synthetic_fixture()
    result = prepare_alpaca_mixed_venue_diagnostics(
        clock,
        requests,
        authority,
        inputs,
        _fictional_verifiers(),
        timezone_identifier="Synthetic/Eastern",
        trusted_timezone_tzif=session_test_support.timezone_bytes(),
    )
    symbols = (
        "VOO",
        "IJH",
        "IJR",
        "QQQ",
        "VEA",
        "VWO",
        "SHY",
        "IEF",
        "TLT",
        "TIP",
        "LQD",
        "GLD",
    )
    assert {item.member.symbol for item in result.windows} == set(symbols)
    assert result.clock_hash == clock.clock_hash
    assert result.listing_identity_status == "UNVERIFIED"
    assert result.snapshot_status == "SNAPSHOT_UNVERIFIED"
    assert result.grade == "diagnostic"
    assert all(len(item.bars) == 1 for item in result.windows)


def test_common_replay_refuses_fictional_source_bytes_that_contradict_dates() -> None:
    from drift.adapters.alpaca_exploratory import prepare_alpaca_mixed_venue_diagnostics

    clock, requests, authority, inputs = _twelve_synthetic_fixture(
        contradict_response=True
    )
    with pytest.raises(ValueError, match="response does not match"):
        prepare_alpaca_mixed_venue_diagnostics(
            clock,
            requests,
            authority,
            inputs,
            _fictional_verifiers(),
            timezone_identifier="Synthetic/Eastern",
            trusted_timezone_tzif=session_test_support.timezone_bytes(),
        )


def test_common_replay_refuses_missing_source_specific_verifiers() -> None:
    from drift.adapters.alpaca_exploratory import prepare_alpaca_mixed_venue_diagnostics

    clock, requests, authority, inputs = _twelve_synthetic_fixture()
    with pytest.raises(ValueError, match="source-specific verifier"):
        prepare_alpaca_mixed_venue_diagnostics(clock, requests, authority, inputs)


@pytest.mark.parametrize("kind", ["false", "async"])
def test_common_replay_rejects_nonconforming_source_verifiers(kind: str) -> None:
    from drift.evaluator.clock import verify_common_clock_replay

    clock, requests, authority, _inputs = _twelve_synthetic_fixture(
        contradict_response=True
    )

    async def async_verifier(*_args: Any) -> None:
        raise AssertionError("an async verifier must not be accepted")

    def false_verifier(*_args: Any) -> bool:
        return False

    verifier: Any = async_verifier if kind == "async" else false_verifier
    with pytest.raises(ValueError, match="verifier"):
        verify_common_clock_replay(
            clock, requests, authority, {"ARCX": verifier, "XNAS": verifier}
        )


def test_mixed_diagnostics_rejects_two_agreeing_foreign_timezone_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from struct import pack
    from types import SimpleNamespace

    import drift.evaluator.clock as clock_module
    import drift.markets.session_generation as generation
    from drift.adapters.alpaca_exploratory import prepare_alpaca_mixed_venue_diagnostics

    clock, requests, authority, inputs = _twelve_synthetic_fixture()
    trusted = session_test_support.timezone_bytes()
    altered = trusted.replace(pack(">lbb", -18_000, 0, 0), pack(">lbb", -10_800, 0, 0))
    assert altered != trusted
    monkeypatch.setattr(clock_module, "verify_common_clock_replay", lambda *_args: ())
    monkeypatch.setattr(
        generation,
        "_load_timezone_input",
        lambda *_args: (
            SimpleNamespace(timezone_identifier="Synthetic/Eastern"),
            altered,
        ),
    )
    changed = []
    for item in inputs:
        payload = json.loads(item.pages[0].body)
        payload["bars"][item.member.symbol][0]["t"] = "2026-01-05T03:00:00Z"
        page = type(item.pages[0])(None, json.dumps(payload).encode())
        changed.append(
            replace(
                item,
                pages=(page,),
                expected_timestamps={
                    clock.window_start: datetime(2026, 1, 5, 3, tzinfo=UTC)
                },
            )
        )
    with pytest.raises(ValueError, match="timezone"):
        prepare_alpaca_mixed_venue_diagnostics(
            clock,
            requests,
            authority,
            tuple(changed),
            _fictional_verifiers(),
            timezone_identifier="Synthetic/Eastern",
            trusted_timezone_tzif=trusted,
        )


def test_mixed_diagnostics_accepts_equivalent_configured_timezone_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    import drift.evaluator.clock as clock_module
    import drift.markets.session_generation as generation
    from drift.adapters.alpaca_exploratory import prepare_alpaca_mixed_venue_diagnostics

    clock, requests, authority, inputs = _twelve_synthetic_fixture()
    trusted = session_test_support.timezone_bytes()
    equivalent = trusted.replace(b"EST", b"XYZ")
    assert trusted != equivalent
    monkeypatch.setattr(clock_module, "verify_common_clock_replay", lambda *_args: ())
    monkeypatch.setattr(
        generation,
        "_load_timezone_input",
        lambda *_args: (
            SimpleNamespace(timezone_identifier="Synthetic/Eastern"),
            equivalent,
        ),
    )
    result = prepare_alpaca_mixed_venue_diagnostics(
        clock,
        requests,
        authority,
        inputs,
        _fictional_verifiers(),
        timezone_identifier="Synthetic/Eastern",
        trusted_timezone_tzif=trusted,
    )
    assert result.grade == "diagnostic"


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_symbol",
        "duplicate_symbol",
        "duplicate_security",
        "foreign_venue",
        "wrong_parameters",
        "missing_clock_proof",
        "wrong_clock_source",
        "single_venue",
        "matched_wrong_label",
    ],
)
def test_twelve_symbol_diagnostics_reject_incomplete_or_foreign_inputs(
    mutation: str,
) -> None:
    from drift.adapters.alpaca_exploratory import prepare_alpaca_mixed_venue_diagnostics

    clock, requests, authority, original = _twelve_synthetic_fixture()
    inputs = list(original)
    if mutation == "missing_symbol":
        inputs.pop()
    elif mutation == "duplicate_symbol":
        inputs[1] = replace(
            inputs[1], member=replace(inputs[1].member, symbol=inputs[0].member.symbol)
        )
    elif mutation == "duplicate_security":
        inputs[1] = replace(
            inputs[1],
            member=replace(inputs[1].member, security_id=inputs[0].member.security_id),
        )
    elif mutation == "foreign_venue":
        inputs[1] = replace(
            inputs[1], member=replace(inputs[1].member, venue=ListingVenue.XNYS)
        )
    elif mutation == "wrong_parameters":
        inputs[0] = replace(
            inputs[0], parameters=dict(inputs[0].parameters) | {"symbols": "QQQ"}
        )
    elif mutation == "missing_clock_proof":
        requests = requests[:1]
    elif mutation == "single_venue":
        inputs = [
            replace(item, member=replace(item.member, venue=ListingVenue.ARCX))
            for item in inputs
        ]
    elif mutation == "matched_wrong_label":
        changed = []
        for item in inputs:
            payload = json.loads(item.pages[0].body)
            wrong = "2026-01-05T21:00:00+00:00"
            payload["bars"][item.member.symbol][0]["t"] = wrong
            page = type(item.pages[0])(None, json.dumps(payload).encode())
            changed.append(
                replace(
                    item,
                    pages=(page,),
                    expected_timestamps={
                        clock.window_start: datetime(2026, 1, 5, 21, tzinfo=UTC)
                    },
                )
            )
        inputs = changed
    else:
        authority = dict(authority) | {"ARCX": ("f" * 64, "calendar-source")}
    with pytest.raises(ValueError):
        prepare_alpaca_mixed_venue_diagnostics(
            clock,
            requests,
            authority,
            tuple(inputs),
            _fictional_verifiers(),
            timezone_identifier="Synthetic/Eastern",
            trusted_timezone_tzif=session_test_support.timezone_bytes(),
        )
