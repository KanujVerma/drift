"""Immutable fixture and adversarial joined-replay acceptance for M1d."""

# ruff: noqa: E501

import ast
import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from threading import Barrier, Thread
from typing import Any, cast

import pytest
from m1d_fixture_generator import (
    EXPECTED_MATRIX_IDS,
    REQUIRED_JOINED_IDS,
    V1_FIXTURE_ROOT,
    JoinedScenario,
    write_fixture_v2,
)
from m1d_fixture_generator import (
    joined_scenario as _joined_scenario,
)
from m1d_fixture_support import (
    EXPECTED_HASH_INDEX_SHA256,
    FIXTURE_ROOT,
    assert_roundtrip_replays,
    field,
    load_m1d_fixture_v2,
    materialize_result,
)
from pydantic import BaseModel

from drift.datasets.resolver import (
    ResolverLimits,
    VerifiedArtifactBytes,
    read_verified_local_artifact,
)
from drift.domain.normalization import (
    DerivedObservationViewV1,
    ExactRatioV1,
    NormalizationDerivationV1,
    NormalizationResultV1,
    ObservationDecisionReferenceV1,
    ObservationOutcomeReferenceV1,
)
from drift.errors import ArtifactIntegrityError
from drift.markets.normalization import (
    materialize_observation_decision,
    materialize_observation_outcome,
    verify_normalization,
)
from drift.markets.observation_usability import resolve_listing_session_eligibility
from drift.markets.observation_validation import m1d_context_hash
from drift.serialization.canonical import canonical_json, content_hash


def joined_scenario(**kwargs: Any) -> JoinedScenario:
    from datetime import UTC, datetime

    kwargs.setdefault("decision_time", datetime(2026, 12, 2, tzinfo=UTC))
    kwargs.setdefault("knowledge_cutoff", datetime(2026, 12, 2, tzinfo=UTC))
    kwargs.setdefault("effective_cutoff", datetime(2026, 12, 1, tzinfo=UTC))
    return _joined_scenario(**kwargs)


DEFERRED_TASK8_POINTER = (
    "tests/integration/test_m1d_compatibility.py::"
    "test_c03_forbidden_runtime_capabilities_and_dependencies_remain_absent"
)

EXPECTED_LITERAL_POINTERS = {
    "A08": {
        "tests/integration/test_m1d_action_normalization.py::test_a08_joined_crossing_window_conflict_blocks_factor",
        "tests/unit/test_action_sessions.py::test_a08_same_occurrence_conflict_blocks_before_window_filtering",
    },
    "C01": {
        "tests/integration/test_m1_m0_compatibility.py::test_m0_fixture_serialization_and_event_hashes_are_unchanged",
        "tests/integration/test_replay.py::test_replay_verifies_integrity_before_returning_events",
        "tests/integration/test_m1b_m1a_compatibility.py::test_m1a_manifest_decision_and_events_keep_their_canonical_identity",
        "tests/unit/test_assertions.py::test_cutoff_selection_does_not_use_later_correction",
        "tests/unit/test_security_identity.py::test_assignment_resolution_rebuilds_the_same_internal_identity",
        "tests/integration/test_m1c_action_matrix.py::test_m1c_selected_value_substitution",
    },
    "C02": {
        "tests/integration/test_m1c_pinned_replay.py::test_pinned_replay_executes_all_archived_v1_cases",
        "tests/integration/test_m1c_pinned_replay.py::test_protected_input_tampering_is_rejected_by_literal_sha256_pins",
        "tests/integration/test_m1c_pinned_replay.py::test_missing_literal_inventory_pin_is_rejected_before_archive_extraction",
        "tests/integration/test_m1c_pinned_replay.py::test_re_signed_literal_inventory_digest_is_rejected_before_archive_extraction",
        "tests/integration/test_m1c_pinned_replay.py::test_child_failure_output_is_propagated_to_the_parent",
    },
    "O09": {
        "tests/integration/test_m1d_observation_history.py::test_o09_joined_mixed_adjustment_basis_is_retained_and_refused",
    },
    "O10": {
        "tests/integration/test_m1d_observation_history.py::test_o10_joined_official_close_requires_exact_active_equivalence",
    },
    "O11": {
        "tests/integration/test_m1d_observation_history.py::test_o11_joined_unrelated_population_containment_is_refused",
    },
    "P07": {
        "tests/integration/test_m1d_adversarial_matrix.py::test_p07_package_identity_changes_only_for_python_bytes",
    },
    "S08": {
        "tests/unit/test_session_artifacts.py::test_changed_producer_lineage_preserves_semantic_output_only",
        "tests/unit/test_session_artifacts.py::test_authorized_utc_change_updates_semantic_and_derivation_identity",
    },
    "S20": {
        "tests/unit/test_session_artifacts.py::test_unsupported_raw_precision_stops_before_ambient_timezone_parsing",
        "tests/unit/test_session_artifacts.py::test_public_generation_and_replay_need_no_ambient_timezone_lookup",
    },
}


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURE_ROOT / name).read_bytes()


def _fixture_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _model_values(value: BaseModel) -> dict[str, object]:
    return {name: getattr(value, name) for name in type(value).model_fields}


def _positive_result(scenario: JoinedScenario) -> NormalizationResultV1:
    result = scenario.normalize()
    assert_roundtrip_replays(result, scenario.context)
    assert result.classification == "materialized"
    assert result.reference is not None
    assert materialize_result(result, scenario.context) == result.view
    return result


def test_current_v2_fixture_hash_index_is_exact() -> None:
    raw_index = _fixture_bytes("hash-index.json")
    assert sha256(raw_index).hexdigest() == EXPECTED_HASH_INDEX_SHA256
    parsed = json.loads(raw_index)
    assert canonical_json(parsed) == raw_index
    assert parsed["schema_version"] == "1"
    assert parsed["fixture_version"] == "m1d/v2"
    declared = {entry["path"] for entry in parsed["entries"]}
    actual = set(_fixture_files(FIXTURE_ROOT))
    assert actual == declared | {"hash-index.json"}
    assert "joined-context.json" in declared
    assert "joined-schedule-result.json" in declared
    assert "reconstruction-context.json" not in declared
    assert any(path.startswith("objects/sha256/") for path in declared)
    for entry in parsed["entries"]:
        data = _fixture_bytes(entry["path"])
        assert len(data) == entry["byte_size"]
        assert sha256(data).hexdigest() == entry["sha256"]


def test_v2_generator_reproduces_exact_bytes_and_refuses_both_versions(
    tmp_path: Path,
) -> None:
    generated = tmp_path / "v2"
    write_fixture_v2(generated)
    assert _fixture_files(generated) == _fixture_files(FIXTURE_ROOT)
    with pytest.raises(FileExistsError, match="cannot be overwritten"):
        write_fixture_v2(generated)
    with pytest.raises(FileExistsError, match="v1 fixture cannot be overwritten"):
        write_fixture_v2(V1_FIXTURE_ROOT)


def test_v2_generator_exclusively_reserves_concurrent_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "v2"
    start = Barrier(3)
    successes: list[str] = []
    failures: list[FileExistsError] = []

    def payload_factory() -> dict[str, bytes]:
        return {"fixture-metadata.json": b"{}"}

    def writer(name: str) -> None:
        start.wait()
        try:
            write_fixture_v2(target, payload_factory=payload_factory)
        except FileExistsError as error:
            failures.append(error)
        else:
            successes.append(name)

    threads = [Thread(target=writer, args=(name,)) for name in ("one", "two")]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join()

    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], FileExistsError)
    assert _fixture_files(target) == {
        "fixture-metadata.json": b"{}",
        "hash-index.json": (target / "hash-index.json").read_bytes(),
    }
    assert not (tmp_path / ".v2.generation.lock").exists()
    with pytest.raises(FileExistsError, match="cannot be overwritten"):
        write_fixture_v2(target, payload_factory=payload_factory)


def test_task7_expected_decision_and_outcome_bytes_replay() -> None:
    fixture = load_m1d_fixture_v2()
    assert_roundtrip_replays(fixture.decision_result, fixture.context)
    assert_roundtrip_replays(fixture.outcome_result, fixture.context)
    assert materialize_result(fixture.decision_result, fixture.context) == (
        fixture.decision_result.view
    )
    assert materialize_result(fixture.outcome_result, fixture.context) == (
        fixture.outcome_result.view
    )
    assert fixture.decision_query.observation.input_context_hash == m1d_context_hash(
        fixture.context
    )
    assert fixture.outcome_query.observation.input_context_hash == m1d_context_hash(
        fixture.context
    )
    schedule = fixture.schedule_artifact
    assert schedule.query == fixture.decision_query.observation
    assert schedule.classification == "generated"
    assert len(schedule.rows) == 1
    assert schedule.selected_source_proof_hash is not None
    assert schedule.selected_coverage_proof_hash is not None
    dependencies = set(fixture.decision_result.dependency_hashes)
    assert schedule.rows[0].source_version_hash in dependencies
    eligibility = resolve_listing_session_eligibility(
        fixture.decision_query.observation, fixture.context
    )
    stable_schedule_hash = content_hash(
        schedule.model_dump(mode="python", exclude={"generated_at"})
    )
    assert eligibility.generated_schedule_hash == stable_schedule_hash
    assert content_hash(eligibility) in dependencies
    assert fixture.decision_result.derivation is not None
    assert set(fixture.decision_result.derivation.session_proof_hashes).issubset(
        dependencies
    )
    metadata = json.loads(_fixture_bytes("fixture-metadata.json"))
    assert metadata["joined_schedule_generation"] == {
        "context": "joined-context.json",
        "artifact": "joined-schedule-result.json",
        "tzif_object_hash": schedule.timezone_bytes_hash,
        "consumed_by_joined_normalization": True,
        "purpose": "replay of the source session consumed by joined normalization",
    }


def test_fixture_only_replay_needs_no_unit_harness_or_generator_import() -> None:
    project_root = Path(__file__).parents[2]
    program = """
import sys
from m1d_fixture_support import load_m1d_fixture_v2, materialize_result
loaded = load_m1d_fixture_v2()
assert materialize_result(loaded.decision_result, loaded.context) == loaded.decision_result.view
assert materialize_result(loaded.outcome_result, loaded.context) == loaded.outcome_result.view
for name in ('observation_test_support', 'action_session_test_support', 'session_test_support', 'm1d_fixture_generator'):
    assert name not in sys.modules, name
"""
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            (str(project_root / "src"), str(project_root / "tests" / "integration"))
        ),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_task7_matrix_inventory_names_all_current_rows() -> None:
    parsed = json.loads(_fixture_bytes("matrix-index.json"))
    rows = parsed["rows"]
    assert {row["id"] for row in rows} == EXPECTED_MATRIX_IDS
    assert len(rows) == len(EXPECTED_MATRIX_IDS) == 81
    assert {row["id"] for row in rows if row["coverage"] == "joined"} == (
        REQUIRED_JOINED_IDS
    )
    assert {row["id"] for row in rows if row["coverage"] == "task8"} == {"C03"}
    by_id = {row["id"]: row for row in rows}
    assert by_id["C01"]["coverage"] == "focused"
    assert by_id["C02"]["coverage"] == "focused"
    assert [row["id"] for row in rows] == sorted(EXPECTED_MATRIX_IDS)
    for matrix_id, expected in EXPECTED_LITERAL_POINTERS.items():
        assert expected.issubset(set(by_id[matrix_id]["pointers"]))

    project_root = Path(__file__).parents[2]
    for row in rows:
        assert row["pointers"]
        for pointer in row["pointers"]:
            relative, function = pointer.split("::", maxsplit=1)
            if pointer == DEFERRED_TASK8_POINTER:
                assert row["id"] == "C03"
                continue
            tree = ast.parse((project_root / relative).read_text())
            functions = {
                node.name
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            assert function in functions, pointer


@pytest.mark.parametrize("case", ("date", "q", "schedule", "mapping", "dependency"))
def test_p01_joined_dependent_substitutions_reject_exact_replay(case: str) -> None:
    original = joined_scenario(outer_kind="decision")
    result = _positive_result(original)
    if case == "dependency":
        forged = NormalizationResultV1.model_construct(
            **{  # type: ignore[arg-type]
                **_model_values(result),
                "dependency_hashes": result.dependency_hashes[1:],
            }
        )
        with pytest.raises(ValueError, match="replay mismatch"):
            verify_normalization(forged, original.context)
        return

    changed = {
        "date": lambda: joined_scenario(
            outer_kind="decision", correction_basis="2026-11-27T14:00:00Z"
        ),
        "q": lambda: joined_scenario(outer_kind="decision", ratio=("3", "1")),
        "schedule": lambda: joined_scenario(
            outer_kind="decision", corrected_schedule_state="unknown"
        ),
        "mapping": lambda: joined_scenario(
            outer_kind="decision",
            action_basis="2026-11-27",
            mapping_mode="explicit_first_basis_date",
        ),
    }[case]()
    changed_query = changed.query.model_copy(
        update={
            "observation": changed.query.observation.model_copy(
                update={"input_context_hash": m1d_context_hash(changed.context)}
            )
        }
    )
    result_reference = cast(ObservationDecisionReferenceV1, result.reference)
    reference = result_reference.model_copy(
        update={
            "query_hash": content_hash(changed_query),
            "context_hash": m1d_context_hash(changed.context),
        }
    )
    if isinstance(reference, ObservationDecisionReferenceV1):
        with pytest.raises(
            ValueError, match="does not match exact replay|no longer materializes"
        ):
            materialize_observation_decision(reference, changed_query, changed.context)
    else:
        pytest.fail("P01 uses a decision reference")


def test_p02_joined_factor_view_and_reference_substitutions_are_rejected() -> None:
    scenario = joined_scenario(outer_kind="decision")
    result = _positive_result(scenario)
    derivation = cast(NormalizationDerivationV1, result.derivation)
    view = cast(DerivedObservationViewV1, result.view)
    reference = cast(ObservationDecisionReferenceV1, result.reference)
    forged_derivation = NormalizationDerivationV1.model_construct(
        **{  # type: ignore[arg-type]
            **_model_values(derivation),
            "price_factor": ExactRatioV1(numerator="1", denominator="1"),
        }
    )
    forged_view = DerivedObservationViewV1.model_construct(
        **{  # type: ignore[arg-type]
            **_model_values(view),
            "output_hash": "f" * 64,
        }
    )
    for update in ({"derivation": forged_derivation}, {"view": forged_view}):
        forged = NormalizationResultV1.model_construct(
            **{  # type: ignore[arg-type]
                **_model_values(result),
                **update,
            }
        )
        with pytest.raises(ValueError, match="replay mismatch"):
            verify_normalization(forged, scenario.context)
    forged_reference = reference.model_copy(update={"view_hash": "f" * 64})
    with pytest.raises(ValueError, match="does not match exact replay"):
        materialize_observation_decision(
            forged_reference, scenario.query, scenario.context
        )


def test_p03_joined_decision_and_outcome_roles_are_noninterchangeable() -> None:
    decision = joined_scenario(outer_kind="decision")
    outcome = decision.with_query(outer_kind="outcome")
    decision_result = _positive_result(decision)
    outcome_result = _positive_result(outcome)
    decision_reference = cast(ObservationDecisionReferenceV1, decision_result.reference)
    outcome_reference = cast(ObservationOutcomeReferenceV1, outcome_result.reference)
    with pytest.raises(TypeError):
        materialize_observation_decision(
            outcome_reference,  # type: ignore[arg-type]
            outcome.query,
            outcome.context,
        )
    with pytest.raises(TypeError):
        materialize_observation_outcome(
            decision_reference,  # type: ignore[arg-type]
            decision.query,
            decision.context,
        )


def test_p04_joined_equal_numbers_under_changed_policy_have_distinct_lineage() -> None:
    first = joined_scenario(outer_kind="decision")
    first_result = first.normalize()
    old_policy = first.context.supporting_artifacts[first.query.policy_hash]
    parsed = json.loads(old_policy.data)
    parsed["policy_version"] = "2"
    changed_bytes = canonical_json(parsed)
    changed_hash = sha256(changed_bytes).hexdigest()
    support = dict(first.context.supporting_artifacts)
    support[changed_hash] = VerifiedArtifactBytes(
        data=changed_bytes, byte_size=len(changed_bytes), content_hash=changed_hash
    )
    changed_context = replace(first.context, supporting_artifacts=support)
    changed_query = first.query.model_copy(
        update={
            "policy_hash": changed_hash,
            "observation": first.query.observation.model_copy(
                update={"input_context_hash": m1d_context_hash(changed_context)}
            ),
        }
    )
    second = replace(first, context=changed_context, query=changed_query)
    second_result = second.normalize()
    assert (
        field(first_result, "close").quantized_value
        == field(second_result, "close").quantized_value
    )
    assert first_result.derivation_hash != second_result.derivation_hash
    assert first_result.reference != second_result.reference
    assert_roundtrip_replays(first_result, first.context)
    assert_roundtrip_replays(second_result, second.context)
    assert materialize_result(first_result, first.context) == first_result.view
    assert materialize_result(second_result, second.context) == second_result.view


def test_p05_joined_content_identity_ignores_location_but_rejects_wrong_bytes(
    tmp_path: Path,
) -> None:
    scenario = joined_scenario(outer_kind="decision")
    result = _positive_result(scenario)
    data = scenario.context.supporting_artifacts[scenario.query.policy_hash].data
    digest = sha256(data).hexdigest()
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    wrong_root = tmp_path / "wrong"
    for root in (first_root, second_root, wrong_root):
        root.mkdir()
    (first_root / "policy.json").write_bytes(data)
    (second_root / "moved.json").write_bytes(data)
    (wrong_root / "policy.json").write_bytes(b"{}")
    first = read_verified_local_artifact(
        first_root, "policy.json", digest, ResolverLimits(max_bytes=4096)
    )
    second = read_verified_local_artifact(
        second_root, "moved.json", digest, ResolverLimits(max_bytes=4096)
    )
    assert first == second
    for captured in (first, second):
        support = dict(scenario.context.supporting_artifacts)
        support[scenario.query.policy_hash] = captured
        captured_context = replace(scenario.context, supporting_artifacts=support)
        assert (
            captured_context.supporting_artifacts[scenario.query.policy_hash]
            is captured
        )
        assert materialize_result(result, captured_context) == result.view
    with pytest.raises(ArtifactIntegrityError, match="SHA-256"):
        read_verified_local_artifact(
            wrong_root, "policy.json", digest, ResolverLimits(max_bytes=4096)
        )


def test_p06_joined_verified_snapshot_survives_path_mutation_but_context_substitution_fails(
    tmp_path: Path,
) -> None:
    scenario = joined_scenario(outer_kind="decision")
    result = _positive_result(scenario)
    reference = cast(ObservationDecisionReferenceV1, result.reference)
    data = scenario.context.supporting_artifacts[scenario.query.policy_hash].data
    digest = sha256(data).hexdigest()
    path = tmp_path / "policy.json"
    path.write_bytes(data)
    captured = read_verified_local_artifact(
        tmp_path, path.name, digest, ResolverLimits(max_bytes=4096)
    )
    path.write_bytes(b'{"substituted":true}')
    support = dict(scenario.context.supporting_artifacts)
    support[scenario.query.policy_hash] = captured
    captured_context = replace(scenario.context, supporting_artifacts=support)
    assert captured_context.supporting_artifacts[scenario.query.policy_hash] is captured
    assert (
        materialize_observation_decision(reference, scenario.query, captured_context)
        == result.view
    )
    with pytest.raises(ArtifactIntegrityError, match="SHA-256"):
        read_verified_local_artifact(
            tmp_path, path.name, digest, ResolverLimits(max_bytes=4096)
        )
    substituted = VerifiedArtifactBytes(
        data=b"{}", byte_size=2, content_hash=captured.content_hash
    )
    support[scenario.query.policy_hash] = substituted
    with pytest.raises(ValueError, match="policy artifact"):
        materialize_observation_decision(
            reference,
            scenario.query,
            replace(scenario.context, supporting_artifacts=support),
        )


def _package_hash(source_root: Path) -> tuple[str, str]:
    program = """
import json
from drift.domain.economic_common import economic_implementation_hash
from drift.domain.observation_query import m1d_implementation_hash
print(json.dumps([m1d_implementation_hash(), economic_implementation_hash()]))
"""
    environment = {
        **os.environ,
        "PYTHONPATH": str(source_root),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=source_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    values = json.loads(completed.stdout)
    return cast(tuple[str, str], tuple(values))


def test_p07_package_identity_changes_only_for_python_bytes(tmp_path: Path) -> None:
    project_root = Path(__file__).parents[2]
    first_root = tmp_path / "first" / "src"
    first_package = first_root / "drift"
    shutil.copytree(project_root / "src" / "drift", first_package)
    baseline = _package_hash(first_root)
    assert baseline[0] == baseline[1]

    for relative in (
        "markets/normalization.py",
        "serialization/canonical.py",
        "config/settings.py",
    ):
        path = first_package / relative
        original = path.read_bytes()
        path.write_bytes(original + b"\n# Task 7 P07 mutation\n")
        assert _package_hash(first_root) != baseline
        path.write_bytes(original)
        assert _package_hash(first_root) == baseline

    (first_package / "non-python-note.txt").write_text("not an identity input\n")
    assert _package_hash(first_root) == baseline

    moved_root = tmp_path / "moved" / "src"
    shutil.copytree(first_package, moved_root / "drift")
    assert _package_hash(moved_root) == baseline
