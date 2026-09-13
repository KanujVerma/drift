"""Behavioral and algebraic tests for causal observation normalization."""

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from fractions import Fraction
from itertools import permutations
from math import gcd
from pathlib import Path
from typing import Literal, cast

import pytest
from observation_test_support import NormalizationHarness
from pydantic import ValidationError

from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.economic_common import ActionKind, economic_implementation_hash
from drift.domain.normalization import (
    DerivedObservationViewV1,
    ExactRatioV1,
    FieldTransformV1,
    NormalizationPolicyV1,
    NormalizationResultV1,
    ObservationDecisionReferenceV1,
    normalization_algorithm_hash,
)
from drift.domain.observation_query import m1d_implementation_hash
from drift.domain.observations import DailySourceObservationVersionV1
from drift.markets.normalization import (
    compose_split_factors,
    materialize_observation_decision,
    materialize_observation_outcome,
    quantize_exact_ratio,
    verify_normalization,
)
from drift.serialization.canonical import content_hash

COPRIME_RATIOS = tuple(
    (numerator, denominator)
    for numerator in range(1, 13)
    for denominator in range(1, 13)
    if gcd(numerator, denominator) == 1
)


@pytest.mark.parametrize(("numerator", "denominator"), COPRIME_RATIOS)
def test_n04_composed_split_factors_are_exact_reciprocals(
    numerator: int, denominator: int
) -> None:
    price, share_volume = compose_split_factors(
        (ExactRatioV1(numerator=str(numerator), denominator=str(denominator)),)
    )

    assert Fraction(int(price.numerator), int(price.denominator)) == Fraction(
        denominator, numerator
    )
    assert Fraction(
        int(share_volume.numerator), int(share_volume.denominator)
    ) == Fraction(numerator, denominator)


@pytest.mark.parametrize(
    "ratios",
    (
        ((3, 2), (2, 3)),
        ((2, 1), (1, 10), (5, 1)),
        ((7, 3), (5, 4), (12, 7)),
    ),
)
def test_n05_pure_split_composition_is_permutation_invariant(
    ratios: tuple[tuple[int, int], ...],
) -> None:
    observed = {
        tuple(
            (factor.numerator, factor.denominator)
            for factor in compose_split_factors(
                tuple(
                    ExactRatioV1(numerator=str(n), denominator=str(d))
                    for n, d in ordering
                )
            )
        )
        for ordering in permutations(ratios)
    }

    assert len(observed) == 1


def test_n05_reciprocal_sequence_reduces_to_identity_before_rounding() -> None:
    factors = compose_split_factors(
        (
            ExactRatioV1(numerator="3", denominator="2"),
            ExactRatioV1(numerator="2", denominator="3"),
        )
    )

    assert tuple((factor.numerator, factor.denominator) for factor in factors) == (
        ("1", "1"),
        ("1", "1"),
    )


def test_n05_identity_ratio_preserves_both_units() -> None:
    price, share_volume = compose_split_factors(
        (ExactRatioV1(numerator="1", denominator="1"),)
    )

    assert (price.numerator, price.denominator) == ("1", "1")
    assert (share_volume.numerator, share_volume.denominator) == ("1", "1")


def test_n05_same_session_reciprocal_splits_cancel_before_quantization() -> None:
    harness = NormalizationHarness(
        ratio=("3", "2"),
        additional_splits=(
            (
                "2026-11-27T18:10:00Z",
                ("2", "3"),
                ActionKind.REVERSE_SPLIT,
            ),
        ),
    )
    result = harness.normalize(
        harness.normalization_query("split_normalized", anchor_date=date(2026, 11, 30))
    )

    assert result.classification == "materialized"
    assert _field(result, "close").exact_factor == ExactRatioV1(
        numerator="1", denominator="1"
    )
    assert _field(result, "volume").exact_factor == ExactRatioV1(
        numerator="1", denominator="1"
    )
    assert len(result.action_mapping_hashes) == 2


@pytest.mark.parametrize(
    ("numerator", "denominator"),
    (("0", "2"), ("01", "1"), ("1", "0"), ("+1", "1"), ("-0", "1")),
)
def test_exact_ratio_rejects_noncanonical_components(
    numerator: str, denominator: str
) -> None:
    with pytest.raises(ValidationError):
        ExactRatioV1(numerator=numerator, denominator=denominator)


def test_exact_ratio_accepts_only_canonical_reduced_zero() -> None:
    assert ExactRatioV1(numerator="0", denominator="1").model_dump() == {
        "schema_version": "1",
        "numerator": "0",
        "denominator": "1",
    }


def test_source_basis_policy_cannot_claim_mapping_or_quantization() -> None:
    with pytest.raises(ValidationError):
        NormalizationPolicyV1(
            policy_id="source-v1",
            policy_version="1",
            mode="source_basis",
            profile_hash="1" * 64,
            mapping_policy_hash="2" * 64,
            price_output_scale=2,
            volume_output_scale=0,
            rounding="half_even",
            semantic_algorithm_hash=normalization_algorithm_hash(),
            implementation_hash=m1d_implementation_hash(),
        )


def test_split_policy_requires_mapping_and_bounded_scales() -> None:
    with pytest.raises(ValidationError):
        NormalizationPolicyV1(
            policy_id="split-v1",
            policy_version="1",
            mode="split_normalized",
            profile_hash="1" * 64,
            mapping_policy_hash=None,
            price_output_scale=2,
            volume_output_scale=0,
            rounding="half_even",
            semantic_algorithm_hash=normalization_algorithm_hash(),
            implementation_hash=m1d_implementation_hash(),
        )


def test_n06_field_transform_rejects_unadmitted_volume_meaning() -> None:
    with pytest.raises(ValidationError):
        FieldTransformV1(
            field_name="volume",
            method_id="dollar-volume-v1",
            meaning="dollar_volume",  # type: ignore[arg-type]
            source_value=Decimal("1000"),
            exact_factor=ExactRatioV1(numerator="2", denominator="1"),
            exact_transformed_value=ExactRatioV1(numerator="2000", denominator="1"),
            quantized_value=Decimal("2000"),
            output_scale=0,
            rounded_to_zero=False,
        )


def test_field_transform_rejects_nonpositive_applied_factor() -> None:
    with pytest.raises(ValidationError, match="strictly positive"):
        FieldTransformV1(
            field_name="close",
            method_id="close-v1",
            meaning="price",
            source_value=Decimal("100"),
            exact_factor=ExactRatioV1(numerator="-1", denominator="1"),
            exact_transformed_value=ExactRatioV1(numerator="-100", denominator="1"),
            quantized_value=Decimal("-100.00"),
            output_scale=2,
            rounded_to_zero=False,
        )


@pytest.mark.parametrize("scale", range(7))
@pytest.mark.parametrize(
    ("source", "factor", "expected"),
    (
        ("3", (2, 3), Fraction(2)),
        ("0.125", (8, 1), Fraction(1)),
        ("12.50", (1, 10), Fraction(5, 4)),
        ("-1.5", (3, 2), Fraction(-9, 4)),
    ),
)
def test_exact_source_ratio_round_trip_and_scale_do_not_change_unrounded_value(
    source: str, factor: tuple[int, int], expected: Fraction, scale: int
) -> None:
    transformed, _quantized = quantize_exact_ratio(
        Decimal(source),
        ExactRatioV1(numerator=str(factor[0]), denominator=str(factor[1])),
        scale,
    )

    assert (
        Fraction(int(transformed.numerator), int(transformed.denominator)) == expected
    )
    assert expected / Fraction(factor[0], factor[1]) == Fraction(Decimal(source))


@pytest.mark.parametrize(
    ("value", "scale", "expected"),
    (
        ("1.005", 2, "1.00"),
        ("1.015", 2, "1.02"),
        ("-1.005", 2, "-1.00"),
        ("-1.015", 2, "-1.02"),
        ("2.5", 0, "2"),
        ("3.5", 0, "4"),
    ),
)
def test_n11_final_quantization_uses_signed_half_even(
    value: str, scale: int, expected: str
) -> None:
    _exact, quantized = quantize_exact_ratio(
        Decimal(value), ExactRatioV1(numerator="1", denominator="1"), scale
    )

    assert str(quantized) == expected


def test_computational_guard_rejects_huge_decimal_expansion_before_allocation() -> None:
    with pytest.raises(ValueError, match="computational expansion"):
        quantize_exact_ratio(
            Decimal("1e100000000"),
            ExactRatioV1(numerator="1", denominator="1"),
            2,
        )


def test_computational_guard_rejects_factor_product_before_integer_expansion() -> None:
    large = ExactRatioV1(numerator="1" + ("0" * 3000), denominator="1")

    with pytest.raises(ValueError, match="computational expansion"):
        compose_split_factors((large, large))


def _field(result: NormalizationResultV1, name: str) -> FieldTransformV1:
    assert result.view is not None
    return next(item for item in result.view.fields if item.field_name == name)


def test_n01_source_basis_materializes_without_any_m1c_context() -> None:
    harness = NormalizationHarness(source_only=True)
    query = harness.normalization_query("source_basis")

    result = harness.normalize(query)

    assert harness.context.economic_context is None
    assert result.classification == "materialized"
    assert result.view is not None
    assert result.view.basis_mode == "source_basis"
    assert result.view.anchor_session is None
    assert _field(result, "close").source_value == Decimal("100.000")
    assert _field(result, "close").exact_factor == ExactRatioV1(
        numerator="1", denominator="1"
    )
    assert _field(result, "close").exact_transformed_value is None
    assert _field(result, "close").quantized_value is None
    assert result.selected_action_hashes == ()


def test_n01_source_basis_does_not_validate_attached_m1c_inputs() -> None:
    harness = NormalizationHarness()
    query = harness.normalization_query("source_basis")
    assert harness.context.economic_context is not None
    harness.context = replace(
        harness.context,
        economic_context=replace(harness.context.economic_context, datasets=()),
    )

    result = harness.normalize(query)

    assert result.classification == "materialized"
    assert result.selected_action_hashes == ()


def test_n01_split_normalization_uses_only_causal_action_before_anchor() -> None:
    harness = NormalizationHarness()
    query = harness.normalization_query(
        "split_normalized", anchor_date=date(2026, 11, 30)
    )

    result = harness.normalize(query)

    assert result.classification == "materialized"
    assert _field(result, "close").exact_factor == ExactRatioV1(
        numerator="1", denominator="2"
    )
    assert _field(result, "close").exact_transformed_value == ExactRatioV1(
        numerator="50", denominator="1"
    )
    assert _field(result, "close").quantized_value == Decimal("50.00")
    assert _field(result, "volume").exact_factor == ExactRatioV1(
        numerator="2", denominator="1"
    )
    assert _field(result, "volume").quantized_value == Decimal("2000")
    assert len(result.selected_action_hashes) == 1


def test_n02_action_after_anchor_is_not_selected_or_exposed() -> None:
    harness = NormalizationHarness(omit_effect=True)
    query = harness.normalization_query(
        "split_normalized", anchor_date=date(2026, 11, 30)
    )

    result = harness.normalize(query)

    assert result.classification == "materialized"
    assert _field(result, "close").exact_factor == ExactRatioV1(
        numerator="1", denominator="1"
    )
    assert result.selected_action_hashes == ()
    assert result.action_mapping_hashes == ()


def test_n03_anchor_after_decision_effective_cutoff_is_indeterminate() -> None:
    harness = NormalizationHarness(outer_kind="decision")
    query = harness.normalization_query(
        "split_normalized",
        anchor_date=date(2026, 11, 30),
        effective_cutoff="2026-11-28T00:00:00Z",
    )

    result = harness.normalize(query)

    assert result.classification == "indeterminate"
    assert result.view is None
    assert "anchor_basis_beyond_effective_cutoff" in result.reasons


@pytest.mark.parametrize(
    ("ratio", "price_factor", "volume_factor"),
    (
        (("2", "1"), ("1", "2"), ("2", "1")),
        (("1", "10"), ("10", "1"), ("1", "10")),
    ),
)
def test_n04_forward_and_reverse_split_use_reciprocal_units(
    ratio: tuple[str, str],
    price_factor: tuple[str, str],
    volume_factor: tuple[str, str],
) -> None:
    harness = NormalizationHarness(
        ratio=ratio,
        action_kind=(
            ActionKind.FORWARD_SPLIT
            if ratio == ("2", "1")
            else ActionKind.REVERSE_SPLIT
        ),
    )
    result = harness.normalize(
        harness.normalization_query("split_normalized", anchor_date=date(2026, 11, 30))
    )

    assert result.classification == "materialized"
    assert (
        _field(result, "close").exact_factor.numerator,
        _field(result, "close").exact_factor.denominator,
    ) == price_factor
    assert (
        _field(result, "volume").exact_factor.numerator,
        _field(result, "volume").exact_factor.denominator,
    ) == volume_factor


def test_n07_relevant_non_split_share_basis_change_is_indeterminate() -> None:
    harness = NormalizationHarness(action_kind=ActionKind.STOCK_DIVIDEND)
    result = harness.normalize(
        harness.normalization_query("split_normalized", anchor_date=date(2026, 11, 30))
    )

    assert result.classification == "indeterminate"
    assert "unsupported_relevant_share_basis_action" in result.reasons


def test_n08_split_with_cash_component_cannot_be_advertised_as_pure_units() -> None:
    harness = NormalizationHarness(extra_component=True)
    result = harness.normalize(
        harness.normalization_query("split_normalized", anchor_date=date(2026, 11, 30))
    )

    assert result.classification == "indeterminate"
    assert "split_mapping_indeterminate" in result.reasons


def test_n08_independent_cash_only_effect_is_neutral_to_split_units() -> None:
    harness = NormalizationHarness(include_cash_only_effect=True)
    result = harness.normalize(
        harness.normalization_query("split_normalized", anchor_date=date(2026, 11, 30))
    )

    assert result.classification == "materialized"
    assert _field(result, "close").exact_factor == ExactRatioV1(
        numerator="1", denominator="2"
    )
    assert len(result.selected_action_hashes) == 1


def test_n08_same_occurrence_conflict_is_compared_before_anchor_filtering() -> None:
    harness = NormalizationHarness(duplicate="conflict_outside_window")
    result = harness.normalize(
        harness.normalization_query("split_normalized", anchor_date=date(2026, 11, 30))
    )

    assert result.classification == "indeterminate"
    assert "same_occurrence_economic_disagreement" in result.reasons


def test_n09_incomplete_relevant_action_history_blocks_factor_claim() -> None:
    harness = NormalizationHarness(
        coverage_action_kinds=(ActionKind.FORWARD_SPLIT, ActionKind.REVERSE_SPLIT)
    )
    result = harness.normalize(
        harness.normalization_query("split_normalized", anchor_date=date(2026, 11, 30))
    )

    assert result.classification == "indeterminate"
    assert "economic_action_class_coverage_incomplete" in result.reasons


def test_n09_definitely_pre_source_unsupported_event_is_harmless() -> None:
    harness = NormalizationHarness(
        action_kind=ActionKind.STOCK_DIVIDEND,
        basis="2026-11-26T14:00:00Z",
    )
    result = harness.normalize(
        harness.normalization_query("split_normalized", anchor_date=date(2026, 11, 30))
    )

    assert result.classification == "materialized"
    assert result.selected_action_hashes == ()


def test_n10_source_session_already_on_post_basis_gets_identity_factor() -> None:
    harness = NormalizationHarness()
    result = harness.normalize(
        harness.normalization_query("split_normalized", anchor_date=date(2026, 11, 27))
    )

    assert result.classification == "materialized"
    assert _field(result, "close").exact_factor == ExactRatioV1(
        numerator="1", denominator="1"
    )


def test_n11_positive_price_rounding_to_zero_rejects_view() -> None:
    harness = NormalizationHarness(
        numeric_values=("0.004", "0.004", "0.004", "0.004", "1")
    )
    result = harness.normalize(
        harness.normalization_query(
            "split_normalized", anchor_date=date(2026, 11, 27), price_scale=2
        )
    )

    assert result.classification == "unusable"
    assert result.view is None
    assert "positive_price_rounded_to_zero" in result.reasons


def test_n11_share_volume_rounding_to_zero_keeps_exact_nonzero_quantity() -> None:
    harness = NormalizationHarness(
        ratio=("1", "10"),
        action_kind=ActionKind.REVERSE_SPLIT,
        numeric_values=("100", "100", "100", "100", "1"),
    )
    result = harness.normalize(
        harness.normalization_query(
            "split_normalized",
            anchor_date=date(2026, 11, 30),
            volume_scale=0,
        )
    )

    assert result.classification == "materialized"
    volume = _field(result, "volume")
    assert volume.exact_transformed_value == ExactRatioV1(
        numerator="1", denominator="10"
    )
    assert volume.quantized_value == Decimal("0")
    assert volume.rounded_to_zero is True


def test_n11_split_mode_quantizes_only_once_at_final_half_even_tie() -> None:
    harness = NormalizationHarness(
        numeric_values=("1.005", "1.015", "1.005", "1.005", "10")
    )
    result = harness.normalize(
        harness.normalization_query(
            "split_normalized", anchor_date=date(2026, 11, 27), price_scale=2
        )
    )

    assert result.classification == "materialized"
    assert _field(result, "open").quantized_value == Decimal("1.00")
    assert _field(result, "high").quantized_value == Decimal("1.02")


def test_n12_all_fourteen_action_classes_are_required() -> None:
    harness = NormalizationHarness(
        coverage_action_kinds=(ActionKind.FORWARD_SPLIT, ActionKind.REVERSE_SPLIT)
    )
    result = harness.normalize(
        harness.normalization_query("split_normalized", anchor_date=date(2026, 11, 30))
    )

    assert result.classification == "indeterminate"


def test_n13_incomplete_settlement_does_not_block_split_unit_factors() -> None:
    harness = NormalizationHarness(settlement_coverage="partial")
    result = harness.normalize(
        harness.normalization_query("split_normalized", anchor_date=date(2026, 11, 30))
    )

    assert result.classification == "materialized"
    assert _field(result, "close").quantized_value == Decimal("50.00")
    assert "settlement_coverage_incomplete_audit_only" in result.reasons


@pytest.mark.parametrize("kind", ("decision", "outcome"))
def test_p02_result_view_reference_and_output_replay_after_dump_load(kind: str) -> None:
    harness = NormalizationHarness(
        outer_kind=cast(Literal["decision", "outcome"], kind)
    )
    query = harness.normalization_query(
        "split_normalized", anchor_date=date(2026, 11, 30)
    )
    result = harness.normalize(query)
    loaded = NormalizationResultV1.model_validate_json(result.model_dump_json())

    verify_normalization(loaded, harness.context)
    assert loaded.view is not None
    assert loaded.reference is not None
    forged_field = loaded.view.fields[0].model_copy(
        update={"exact_factor": ExactRatioV1(numerator="1", denominator="1")}
    )
    forged_view = DerivedObservationViewV1.model_construct(
        **{
            **{
                name: getattr(loaded.view, name)
                for name in DerivedObservationViewV1.model_fields
            },
            "fields": (forged_field, *loaded.view.fields[1:]),
        }
    )
    forged = NormalizationResultV1.model_construct(
        **{
            **{
                name: getattr(loaded, name)
                for name in NormalizationResultV1.model_fields
            },
            "view": forged_view,
        }
    )
    with pytest.raises(ValueError, match="replay mismatch"):
        verify_normalization(forged, harness.context)


def test_p03_decision_and_outcome_references_are_noninterchangeable() -> None:
    decision_harness = NormalizationHarness(outer_kind="decision")
    decision_query = decision_harness.normalization_query(
        "split_normalized", anchor_date=date(2026, 11, 30)
    )
    decision_result = decision_harness.normalize(decision_query)
    assert isinstance(decision_result.reference, ObservationDecisionReferenceV1)

    with pytest.raises(TypeError):
        materialize_observation_outcome(
            decision_result.reference,  # type: ignore[arg-type]
            decision_query,
            decision_harness.context,
        )


def test_p02_forged_derivation_output_and_reference_each_fail_complete_replay() -> None:
    harness = NormalizationHarness(outer_kind="decision")
    result = harness.normalize(
        harness.normalization_query("split_normalized", anchor_date=date(2026, 11, 30))
    )
    loaded = NormalizationResultV1.model_validate_json(result.model_dump_json())
    assert loaded.view is not None
    assert loaded.derivation is not None
    assert isinstance(loaded.reference, ObservationDecisionReferenceV1)

    forged_view = DerivedObservationViewV1.model_construct(
        **{
            **{
                name: getattr(loaded.view, name)
                for name in DerivedObservationViewV1.model_fields
            },
            "output_hash": "f" * 64,
        }
    )
    forged_derivation = type(loaded.derivation).model_construct(
        **{
            **{
                name: getattr(loaded.derivation, name)
                for name in type(loaded.derivation).model_fields
            },
            "price_factor": ExactRatioV1(numerator="1", denominator="1"),
        }
    )
    forged_reference = ObservationDecisionReferenceV1.model_construct(
        **{
            **{
                name: getattr(loaded.reference, name)
                for name in ObservationDecisionReferenceV1.model_fields
            },
            "view_hash": "f" * 64,
        }
    )
    for update in (
        {"view": forged_view},
        {"derivation": forged_derivation},
        {"reference": forged_reference},
    ):
        forged = NormalizationResultV1.model_construct(
            **{
                **{
                    name: getattr(loaded, name)
                    for name in NormalizationResultV1.model_fields
                },
                **update,
            }
        )
        with pytest.raises(ValueError, match="replay mismatch"):
            verify_normalization(forged, harness.context)


def test_p04_same_numbers_under_changed_policy_have_distinct_lineage() -> None:
    first = NormalizationHarness()
    first_result = first.normalize(
        first.normalization_query(
            "split_normalized", anchor_date=date(2026, 11, 27), price_scale=2
        )
    )
    second = NormalizationHarness()
    second_result = second.normalize(
        second.normalization_query(
            "split_normalized", anchor_date=date(2026, 11, 27), price_scale=3
        )
    )

    assert (
        _field(first_result, "close").exact_transformed_value
        == _field(second_result, "close").exact_transformed_value
    )
    assert first_result.derivation_hash != second_result.derivation_hash
    assert first_result.reference != second_result.reference


def test_p06_materializer_requires_full_original_query_and_context() -> None:
    harness = NormalizationHarness(outer_kind="decision")
    query = harness.normalization_query(
        "split_normalized", anchor_date=date(2026, 11, 30)
    )
    result = harness.normalize(query)
    assert isinstance(result.reference, ObservationDecisionReferenceV1)

    view = materialize_observation_decision(result.reference, query, harness.context)
    assert isinstance(view, DerivedObservationViewV1)
    changed = query.model_copy(
        update={
            "anchor_session": query.anchor_session.model_copy(
                update={"local_date": date(2026, 11, 27)}
            )
            if query.anchor_session is not None
            else None
        }
    )
    with pytest.raises(ValueError):
        materialize_observation_decision(result.reference, changed, harness.context)


def test_p06_context_artifact_substitution_is_rejected_at_materialization() -> None:
    harness = NormalizationHarness(outer_kind="decision")
    query = harness.normalization_query(
        "split_normalized", anchor_date=date(2026, 11, 30)
    )
    result = harness.normalize(query)
    assert isinstance(result.reference, ObservationDecisionReferenceV1)
    support = dict(harness.context.supporting_artifacts)
    original = support[query.policy_hash]
    support[query.policy_hash] = VerifiedArtifactBytes(
        data=b"{}",
        byte_size=2,
        content_hash=original.content_hash,
    )
    substituted = replace(harness.context, supporting_artifacts=support)

    with pytest.raises(ValueError):
        materialize_observation_decision(result.reference, query, substituted)


def test_large_exponent_source_is_retained_but_split_normalization_fails_safely() -> (
    None
):
    harness = NormalizationHarness(
        numeric_values=(
            "1e100000000",
            "1e100000000",
            "1e100000000",
            "1e100000000",
            "1",
        )
    )
    query = harness.normalization_query(
        "split_normalized", anchor_date=date(2026, 11, 27)
    )

    result = harness.normalize(query)

    assert result.classification == "indeterminate"
    assert "normalization_computational_expansion" in result.reasons
    source_record = harness.context.observation_datasets[0].records[0]
    assert isinstance(source_record, DailySourceObservationVersionV1)
    assert next(
        item.value for item in source_record.fields if item.field_name == "close"
    ) == Decimal("1e100000000")


def test_large_exponent_source_basis_stays_native_and_never_expands_to_ratio() -> None:
    harness = NormalizationHarness(
        source_only=True,
        numeric_values=(
            "1e100000000",
            "1e100000000",
            "1e100000000",
            "1e100000000",
            "1",
        ),
    )
    result = harness.normalize(harness.normalization_query("source_basis"))

    assert result.classification == "materialized"
    assert _field(result, "close").source_value == Decimal("1e100000000")
    assert _field(result, "close").exact_transformed_value is None


@pytest.mark.parametrize(
    ("meaning", "unit"),
    (
        ("dollar_volume", "currency_notional"),
        ("trade_count", "trades"),
        ("lot_count", "lots"),
        ("unknown", "unknown"),
    ),
)
def test_n06_end_to_end_normalization_rejects_nonshare_volume_semantics(
    meaning: str, unit: str
) -> None:
    harness = NormalizationHarness(
        volume_semantics=(meaning, unit)  # type: ignore[arg-type]
    )

    result = harness.normalize(
        harness.normalization_query("split_normalized", anchor_date=date(2026, 11, 30))
    )

    assert result.classification == "unusable"
    assert result.view is None
    assert any("incompatible" in item for item in result.reasons)


def test_nonmaterialized_result_rejects_every_partial_output_member() -> None:
    denied_harness = NormalizationHarness(outer_kind="decision")
    denied = denied_harness.normalize(
        denied_harness.normalization_query(
            "split_normalized",
            anchor_date=date(2026, 11, 30),
            effective_cutoff="2026-11-28T00:00:00Z",
        )
    )
    allowed_harness = NormalizationHarness()
    allowed = allowed_harness.normalize(
        allowed_harness.normalization_query(
            "split_normalized", anchor_date=date(2026, 11, 30)
        )
    )
    assert allowed.view is not None
    assert allowed.derivation is not None
    assert allowed.derivation_hash is not None
    assert allowed.reference is not None
    additions = {
        "view": allowed.view,
        "derivation": allowed.derivation,
        "derivation_hash": allowed.derivation_hash,
        "reference": allowed.reference,
    }
    base = denied.model_dump(mode="python")
    for field, value in additions.items():
        with pytest.raises(ValidationError, match="nonmaterialized"):
            NormalizationResultV1.model_validate({**base, field: value})
        with pytest.raises(ValidationError, match="nonmaterialized"):
            denied.model_copy(update={field: value})

    payload = json.loads(denied.model_dump_json())
    payload["view"] = json.loads(allowed.view.model_dump_json())
    with pytest.raises(ValidationError, match="nonmaterialized"):
        NormalizationResultV1.model_validate_json(json.dumps(payload))


def test_n10_source_session_equal_to_mapped_first_post_gets_factor_one() -> None:
    harness = NormalizationHarness(basis="2026-11-27T14:00:00Z")
    mapping = harness.action.map()
    assert mapping.first_post_session is not None
    assert mapping.first_post_session.local_date == harness.source.session_date

    result = harness.normalize(
        harness.normalization_query("split_normalized", anchor_date=date(2026, 11, 30))
    )

    assert result.classification == "materialized"
    assert _field(result, "close").exact_factor == ExactRatioV1(
        numerator="1", denominator="1"
    )
    assert result.selected_action_hashes == ()
    assert len(result.action_mapping_hashes) == 1


def test_p03_both_materializers_reject_opposite_role_reference_and_query() -> None:
    decision_harness = NormalizationHarness(outer_kind="decision")
    decision_query = decision_harness.normalization_query(
        "split_normalized", anchor_date=date(2026, 11, 30)
    )
    decision = decision_harness.normalize(decision_query)
    outcome_harness = NormalizationHarness(outer_kind="outcome")
    outcome_query = outcome_harness.normalization_query(
        "split_normalized", anchor_date=date(2026, 11, 30)
    )
    outcome = outcome_harness.normalize(outcome_query)
    assert isinstance(decision.reference, ObservationDecisionReferenceV1)
    assert outcome.reference is not None

    with pytest.raises(TypeError):
        materialize_observation_decision(
            outcome.reference,
            outcome_query,
            outcome_harness.context,
        )
    with pytest.raises(TypeError):
        materialize_observation_outcome(
            decision.reference,  # type: ignore[arg-type]
            decision_query,
            decision_harness.context,
        )
    with pytest.raises(TypeError):
        materialize_observation_decision(
            decision.reference,
            outcome_query,
            outcome_harness.context,
        )


def test_p08_unimported_python_changes_nested_and_joined_lineage_only() -> None:
    before = NormalizationHarness()
    before_query = before.normalization_query(
        "split_normalized", anchor_date=date(2026, 11, 30)
    )
    before_result = before.normalize(before_query)
    before_package_hash = m1d_implementation_hash()
    before_economic_hash = economic_implementation_hash()
    before_source_record = before.context.observation_datasets[0].records[0]
    before_source_hash = content_hash(before_source_record)
    before_numbers = (
        tuple(
            (item.field_name, item.source_value, item.exact_transformed_value)
            for item in before_result.view.fields
        )
        if before_result.view is not None
        else ()
    )
    probe = Path(__file__).parents[2] / "src" / "drift" / "_m1d_p08_probe.py"
    assert not probe.exists()
    try:
        probe.write_text("PROBE = 'unimported implementation identity input'\n")
        assert m1d_implementation_hash() != before_package_hash
        assert economic_implementation_hash() != before_economic_hash
        with pytest.raises((ValidationError, ValueError)):
            assert before_result.reference is not None
            materialize_observation_outcome(
                before_result.reference,
                before_query,
                before.context,
            )

        changed = NormalizationHarness()
        changed_result = changed.normalize(
            changed.normalization_query(
                "split_normalized", anchor_date=date(2026, 11, 30)
            )
        )
        assert changed_result.view is not None
        changed_numbers = tuple(
            (item.field_name, item.source_value, item.exact_transformed_value)
            for item in changed_result.view.fields
        )
        assert changed_numbers == before_numbers
        changed_source_record = changed.context.observation_datasets[0].records[0]
        assert content_hash(changed_source_record) == before_source_hash
        assert (
            changed_result.selected_action_hashes
            == before_result.selected_action_hashes
        )
        assert (
            changed_result.action_mapping_hashes != before_result.action_mapping_hashes
        )
        assert changed_result.derivation_hash != before_result.derivation_hash
        assert changed_result.reference != before_result.reference
    finally:
        probe.unlink(missing_ok=True)
    assert m1d_implementation_hash() == before_package_hash
    assert economic_implementation_hash() == before_economic_hash


def test_finite_ratio_scale_product_covers_exact_laws_without_filtering() -> None:
    identity = ExactRatioV1(numerator="1", denominator="1")
    executed = 0
    for numerator, denominator in COPRIME_RATIOS:
        ratio = ExactRatioV1(numerator=str(numerator), denominator=str(denominator))
        price, share = compose_split_factors((ratio,))
        assert Fraction(int(price.numerator), int(price.denominator)) == Fraction(
            denominator, numerator
        )
        assert Fraction(int(share.numerator), int(share.denominator)) == Fraction(
            numerator, denominator
        )
        for scale in range(7):
            source = Decimal("12.5")
            exact, _display = quantize_exact_ratio(source, price, scale)
            exact_fraction = Fraction(int(exact.numerator), int(exact.denominator))
            assert exact_fraction / Fraction(denominator, numerator) == Fraction(25, 2)
            even_source = Decimal(25).scaleb(-(scale + 1))
            odd_source = Decimal(35).scaleb(-(scale + 1))
            _even_exact, even_display = quantize_exact_ratio(
                even_source, identity, scale
            )
            _odd_exact, odd_display = quantize_exact_ratio(odd_source, identity, scale)
            assert even_display == Decimal(2).scaleb(-scale)
            assert odd_display == Decimal(4).scaleb(-scale)
            executed += 1
    assert executed == len(COPRIME_RATIOS) * 7


def test_factor_product_bound_becomes_replayable_indeterminate_result() -> None:
    large = "1" + ("0" * 3000)
    harness = NormalizationHarness(
        ratio=(large, "1"),
        additional_splits=(
            (
                "2026-11-27T18:10:00Z",
                (large, "1"),
                ActionKind.FORWARD_SPLIT,
            ),
        ),
    )

    result = harness.normalize(
        harness.normalization_query("split_normalized", anchor_date=date(2026, 11, 30))
    )

    assert result.classification == "indeterminate"
    assert "normalization_computational_expansion" in result.reasons
    assert len(result.action_mapping_hashes) == 2
    assert result.selected_action_hashes
    assert result.dependency_hashes
    loaded = NormalizationResultV1.model_validate_json(result.model_dump_json())
    verify_normalization(loaded, harness.context)


def test_anchor_opening_evidence_materializes_before_close_without_anchor_bar() -> None:
    harness = NormalizationHarness(
        basis="2026-11-27T14:00:00Z",
        anchor_opening_case="matching",
        economic_through="2026-11-30T14:40:00Z",
        source_session_date=date(2026, 11, 25),
        include_prior_open=True,
    )
    result = harness.normalize(
        harness.normalization_query("split_normalized", anchor_date=date(2026, 11, 30))
    )

    assert result.classification == "materialized"


def test_normalization_rejects_policy_history_start_after_source_open() -> None:
    harness = NormalizationHarness(
        economic_history_start="2026-11-28T00:00:00Z",
        economic_through="2026-11-30T14:30:00Z",
    )
    query = harness.normalization_query(
        "split_normalized",
        anchor_date=date(2026, 11, 30),
        outer_horizon="2026-12-01T00:00:00Z",
    )

    result = harness.normalize(query)

    assert result.classification == "indeterminate"
    assert result.view is None
    assert "economic_history_window_mismatch" in result.reasons


def test_normalization_ignores_outer_uncertainty_after_proven_anchor_open() -> None:
    harness = NormalizationHarness(
        economic_history_start="2026-11-27T14:30:00Z",
        economic_through="2026-11-30T14:30:00Z",
    )
    query = harness.normalization_query(
        "split_normalized",
        anchor_date=date(2026, 11, 30),
        outer_horizon="2026-12-01T00:00:00Z",
    )

    result = harness.normalize(query)

    assert result.classification == "materialized"
    assert result.view is not None
    assert _field(result, "close").quantized_value == Decimal("50.00")


def test_split_first_post_session_can_reuse_opening_only_anchor_companion() -> None:
    harness = NormalizationHarness(
        basis="2026-11-30T14:00:00Z",
        anchor_opening_case="matching",
        economic_history_start="2026-11-27T14:30:00Z",
        economic_through="2026-11-30T14:30:00Z",
    )
    query = harness.normalization_query(
        "split_normalized", anchor_date=date(2026, 11, 30)
    )

    result = harness.normalize(query)

    assert result.classification == "materialized"
    assert result.view is not None
    assert _field(result, "close").quantized_value == Decimal("50.00")
    anchor_records = tuple(
        record
        for dataset in harness.context.session_datasets
        if dataset.manifest.dataset_role.name == "realized_session"
        for record in dataset.records
        if record.session_key.local_date == date(2026, 11, 30)  # type: ignore[union-attr]
    )
    assert len(anchor_records) == 1
    anchor = anchor_records[0]
    assert anchor.outcome == "opened"  # type: ignore[union-attr]
    assert anchor.actual_open is None  # type: ignore[union-attr]
    assert anchor.actual_close is None  # type: ignore[union-attr]


@pytest.mark.parametrize("case", ("missing", "mismatched", "backdated", "did_not_open"))
def test_anchor_opening_evidence_fails_closed_when_not_exact(case: str) -> None:
    harness = NormalizationHarness(
        basis="2026-11-27T14:00:00Z",
        anchor_opening_case=case,  # type: ignore[arg-type]
        economic_through="2026-11-30T14:40:00Z",
        source_session_date=date(2026, 11, 25),
        include_prior_open=True,
    )
    result = harness.normalize(
        harness.normalization_query("split_normalized", anchor_date=date(2026, 11, 30))
    )

    assert result.classification == "indeterminate"
    assert result.view is None
    assert "anchor_basis_unproved" in result.reasons


@pytest.mark.parametrize(
    ("group_case", "neutral_suffix", "neutral_sorts_first"),
    (
        ("cancelled_conflict", 6110, False),
        ("cash_conflict", 6110, False),
        ("cash_conflict", 6111, True),
    ),
)
def test_same_occurrence_conflict_rejects_both_hash_order_permutations(
    group_case: str, neutral_suffix: int, neutral_sorts_first: bool
) -> None:
    harness = NormalizationHarness(
        occurrence_group_case=group_case,  # type: ignore[arg-type]
        neutral_suffix=neutral_suffix,
    )
    ordered = sorted(harness.action.effects, key=content_hash)
    first_is_split = ordered[0].payload is not None and ordered[
        0
    ].payload.action_kind in {ActionKind.FORWARD_SPLIT, ActionKind.REVERSE_SPLIT}
    assert first_is_split is not neutral_sorts_first

    result = harness.normalize(
        harness.normalization_query("split_normalized", anchor_date=date(2026, 11, 30))
    )

    assert result.classification == "indeterminate"
    assert result.view is None
    assert "same_occurrence_economic_disagreement" in result.reasons


@pytest.mark.parametrize("group_case", ("cancelled_neutral", "cash_neutral"))
def test_consistent_same_occurrence_neutral_reports_stay_neutral(
    group_case: str,
) -> None:
    harness = NormalizationHarness(
        occurrence_group_case=group_case  # type: ignore[arg-type]
    )
    result = harness.normalize(
        harness.normalization_query("split_normalized", anchor_date=date(2026, 11, 30))
    )

    assert result.classification == "materialized"
    assert _field(result, "close").exact_factor == ExactRatioV1(
        numerator="1", denominator="1"
    )
    assert result.selected_action_hashes == ()


def test_valid_duplicate_split_occurrence_contributes_one_factor() -> None:
    harness = NormalizationHarness(duplicate="equal")
    result = harness.normalize(
        harness.normalization_query("split_normalized", anchor_date=date(2026, 11, 30))
    )

    assert result.classification == "materialized"
    assert _field(result, "close").exact_factor == ExactRatioV1(
        numerator="1", denominator="2"
    )
    assert len(result.action_mapping_hashes) == 1
    assert len(result.selected_action_hashes) == 2
