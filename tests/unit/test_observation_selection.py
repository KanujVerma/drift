"""Behavioral tests for finite M1d source-record selection."""

from datetime import date

import pytest
from observation_test_support import ObservationHarness
from session_test_support import generation_case, instant

from drift.domain.observations import DailySourceObservationVersionV1
from drift.serialization.canonical import content_hash


def test_correction_does_not_rewrite_prior_selection() -> None:
    from drift.markets.observation_selection import (
        select_observation_records,
        verify_observation_selection,
    )

    h = ObservationHarness()
    old = h.decision(
        "2026-01-05T22:00:00Z",
        "2026-01-05T22:00:00Z",
        "2026-01-05T22:00:00Z",
        "2026-01-05",
    )
    original_context = h.context
    before = select_observation_records(old, "observation", original_context)
    h.replace_source_revision(close="99.500", available_at="2026-01-08T00:00:00Z")
    expanded = h.decision(
        "2026-01-05T22:00:00Z",
        "2026-01-05T22:00:00Z",
        "2026-01-05T22:00:00Z",
        "2026-01-05",
    )
    after = select_observation_records(expanded, "observation", h.context)

    assert before.records == after.records
    assert old.input_context_hash != expanded.input_context_hash
    assert select_observation_records(old, "observation", original_context) == before
    verify_observation_selection(before, original_context)
    with pytest.raises(ValueError, match="context hash mismatch"):
        select_observation_records(old, "observation", h.context)


def test_finite_vintage_selects_the_correction_only_after_it_is_available() -> None:
    from drift.markets.observation_selection import select_observation_records

    h = ObservationHarness()
    h.replace_source_revision(close="99.500", available_at="2026-01-08T00:00:00Z")
    before_query = h.outcome(
        "2026-01-07T00:00:00Z", "2026-01-07T00:00:00Z", "2026-01-05"
    )
    after_query = h.outcome(
        "2026-01-08T01:00:00Z", "2026-01-08T01:00:00Z", "2026-01-05"
    )

    before = select_observation_records(before_query, "observation", h.context)
    after = select_observation_records(after_query, "observation", h.context)

    assert isinstance(before.records[0], DailySourceObservationVersionV1)
    assert isinstance(after.records[0], DailySourceObservationVersionV1)
    assert before.records[0].fields[0].field_name == "close"
    assert before.records[0].fields[0].native_text == "100.000"
    assert after.records[0].fields[0].native_text == "99.500"


def test_completed_bar_cannot_be_selected_at_same_day_open() -> None:
    from drift.markets.observation_selection import select_observation_records

    h = ObservationHarness(available_at="2026-01-05T14:00:00Z")
    query = h.decision(
        "2026-01-05T14:35:00Z",
        "2026-01-05T14:30:00Z",
        "2026-01-05T14:30:00Z",
        "2026-01-05",
    )

    selected = select_observation_records(query, "observation", h.context)

    assert selected.records == ()
    assert selected.proof.classification == "indeterminate"


def test_contract_must_be_available_independently_of_early_source_publication() -> None:
    from drift.markets.observation_selection import select_observation_records

    h = ObservationHarness(
        session_date=date(2026, 1, 2),
        available_at="2026-01-02T20:00:00Z",
    )
    query = h.outcome("2026-01-02T22:00:00Z", "2026-01-02T22:00:00Z", "2026-01-02")

    selected = select_observation_records(query, "observation", h.context)

    assert selected.records == ()
    assert selected.proof.classification == "indeterminate"


def test_session_roles_use_their_exact_policy_source_not_the_bar_source() -> None:
    from drift.domain.sessions import SelectedSessionRecordsV1
    from drift.markets.observation_selection import (
        select_observation_records,
        verify_observation_selection,
    )

    context, query, _policy = generation_case()

    selected = select_observation_records(query, "scheduled_session", context)

    assert isinstance(selected, SelectedSessionRecordsV1)
    assert selected.records[0].source_id == "calendar-source"
    assert selected.proof.subject.source_id == "calendar-source"
    assert query.source_id == "bar-source"
    verify_observation_selection(selected, context)


def test_session_selection_uses_finite_cutoff_for_corrections() -> None:
    from drift.domain.sessions import SelectedSessionRecordsV1
    from drift.markets.observation_selection import select_observation_records

    context, query, _policy = generation_case(
        corrected=True,
        record_availability_day=1,
        coverage_availability_day=1,
        methodology_availability_day=1,
        offset_availability_day=1,
    )
    before_query = query.model_copy(update={"knowledge_cutoff": instant(2)})
    after_query = query.model_copy(update={"knowledge_cutoff": instant(3)})

    before = select_observation_records(before_query, "scheduled_session", context)
    after = select_observation_records(after_query, "scheduled_session", context)

    assert isinstance(before, SelectedSessionRecordsV1)
    assert isinstance(after, SelectedSessionRecordsV1)
    assert content_hash(before.records[0]) != content_hash(after.records[0])
    assert before.records[0].revision.source_sequence == 0
    assert after.records[0].revision.source_sequence == 1


def test_selection_replay_rejects_complete_value_and_query_substitution() -> None:
    from drift.markets.observation_selection import (
        select_observation_records,
        verify_observation_selection,
    )

    h = ObservationHarness()
    query = h.outcome("2026-01-06T00:00:00Z", "2026-01-06T00:00:00Z", "2026-01-05")
    selected = select_observation_records(query, "observation", h.context)
    selected_values = {
        "schema_version": selected.schema_version,
        "query": selected.query,
        "purpose": selected.purpose,
        "dataset_role": selected.dataset_role,
        "records": selected.records,
        "proof": selected.proof,
    }
    substituted = type(selected).model_construct(
        **{**selected_values, "records": ()}  # type: ignore[arg-type]
    )
    changed_query = h.decision(
        "2026-01-06T00:00:00Z",
        "2026-01-06T00:00:00Z",
        "2026-01-06T00:00:00Z",
        "2026-01-05",
    )
    changed = type(selected).model_construct(
        **{**selected_values, "query": changed_query}  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="replay mismatch"):
        verify_observation_selection(substituted, h.context)
    with pytest.raises((ValueError, TypeError)):
        verify_observation_selection(changed, h.context)


def test_empty_verified_inventory_is_absent_but_unknown_inventory_is_not() -> None:
    from drift.markets.observation_selection import select_observation_records
    from drift.markets.observation_validation import (
        M1dResolutionContext,
        m1d_context_hash,
    )

    h = ObservationHarness()
    h.use_empty_source_inventory()
    empty_query = h.outcome(
        "2026-01-07T00:00:00Z", "2026-01-07T00:00:00Z", "2026-01-05"
    )
    empty = select_observation_records(empty_query, "observation", h.context)
    unknown_context = M1dResolutionContext(
        observation_datasets=(),
        availability_policies=h.context.availability_policies,
        retained_evidence=h.context.retained_evidence,
        supporting_artifacts=h.context.supporting_artifacts,
    )
    unknown_query = empty_query.model_copy(
        update={"input_context_hash": m1d_context_hash(unknown_context)}
    )
    unknown = select_observation_records(unknown_query, "observation", unknown_context)

    assert empty.records == unknown.records == ()
    assert empty.proof.classification == "absent"
    assert unknown.proof.classification == "indeterminate"


def test_opened_realization_cannot_be_selected_before_actual_close() -> None:
    from drift.markets.observation_selection import select_observation_records

    h = ObservationHarness()
    h.attach_sessions(
        realized_outcome="opened",
        realized_available_at="2026-01-05T14:00:00Z",
    )
    query = h.decision(
        "2026-01-05T15:00:00Z",
        "2026-01-05T15:00:00Z",
        "2026-01-05T15:00:00Z",
        "2026-01-05",
    )

    selected = select_observation_records(query, "realized_session", h.context)

    assert selected.records == ()
    assert selected.proof.classification == "indeterminate"


def test_future_did_not_open_cannot_be_selected_by_early_publication() -> None:
    from drift.markets.observation_selection import select_observation_records

    h = ObservationHarness()
    h.attach_sessions(
        realized_outcome="did_not_open",
        realized_available_at="2026-01-01T00:00:00Z",
        completion_evidence="legacy",
    )
    query = h.outcome("2026-01-01T12:00:00Z", "2026-01-01T12:00:00Z", "2026-01-05")

    selected = select_observation_records(query, "realized_session", h.context)

    assert selected.records == ()
    assert selected.proof.classification == "indeterminate"


def test_backdated_completion_companion_remains_indeterminate_at_later_vintage() -> (
    None
):
    from drift.markets.observation_selection import select_observation_records

    h = ObservationHarness()
    h.attach_sessions(
        realized_outcome="did_not_open",
        realized_available_at="2026-01-01T00:00:00Z",
        completion_evidence="legacy",
    )
    query = h.outcome("2026-01-09T00:00:00Z", "2026-01-09T00:00:00Z", "2026-01-05")

    selected = select_observation_records(query, "realized_session", h.context)

    assert selected.records == ()
    assert selected.proof.classification == "indeterminate"


def test_matching_completion_witness_with_early_bounds_stays_indeterminate() -> None:
    from drift.markets.observation_selection import select_observation_records

    h = ObservationHarness()
    h.attach_sessions(
        realized_outcome="did_not_open",
        realized_available_at="2026-01-01T00:00:00Z",
        completion_evidence="matching",
    )
    query = h.outcome("2026-01-09T00:00:00Z", "2026-01-09T00:00:00Z", "2026-01-05")

    selected = select_observation_records(query, "realized_session", h.context)

    assert selected.records == ()
    assert selected.proof.classification == "indeterminate"


@pytest.mark.parametrize(
    "completion_evidence", ("mismatched_availability", "foreign_availability")
)
def test_completion_companion_requires_exact_record_availability_hash(
    completion_evidence: str,
) -> None:
    from drift.markets.observation_selection import select_observation_records

    h = ObservationHarness()
    h.attach_sessions(
        realized_outcome="did_not_open",
        completion_evidence=completion_evidence,  # type: ignore[arg-type]
    )
    query = h.outcome("2026-01-09T00:00:00Z", "2026-01-09T00:00:00Z", "2026-01-05")

    selected = select_observation_records(query, "realized_session", h.context)

    assert selected.records == ()
    assert selected.proof.classification == "indeterminate"


def test_corrected_realized_evidence_can_become_selectable_after_completion() -> None:
    from drift.domain.sessions import SelectedSessionRecordsV1
    from drift.markets.observation_selection import select_observation_records

    h = ObservationHarness()
    h.attach_sessions(
        realized_outcome="did_not_open",
        realized_available_at="2026-01-01T00:00:00Z",
        corrected_realized_available_at="2026-01-06T00:00:00Z",
    )
    before_query = h.outcome(
        "2026-01-05T22:00:00Z", "2026-01-05T22:00:00Z", "2026-01-05"
    )
    after_query = h.outcome(
        "2026-01-07T00:00:00Z", "2026-01-07T00:00:00Z", "2026-01-05"
    )

    before = select_observation_records(before_query, "realized_session", h.context)
    after = select_observation_records(after_query, "realized_session", h.context)

    assert before.records == ()
    assert before.proof.classification == "indeterminate"
    assert isinstance(after, SelectedSessionRecordsV1)
    assert len(after.records) == 1
    assert after.records[0].revision.source_sequence == 1


@pytest.mark.parametrize(
    ("completion_evidence", "expected_count"),
    (("matching", 1), ("missing", 0), ("mismatched", 0)),
)
def test_unbounded_realization_requires_exact_matching_completion_evidence(
    completion_evidence: str, expected_count: int
) -> None:
    from drift.markets.observation_selection import select_observation_records

    h = ObservationHarness()
    h.attach_sessions(
        realized_outcome="did_not_open",
        completion_evidence=completion_evidence,  # type: ignore[arg-type]
    )
    query = h.outcome("2026-01-07T00:00:00Z", "2026-01-07T00:00:00Z", "2026-01-05")

    selected = select_observation_records(query, "realized_session", h.context)

    assert len(selected.records) == expected_count
    assert selected.proof.classification == (
        "selected" if expected_count else "indeterminate"
    )


def test_contract_is_a_public_policy_authorized_selection_purpose() -> None:
    from drift.markets.observation_selection import (
        SelectedObservationContractV1,
        select_observation_records,
        verify_observation_selection,
    )

    h = ObservationHarness()
    query = h.outcome("2026-01-07T00:00:00Z", "2026-01-07T00:00:00Z", "2026-01-05")

    selected = select_observation_records(query, "contract", h.context)

    assert isinstance(selected, SelectedObservationContractV1)
    assert selected.contract is not None
    assert content_hash(selected.contract) == query.contract_hash
    assert selected.proof.classification == "selected"
    verify_observation_selection(selected, h.context)


def test_contract_selection_rejects_wrong_policy_authority() -> None:
    from drift.markets.observation_selection import (
        SelectedObservationContractV1,
        select_observation_records,
    )

    h = ObservationHarness()
    h.use_wrong_contract_policy()
    query = h.outcome("2026-01-07T00:00:00Z", "2026-01-07T00:00:00Z", "2026-01-05")

    selected = select_observation_records(query, "contract", h.context)

    assert isinstance(selected, SelectedObservationContractV1)
    assert selected.contract is None
    assert selected.proof.classification == "indeterminate"


@pytest.mark.parametrize("retained", (False, True))
def test_contract_selection_requires_exact_singleton_methodology_inventory(
    retained: bool,
) -> None:
    from drift.markets.observation_selection import (
        SelectedObservationContractV1,
        select_observation_records,
    )

    h = ObservationHarness()
    h.use_extra_contract_methodology(retained=retained)
    query = h.outcome("2026-01-07T00:00:00Z", "2026-01-07T00:00:00Z", "2026-01-05")

    selected = select_observation_records(query, "contract", h.context)

    assert isinstance(selected, SelectedObservationContractV1)
    assert selected.contract is None
    assert selected.proof.classification == "indeterminate"


@pytest.mark.parametrize("retained", (False, True))
def test_observation_selection_rejects_extra_contract_methodology_inventory(
    retained: bool,
) -> None:
    from drift.domain.observation_query import M1dSelectedRecordsV1
    from drift.markets.observation_selection import select_observation_records

    h = ObservationHarness()
    h.use_extra_contract_methodology(retained=retained)
    query = h.outcome("2026-01-07T00:00:00Z", "2026-01-07T00:00:00Z", "2026-01-05")

    selected = select_observation_records(query, "observation", h.context)

    assert isinstance(selected, M1dSelectedRecordsV1)
    assert selected.records == ()
    assert selected.proof.classification == "indeterminate"


def test_observation_selection_accepts_exact_singleton_methodology_inventory() -> None:
    from drift.domain.observation_query import M1dSelectedRecordsV1
    from drift.markets.observation_selection import select_observation_records

    h = ObservationHarness()
    query = h.outcome("2026-01-07T00:00:00Z", "2026-01-07T00:00:00Z", "2026-01-05")

    selected = select_observation_records(query, "observation", h.context)

    assert isinstance(selected, M1dSelectedRecordsV1)
    assert len(selected.records) == 1
    assert selected.proof.classification == "selected"


def test_contract_selection_replay_rejects_forged_contract_and_proof() -> None:
    from drift.markets.observation_selection import (
        SelectedObservationContractV1,
        select_observation_records,
        verify_observation_selection,
    )

    h = ObservationHarness()
    query = h.outcome("2026-01-07T00:00:00Z", "2026-01-07T00:00:00Z", "2026-01-05")
    selected = select_observation_records(query, "contract", h.context)
    assert isinstance(selected, SelectedObservationContractV1)
    assert selected.contract is not None
    forged_contract = selected.contract.model_copy(update={"source_id": "other-source"})
    forged_value = SelectedObservationContractV1.model_construct(
        query=selected.query,
        purpose=selected.purpose,
        contract=forged_contract,
        proof=selected.proof,
    )
    forged_proof = selected.proof.model_construct(
        **{
            name: (() if name == "selected_hashes" else getattr(selected.proof, name))
            for name in type(selected.proof).model_fields
        }  # type: ignore[arg-type]
    )
    forged_proof_value = SelectedObservationContractV1.model_construct(
        query=selected.query,
        purpose=selected.purpose,
        contract=selected.contract,
        proof=forged_proof,
    )

    with pytest.raises(ValueError, match="replay mismatch"):
        verify_observation_selection(forged_value, h.context)
    with pytest.raises(ValueError, match="replay mismatch"):
        verify_observation_selection(forged_proof_value, h.context)


def test_equivalent_overlapping_bindings_collapse_to_one_authority() -> None:
    from drift.markets.observation_selection import select_observation_records

    h = ObservationHarness()
    h.use_overlapping_binding(kind="equivalent_observation")
    query = h.outcome("2026-01-07T00:00:00Z", "2026-01-07T00:00:00Z", "2026-01-05")

    selected = select_observation_records(query, "observation", h.context)

    assert len(selected.records) == 1
    assert selected.proof.classification == "selected"


def test_distinct_overlapping_session_bindings_remain_indeterminate() -> None:
    from drift.markets.observation_selection import select_observation_records

    h = ObservationHarness()
    h.attach_sessions()
    h.use_overlapping_binding(kind="distinct_schedule")
    query = h.outcome("2026-01-07T00:00:00Z", "2026-01-07T00:00:00Z", "2026-01-05")

    selected = select_observation_records(query, "scheduled_session", h.context)

    assert selected.records == ()
    assert selected.proof.classification == "indeterminate"
