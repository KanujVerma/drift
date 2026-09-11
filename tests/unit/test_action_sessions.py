"""Verified M1c action-to-session application boundaries."""

from datetime import date
from typing import Literal
from uuid import UUID

import pytest
from action_session_test_support import FOREIGN_LISTING_ID, action_session_case
from observation_test_support import ObservationHarness

from drift.domain.action_sessions import (
    ActionSessionQueryV1,
    FirstPostActionSessionResultV1,
)
from drift.domain.economic_common import ActionKind
from drift.markets.action_sessions import (
    map_action_to_session,
    verify_action_session_mapping,
)
from drift.serialization.canonical import canonical_json


@pytest.mark.parametrize(
    ("basis", "mode", "expected", "expected_date"),
    [
        ("2026-11-26", "explicit_first_basis_date", "indeterminate", None),
        (
            "2026-11-27T18:05:00Z",
            "exact_trading_basis_transition",
            "mapped",
            "2026-11-30",
        ),
        (
            "2026-11-27T14:00:00Z",
            "exact_trading_basis_transition",
            "mapped",
            "2026-11-27",
        ),
        (
            "2026-11-27T16:00:00Z",
            "exact_trading_basis_transition",
            "indeterminate",
            None,
        ),
    ],
)
def test_mapping_has_no_implicit_date_roll(
    basis: str,
    mode: Literal["explicit_first_basis_date", "exact_trading_basis_transition"],
    expected: Literal["mapped", "indeterminate"],
    expected_date: str | None,
) -> None:
    result = ObservationHarness().map_action(basis, mode)
    assert result.classification == expected
    assert (
        result.first_post_session.local_date.isoformat()
        if result.first_post_session is not None
        else None
    ) == expected_date


def test_a01_explicit_ex_basis_date_maps_only_when_actually_open() -> None:
    result = action_session_case("2026-11-27", "explicit_first_basis_date").map()
    assert result.classification == "mapped"
    assert result.first_post_session is not None
    assert result.first_post_session.local_date == date(2026, 11, 27)
    assert result.transition_claim is not None
    assert result.transition_claim.relationship == "explicit_first_basis_date"


def test_explicit_first_basis_date_uses_proven_session_at_horizon_edge() -> None:
    result = action_session_case("2026-11-30", "explicit_first_basis_date").map()
    assert result.classification == "mapped"
    assert result.first_post_session is not None
    assert result.first_post_session.local_date == date(2026, 11, 30)


@pytest.mark.parametrize("basis", ["2026-11-27T14:30:00Z", "2026-11-27T18:00:00Z"])
def test_a03_equal_session_endpoint_requires_explicit_designation(basis: str) -> None:
    result = action_session_case(basis, "exact_trading_basis_transition").map()
    assert result.classification == "indeterminate"
    assert result.first_post_session is None
    assert "transition_endpoint_undesignated" in result.reasons


def test_designated_open_keeps_truthful_endpoint_relationship() -> None:
    result = action_session_case(
        "2026-11-27T14:30:00Z",
        "exact_trading_basis_transition",
        open_endpoint_designation="post_basis",
    ).map()
    assert result.classification == "mapped"
    assert result.transition_claim is not None
    assert result.transition_claim.relationship == "exactly_at_open"
    assert result.transition_claim.applied_rule == "designated_open_post_basis"


def test_designated_close_keeps_truthful_endpoint_relationship() -> None:
    result = action_session_case(
        "2026-11-27T18:00:00Z",
        "exact_trading_basis_transition",
        close_endpoint_designation="pre_basis",
    ).map()
    assert result.classification == "mapped"
    assert result.first_post_session is not None
    assert result.first_post_session.local_date == date(2026, 11, 30)
    assert result.transition_claim is not None
    assert result.transition_claim.relationship == "exactly_at_close"
    assert result.transition_claim.source_session_key.local_date == date(2026, 11, 27)
    assert result.transition_claim.session_key.local_date == date(2026, 11, 30)
    assert (
        result.transition_claim.applied_rule
        == "designated_close_pre_basis_next_open_complete_coverage"
    )


@pytest.mark.parametrize("role", ["announcement", "record", "payable", "legal_effect"])
def test_a04_generic_legal_dates_are_not_trading_basis(role: str) -> None:
    result = action_session_case(
        "2026-11-27",
        "explicit_first_basis_date",
        date_role=role,  # type: ignore[arg-type]
    ).map()
    assert result.classification == "indeterminate"
    assert "date_role_not_trading_basis" in result.reasons


@pytest.mark.parametrize("effect_kind", ["cancelled_action", "unknown"])
def test_announcement_or_nonoccurrence_cannot_apply_share_basis(
    effect_kind: Literal["cancelled_action", "unknown"],
) -> None:
    result = action_session_case(
        "2026-11-27",
        "explicit_first_basis_date",
        effect_kind=effect_kind,
    ).map()
    assert result.classification == (
        "not_applicable" if effect_kind == "cancelled_action" else "indeterminate"
    )
    assert result.first_post_session is None


def test_selected_upcoming_effect_cannot_apply_an_earlier_terms_date() -> None:
    result = action_session_case(
        "2026-11-27",
        "explicit_first_basis_date",
        effect_basis="2026-12-01T12:00:00Z",
    ).map()
    assert result.classification == "indeterminate"
    assert "selected_action_occurrence_not_effective" in result.reasons


def test_a05_later_emergency_did_not_open_blocks_mapping() -> None:
    result = action_session_case(
        "2026-11-27",
        "explicit_first_basis_date",
        emergency_date=date(2026, 11, 27),
    ).map()
    assert result.classification == "indeterminate"
    assert "candidate_session_did_not_open" in result.reasons


def test_a06_methodology_must_match_exact_venue_listing_and_security() -> None:
    result = action_session_case(
        "2026-11-27",
        "explicit_first_basis_date",
        method_mic="XNAS",
    ).map()
    assert result.classification == "indeterminate"
    assert "date_methodology_subject_mismatch" in result.reasons


def test_terms_date_uses_terms_owner_when_effect_owner_differs() -> None:
    result = action_session_case(
        "2026-11-27",
        "explicit_first_basis_date",
        terms_source_id="terms-owner",
        effect_source_id="effect-owner",
    ).map()
    assert result.classification == "mapped"


def test_terms_date_rejects_effect_owner_as_date_source() -> None:
    result = action_session_case(
        "2026-11-27",
        "explicit_first_basis_date",
        terms_source_id="terms-owner",
        effect_source_id="effect-owner",
        method_source_id="effect-owner",
    ).map()
    assert result.classification == "indeterminate"
    assert "date_methodology_source_mismatch" in result.reasons


@pytest.mark.parametrize("terms_listing_id", [None, FOREIGN_LISTING_ID])
def test_terms_date_requires_exact_listing_applicability(
    terms_listing_id: UUID | None,
) -> None:
    result = action_session_case(
        "2026-11-27",
        "explicit_first_basis_date",
        terms_listing_id=terms_listing_id,
    ).map()
    assert result.classification == "indeterminate"
    assert "selected_terms_listing_mismatch" in result.reasons


def test_a07_terms_correction_revises_later_mapping_without_rewriting_old_context() -> (
    None
):
    old_case = action_session_case(
        "2026-11-27T14:00:00Z", "exact_trading_basis_transition"
    )
    old_result = old_case.map()
    new_case = action_session_case(
        "2026-11-27T14:00:00Z",
        "exact_trading_basis_transition",
        correction_basis="2026-11-27T18:05:00Z",
    )
    new_result = new_case.map()
    assert old_result.classification == "mapped"
    assert new_result.classification == "mapped"
    assert old_result.first_post_session is not None
    assert new_result.first_post_session is not None
    assert old_result.first_post_session.local_date == date(2026, 11, 27)
    assert new_result.first_post_session.local_date == date(2026, 11, 30)
    assert old_result.selected_terms_hash != new_result.selected_terms_hash
    verify_action_session_mapping(old_result, old_case.context)


def test_s07_schedule_correction_changes_new_snapshot_not_old_replay() -> None:
    old_case = action_session_case(
        "2026-11-27T18:05:00Z", "exact_trading_basis_transition"
    )
    old_result = old_case.map()
    corrected_case = action_session_case(
        "2026-11-27T18:05:00Z",
        "exact_trading_basis_transition",
        corrected_schedule_state="closed",
    )
    corrected_result = corrected_case.map()
    assert old_result.classification == "mapped"
    assert corrected_result.classification == "indeterminate"
    assert "basis_source_session_unproved" in corrected_result.reasons
    verify_action_session_mapping(old_result, old_case.context)


def test_a08_equal_same_occurrence_reports_map_once() -> None:
    result = action_session_case(
        "2026-11-27",
        "explicit_first_basis_date",
        duplicate="equal",
    ).map()
    assert result.classification == "mapped"
    assert len(result.same_occurrence_effect_hashes) == 2
    assert result.first_post_session is not None
    assert result.first_post_session.local_date == date(2026, 11, 27)


def test_a08_same_occurrence_conflict_blocks_before_window_filtering() -> None:
    result = action_session_case(
        "2026-11-27T14:00:00Z",
        "exact_trading_basis_transition",
        duplicate="conflict_outside_window",
    ).map()
    assert result.classification == "indeterminate"
    assert result.first_post_session is None
    assert "same_occurrence_economic_disagreement" in result.reasons


def test_a08_same_occurrence_effect_time_disagreement_blocks_mapping() -> None:
    result = action_session_case(
        "2026-11-27T14:00:00Z",
        "exact_trading_basis_transition",
        duplicate="effect_time_conflict",
    ).map()
    assert result.classification == "indeterminate"
    assert "same_occurrence_economic_disagreement" in result.reasons


@pytest.mark.parametrize("basis", ["2026-11-27T23:30:00-05:00", "2026-11-28T04:30:00Z"])
def test_exact_transition_is_representation_independent_across_midnight(
    basis: str,
) -> None:
    result = action_session_case(
        basis,
        "exact_trading_basis_transition",
    ).map()
    assert result.classification == "mapped"
    assert result.first_post_session is not None
    assert result.first_post_session.local_date == date(2026, 11, 30)
    assert result.transition_claim is not None
    assert result.transition_claim.source_session_key.local_date == date(2026, 11, 27)


def test_a09_no_foreign_source_equality_seam() -> None:
    case = action_session_case("2026-11-27", "explicit_first_basis_date")
    foreign = case.query.model_copy(update={"source_id": "synthetic-b"})
    result = map_action_to_session(foreign, case.context)
    assert result.classification == "indeterminate"
    assert "date_methodology_subject_mismatch" in result.reasons


def test_a10_effect_terms_association_rejects_substituted_same_security_terms() -> None:
    result = action_session_case(
        "2026-11-27",
        "explicit_first_basis_date",
        selected_terms="substitute",
    ).map()
    assert result.classification == "indeterminate"
    assert "selected_terms_association_mismatch" in result.reasons


def test_a10_unresolved_terms_cannot_supply_a_date() -> None:
    result = action_session_case(
        "2026-11-27",
        "explicit_first_basis_date",
        unresolved_terms=True,
    ).map()
    assert result.classification == "indeterminate"
    assert "selected_terms_association_unresolved" in result.reasons


def test_effect_time_requires_exact_associated_terms_when_hash_is_present() -> None:
    valid = action_session_case(
        "2026-11-27T14:00:00Z",
        "exact_trading_basis_transition",
        field_origin="selected_effect_time",
    ).map()
    arbitrary = action_session_case(
        "2026-11-27T14:00:00Z",
        "exact_trading_basis_transition",
        field_origin="selected_effect_time",
        selected_terms="arbitrary",
    ).map()
    substituted = action_session_case(
        "2026-11-27T14:00:00Z",
        "exact_trading_basis_transition",
        field_origin="selected_effect_time",
        selected_terms="substitute",
    ).map()
    assert valid.classification == "mapped"
    assert arbitrary.classification == "indeterminate"
    assert substituted.classification == "indeterminate"
    assert arbitrary.reasons == ("selected_terms_association_mismatch",)
    assert substituted.reasons == ("selected_terms_association_mismatch",)


def test_effect_time_without_terms_hash_maps_from_complete_effect_only() -> None:
    result = action_session_case(
        "2026-11-27T14:00:00Z",
        "exact_trading_basis_transition",
        field_origin="selected_effect_time",
        selected_terms="absent",
    ).map()
    assert result.classification == "mapped"
    assert result.selected_terms_hash is None
    assert result.association_result_hash is None


@pytest.mark.parametrize(
    ("effect_kind", "ratio", "extra_component"),
    [
        ("unknown", ("2", "1"), False),
        ("occurred", ("1", "2"), False),
        ("occurred", ("2", "1"), True),
    ],
)
def test_effect_time_without_terms_rejects_incomplete_effect(
    effect_kind: Literal["occurred", "unknown"],
    ratio: tuple[str, str],
    extra_component: bool,
) -> None:
    result = action_session_case(
        "2026-11-27T14:00:00Z",
        "exact_trading_basis_transition",
        field_origin="selected_effect_time",
        selected_terms="absent",
        effect_kind=effect_kind,
        ratio=ratio,
        extra_component=extra_component,
    ).map()
    assert result.classification == "indeterminate"
    assert result.selected_terms_hash is None
    assert result.association_result_hash is None


def test_before_open_requires_complete_current_session_coverage() -> None:
    result = action_session_case(
        "2026-11-27T14:00:00Z",
        "exact_trading_basis_transition",
        session_coverage="partial",
    ).map()
    assert result.classification == "indeterminate"
    assert "source_session_coverage_incomplete" in result.reasons


def test_associated_terms_action_kind_must_match_occurred_effect() -> None:
    result = action_session_case(
        "2026-11-27",
        "explicit_first_basis_date",
        terms_action_kind=ActionKind.STOCK_DIVIDEND,
    ).map()
    assert result.classification == "indeterminate"
    assert "selected_terms_effect_action_kind_mismatch" in result.reasons


@pytest.mark.parametrize(
    ("action_kind", "ratio", "expected"),
    [
        (ActionKind.FORWARD_SPLIT, ("2", "1"), "mapped"),
        (ActionKind.FORWARD_SPLIT, ("1", "2"), "indeterminate"),
        (ActionKind.REVERSE_SPLIT, ("1", "10"), "mapped"),
        (ActionKind.REVERSE_SPLIT, ("2", "1"), "indeterminate"),
    ],
)
def test_split_ratio_direction_matches_action_kind(
    action_kind: ActionKind,
    ratio: tuple[str, str],
    expected: Literal["mapped", "indeterminate"],
) -> None:
    result = action_session_case(
        "2026-11-27",
        "explicit_first_basis_date",
        action_kind=action_kind,
        terms_action_kind=action_kind,
        ratio=ratio,
    ).map()
    assert result.classification == expected


def test_incomplete_terms_cannot_authorize_split_projection() -> None:
    result = action_session_case(
        "2026-11-27",
        "explicit_first_basis_date",
        terms_payload_kind="incomplete",
    ).map()
    assert result.classification == "indeterminate"
    assert "selected_terms_not_fixed" in result.reasons


def test_extra_mixed_components_cannot_authorize_pure_split_projection() -> None:
    result = action_session_case(
        "2026-11-27",
        "explicit_first_basis_date",
        extra_component=True,
    ).map()
    assert result.classification == "indeterminate"
    assert "pure_split_component_shape_unproved" in result.reasons


def test_n12_all_fourteen_action_classes_are_required_for_complete_scope() -> None:
    result = action_session_case(
        "2026-11-27",
        "explicit_first_basis_date",
        coverage_action_kinds=(ActionKind.FORWARD_SPLIT, ActionKind.REVERSE_SPLIT),
    ).map()
    assert result.classification == "indeterminate"
    assert "economic_action_class_coverage_incomplete" in result.reasons


def test_n13_incomplete_settlement_does_not_block_proven_split_units() -> None:
    result = action_session_case(
        "2026-11-27",
        "explicit_first_basis_date",
        settlement_coverage="partial",
    ).map()
    assert result.classification == "mapped"
    assert "settlement_coverage_incomplete_audit_only" in result.reasons


def test_after_close_requires_complete_intervening_session_coverage() -> None:
    result = action_session_case(
        "2026-11-27T18:05:00Z",
        "exact_trading_basis_transition",
        session_coverage="partial",
    ).map()
    assert result.classification == "indeterminate"
    assert "intervening_session_coverage_incomplete" in result.reasons


def test_p01_exact_replay_rejects_selected_session_substitution() -> None:
    case = action_session_case("2026-11-27", "explicit_first_basis_date")
    result = case.map()
    assert result.first_post_session is not None
    forged = result.model_copy(
        update={
            "first_post_session": result.first_post_session.model_copy(
                update={"local_date": date(2026, 11, 30)}
            )
        }
    )
    with pytest.raises(ValueError, match="action session mapping replay mismatch"):
        verify_action_session_mapping(forged, case.context)


def test_p01_exact_replay_rejects_omitted_dependency() -> None:
    case = action_session_case("2026-11-27", "explicit_first_basis_date")
    result = case.map()
    forged = result.model_copy(
        update={"dependency_hashes": result.dependency_hashes[:-1]}
    )
    with pytest.raises(ValueError, match="action session mapping replay mismatch"):
        verify_action_session_mapping(forged, case.context)


def test_role_and_query_are_preserved_through_dump_load_and_replay() -> None:
    case = action_session_case("2026-11-27", "explicit_first_basis_date")
    result = case.map()
    loaded = FirstPostActionSessionResultV1.model_validate_json(canonical_json(result))
    assert loaded.economic_query.kind == "outcome"
    assert loaded.query.outer_query.kind == "outcome"
    verify_action_session_mapping(loaded, case.context)


def test_p03_outcome_economic_input_cannot_be_injected_into_decision_result() -> None:
    decision_case = action_session_case(
        "2026-11-27",
        "explicit_first_basis_date",
        outer_kind="decision",
    )
    decision_result = decision_case.map()
    outcome_result = action_session_case(
        "2026-11-27", "explicit_first_basis_date"
    ).map()
    assert decision_result.economic_query.kind == "decision"
    with pytest.raises(ValueError, match="action mapping nested role mismatch"):
        decision_result.model_copy(
            update={
                "economic_query": outcome_result.economic_query,
                "economic_query_hash": outcome_result.economic_query_hash,
            }
        )


def test_query_rejects_nested_subject_substitution() -> None:
    case = action_session_case("2026-11-27", "explicit_first_basis_date")
    payload = case.query.model_dump(mode="python")
    payload["security_id"] = UUID("019b8240-0000-7000-8000-000000000022")
    with pytest.raises(ValueError, match="action query subject must match outer query"):
        ActionSessionQueryV1.model_validate(payload)
