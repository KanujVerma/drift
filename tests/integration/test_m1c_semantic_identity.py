"""M1c evidence identity survives unrelated edits (issue 63, stage 2).

Stage 1 moved the M1d evidence identity onto the ``m1d-evidence-v1`` semantic
attestation, but every M1c identity still bound the whole installed source
inventory: the M1c validator run identity inside every M1c validation decision,
and the selection, projection and composition identities inside every M1c
selection proof, safe fact projection and outcome. Split-normalized M1d
evidence composes M1c history, and M2 bundles carry M1c outcomes, so a comment
anywhere in ``src/drift`` still moved them (the stage 1 residual). Stage 2
binds the validator run to ``m1c-source-validation-v1`` and the other three to
``m1c-evidence-v1``, and keeps the whole inventory as build provenance only.

Each scenario runs in a fresh interpreter over its own copy of the installed
``drift`` package, because an attestation is computed once per process: an
in-process edit could never show that an identity ignores it. The copies are:

* ``pristine``: the installed package, unchanged;
* ``unrelated``: a comment in ``drift/evaluator/engine.py``, declared by no
  closure;
* ``m1c_evidence``: the same comment in ``drift/markets/economic_outcomes.py``,
  declared by ``m1c-evidence-v1`` (and so by ``m1d-evidence-v1``);
* ``m1c_validation``: the same comment in
  ``drift/markets/economic_validation.py``, declared by both M1c closures;
* ``m1d_only``: the same comment in ``drift/markets/session_binding.py``,
  declared by ``m1d-evidence-v1`` only.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))

from test_alpaca_exploratory_adapter import run_pinned_intake  # noqa: E402

from drift.domain.economic_common import economic_implementation_hash  # noqa: E402
from drift.domain.observation_query import (  # noqa: E402
    drift_source_inventory_hash,
    m1d_implementation_hash,
)
from drift.markets.economic_validation import (  # noqa: E402
    economic_validator_implementation_hash,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMENT_EDIT = b"\n# issue 63 stage 2: a comment-only edit\n"
EDITS = {
    "pristine": None,
    "unrelated": "evaluator/engine.py",
    "m1c_evidence": "markets/economic_outcomes.py",
    "m1c_validation": "markets/economic_validation.py",
    "m1d_only": "markets/session_binding.py",
}
M1C_EVIDENCE_STAMPS = ("m1c_selection", "m1c_projection", "m1c_composition")
"""Where the M1c evidence identity is stamped: selection proofs, safe fact
projections and outcome compositions, read from genuine M1c results."""
SPLIT_AND_MEMBER_HASHES = (
    "split_derivation_hash",
    "split_action_mapping_hashes",
    "split_result_hash",
    "m1c_outcome_hash",
    "bundle_hash",
    "proof_hash",
    "qualified_hash",
    "snapshot_hash",
    "admission_hash",
    "fully_populated_bundle_hash",
)
"""Split-normalized evidence, the genuine M1c outcome, the M1c-member promotion
case and the bundle carrying every authority-bearing class."""
ENGINE_HASHES = (
    "engine_bundle_hash",
    "engine_admission_hash",
    "engine_evidence_hash",
    "engine_result_hash",
    "engine_trace_hash",
)

_PRELUDE = """
import json
import sys
from pathlib import Path

import drift

root = Path(sys.argv[1]).resolve()
if not Path(drift.__file__).resolve().is_relative_to(root):
    raise SystemExit(f"imported Drift outside the source copy: {drift.__file__}")

from datetime import date

import test_evaluator_engine as eng
import test_replay_provenance as rp
from economic_test_support import validated_case
from observation_test_support import NormalizationHarness

from drift.domain.economic_common import economic_implementation_hash
from drift.domain.observation_query import m1d_implementation_hash
from drift.markets.economic_outcomes import resolve_economic_facts
from drift.markets.economic_selection import (
    project_market_facts,
    select_market_records,
)
from drift.markets.economic_validation import economic_validator_implementation_hash
from drift.serialization.canonical import canonical_json, content_hash

SPLIT_ANCHOR = date(2026, 11, 30)


def empty_case():
    case = validated_case(())
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    return case, query


def split_case():
    harness = NormalizationHarness()
    query = harness.normalization_query("split_normalized", anchor_date=SPLIT_ANCHOR)
    return harness, query


def member_case():
    harness, decision_query, reference = rp._decision_case()
    snapshot = rp.qualified_snapshot(harness.context)
    qualified = rp.qualify_replay_context(context=harness.context, snapshot=snapshot)
    outcome, economic_request = rp._genuine_economic(harness, decision_query)
    bundle = rp._covered_bundle(
        harness, decision_query, reference, snapshot, economic_outcomes=(outcome,)
    )
    return (
        harness,
        decision_query,
        reference,
        snapshot,
        qualified,
        outcome,
        economic_request,
        bundle,
    )


def refusal(check):
    try:
        check()
    except Exception as error:
        return f"{type(error).__name__}: {error}"
    return "ok"
"""

_REPORT_PROGRAM = (
    _PRELUDE
    + """
from drift.domain.evaluator_corporate_actions import SecurityEconomicOutcomeV1
from drift.evaluator.engine import SessionEvaluatorEvidence

(
    harness,
    decision_query,
    reference,
    snapshot,
    qualified,
    member,
    economic_request,
    bundle,
) = member_case()
economic_context = harness.context.economic_context
economic_policy = harness.context.economic_source_policy
selection = select_market_records(economic_request, economic_context, economic_policy)
projections = project_market_facts(
    economic_request, economic_context, economic_policy
)
if not projections:
    raise SystemExit("the genuine M1c case projected no safe fact")
proof = rp._mint(
    harness,
    decision_query,
    reference,
    bundle,
    qualified,
    economic_requests=(economic_request,),
)
gate = rp._promotion_case(bundle, proof, snapshot, qualified)
rp.validate_promotion_admission(**gate)

split, split_query = split_case()
split_result = split.normalize(split_query)
if split_result.classification != "materialized":
    raise SystemExit(f"split result did not materialize: {split_result.classification}")

# The engine run of plan decision D10: a genuine M1c resolution, for a security
# outside the run's cohort, carried as a bundle member and as evaluator
# evidence. It proves identity flow into the result and trace, not accounting.
case, outcome_query = empty_case()
genuine = resolve_economic_facts(outcome_query, case.context, case.source_policy)
engine = eng._engine(
    bundle=eng._bundle(economic_outcomes=(genuine,)),
    evidence=SessionEvaluatorEvidence(
        listing_role_records=eng.ROLE_RECORDS,
        economic_outcomes=(
            SecurityEconomicOutcomeV1(
                security_id=genuine.query.security_id, resolution=genuine
            ),
        ),
    ),
)
artifacts = eng._run(engine)
if artifacts.result.classification.value != "complete":
    raise SystemExit(f"engine run did not complete: {artifacts.result.classification}")

print(json.dumps({
    "whole_tree": economic_implementation_hash(),
    "m1d_evidence": m1d_implementation_hash(),
    "m1c_validator": economic_validator_implementation_hash(),
    "m1c_selection": selection.selection_implementation_hash,
    "m1c_projection": sorted(
        {item.projection_implementation_hash for item in projections}
    ),
    "m1c_composition": member.composition_implementation_hash,
    "split_derivation_hash": split_result.derivation_hash,
    "split_action_mapping_hashes": list(split_result.action_mapping_hashes),
    "split_result_hash": content_hash(split_result),
    "m1c_outcome_hash": content_hash(member),
    "bundle_hash": bundle.bundle_hash,
    "proof_hash": proof.proof_hash,
    "qualified_hash": qualified.qualified_hash,
    "snapshot_hash": snapshot.snapshot_hash,
    "admission_hash": gate["admission"].admission_hash,
    "fully_populated_bundle_hash": rp._fully_populated_bundle().bundle_hash,
    "engine_bundle_hash": engine.bundle.bundle_hash,
    "engine_admission_hash": engine.admission.admission_hash,
    "engine_evidence_hash": engine.evaluator_evidence_hash,
    "engine_result_hash": artifacts.result.result_hash,
    "engine_trace_hash": artifacts.trace.trace_hash,
}))
"""
)

_MINT_PROGRAM = (
    _PRELUDE
    + """
retained = Path(sys.argv[2])

case, outcome_query = empty_case()
outcome = resolve_economic_facts(outcome_query, case.context, case.source_policy)
selection = select_market_records(outcome_query, case.context, case.source_policy)
(retained / "outcome.json").write_bytes(canonical_json(outcome))
(retained / "selection.json").write_bytes(canonical_json(selection))
(retained / "validation.json").write_text(
    json.dumps(
        [
            {
                "run": canonical_json(dataset.validation_run).decode(),
                "decision": canonical_json(dataset.decision).decode(),
                "bundle": canonical_json(dataset.bundle).decode(),
            }
            for dataset in case.context.datasets
        ]
    )
)

split, split_query = split_case()
split_result = split.normalize(split_query)
if split_result.classification != "materialized":
    raise SystemExit(f"split result did not materialize: {split_result.classification}")
(retained / "split.json").write_bytes(canonical_json(split_result))

(
    harness,
    decision_query,
    reference,
    _snapshot,
    _qualified,
    _outcome,
    economic_request,
    bundle,
) = member_case()
(retained / "bundle.json").write_bytes(canonical_json(bundle))
(retained / "requests.json").write_text(
    json.dumps(
        {
            "decision_query": canonical_json(decision_query).decode(),
            "reference": canonical_json(reference).decode(),
            "economic_request": canonical_json(economic_request).decode(),
            "session_queries": [
                canonical_json(item).decode()
                for item in rp.normalization_session_queries(harness)
            ],
        }
    )
)
print(json.dumps({"minted": sorted(path.name for path in retained.iterdir())}))
"""
)

_CHECK_PROGRAM = (
    _PRELUDE
    + """
from dataclasses import replace

from drift.domain.dataset_validation import (
    DatasetValidationDecisionV2,
    ValidatedDatasetBundleV1,
    ValidationRunContextV1,
)
from drift.domain.economic_queries import MarketSelectionProofV1
from drift.domain.economic_results import EconomicOutcomeResolutionV1
from drift.domain.evaluator_bundles import EvaluationInputBundleV1
from drift.domain.normalization import NormalizationResultV1
from drift.evaluator.bundles import verify_evaluation_input_bundle
from drift.markets.economic_outcomes import verify_economic_outcome
from drift.markets.economic_selection import verify_market_selection
from drift.markets.economic_validation import validate_economic_context
from drift.markets.normalization import materialize_observation_outcome

retained = Path(sys.argv[2])
report = {}

case, _outcome_query = empty_case()
outcome = EconomicOutcomeResolutionV1.model_validate_json(
    (retained / "outcome.json").read_bytes()
)
selection = MarketSelectionProofV1.model_validate_json(
    (retained / "selection.json").read_bytes()
)
report["outcome"] = refusal(
    lambda: verify_economic_outcome(outcome, case.context, case.source_policy)
)
report["selection"] = refusal(
    lambda: verify_market_selection(selection, case.context, case.source_policy)
)

runs = json.loads((retained / "validation.json").read_text())
datasets = tuple(
    replace(
        dataset,
        validation_run=ValidationRunContextV1.model_validate_json(item["run"]),
        decision=DatasetValidationDecisionV2.model_validate_json(item["decision"]),
        bundle=ValidatedDatasetBundleV1.model_validate_json(item["bundle"]),
    )
    for dataset, item in zip(case.context.datasets, runs, strict=True)
)
report["validation"] = refusal(
    lambda: validate_economic_context(replace(case.context, datasets=datasets))
)

split_bytes = (retained / "split.json").read_bytes()
split, split_query = split_case()
try:
    split_result = NormalizationResultV1.model_validate_json(split_bytes)
except ValueError as error:
    report["split"] = {"valid": False, "error": str(error)}
else:
    rederived = split.normalize(split_query)
    report["split"] = {
        "valid": True,
        "rederived_identical": canonical_json(rederived) == split_bytes,
        "materialized": refusal(
            lambda: materialize_observation_outcome(
                split_result.reference, split_query, split.context
            )
        ),
    }

harness, *_ = member_case()
requests = json.loads((retained / "requests.json").read_text())
fresh_query = harness.normalization_query("split_normalized", anchor_date=SPLIT_ANCHOR)
fresh_reference = harness.normalize(fresh_query).reference
fresh_outcome, fresh_request = rp._genuine_economic(harness, fresh_query)
fresh_sessions = rp.normalization_session_queries(harness)
decision_query = type(fresh_query).model_validate_json(requests["decision_query"])
reference = type(fresh_reference).model_validate_json(requests["reference"])
economic_request = type(fresh_request).model_validate_json(
    requests["economic_request"]
)
session_queries = tuple(
    type(fresh).model_validate_json(item)
    for fresh, item in zip(fresh_sessions, requests["session_queries"], strict=True)
)
bundle_bytes = (retained / "bundle.json").read_bytes()
try:
    bundle = EvaluationInputBundleV1.model_validate_json(bundle_bytes)
except ValueError as error:
    report["bundle"] = {"valid": False, "error": str(error)}
else:
    report["bundle"] = {
        "valid": True,
        "verified": refusal(
            lambda: verify_evaluation_input_bundle(
                bundle=bundle,
                context=harness.context,
                session_queries=session_queries,
                decision_requests=((reference, decision_query),),
                economic_requests=(economic_request,),
            )
        ),
    }
print(json.dumps(report))
"""
)


def _source_copy(base: Path, name: str, edited: str | None) -> Path:
    """Copy the installed package (and its lock) and apply one comment edit."""
    root = base / name
    shutil.copytree(
        REPO_ROOT / "src" / "drift",
        root / "src" / "drift",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy2(REPO_ROOT / "uv.lock", root / "uv.lock")
    if edited is not None:
        target = root / "src" / "drift" / edited
        assert target.is_file(), edited
        target.write_bytes(target.read_bytes() + COMMENT_EDIT)
    return root


def _run(root: Path, program: str, *arguments: str) -> dict[str, Any]:
    """Run one program in a fresh interpreter importing Drift from ``root``."""
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            (
                str(root / "src"),
                str(REPO_ROOT / "tests" / "unit"),
                str(REPO_ROOT / "tests"),
            )
        ),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    environment.pop("PYTEST_ADDOPTS", None)
    completed = subprocess.run(
        [sys.executable, "-c", program, str(root / "src"), *arguments],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    document = json.loads(completed.stdout.strip().splitlines()[-1])
    assert isinstance(document, dict)
    return document


@pytest.fixture(scope="module")
def copies(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("m1c-semantic-identity")
    return {name: _source_copy(base, name, edit) for name, edit in EDITS.items()}


@pytest.fixture(scope="module")
def reports(copies: dict[str, Path]) -> dict[str, dict[str, Any]]:
    return {name: _run(root, _REPORT_PROGRAM) for name, root in copies.items()}


@pytest.fixture(scope="module")
def checks(
    copies: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> dict[str, dict[str, Any]]:
    """Mint retained M1c evidence under ``pristine``; re-check it everywhere."""
    retained = tmp_path_factory.mktemp("m1c-retained")
    _run(copies["pristine"], _MINT_PROGRAM, str(retained))
    return {
        name: _run(root, _CHECK_PROGRAM, str(retained))
        for name, root in copies.items()
        if name != "pristine"
    }


def _moved(
    reports: dict[str, dict[str, Any]], name: str, keys: tuple[str, ...]
) -> set[str]:
    return {key for key in keys if reports[name][key] != reports["pristine"][key]}


def test_the_pristine_copy_is_the_installed_package(
    reports: dict[str, dict[str, Any]],
) -> None:
    """The copies are faithful, so their identities describe this tree."""
    pristine = reports["pristine"]
    assert pristine["whole_tree"] == economic_implementation_hash()
    assert pristine["m1d_evidence"] == m1d_implementation_hash()
    assert pristine["m1c_validator"] == economic_validator_implementation_hash()
    # One evidence identity is stamped at every M1c evidence site.
    assert pristine["m1c_projection"] == [pristine["m1c_selection"]]
    assert pristine["m1c_composition"] == pristine["m1c_selection"]
    for name in EDITS:
        if name != "pristine":
            assert reports[name]["whole_tree"] != pristine["whole_tree"], name


def test_an_unrelated_edit_moves_neither_split_normalized_nor_m1c_member_evidence(
    reports: dict[str, dict[str, Any]],
) -> None:
    """The issue 46 reproduction for M1c: identical inputs, identical hashes.

    Only the whole-tree build provenance sees the edit. The M1c validator and
    evidence identities, split-normalized evidence, the genuine M1c outcome,
    the M1c-member promotion case (bundle, provenance proof, qualified replay
    context, snapshot and admission) and the fully populated bundle are equal.
    """
    keys = (
        "m1d_evidence",
        "m1c_validator",
        *M1C_EVIDENCE_STAMPS,
        *SPLIT_AND_MEMBER_HASHES,
    )
    assert _moved(reports, "unrelated", keys) == set()
    assert reports["unrelated"]["whole_tree"] != reports["pristine"]["whole_tree"]


def test_an_unrelated_edit_moves_no_m1c_member_engine_run(
    reports: dict[str, dict[str, Any]],
) -> None:
    """A genuine M1c resolution flows into an engine run without the tree.

    The resolution is for a security outside the run's cohort (plan decision
    D10), so this proves identity flow into the bundle, admission, evaluator
    evidence, result and trace, not accounting. The declared M1c edit is the
    control: it moves all five.
    """
    assert _moved(reports, "unrelated", ENGINE_HASHES) == set()
    assert _moved(reports, "m1c_evidence", ENGINE_HASHES) == set(ENGINE_HASHES)


def test_a_declared_m1c_evidence_edit_moves_evidence_but_not_the_validator_identity(
    reports: dict[str, dict[str, Any]],
) -> None:
    """Selection and composition edits do not stale validated M1c datasets."""
    assert _moved(reports, "m1c_evidence", ("m1c_validator",)) == set()
    assert _moved(reports, "m1c_evidence", M1C_EVIDENCE_STAMPS) == set(
        M1C_EVIDENCE_STAMPS
    )
    # M1d executes M1c code in process, so the M1d identity is a superset.
    assert _moved(reports, "m1c_evidence", ("m1d_evidence",)) == {"m1d_evidence"}
    assert _moved(reports, "m1c_evidence", SPLIT_AND_MEMBER_HASHES) >= {
        "split_derivation_hash",
        "split_action_mapping_hashes",
        "split_result_hash",
        "m1c_outcome_hash",
        "bundle_hash",
        "fully_populated_bundle_hash",
    }


def test_a_validator_edit_moves_both_m1c_identities(
    reports: dict[str, dict[str, Any]],
) -> None:
    """Sensitivity control: the validator is part of both M1c closures."""
    assert _moved(
        reports, "m1c_validation", ("m1c_validator", *M1C_EVIDENCE_STAMPS)
    ) == {"m1c_validator", *M1C_EVIDENCE_STAMPS}
    assert _moved(reports, "m1c_validation", ("m1d_evidence",)) == {"m1d_evidence"}


def test_an_m1d_only_edit_moves_no_m1c_identity(
    reports: dict[str, dict[str, Any]],
) -> None:
    """The M1c closures are subsets of the M1d ones, never the other way."""
    assert (
        _moved(
            reports,
            "m1d_only",
            ("m1c_validator", *M1C_EVIDENCE_STAMPS, "m1c_outcome_hash"),
        )
        == set()
    )
    assert _moved(reports, "m1d_only", ("m1d_evidence",)) == {"m1d_evidence"}


def test_a_retained_m1c_outcome_and_selection_proof_reverify_after_unrelated_and_m1d_only_edits(  # noqa: E501
    checks: dict[str, dict[str, Any]],
) -> None:
    """Retained M1c audit artifacts replay exactly unless M1c code changed."""
    for name in ("unrelated", "m1d_only"):
        assert checks[name]["outcome"] == "ok", name
        assert checks[name]["selection"] == "ok", name
    assert checks["m1c_evidence"]["outcome"] == (
        "ValueError: economic outcome does not match exact replay"
    )
    assert checks["m1c_evidence"]["selection"] == (
        "ValueError: selection proof does not match exact replay"
    )


def test_a_retained_m1c_validation_run_revalidates_after_an_unrelated_edit(
    checks: dict[str, dict[str, Any]],
) -> None:
    """A retained validation run and decision stay valid unless the validator did.

    An evidence-only edit is the other half of plan decision D3: it does not
    stale a validated M1c dataset either.
    """
    for name in ("unrelated", "m1d_only", "m1c_evidence"):
        assert checks[name]["validation"] == "ok", name
    assert checks["m1c_validation"]["validation"] == (
        "DatasetValidationError: economic_validation_run_mismatch"
    )


def test_a_retained_split_normalized_result_and_m1c_member_bundle_reverify_after_an_unrelated_edit(  # noqa: E501
    checks: dict[str, dict[str, Any]],
) -> None:
    """The split-normalized residual of stage 1 is closed.

    A retained split-normalized result validates, re-derives to identical
    bytes and still materializes, and a retained bundle carrying a genuine M1c
    outcome verifies against exact upstream replay, after an unrelated edit.

    A declared M1c edit refuses both. The first refusal is the M1d one,
    because the M1d evidence closure contains every M1c module: the retained
    split derivation no longer validates, and the bundle's decision view no
    longer re-materializes. The M1c-specific refusal of a retained outcome is
    the retained-outcome test above.
    """
    unrelated = checks["unrelated"]
    assert unrelated["split"] == {
        "valid": True,
        "rederived_identical": True,
        "materialized": "ok",
    }
    assert unrelated["bundle"] == {"valid": True, "verified": "ok"}

    declared = checks["m1c_evidence"]
    assert declared["split"]["valid"] is False
    assert (
        "normalization derivation implementation mismatch" in declared["split"]["error"]
    )
    assert declared["bundle"] == {
        "valid": True,
        "verified": "ValueError: normalization policy artifact unavailable",
    }


def test_the_alpaca_terms_decision_carries_the_m1c_validation_identity_not_provenance(
    tmp_path: Path,
) -> None:
    """The bridge's M1c terms decision binds the validator run identity.

    Which code collected the bytes stays whole-tree provenance; which code
    validated the M1c dataset is the ``m1c-source-validation-v1`` attestation.
    """
    from drift.domain.semantic_attestation import m1c_validation_attestation_hash

    intake = run_pinned_intake(tmp_path / "private")
    identity = intake.economic_terms.decision.validator_implementation_hash
    assert identity == economic_validator_implementation_hash()
    assert identity == m1c_validation_attestation_hash()
    provenance = drift_source_inventory_hash()
    assert identity != provenance
    assert provenance == economic_implementation_hash()
    assert intake.acquisition.receipt.collector_source_hash == provenance
