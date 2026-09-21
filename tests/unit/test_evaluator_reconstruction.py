"""Unit tests for M2 exploratory reconstruction contracts and builder."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

import pytest
from observation_test_support import ObservationHarness
from pydantic import ValidationError

from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_BOUNDED_COHORT,
    ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
    ALPACA_LIMITATION_UNVERSIONED_BARS,
)
from drift.domain.evaluator_reconstruction import (
    REQUIRED_RECONSTRUCTION_FIELDS,
    ExploratoryCohortAuthorizationV1,
    ExploratoryReconstructedFieldV1,
    ExploratoryReconstructedSessionObservationV1,
    ExploratoryReconstructionPolicyV1,
    cohort_authorization_hash,
    cohort_required_limitations,
    exploratory_reconstruction_hash,
    exploratory_reconstruction_semantic_hash,
    reconstruction_policy_hash,
)
from drift.domain.normalization import DerivedObservationViewV1
from drift.domain.observation_query import ObservationOutcomeQueryV1
from drift.domain.observations import DailySourceObservationVersionV1
from drift.domain.sessions import ScheduleArtifactV1, ScheduleGenerationPolicyV1
from drift.evaluator.reconstruction import (
    build_exploratory_reconstructed_session_observation,
)
from drift.markets.observation_selection import (
    SelectedM1dRecordsV1,
    select_observation_records,
)
from drift.markets.observation_validation import M1dResolutionContext
from drift.markets.session_generation import generate_schedule

H0 = "0" * 64
H1 = "1" * 64

SEC_A = UUID("019b8240-0000-7000-8000-000000000200")
SEC_B = UUID("019b8240-0000-7000-8000-000000000201")
SEC_FOREIGN = UUID("019b8240-0000-7000-8000-000000000900")


def make_cohort(
    *security_ids: UUID, cohort_id: str = "cohort-alpha"
) -> ExploratoryCohortAuthorizationV1:
    draft = ExploratoryCohortAuthorizationV1.model_construct(
        schema_version="1",
        kind="predeclared_bounded_security_cohort",
        cohort_id=cohort_id,
        cohort_version="1",
        security_ids=tuple(sorted(security_ids, key=str)),
        cohort_hash=H0,
    )
    candidate = draft.model_copy(
        update={"cohort_hash": cohort_authorization_hash(draft)}
    )
    return ExploratoryCohortAuthorizationV1.model_validate(candidate.model_dump())


def make_policy(**overrides: object) -> ExploratoryReconstructionPolicyV1:
    base: dict[str, object] = {
        "schema_version": "1",
        "policy_id": "exploratory-scheduled-source-basis",
        "policy_version": "1",
        "mode": "source_basis_scheduled_session_reconstruction_v1",
        "required_fields": REQUIRED_RECONSTRUCTION_FIELDS,
        "required_basis": "unadjusted",
        "semantic_policy_hash": exploratory_reconstruction_semantic_hash(),
        "policy_hash": H0,
    }
    base.update(overrides)
    draft = ExploratoryReconstructionPolicyV1.model_construct(**base)  # type: ignore[arg-type]
    candidate = draft.model_copy(
        update={"policy_hash": reconstruction_policy_hash(draft)}
    )
    return ExploratoryReconstructionPolicyV1.model_validate(candidate.model_dump())


ScheduleStateT = Literal["regular", "early_close", "closed", "unknown"]
RealizedOutcomeT = Literal[
    "opened", "opened_without_bounds", "did_not_open", "unknown", "missing"
]


def _ready_harness(
    *,
    schedule_state: ScheduleStateT = "regular",
    realized_outcome: RealizedOutcomeT = "missing",
    close: str = "100.000",
) -> ObservationHarness:
    harness = ObservationHarness(close=close)
    harness.attach_sessions(
        schedule_state=schedule_state, realized_outcome=realized_outcome
    )
    return harness


def _outcome_query(harness: ObservationHarness) -> ObservationOutcomeQueryV1:
    return harness.outcome(
        economic_horizon="2026-01-06T00:00:00Z",
        evidence_vintage_cutoff="2026-01-06T00:00:00Z",
        session_date="2026-01-05",
    )


# --- Cohort contract ---


def test_cohort_nonempty_accepted_and_hash_verifiable() -> None:
    cohort = make_cohort(SEC_A)
    assert cohort.kind == "predeclared_bounded_security_cohort"
    assert cohort.cohort_hash == cohort_authorization_hash(cohort)
    assert cohort_required_limitations(cohort) == (ALPACA_LIMITATION_BOUNDED_COHORT,)


def test_cohort_empty_rejected() -> None:
    with pytest.raises(ValidationError, match="at least one security"):
        ExploratoryCohortAuthorizationV1(
            cohort_id="cohort-empty",
            cohort_version="1",
            security_ids=(),
            cohort_hash=H0,
        )


def test_cohort_duplicate_security_rejected() -> None:
    with pytest.raises(ValidationError, match="unique"):
        ExploratoryCohortAuthorizationV1(
            cohort_id="cohort-dup",
            cohort_version="1",
            security_ids=(SEC_A, SEC_A),
            cohort_hash=H0,
        )


def test_cohort_unsorted_input_is_canonicalized() -> None:
    first = make_cohort(SEC_A, SEC_B)
    second = make_cohort(SEC_B, SEC_A)
    assert first == second
    assert first.cohort_hash == second.cohort_hash


def test_cohort_member_change_changes_hash() -> None:
    assert make_cohort(SEC_A).cohort_hash != make_cohort(SEC_B).cohort_hash


def test_cohort_tampered_hash_rejected() -> None:
    cohort = make_cohort(SEC_A)
    payload = cohort.model_dump(mode="python")
    payload["cohort_hash"] = H1
    with pytest.raises(ValidationError, match="cohort hash mismatch"):
        ExploratoryCohortAuthorizationV1.model_validate(payload)


def test_cohort_carries_no_universe_or_listing_claims() -> None:
    forbidden = {
        "listing_id",
        "ticker",
        "universe_hash",
        "membership_hash",
        "primary_listing_hash",
        "created_at",
        "provider",
        "structural_eligibility_hash",
    }
    assert forbidden.isdisjoint(ExploratoryCohortAuthorizationV1.model_fields)


def test_cohort_is_frozen() -> None:
    cohort = make_cohort(SEC_A)
    with pytest.raises(ValidationError):
        cohort.cohort_version = "2"


# --- Reconstruction policy ---


def test_policy_valid_and_hash_verified() -> None:
    policy = make_policy()
    assert policy.mode == "source_basis_scheduled_session_reconstruction_v1"
    assert policy.required_fields == REQUIRED_RECONSTRUCTION_FIELDS
    assert policy.required_basis == "unadjusted"
    assert policy.policy_hash == reconstruction_policy_hash(policy)


def test_policy_requires_exact_canonical_field_inventory() -> None:
    with pytest.raises(ValidationError, match="canonical"):
        make_policy(required_fields=("open", "high", "low", "close"))
    with pytest.raises(ValidationError, match="canonical"):
        make_policy(required_fields=("open", "high", "low", "close", "volume", "vwap"))
    with pytest.raises(ValidationError, match="canonical"):
        make_policy(required_fields=("open", "high", "low", "close", "volume", "open"))
    with pytest.raises(ValidationError, match="canonical"):
        make_policy(required_fields=("volume", "close", "low", "high", "open"))


def test_policy_requires_unadjusted_basis() -> None:
    with pytest.raises(ValidationError):
        make_policy(required_basis="split_adjusted")


def test_policy_tampered_semantic_hash_rejected() -> None:
    with pytest.raises(ValidationError, match="semantic policy hash"):
        make_policy(semantic_policy_hash=H1)


def test_policy_tampered_hash_rejected() -> None:
    policy = make_policy()
    payload = policy.model_dump(mode="python")
    payload["policy_hash"] = H1
    with pytest.raises(ValidationError, match="policy hash mismatch"):
        ExploratoryReconstructionPolicyV1.model_validate(payload)


def test_policy_is_frozen() -> None:
    policy = make_policy()
    with pytest.raises(ValidationError):
        policy.policy_version = "2"


# --- Reconstructed field ---


def make_field(
    name: str = "close",
    value: object = Decimal("100.000"),
    meaning: str = "price",
    source_field_hash: str = H1,
) -> ExploratoryReconstructedFieldV1:
    return ExploratoryReconstructedFieldV1(
        schema_version="1",
        field_name=name,
        source_value=value,  # type: ignore[arg-type]
        method_id=f"{name}-v1",
        meaning=meaning,  # type: ignore[arg-type]
        source_field_hash=source_field_hash,
    )


def test_field_accepts_exact_decimal() -> None:
    field = make_field()
    assert field.source_value == Decimal("100.000")
    assert field.meaning == "price"


def test_field_rejects_float_and_non_finite() -> None:
    for bad in (1.25, float("nan"), Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(ValidationError, match="exact decimal"):
            make_field(value=bad)


def test_field_meaning_must_match_field_kind() -> None:
    with pytest.raises(ValidationError, match="requires meaning 'share_volume'"):
        make_field(name="volume", meaning="price")
    with pytest.raises(ValidationError, match="requires meaning 'price'"):
        make_field(name="open", meaning="share_volume")


def test_field_rejects_unknown_name() -> None:
    with pytest.raises(ValidationError, match="unsupported reconstruction field"):
        make_field(name="vwap")


def test_field_is_frozen() -> None:
    field = make_field()
    with pytest.raises(ValidationError):
        field.source_value = Decimal("1.0")


# --- Builder ---


def build_from_harness(
    harness: ObservationHarness,
    cohort: ExploratoryCohortAuthorizationV1 | None = None,
    policy: ExploratoryReconstructionPolicyV1 | None = None,
) -> ExploratoryReconstructedSessionObservationV1:
    return build_exploratory_reconstructed_session_observation(
        _outcome_query(harness),
        harness.context,
        cohort if cohort is not None else make_cohort(harness.security_id),
        policy if policy is not None else make_policy(),
    )


def test_builder_produces_canonical_reconstruction() -> None:
    harness = _ready_harness()
    built = build_from_harness(harness)
    assert isinstance(built, ExploratoryReconstructedSessionObservationV1)
    assert built.kind == "exploratory_reconstructed_session_observation"
    assert built.reconstruction_hash == exploratory_reconstruction_hash(built)
    assert built.security_id == harness.security_id
    assert built.listing_id == harness.listing_id
    assert built.currency == "USD"
    assert tuple(item.field_name for item in built.fields) == (
        REQUIRED_RECONSTRUCTION_FIELDS
    )
    by_name = {item.field_name: item for item in built.fields}
    assert {by_name[name].meaning for name in ("open", "high", "low", "close")} == {
        "price"
    }
    assert by_name["volume"].meaning == "share_volume"
    assert set(built.acknowledged_limitations) == {
        ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
        ALPACA_LIMITATION_UNVERSIONED_BARS,
    }


def test_builder_output_is_not_a_derived_view() -> None:
    built = build_from_harness(_ready_harness())
    assert not isinstance(built, DerivedObservationViewV1)


def test_builder_rejects_decision_query() -> None:
    harness = _ready_harness()
    decision_query = harness.decision(
        decision_time="2026-01-05T21:00:00Z",
        knowledge_cutoff="2026-01-05T21:00:00Z",
        effective_cutoff="2026-01-05T21:00:00Z",
        session_date="2026-01-05",
    )
    with pytest.raises(ValueError, match="requires an outcome query"):
        build_exploratory_reconstructed_session_observation(
            decision_query,  # type: ignore[arg-type]
            harness.context,
            make_cohort(harness.security_id),
            make_policy(),
        )


def test_builder_rejects_security_outside_cohort() -> None:
    harness = _ready_harness()
    with pytest.raises(ValueError, match="not authorized by the declared cohort"):
        build_exploratory_reconstructed_session_observation(
            _outcome_query(harness),
            harness.context,
            make_cohort(SEC_FOREIGN),
            make_policy(),
        )


def test_builder_rejects_foreign_listing_or_venue_or_date_query() -> None:
    harness = _ready_harness()
    cohort = make_cohort(harness.security_id)
    wrong_listing = _outcome_query(harness).model_copy(
        update={"listing_id": SEC_FOREIGN}
    )
    with pytest.raises(ValueError):
        build_exploratory_reconstructed_session_observation(
            wrong_listing, harness.context, cohort, make_policy()
        )
    wrong_date = harness.outcome(
        economic_horizon="2026-01-07T00:00:00Z",
        evidence_vintage_cutoff="2026-01-07T00:00:00Z",
        session_date="2026-01-06",
    )
    with pytest.raises(ValueError):
        build_exploratory_reconstructed_session_observation(
            wrong_date, harness.context, cohort, make_policy()
        )


def test_builder_rejects_unknown_or_indeterminate_schedule() -> None:
    harness = _ready_harness(schedule_state="unknown")
    with pytest.raises(ValueError):
        build_from_harness(harness)


def test_builder_rejects_adjusted_contract() -> None:
    harness = _ready_harness()
    harness.use_field_case("split_adjusted")
    with pytest.raises(ValueError, match="unadjusted"):
        build_from_harness(harness)


def test_builder_accepts_authorized_early_close_schedule() -> None:
    built = build_from_harness(_ready_harness(schedule_state="early_close"))
    assert built.reconstruction_hash == exploratory_reconstruction_hash(built)


def test_builder_rejects_tampered_cohort_or_policy() -> None:
    harness = _ready_harness()
    good = make_cohort(harness.security_id)
    bad_cohort = ExploratoryCohortAuthorizationV1.model_construct(
        schema_version="1",
        kind=good.kind,
        cohort_id=good.cohort_id,
        cohort_version="2",
        security_ids=good.security_ids,
        cohort_hash=good.cohort_hash,
    )
    with pytest.raises(ValueError, match="cohort authorization hash"):
        build_from_harness(harness, cohort=bad_cohort)
    good_policy = make_policy()
    bad_policy = ExploratoryReconstructionPolicyV1.model_construct(
        schema_version="1",
        policy_id=good_policy.policy_id,
        policy_version="2",
        mode=good_policy.mode,
        required_fields=good_policy.required_fields,
        required_basis=good_policy.required_basis,
        semantic_policy_hash=good_policy.semantic_policy_hash,
        policy_hash=good_policy.policy_hash,
    )
    with pytest.raises(ValueError, match="reconstruction policy hash"):
        build_from_harness(harness, policy=bad_policy)


def test_builder_rejects_missing_required_ohlcv_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_high(
        query: ObservationOutcomeQueryV1,
        purpose: str,
        context: M1dResolutionContext,
    ) -> SelectedM1dRecordsV1:
        selected = select_observation_records(query, purpose, context)
        if purpose != "observation":
            return selected
        record = selected.records[0]
        if not isinstance(record, DailySourceObservationVersionV1):
            raise AssertionError("observation selection did not return a daily row")
        fields = tuple(field for field in record.fields if field.field_name != "high")
        record_values = {
            name: getattr(record, name) for name in type(record).model_fields
        }
        record_values["fields"] = fields
        bad_record = type(record).model_construct(**record_values)
        selected_values = {
            name: getattr(selected, name) for name in type(selected).model_fields
        }
        selected_values["records"] = (bad_record,)
        return type(selected).model_construct(**selected_values)

    monkeypatch.setattr(
        "drift.evaluator.reconstruction.select_observation_records",
        missing_high,
    )
    with pytest.raises(ValueError, match="required field high is missing"):
        build_from_harness(_ready_harness())


def test_reconstruction_rejects_tampered_hash() -> None:
    built = build_from_harness(_ready_harness())
    payload = built.model_dump(mode="python")
    payload["reconstruction_hash"] = H1
    with pytest.raises(ValidationError, match="reconstruction hash mismatch"):
        ExploratoryReconstructedSessionObservationV1.model_validate(payload)


def test_reconstruction_does_not_resolve_structural_eligibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("resolve_structural_eligibility must not be called")

    monkeypatch.setattr(
        "drift.markets.universes.resolve_structural_eligibility",
        forbidden,
    )
    built = build_from_harness(_ready_harness())
    assert built.reconstruction_hash == exploratory_reconstruction_hash(built)


def test_reconstruction_rejects_selected_source_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mismatched(
        query: ObservationOutcomeQueryV1,
        context: M1dResolutionContext,
        policy: ScheduleGenerationPolicyV1,
    ) -> ScheduleArtifactV1:
        artifact = generate_schedule(query, context, policy)
        row = artifact.rows[0]
        bad_row = row.model_copy(update={"source_version_hash": "ab" * 32})
        return artifact.model_copy(update={"rows": (bad_row, *artifact.rows[1:])})

    monkeypatch.setattr(
        "drift.evaluator.reconstruction.generate_schedule",
        mismatched,
    )
    with pytest.raises(ValueError, match="independently selected scheduled session"):
        build_from_harness(_ready_harness())


def test_reconstruction_determinism_and_input_sensitivity() -> None:
    base_one = build_from_harness(_ready_harness())
    base_two = build_from_harness(_ready_harness())
    assert base_one.reconstruction_hash == base_two.reconstruction_hash

    shifted = _ready_harness(close="101.500")
    assert (
        build_from_harness(shifted).reconstruction_hash != base_one.reconstruction_hash
    )

    harness = _ready_harness()
    alternate_cohort = build_from_harness(
        harness, cohort=make_cohort(harness.security_id, cohort_id="cohort-beta")
    )
    assert alternate_cohort.reconstruction_hash != base_one.reconstruction_hash

    alternate_policy = build_from_harness(
        _ready_harness(), policy=make_policy(policy_id="exploratory-alt-basis")
    )
    assert alternate_policy.reconstruction_hash != base_one.reconstruction_hash
