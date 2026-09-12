"""Exact immutable fixture support for M1d Task 7 integration tests."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, cast

from pydantic import ValidationError

UNIT_TEST_ROOT = Path(__file__).parents[1] / "unit"
if not UNIT_TEST_ROOT.is_dir():
    UNIT_TEST_ROOT = Path(__file__).parents[2] / "tests" / "unit"
sys.path.insert(0, str(UNIT_TEST_ROOT))

from action_session_test_support import action_session_case
from economic_test_support import uid as economic_uid
from observation_test_support import (  # type: ignore[attr-defined]
    ObservationHarness,
    regular_session_trade_bar_profile_hash,
)
from session_test_support import (
    boundary_at as session_boundary_at,
)
from session_test_support import (
    generation_case,
    session_dataset,
    timezone_bytes,
)
from session_test_support import (
    uid as session_uid,
)

from drift.datasets.hashing import (
    assertion_version_payload,
    manifest_hash,
)
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.action_sessions import EconomicDateRole
from drift.domain.economic_common import ActionKind
from drift.domain.normalization import (
    NormalizationPolicyV1,
    NormalizationQueryV1,
    NormalizationResultV1,
    normalization_algorithm_hash,
)
from drift.domain.observation_query import (
    ObservationDecisionQueryV1,
    ObservationOutcomeQueryV1,
    ObservationQueryV1,
    ObservationSourceSelectionPolicyV1,
    m1d_implementation_hash,
)
from drift.domain.revisions import RevisionKind
from drift.domain.sessions import (
    RealizedSessionVersionV1,
    ScheduledSessionVersionV1,
    ScheduleGenerationPolicyV1,
    SessionCoverageVersionV1,
    SessionInventoryEntryV1,
    SessionKeyV1,
)
from drift.markets.normalization import (
    normalize_observation,
    verify_normalization,
)
from drift.markets.observation_validation import (
    M1dResolutionContext,
    m1d_context_hash,
)
from drift.markets.session_generation import generate_schedule
from drift.serialization.canonical import canonical_json, content_hash

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "m1d" / "v1"

__all__ = (
    "EXPECTED_MATRIX_IDS",
    "FIXTURE_ROOT",
    "MATRIX_POINTERS",
    "REQUIRED_JOINED_IDS",
    "JoinedScenario",
    "ObservationHarness",
    "action_session_case",
    "fixture_payloads",
    "joined_scenario",
    "matrix_index_bytes",
    "timezone_bytes",
    "write_fixture_v1",
)

EXPECTED_MATRIX_IDS = frozenset(
    [
        "A01",
        "A02",
        "A03",
        "A04",
        "A05",
        "A06",
        "A07",
        "A08",
        "A09",
        "A10",
        "C01",
        "C02",
        "C03",
        "M01",
        "M02",
        "M03",
        "M04",
        "M05",
        "M06",
        "M07",
        "M08",
        "M09",
        "N01",
        "N02",
        "N03",
        "N04",
        "N05",
        "N06",
        "N07",
        "N08",
        "N09",
        "N10",
        "N11",
        "N12",
        "N13",
        "O01",
        "O02",
        "O03",
        "O04",
        "O05",
        "O06",
        "O07",
        "O09",
        "O10",
        "O11",
        "O08",
        "O09",
        "O10",
        "O11",
        "P01",
        "P02",
        "P03",
        "P04",
        "P05",
        "P06",
        "P07",
        "P08",
        "S01",
        "S02",
        "S03",
        "S04",
        "S05",
        "S06",
        "S07",
        "S08",
        "S09",
        "S10",
        "S11",
        "S12",
        "S13",
        "S14",
        "S15",
        "S16",
        "S17",
        "S18",
        "S19",
        "S20",
        "S21",
        "T01",
        "T02",
        "T03",
        "T04",
        "T05",
        "T06",
    ]
)

REQUIRED_JOINED_IDS = frozenset(
    [
        "O01",
        "T02",
        "S03",
        "S07",
        "A01",
        "A02",
        "A03",
        "A04",
        "A05",
        "A06",
        "A07",
        "A08",
        "N01",
        "N02",
        "N03",
        "N04",
        "O07",
        "P01",
        "P02",
        "P03",
        "P04",
        "P05",
        "P06",
    ]
)

MATRIX_POINTERS: dict[str, tuple[str, ...]] = {
    "A01": (
        "tests/integration/test_m1d_action_normalization.py::test_a01_joined_explicit_first_basis_date_maps_on_proven_open",
    ),
    "A02": (
        "tests/integration/test_m1d_action_normalization.py::test_a02_joined_after_early_close_uses_next_proven_open",
    ),
    "A03": (
        "tests/integration/test_m1d_action_normalization.py::test_a03_joined_before_open_maps_but_undesignated_endpoint_blocks",
    ),
    "A04": (
        "tests/integration/test_m1d_action_normalization.py::test_a04_joined_legal_dates_never_gain_trading_basis_meaning",
    ),
    "A05": (
        "tests/integration/test_m1d_action_normalization.py::test_a05_joined_emergency_did_not_open_blocks_mapping",
    ),
    "A06": (
        "tests/integration/test_m1d_action_normalization.py::test_a06_joined_subject_mismatch_blocks_action_mapping",
    ),
    "A07": (
        "tests/integration/test_m1d_action_normalization.py::test_a07_joined_correction_changes_only_later_mapping",
        "tests/unit/test_action_sessions.py::test_a07_terms_correction_revises_later_mapping_without_rewriting_old_context",
    ),
    "A08": (
        "tests/integration/test_m1d_action_normalization.py::test_a08_joined_duplicate_occurrence_applies_one_factor",
        "tests/integration/test_m1d_action_normalization.py::test_a08_joined_crossing_window_conflict_blocks_factor",
        "tests/unit/test_action_sessions.py::test_a08_same_occurrence_conflict_blocks_before_window_filtering",
    ),
    "A09": (
        "tests/unit/test_action_sessions.py::test_a09_no_foreign_source_equality_seam",
    ),
    "A10": (
        "tests/unit/test_action_sessions.py::test_a10_effect_terms_association_rejects_substituted_same_security_terms",
        "tests/unit/test_action_sessions.py::test_a10_unresolved_terms_cannot_supply_a_date",
    ),
    "C01": (
        "tests/integration/test_m1_m0_compatibility.py::test_m0_fixture_serialization_and_event_hashes_are_unchanged",
        "tests/integration/test_replay.py::test_replay_verifies_integrity_before_returning_events",
        "tests/integration/test_m1b_m1a_compatibility.py::test_m1a_manifest_decision_and_events_keep_their_canonical_identity",
        "tests/unit/test_assertions.py::test_cutoff_selection_does_not_use_later_correction",
        "tests/unit/test_security_identity.py::test_assignment_resolution_rebuilds_the_same_internal_identity",
        "tests/integration/test_m1c_action_matrix.py::test_m1c_selected_value_substitution",
    ),
    "C02": (
        "tests/integration/test_m1c_pinned_replay.py::test_pinned_replay_executes_all_archived_v1_cases",
        "tests/integration/test_m1c_pinned_replay.py::test_protected_input_tampering_is_rejected_by_literal_sha256_pins",
        "tests/integration/test_m1c_pinned_replay.py::test_missing_literal_inventory_pin_is_rejected_before_archive_extraction",
        "tests/integration/test_m1c_pinned_replay.py::test_re_signed_literal_inventory_digest_is_rejected_before_archive_extraction",
        "tests/integration/test_m1c_pinned_replay.py::test_child_failure_output_is_propagated_to_the_parent",
    ),
    "C03": (
        "tests/integration/test_m1d_compatibility.py::test_c03_forbidden_runtime_capabilities_and_dependencies_remain_absent",
    ),
    "M01": (
        "tests/unit/test_observation_usability.py::test_exact_absent_row_proves_provider_gap_without_zero_price",
    ),
    "M02": (
        "tests/unit/test_observation_usability.py::test_absent_row_without_complete_historical_coverage_is_not_a_provider_gap",
    ),
    "M03": (
        "tests/unit/test_observation_usability.py::test_explicit_no_price_trade_keeps_any_activity_independent",
    ),
    "M04": (
        "tests/unit/test_observation_usability.py::test_omission_zero_and_null_do_not_infer_no_trade",
    ),
    "M05": (
        "tests/unit/test_observation_usability.py::test_typed_read_failures_do_not_become_absence_or_lifecycle",
    ),
    "M06": (
        "tests/unit/test_observation_usability.py::test_known_ineligible_lifecycle_intervals_are_unusable",
        "tests/unit/test_observation_usability.py::test_delisted_listing_keeps_pretermination_bar_usable",
    ),
    "M07": (
        "tests/unit/test_observation_usability.py::test_partial_suspension_requires_complete_explicit_aggregation",
    ),
    "M08": (
        "tests/unit/test_observation_usability.py::test_multiple_unknown_axes_are_preserved_without_a_dominant_reason",
    ),
    "M09": (
        "tests/unit/test_observation_usability.py::test_present_complete_row_does_not_require_global_coverage",
    ),
    "N01": (
        "tests/integration/test_m1d_action_normalization.py::test_n01_joined_same_context_before_and_after_split",
    ),
    "N02": (
        "tests/integration/test_m1d_action_normalization.py::test_n02_joined_retained_future_action_does_not_leak_then_applies_later",
    ),
    "N03": (
        "tests/integration/test_m1d_action_normalization.py::test_n03_joined_future_anchor_is_denied",
    ),
    "N04": (
        "tests/integration/test_m1d_action_normalization.py::test_n04_joined_forward_and_reverse_factors_are_exact_reciprocals",
    ),
    "N05": (
        "tests/unit/test_normalization.py::test_n05_pure_split_composition_is_permutation_invariant",
        "tests/unit/test_normalization.py::test_n05_reciprocal_sequence_reduces_to_identity_before_rounding",
    ),
    "N06": (
        "tests/unit/test_normalization.py::test_n06_end_to_end_normalization_rejects_nonshare_volume_semantics",
    ),
    "N07": (
        "tests/unit/test_normalization.py::test_n07_relevant_non_split_share_basis_change_is_indeterminate",
    ),
    "N08": (
        "tests/unit/test_normalization.py::test_n08_independent_cash_only_effect_is_neutral_to_split_units",
        "tests/unit/test_normalization.py::test_n08_same_occurrence_conflict_is_compared_before_anchor_filtering",
    ),
    "N09": (
        "tests/unit/test_normalization.py::test_n09_incomplete_relevant_action_history_blocks_factor_claim",
    ),
    "N10": (
        "tests/unit/test_normalization.py::test_n10_source_session_equal_to_mapped_first_post_gets_factor_one",
    ),
    "N11": (
        "tests/unit/test_normalization.py::test_n11_split_mode_quantizes_only_once_at_final_half_even_tie",
        "tests/unit/test_normalization.py::test_n11_positive_price_rounding_to_zero_rejects_view",
    ),
    "N12": (
        "tests/unit/test_normalization.py::test_n12_all_fourteen_action_classes_are_required",
    ),
    "N13": (
        "tests/unit/test_normalization.py::test_n13_incomplete_settlement_does_not_block_split_unit_factors",
    ),
    "O01": (
        "tests/integration/test_m1d_observation_history.py::test_o01_joined_source_values_materialize_without_action_inputs",
    ),
    "O02": (
        "tests/unit/test_observation_usability.py::test_nonconforming_source_claims_are_retained_without_numeric_view",
    ),
    "O03": (
        "tests/unit/test_observation_usability.py::test_proven_official_close_equivalence_can_satisfy_profile",
    ),
    "O04": (
        "tests/unit/test_session_binding.py::test_binds_against_realized_interval_without_rewriting_first_trade",
    ),
    "O05": (
        "tests/unit/test_observation_contracts.py::test_contract_rejects_fallback_branch_owned_by_another_method",
        "tests/unit/test_observation_selection.py::test_selection_replay_rejects_complete_value_and_query_substitution",
    ),
    "O06": (
        "tests/unit/test_observation_usability.py::test_omission_zero_and_null_do_not_infer_no_trade",
    ),
    "O07": (
        "tests/integration/test_m1d_observation_history.py::test_o07_joined_adjusted_or_unknown_source_basis_is_refused",
    ),
    "O08": (
        "tests/unit/test_observation_usability.py::test_nonconforming_source_claims_are_retained_without_numeric_view",
    ),
    "O09": (
        "tests/integration/test_m1d_observation_history.py::test_o09_joined_mixed_adjustment_basis_is_retained_and_refused",
        "tests/unit/test_normalization.py::test_n06_end_to_end_normalization_rejects_nonshare_volume_semantics",
    ),
    "O10": (
        "tests/integration/test_m1d_observation_history.py::test_o10_joined_official_close_requires_exact_active_equivalence",
        "tests/unit/test_observation_contracts.py::test_contract_rejects_fallback_branch_owned_by_another_method",
    ),
    "O11": (
        "tests/integration/test_m1d_observation_history.py::test_o11_joined_unrelated_population_containment_is_refused",
    ),
    "P01": (
        "tests/integration/test_m1d_adversarial_matrix.py::test_p01_joined_dependent_substitutions_reject_exact_replay",
    ),
    "P02": (
        "tests/integration/test_m1d_adversarial_matrix.py::test_p02_joined_factor_view_and_reference_substitutions_are_rejected",
    ),
    "P03": (
        "tests/integration/test_m1d_adversarial_matrix.py::test_p03_joined_decision_and_outcome_roles_are_noninterchangeable",
    ),
    "P04": (
        "tests/integration/test_m1d_adversarial_matrix.py::test_p04_joined_equal_numbers_under_changed_policy_have_distinct_lineage",
    ),
    "P05": (
        "tests/integration/test_m1d_adversarial_matrix.py::test_p05_joined_content_identity_ignores_location_but_rejects_wrong_bytes",
    ),
    "P06": (
        "tests/integration/test_m1d_adversarial_matrix.py::test_p06_joined_verified_snapshot_survives_path_mutation_but_context_substitution_fails",
    ),
    "P07": (
        "tests/integration/test_m1d_adversarial_matrix.py::test_p07_package_identity_changes_only_for_python_bytes",
        "tests/unit/test_observation_contracts.py::test_m1d_fingerprint_delegates_to_whole_installed_package_inventory",
    ),
    "P08": (
        "tests/unit/test_normalization.py::test_p08_unimported_python_changes_nested_and_joined_lineage_only",
    ),
    "S01": (
        "tests/unit/test_session_artifacts.py::test_retained_synthetic_winter_and_summer",
        "tests/unit/test_session_artifacts.py::test_generation_uses_pinned_tzif_and_historical_offsets",
    ),
    "S02": (
        "tests/unit/test_session_artifacts.py::test_sparse_unproven_schedule_date_is_indeterminate_not_closed",
    ),
    "S03": (
        "tests/integration/test_m1d_observation_history.py::test_s03_joined_future_emergency_changes_only_later_binding",
    ),
    "S04": (
        "tests/unit/test_session_artifacts.py::test_realized_dataset_retains_late_early_and_interruption_without_schedule",
        "tests/unit/test_session_binding.py::test_realized_actual_interval_remains_authoritative_when_schedule_differs",
    ),
    "S05": (
        "tests/unit/test_session_binding.py::test_unknown_or_unbounded_realization_never_authorizes_a_completed_bar",
    ),
    "S06": (
        "tests/unit/test_session_artifacts.py::test_realized_report_retains_independent_axes_without_schedule",
    ),
    "S07": (
        "tests/integration/test_m1d_observation_history.py::test_s07_joined_schedule_correction_preserves_old_replay",
    ),
    "S08": (
        "tests/unit/test_session_artifacts.py::test_changed_producer_lineage_preserves_semantic_output_only",
        "tests/unit/test_session_artifacts.py::test_authorized_utc_change_updates_semantic_and_derivation_identity",
    ),
    "S09": (
        "tests/unit/test_session_artifacts.py::test_ambiguous_local_time_requires_fold_and_fold_one_is_exact",
        "tests/unit/test_session_artifacts.py::test_nonexistent_local_gap_is_conflict",
        "tests/unit/test_session_artifacts.py::test_public_generation_and_replay_need_no_ambient_timezone_lookup",
    ),
    "S10": (
        "tests/unit/test_session_binding.py::test_realized_actual_interval_remains_authoritative_when_schedule_differs",
    ),
    "S11": (
        "tests/unit/test_session_binding.py::test_unknown_auction_endpoint_policy_is_not_completed_bar_authority",
    ),
    "S12": (
        "tests/unit/test_session_artifacts.py::test_realized_report_retains_independent_axes_without_schedule",
        "tests/unit/test_session_artifacts.py::test_realized_payload_hash_survives_dump_load_and_rejects_substitution",
    ),
    "S13": (
        "tests/unit/test_session_artifacts.py::test_modern_reconstruction_after_cutoff_does_not_claim_historical_authority",
    ),
    "S14": (
        "tests/unit/test_session_artifacts.py::test_unknown_or_unsupported_historical_offset_is_indeterminate",
    ),
    "S15": (
        "tests/unit/test_session_artifacts.py::test_newer_conflicting_tzif_is_conflict_without_eligible_utc_bounds",
    ),
    "S16": (
        "tests/unit/test_session_artifacts.py::test_semantic_output_identity_ignores_unused_tzif_and_producer_lineage",
    ),
    "S17": (
        "tests/unit/test_session_artifacts.py::test_historical_offset_correction_uses_fresh_context_and_preserves_old_replay",
    ),
    "S18": (
        "tests/unit/test_session_artifacts.py::test_historical_methodology_crosses_cutoff_but_modern_capture_does_not",
    ),
    "S19": (
        "tests/unit/test_session_artifacts.py::test_mismatched_or_foreign_offset_evidence_is_indeterminate",
        "tests/unit/test_session_artifacts.py::test_wrong_fold_conflicts_with_historical_offset_authority",
    ),
    "S20": (
        "tests/unit/test_session_artifacts.py::test_unsupported_raw_precision_stops_before_ambient_timezone_parsing",
        "tests/unit/test_session_artifacts.py::test_public_generation_and_replay_need_no_ambient_timezone_lookup",
    ),
    "S21": (
        "tests/unit/test_session_artifacts.py::test_policy_methodology_set_must_equal_selected_boundary_claims",
        "tests/unit/test_session_artifacts.py::test_timezone_and_generation_policy_require_exact_contract_hashes",
    ),
    "T01": (
        "tests/unit/test_observation_selection.py::test_completed_bar_cannot_be_selected_at_same_day_open",
    ),
    "T02": (
        "tests/integration/test_m1d_observation_history.py::test_t02_joined_finite_correction_selects_original_then_revision",
    ),
    "T03": (
        "tests/unit/test_observation_selection.py::test_contract_must_be_available_independently_of_early_source_publication",
        "tests/unit/test_session_artifacts.py::test_modern_reconstruction_after_cutoff_does_not_claim_historical_authority",
    ),
    "T04": (
        "tests/unit/test_observation_usability.py::test_outcome_vintage_controls_inner_as_known_lifecycle",
    ),
    "T05": (
        "tests/unit/test_observation_selection.py::test_backdated_completion_companion_remains_indeterminate_at_later_vintage",
        "tests/unit/test_observation_selection.py::test_corrected_realized_evidence_can_become_selectable_after_completion",
    ),
    "T06": (
        "tests/unit/test_observation_selection.py::test_finite_vintage_selects_the_correction_only_after_it_is_available",
        "tests/unit/test_observation_contracts.py::test_selected_daily_record_binds_every_query_subject_dimension",
    ),
}

TASK8_IDS = frozenset({"C03"})


def _utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _normalization_policy(
    mode: Literal["source_basis", "split_normalized"], mapping_hash: str
) -> tuple[str, bytes]:
    policy = NormalizationPolicyV1(
        policy_id=f"synthetic-{mode}-policy",
        policy_version="1",
        mode=mode,
        profile_hash=regular_session_trade_bar_profile_hash(),
        mapping_policy_hash=mapping_hash if mode == "split_normalized" else None,
        price_output_scale=2 if mode == "split_normalized" else None,
        volume_output_scale=0 if mode == "split_normalized" else None,
        rounding="half_even",
        semantic_algorithm_hash=normalization_algorithm_hash(),
        implementation_hash=m1d_implementation_hash(),
    )
    data = canonical_json(policy)
    return sha256(data).hexdigest(), data


@dataclass(frozen=True)
class JoinedScenario:
    """One scenario-owned, complete M1b/M1c/M1d normalization input."""

    context: M1dResolutionContext
    query: NormalizationQueryV1

    def normalize(self) -> NormalizationResultV1:
        return normalize_observation(self.query, self.context)

    def with_query(
        self,
        *,
        outer_kind: Literal["decision", "outcome"] | None = None,
        mode: Literal["source_basis", "split_normalized"] | None = None,
        anchor_date: date | None = None,
        decision_time: datetime | None = None,
        knowledge_cutoff: datetime | None = None,
        effective_cutoff: datetime | None = None,
    ) -> JoinedScenario:
        old = self.query.observation
        role = old.kind if outer_kind is None else outer_kind
        target_mode = (
            NormalizationPolicyV1.model_validate_json(
                self.context.supporting_artifacts[self.query.policy_hash].data
            ).mode
            if mode is None
            else mode
        )
        policy_hash = next(
            digest
            for digest, artifact in self.context.supporting_artifacts.items()
            if _is_normalization_policy(artifact, target_mode)
        )
        old_k = (
            old.knowledge_cutoff
            if isinstance(old, ObservationDecisionQueryV1)
            else old.evidence_vintage_cutoff
        )
        old_e = (
            old.effective_cutoff
            if isinstance(old, ObservationDecisionQueryV1)
            else old.economic_horizon
        )
        common = {
            "listing_id": old.listing_id,
            "security_id": old.security_id,
            "venue": old.venue,
            "session_date": old.session_date,
            "source_id": old.source_id,
            "contract_hash": old.contract_hash,
            "source_selection_policy_hash": old.source_selection_policy_hash,
            "profile_hash": old.profile_hash,
            "requested_channel": old.requested_channel,
            "availability_policy_id": old.availability_policy_id,
            "availability_policy_hash": old.availability_policy_hash,
            "input_context_hash": _query_context_hash(self.context, target_mode),
        }
        observation: ObservationQueryV1
        if role == "decision":
            observation = ObservationDecisionQueryV1(
                kind="decision",
                decision_time=decision_time
                or (
                    old.decision_time
                    if isinstance(old, ObservationDecisionQueryV1)
                    else old_k
                ),
                knowledge_cutoff=knowledge_cutoff or old_k,
                effective_cutoff=effective_cutoff or old_e,
                **cast(Any, common),
            )
        else:
            observation = ObservationOutcomeQueryV1(
                kind="outcome",
                economic_horizon=effective_cutoff or old_e,
                evidence_vintage_cutoff=knowledge_cutoff or decision_time or old_k,
                **cast(Any, common),
            )
        anchor = (
            None
            if target_mode == "source_basis"
            else SessionKeyV1(
                mic=observation.venue.value,
                session_scope="regular",
                local_date=anchor_date
                or (
                    self.query.anchor_session.local_date
                    if self.query.anchor_session is not None
                    else observation.session_date
                ),
            )
        )
        return JoinedScenario(
            context=self.context,
            query=NormalizationQueryV1(
                observation=observation,
                policy_hash=policy_hash,
                anchor_session=anchor,
            ),
        )


def _is_normalization_policy(
    artifact: VerifiedArtifactBytes,
    mode: Literal["source_basis", "split_normalized"],
) -> bool:
    try:
        return bool(
            NormalizationPolicyV1.model_validate_json(artifact.data).mode == mode
        )
    except ValidationError:
        return False


def _query_context_hash(
    context: M1dResolutionContext,
    mode: Literal["source_basis", "split_normalized"],
) -> str:
    if mode == "source_basis":
        context = replace(context, economic_context=None, economic_source_policy=None)
    return m1d_context_hash(context)


def _replace_session_dataset(
    context: M1dResolutionContext,
    role: str,
    records: tuple[Any, ...],
    support: dict[str, VerifiedArtifactBytes],
    retained: dict[str, Any],
) -> M1dResolutionContext:
    old = next(
        item
        for item in context.session_datasets
        if item.manifest.dataset_role.name == role
    )
    changed = session_dataset(cast(Any, role), records, support)
    return replace(
        context,
        session_datasets=tuple(
            changed if item is old else item for item in context.session_datasets
        ),
        supporting_artifacts=support,
        retained_evidence=retained,
    )


def _with_future_emergency(
    context: M1dResolutionContext, emergency_date: date
) -> M1dResolutionContext:
    support = dict(context.supporting_artifacts)
    retained = dict(context.retained_evidence)
    dataset = next(
        item
        for item in context.session_datasets
        if item.manifest.dataset_role.name == "realized_session"
    )
    original = cast(
        RealizedSessionVersionV1,
        next(
            item
            for item in dataset.records
            if cast(RealizedSessionVersionV1, item).session_key.local_date
            == emergency_date
        ),
    )
    available_at = datetime.combine(
        emergency_date, datetime.min.time(), UTC
    ) + timedelta(hours=23)
    availability = original.revision.availability[0].model_copy(
        update={
            "lower_bound": available_at,
            "upper_bound": available_at,
            "source_time_label": available_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    retained[content_hash(availability)] = availability
    revision = original.revision.model_copy(
        update={
            "record_version_id": session_uid(5290 + emergency_date.day),
            "revision_kind": RevisionKind.CORRECTION,
            "supersedes_record_version_id": original.revision.record_version_id,
            "source_sequence": original.revision.source_sequence + 1,
            "availability": (availability,),
            "payload_hash": "0" * 64,
        }
    )
    completion = {
        "schema_version": "1",
        "kind": "realized_session_completion",
        "source_id": original.source_id,
        "session_key": original.session_key,
        "outcome": "did_not_open",
        "logical_record_id": revision.logical_record_id,
        "record_version_id": revision.record_version_id,
        "source_artifact_hash": revision.source_artifact.content_hash,
        "record_availability_evidence_hash": content_hash(availability),
        "completion_time": session_boundary_at(available_at, 5295 + emergency_date.day),
    }
    completion_bytes = canonical_json(completion)
    completion_hash = sha256(completion_bytes).hexdigest()
    support[completion_hash] = VerifiedArtifactBytes(
        data=completion_bytes,
        byte_size=len(completion_bytes),
        content_hash=completion_hash,
    )
    values = {name: getattr(original, name) for name in type(original).model_fields}
    values.update(
        {
            "revision": revision,
            "outcome": "did_not_open",
            "actual_open": None,
            "actual_close": None,
            "source_evidence_hashes": tuple(
                sorted((*original.source_evidence_hashes, completion_hash))
            ),
        }
    )
    provisional = RealizedSessionVersionV1.model_construct(**values)
    values["revision"] = revision.model_copy(
        update={"payload_hash": content_hash(assertion_version_payload(provisional))}
    )
    correction = RealizedSessionVersionV1.model_validate(values)
    records = tuple(
        sorted(
            (*dataset.records, correction),
            key=lambda item: (
                str(item.revision.logical_record_id),
                item.revision.source_sequence,
            ),
        )
    )
    return _replace_session_dataset(
        context, "realized_session", records, support, retained
    )


def _retime_schedule_correction(context: M1dResolutionContext) -> M1dResolutionContext:
    support = dict(context.supporting_artifacts)
    retained = dict(context.retained_evidence)
    dataset = next(
        item
        for item in context.session_datasets
        if item.manifest.dataset_role.name == "scheduled_session"
    )
    candidates = [
        cast(ScheduledSessionVersionV1, item)
        for item in dataset.records
        if cast(ScheduledSessionVersionV1, item).session_key.local_date
        == date(2026, 11, 27)
    ]
    correction = max(candidates, key=lambda item: item.revision.source_sequence)
    available_at = datetime(2026, 11, 29, tzinfo=UTC)
    availability = correction.revision.availability[0].model_copy(
        update={
            "lower_bound": available_at,
            "upper_bound": available_at,
            "source_time_label": available_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    retained[content_hash(availability)] = availability
    revision = correction.revision.model_copy(
        update={"availability": (availability,), "payload_hash": "0" * 64}
    )
    values = {name: getattr(correction, name) for name in type(correction).model_fields}
    values["revision"] = revision
    provisional = ScheduledSessionVersionV1.model_construct(**values)
    values["revision"] = revision.model_copy(
        update={"payload_hash": content_hash(assertion_version_payload(provisional))}
    )
    changed = ScheduledSessionVersionV1.model_validate(values)
    records = tuple(changed if item is correction else item for item in dataset.records)
    changed_context = _replace_session_dataset(
        context, "scheduled_session", records, support, retained
    )
    scheduled = next(
        item
        for item in changed_context.session_datasets
        if item.manifest.dataset_role.name == "scheduled_session"
    )
    coverage_dataset = next(
        item
        for item in changed_context.session_datasets
        if item.manifest.dataset_role.name == "session_coverage"
    )
    coverage = cast(SessionCoverageVersionV1, coverage_dataset.records[0])
    coverage_values = {
        name: getattr(coverage, name) for name in type(coverage).model_fields
    }
    coverage_values.update(
        {
            "covered_dataset_hashes": (manifest_hash(scheduled.manifest),),
            "covered_partition_hashes": tuple(
                item.artifact.content_hash for item in scheduled.manifest.partitions
            ),
            "record_inventory": tuple(
                SessionInventoryEntryV1(
                    assertion_id=item.revision.logical_record_id,
                    version_id=item.revision.record_version_id,
                    record_hash=content_hash(item),
                )
                for item in scheduled.records
            ),
        }
    )
    revision = coverage.revision.model_copy(update={"payload_hash": "0" * 64})
    coverage_values["revision"] = revision
    provisional_coverage = SessionCoverageVersionV1.model_construct(**coverage_values)
    coverage_values["revision"] = revision.model_copy(
        update={
            "payload_hash": content_hash(
                assertion_version_payload(provisional_coverage)
            )
        }
    )
    changed_coverage = SessionCoverageVersionV1.model_validate(coverage_values)
    return _replace_session_dataset(
        changed_context,
        "session_coverage",
        (changed_coverage,),
        dict(changed_context.supporting_artifacts),
        dict(changed_context.retained_evidence),
    )


def joined_scenario(
    *,
    outer_kind: Literal["decision", "outcome"] = "outcome",
    mode: Literal["source_basis", "split_normalized"] = "split_normalized",
    source_mutation: Literal[
        "none",
        "correction",
        "split_adjusted",
        "dividend_adjusted",
        "unknown_basis",
        "mixed_adjustment_basis",
        "official_close_unproven",
        "official_close_equivalent",
        "mixed_population",
    ] = "none",
    action_basis: str = "2026-11-27T18:05:00Z",
    mapping_mode: Literal[
        "explicit_first_basis_date", "exact_trading_basis_transition"
    ] = "exact_trading_basis_transition",
    date_role: EconomicDateRole | None = None,
    emergency_date: date | None = None,
    corrected_schedule_state: Literal["closed", "unknown"] | None = None,
    method_mic: str = "XNYS",
    correction_basis: str | None = None,
    duplicate: Literal["none", "equal", "conflict_outside_window"] = "none",
    omit_effect: bool = False,
    omit_terms: bool = False,
    ratio: tuple[str, str] = ("2", "1"),
    action_kind: ActionKind = ActionKind.FORWARD_SPLIT,
    source_session_date: date | None = None,
    anchor_date: date = date(2026, 11, 30),
    decision_time: datetime,
    knowledge_cutoff: datetime,
    effective_cutoff: datetime,
) -> JoinedScenario:
    """Compose one joined scenario through the accepted public validators."""
    source_session_date = source_session_date or (
        date(2026, 11, 25) if correction_basis is not None else date(2026, 11, 27)
    )
    action = action_session_case(
        action_basis,
        mapping_mode,
        date_role=date_role,
        emergency_date=None,
        corrected_schedule_state=corrected_schedule_state,
        method_mic=method_mic,
        correction_basis=correction_basis,
        duplicate=duplicate,
        omit_effect=omit_effect,
        omit_terms=omit_terms,
        ratio=ratio,
        action_kind=action_kind,
        terms_action_kind=action_kind,
        outer_kind=outer_kind,
        include_prior_open=(
            correction_basis is not None or source_session_date == date(2026, 11, 25)
        ),
        economic_through=effective_cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    source = ObservationHarness(
        session_date=source_session_date,
        close="100.000",
        available_at=(
            "2026-11-25T21:05:00Z"
            if source_session_date == date(2026, 11, 25)
            else "2026-11-27T18:05:00Z"
        ),
        security_id=action.query.security_id,
        listing_id=action.query.listing_id,
        issuer_id=economic_uid(20),
        claimed_open_utc=(14, 30),
        claimed_close_utc=(
            (21, 0) if source_session_date == date(2026, 11, 25) else (18, 0)
        ),
    )
    # ObservationHarness needs the issuer bound by its genuine M1b fixture. Its
    # default issuer is intentionally retained; action identity is the security.
    if source_mutation == "correction":
        source.replace_source_revision(
            close="99.500", available_at="2026-11-29T00:00:00Z"
        )
    elif source_mutation == "mixed_adjustment_basis":
        methods = tuple(
            item.model_copy(
                update={
                    "adjustment_basis": (
                        "unadjusted"
                        if item.field_name == "volume"
                        else "split_adjusted"
                    )
                }
            )
            for item in source._contract.field_methods
        )
        source._replace_contract(adjustment_basis="mixed", field_methods=methods)
        source._rebuild()
    elif source_mutation != "none":
        source.use_field_case(source_mutation)
    source.attach_m1b()
    action_context = action.context
    if emergency_date is not None:
        action_context = _with_future_emergency(action_context, emergency_date)
    if corrected_schedule_state is not None:
        action_context = _retime_schedule_correction(action_context)
    action_policy = ObservationSourceSelectionPolicyV1.model_validate_json(
        action_context.supporting_artifacts[
            action.query.outer_query.source_selection_policy_hash
        ].data
    )
    by_role = {
        item.manifest.dataset_role.name: manifest_hash(item.manifest)
        for item in action_context.session_datasets
    }
    action_policy = action_policy.model_copy(
        update={
            "bindings": tuple(
                binding.model_copy(
                    update={"manifest_hashes": (by_role[binding.dataset_role],)}
                )
                if binding.dataset_role in by_role
                else binding
                for binding in action_policy.bindings
            )
        }
    )
    combined_policy = ObservationSourceSelectionPolicyV1(
        policy_id="normalization-source-authority",
        version="1",
        bindings=(*source._observation_bindings, *action_policy.bindings),
    )
    combined_bytes = canonical_json(combined_policy)
    combined_hash = sha256(combined_bytes).hexdigest()
    source_policy_hash, source_policy_bytes = _normalization_policy(
        "source_basis", action.query.action_session_policy_hash
    )
    split_policy_hash, split_policy_bytes = _normalization_policy(
        "split_normalized", action.query.action_session_policy_hash
    )
    schedule_context, _schedule_query, schedule_policy = generation_case(
        local_date=source_session_date
    )
    schedule_policy_bytes = canonical_json(schedule_policy)
    schedule_policy_hash = sha256(schedule_policy_bytes).hexdigest()
    support = {
        **dict(source.context.supporting_artifacts),
        **dict(action_context.supporting_artifacts),
        **dict(schedule_context.supporting_artifacts),
        combined_hash: VerifiedArtifactBytes(
            data=combined_bytes,
            byte_size=len(combined_bytes),
            content_hash=combined_hash,
        ),
        source_policy_hash: VerifiedArtifactBytes(
            data=source_policy_bytes,
            byte_size=len(source_policy_bytes),
            content_hash=source_policy_hash,
        ),
        split_policy_hash: VerifiedArtifactBytes(
            data=split_policy_bytes,
            byte_size=len(split_policy_bytes),
            content_hash=split_policy_hash,
        ),
        schedule_policy_hash: VerifiedArtifactBytes(
            data=schedule_policy_bytes,
            byte_size=len(schedule_policy_bytes),
            content_hash=schedule_policy_hash,
        ),
    }
    context = M1dResolutionContext(
        observation_datasets=source.context.observation_datasets,
        session_datasets=action_context.session_datasets,
        availability_policies={
            **dict(source.context.availability_policies),
            **dict(action_context.availability_policies),
        },
        retained_evidence={
            **dict(source.context.retained_evidence),
            **dict(action_context.retained_evidence),
        },
        supporting_artifacts=support,
        structural_context=source.context.structural_context,
        research_definition=source.context.research_definition,
        issuer_id=source.context.issuer_id,
        structural_methodology_id=source.context.structural_methodology_id,
        m1b_requested_channel=source.context.m1b_requested_channel,
        schedule_generation_policy_hash=schedule_policy_hash,
        economic_context=action_context.economic_context,
        economic_source_policy=action_context.economic_source_policy,
    )
    base: ObservationQueryV1
    if outer_kind == "decision":
        base = source.decision(
            decision_time.isoformat(),
            knowledge_cutoff.isoformat(),
            effective_cutoff.isoformat(),
            source.session_date.isoformat(),
        )
    else:
        base = source.outcome(
            effective_cutoff.isoformat(),
            knowledge_cutoff.isoformat(),
            source.session_date.isoformat(),
        )
    observation = base.model_copy(
        update={
            "source_selection_policy_hash": combined_hash,
            "input_context_hash": _query_context_hash(context, mode),
        }
    )
    return JoinedScenario(
        context=context,
        query=NormalizationQueryV1(
            observation=observation,
            policy_hash=(
                source_policy_hash if mode == "source_basis" else split_policy_hash
            ),
            anchor_session=(
                None
                if mode == "source_basis"
                else SessionKeyV1(
                    mic="XNYS", session_scope="regular", local_date=anchor_date
                )
            ),
        ),
    )


def matrix_index_bytes() -> bytes:
    rows = tuple(
        {
            "id": matrix_id,
            "coverage": (
                "joined"
                if matrix_id in REQUIRED_JOINED_IDS
                else "task8"
                if matrix_id in TASK8_IDS
                else "focused"
            ),
            "pointers": MATRIX_POINTERS[matrix_id],
        }
        for matrix_id in sorted(MATRIX_POINTERS)
    )
    return canonical_json(
        {"schema_version": "1", "matrix_version": "m1d-v1", "rows": rows}
    )


def _put(objects: dict[str, bytes], value: object) -> str:
    return _put_bytes(objects, canonical_json(value))


def _put_bytes(objects: dict[str, bytes], data: bytes) -> str:
    digest = sha256(data).hexdigest()
    existing = objects.setdefault(digest, data)
    if existing != data:
        raise ValueError("SHA-256 collision in fixture payloads")
    return digest


def _put_verified(objects: dict[str, bytes], value: VerifiedArtifactBytes) -> str:
    digest = _put_bytes(objects, value.data)
    if digest != value.content_hash or value.byte_size != len(value.data):
        raise ValueError("invalid verified artifact in fixture source context")
    return digest


def _run_from_decision(decision: Any) -> dict[str, object]:
    return {
        "decision_id": decision.decision_id,
        "validator_version": decision.validator_version,
        "validator_implementation_hash": decision.validator_implementation_hash,
        "validation_profile_id": decision.validation_profile_id,
        "validation_profile_hash": decision.validation_profile_hash,
        "checked_at": decision.checked_at,
    }


def _m1d_dataset_descriptor(
    objects: dict[str, bytes], dataset: Any
) -> dict[str, object]:
    partitions = tuple(
        _put_verified(objects, item) for item in dataset.artifacts.values()
    )
    expected = tuple(
        sorted(part.artifact.content_hash for part in dataset.manifest.partitions)
    )
    if tuple(sorted(partitions)) != expected:
        raise ValueError("M1d fixture partition closure mismatch")
    return {
        "manifest": _put(objects, dataset.manifest),
        "validation_run": _put(objects, dataset.validation_run),
        "decision": _put(objects, dataset.decision),
        "bundle": _put(objects, dataset.bundle),
        "partition_objects": partitions,
    }


def _m1b_records_descriptor(
    objects: dict[str, bytes], name: str, records: Any
) -> dict[str, object]:
    if len(records.manifest.partitions) != 1:
        raise ValueError("fixture serializer expects one M1b partition per role")
    data = canonical_json({"schema_version": "1", "records": records.records})
    partition = _put_bytes(objects, data)
    if partition != records.manifest.partitions[0].artifact.content_hash:
        raise ValueError("reconstructed M1b partition differs from manifest")
    model_name = (
        type(records.records[0]).__name__
        if records.records
        else {"terminations": "ListingTerminationVersionV1"}.get(name)
    )
    return {
        "name": name,
        "record_model": model_name,
        "manifest": _put(objects, records.manifest),
        "validation_run": _put(objects, _run_from_decision(records.decision)),
        "decision": _put(objects, records.decision),
        "partition_objects": (partition,),
    }


def _economic_dataset_descriptor(
    objects: dict[str, bytes], dataset: Any
) -> dict[str, object]:
    partitions = tuple(
        _put_verified(objects, item) for item in dataset.verified_artifacts
    )
    return {
        "manifest": _put(objects, dataset.manifest),
        "validation_run": _put(objects, dataset.validation_run),
        "decision": _put(objects, dataset.decision),
        "bundle": _put(objects, dataset.bundle),
        "partition_objects": partitions,
    }


def _context_descriptor(
    objects: dict[str, bytes], context: M1dResolutionContext
) -> dict[str, object]:
    descriptor: dict[str, object] = {
        "schema_version": "1",
        "context_hash": m1d_context_hash(context),
        "observation_datasets": tuple(
            _m1d_dataset_descriptor(objects, item)
            for item in context.observation_datasets
        ),
        "session_datasets": tuple(
            _m1d_dataset_descriptor(objects, item) for item in context.session_datasets
        ),
        "availability_policies": {
            digest: _put(objects, value)
            for digest, value in sorted(context.availability_policies.items())
        },
        "retained_evidence": {
            digest: _put(objects, value)
            for digest, value in sorted(context.retained_evidence.items())
        },
        "supporting_artifacts": {
            digest: _put_verified(objects, value)
            for digest, value in sorted(context.supporting_artifacts.items())
        },
        "schedule_generation_policy_hash": context.schedule_generation_policy_hash,
    }
    if context.structural_context is not None:
        structural = context.structural_context
        universe = structural.universe
        collections = (
            ("assignments", universe.assignments),
            ("memberships", universe.memberships),
            ("source_definitions", universe.source_definitions),
            ("relationships", structural.relationships),
            ("classifications", structural.classifications),
            ("roles", structural.roles),
            ("lifecycle", structural.lifecycle),
            ("terminations", structural.terminations),
            ("coverage", structural.coverage),
        )
        descriptor["m1b"] = {
            "research_definition": _put(objects, context.research_definition),
            "issuer_id": str(context.issuer_id),
            "structural_methodology_id": context.structural_methodology_id,
            "requested_channel": _put(objects, context.m1b_requested_channel),
            "identity_bundle": _put(objects, universe.identity_bundle),
            "universe_bundle": _put(objects, universe.universe_bundle),
            "availability_policy": _put(objects, universe.policy),
            "retained_evidence": {
                digest: _put(objects, value)
                for digest, value in sorted(universe.retained_evidence.items())
            },
            "collections": tuple(
                _m1b_records_descriptor(objects, name, value)
                for name, value in collections
            ),
        }
    if context.economic_context is not None:
        economic = context.economic_context
        descriptor["m1c"] = {
            "source_policy": _put(objects, context.economic_source_policy),
            "availability_policy": _put(objects, economic.availability_policy),
            "retained_evidence": {
                digest: _put(objects, value)
                for digest, value in sorted(economic.retained_evidence.items())
            },
            "supporting_artifacts": tuple(
                _put_verified(objects, value) for value in economic.supporting_artifacts
            ),
            "datasets": tuple(
                _economic_dataset_descriptor(objects, item)
                for item in economic.datasets
            ),
            "identity": _economic_dataset_descriptor(objects, economic.identity),
        }
    return descriptor


def fixture_payloads() -> dict[str, bytes]:
    decision = joined_scenario(
        outer_kind="decision",
        decision_time=datetime(2026, 12, 2, tzinfo=UTC),
        knowledge_cutoff=datetime(2026, 12, 2, tzinfo=UTC),
        effective_cutoff=datetime(2026, 12, 1, tzinfo=UTC),
    )
    outcome = decision.with_query(outer_kind="outcome")
    decision_result = decision.normalize()
    outcome_result = outcome.normalize()
    if decision_result.reference is None or outcome_result.reference is None:
        raise ValueError("joined fixture requires materialized decision and outcome")
    verify_normalization(decision_result, decision.context)
    verify_normalization(outcome_result, outcome.context)
    objects: dict[str, bytes] = {}
    joined_context = _context_descriptor(objects, decision.context)
    policy_hash = decision.context.schedule_generation_policy_hash
    if policy_hash is None:
        raise ValueError("joined fixture requires schedule generation policy")
    schedule_policy = ScheduleGenerationPolicyV1.model_validate_json(
        decision.context.supporting_artifacts[policy_hash].data
    )
    schedule = generate_schedule(
        decision.query.observation, decision.context, schedule_policy
    )
    schedule = schedule.model_copy(
        update={"generated_at": datetime(2027, 1, 2, tzinfo=UTC)}
    )
    if schedule.classification != "generated" or len(schedule.rows) != 1:
        raise ValueError("joined fixture schedule must generate one consumed session")
    tzif_digest = schedule.timezone_bytes_hash
    payloads = {
        "fixture-metadata.json": canonical_json(
            {
                "schema_version": "1",
                "fixture_version": "m1d/v1",
                "joined_normalization_context": "joined-context.json",
                "joined_schedule_generation": {
                    "context": "joined-context.json",
                    "artifact": "joined-schedule-result.json",
                    "tzif_object_hash": tzif_digest,
                    "consumed_by_joined_normalization": True,
                    "purpose": (
                        "replay of the source session consumed by joined normalization"
                    ),
                },
            }
        ),
        "joined-context.json": canonical_json(joined_context),
        "joined-schedule-result.json": canonical_json(schedule),
        "expected-decision-query.json": canonical_json(decision.query),
        "expected-decision-result.json": canonical_json(decision_result),
        "expected-outcome-query.json": canonical_json(outcome.query),
        "expected-outcome-result.json": canonical_json(outcome_result),
        "matrix-index.json": matrix_index_bytes(),
    }
    payloads.update(
        {f"objects/sha256/{digest}": data for digest, data in objects.items()}
    )
    return payloads


def _hash_index_bytes(payloads: dict[str, bytes]) -> bytes:
    entries = tuple(
        {
            "path": name,
            "byte_size": len(data),
            "sha256": sha256(data).hexdigest(),
        }
        for name, data in sorted(payloads.items())
    )
    return canonical_json(
        {
            "schema_version": "1",
            "fixture_version": "m1d/v1",
            "entries": entries,
        }
    )


def _reserve_fixture_target(target: Path) -> tuple[int, Path]:
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = target.parent / f".{target.name}.generation.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise FileExistsError("M1d fixture target is exclusively reserved") from error
    return descriptor, lock


def write_closed_payloads(target: Path, payloads: dict[str, bytes]) -> None:
    for name, data in sorted(payloads.items()):
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def write_fixture_v1(
    target: Path = FIXTURE_ROOT,
    *,
    payload_factory: Callable[[], dict[str, bytes]] = fixture_payloads,
) -> None:
    descriptor, lock = _reserve_fixture_target(target)
    try:
        if target.exists():
            raise FileExistsError("accepted M1d v1 fixture cannot be overwritten")
        payloads = payload_factory()
        payloads["hash-index.json"] = _hash_index_bytes(payloads)
        with TemporaryDirectory(prefix=".m1d-v1-", dir=target.parent) as temporary:
            staged = Path(temporary)
            write_closed_payloads(staged, payloads)
            staged.rename(target)
    finally:
        os.close(descriptor)
        lock.unlink()


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", nargs="?", type=Path, default=FIXTURE_ROOT)
    arguments = parser.parse_args()
    write_fixture_v1(arguments.target)


if __name__ == "__main__":
    _main()
