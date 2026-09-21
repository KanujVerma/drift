"""Unit tests for the versioned semantic attestation and its closure guard."""

import hashlib
from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import ValidationError

from drift.domain.economic_common import economic_implementation_hash
from drift.domain.semantic_attestation import (
    M1D_VALIDATION_CLOSURE_ID,
    M1D_VALIDATION_SEEDS,
    M1D_VALIDATION_SEMANTIC_MODULES,
    SEMANTIC_ATTESTATION_ALGORITHM_V1,
    SemanticAttestationError,
    SemanticAttestationV1,
    SemanticClosureError,
    SemanticModuleDigestV1,
    build_semantic_attestation,
    m1d_semantic_attestation,
    m1d_semantic_attestation_hash,
    resolve_semantic_closure,
    semantic_attestation_hash,
    verify_semantic_closure,
)
from drift.markets.observation_validation import (
    observation_validator_implementation_hash,
)
from drift.markets.session_validation import session_validator_implementation_hash
from drift.serialization.canonical import content_hash

CLOSURE = "unit-test-closure-v1"

_BASE_FILES = {
    "__init__.py": "",
    "domain/__init__.py": "",
    "domain/core.py": "VALUE = 1\n",
    "markets/__init__.py": "",
    "markets/entry.py": "from drift.domain.core import VALUE\n",
    "markets/extra.py": "OTHER = 2\n",
}

_BASE_DECLARED = (
    "drift",
    "drift.domain",
    "drift.domain.core",
    "drift.markets",
    "drift.markets.entry",
)
_BASE_SEEDS = ("drift.markets.entry",)


def _package(tmp_path: Path, files: Mapping[str, str]) -> Path:
    """Write a synthetic installed ``drift`` package and return its root."""
    root = tmp_path / "drift"
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return root


def _with_entry(source: str) -> dict[str, str]:
    files = dict(_BASE_FILES)
    files["markets/entry.py"] = source
    return files


def _preimage(attestation: SemanticAttestationV1) -> dict[str, object]:
    dump = attestation.model_dump(mode="python")
    dump.pop("attestation_hash")
    return dump


def test_preimage_binds_algorithm_closure_declaration_and_digests(
    tmp_path: Path,
) -> None:
    root = _package(tmp_path, _BASE_FILES)
    attestation = build_semantic_attestation(
        closure_id=CLOSURE, modules=_BASE_DECLARED, package_root=root
    )
    preimage = _preimage(attestation)
    assert preimage["algorithm_id"] == SEMANTIC_ATTESTATION_ALGORITHM_V1
    assert preimage["schema_version"] == "1"
    assert preimage["closure_id"] == CLOSURE
    assert preimage["declared_modules"] == _BASE_DECLARED
    digests = {
        item["module"]: item["source_sha256"]
        for item in attestation.model_dump(mode="python")["module_digests"]
    }
    assert set(digests) == set(_BASE_DECLARED)
    expected = hashlib.sha256((root / "domain" / "core.py").read_bytes()).hexdigest()
    assert digests["drift.domain.core"] == expected
    assert attestation.attestation_hash == content_hash(preimage)
    assert attestation.attestation_hash == semantic_attestation_hash(attestation)


def test_preimage_declares_the_module_set_independently_of_digests(
    tmp_path: Path,
) -> None:
    root = _package(tmp_path, _BASE_FILES)
    attestation = build_semantic_attestation(
        closure_id=CLOSURE, modules=_BASE_DECLARED, package_root=root
    )
    preimage = _preimage(attestation)
    assert "declared_modules" in preimage
    stripped = {key: value for key, value in preimage.items()}
    stripped.pop("declared_modules")
    assert content_hash(stripped) != attestation.attestation_hash


def test_attestation_hash_tracks_declared_module_bytes(tmp_path: Path) -> None:
    root = _package(tmp_path, _BASE_FILES)
    before = build_semantic_attestation(
        closure_id=CLOSURE, modules=_BASE_DECLARED, package_root=root
    )
    (root / "domain" / "core.py").write_text("VALUE = 2\n", encoding="utf-8")
    after = build_semantic_attestation(
        closure_id=CLOSURE, modules=_BASE_DECLARED, package_root=root
    )
    assert before.attestation_hash != after.attestation_hash


def test_attestation_ignores_modules_outside_the_declared_set(
    tmp_path: Path,
) -> None:
    root = _package(tmp_path, _BASE_FILES)
    before = build_semantic_attestation(
        closure_id=CLOSURE, modules=_BASE_DECLARED, package_root=root
    )
    (root / "markets" / "extra.py").write_text("OTHER = 99\n", encoding="utf-8")
    (root / "markets" / "unrelated.py").write_text("NEW = 1\n", encoding="utf-8")
    after = build_semantic_attestation(
        closure_id=CLOSURE, modules=_BASE_DECLARED, package_root=root
    )
    assert before.attestation_hash == after.attestation_hash


def test_attestation_hash_tracks_the_closure_identifier(tmp_path: Path) -> None:
    root = _package(tmp_path, _BASE_FILES)
    first = build_semantic_attestation(
        closure_id=CLOSURE, modules=_BASE_DECLARED, package_root=root
    )
    second = build_semantic_attestation(
        closure_id="other-closure-v1", modules=_BASE_DECLARED, package_root=root
    )
    assert first.attestation_hash != second.attestation_hash


def test_attestation_hash_tracks_the_declared_module_set(tmp_path: Path) -> None:
    root = _package(tmp_path, _BASE_FILES)
    narrow = build_semantic_attestation(
        closure_id=CLOSURE, modules=_BASE_DECLARED, package_root=root
    )
    wide = build_semantic_attestation(
        closure_id=CLOSURE,
        modules=(*_BASE_DECLARED, "drift.markets.extra"),
        package_root=root,
    )
    assert narrow.attestation_hash != wide.attestation_hash


def test_attestation_rejects_hash_tampering(tmp_path: Path) -> None:
    root = _package(tmp_path, _BASE_FILES)
    attestation = build_semantic_attestation(
        closure_id=CLOSURE, modules=_BASE_DECLARED, package_root=root
    )
    payload = attestation.model_dump(mode="python")
    payload["attestation_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="attestation hash mismatch"):
        SemanticAttestationV1.model_validate(payload)


def test_attestation_rejects_digests_disagreeing_with_the_declaration(
    tmp_path: Path,
) -> None:
    root = _package(tmp_path, _BASE_FILES)
    attestation = build_semantic_attestation(
        closure_id=CLOSURE, modules=_BASE_DECLARED, package_root=root
    )
    payload = attestation.model_dump(mode="python")
    payload["declared_modules"] = tuple(
        item for item in _BASE_DECLARED if item != "drift.domain.core"
    )
    with pytest.raises(ValidationError, match="declared modules"):
        SemanticAttestationV1.model_validate(payload)


def test_attestation_rejects_unsorted_or_duplicate_declarations() -> None:
    digest = SemanticModuleDigestV1(module="drift", source_sha256="0" * 64)
    with pytest.raises(ValidationError, match="unique, sorted"):
        SemanticAttestationV1.model_validate(
            {
                "schema_version": "1",
                "algorithm_id": SEMANTIC_ATTESTATION_ALGORITHM_V1,
                "closure_id": CLOSURE,
                "declared_modules": ("drift.domain", "drift"),
                "module_digests": (digest.model_dump(mode="python"),),
                "attestation_hash": "0" * 64,
            }
        )
    with pytest.raises(ValidationError, match="unique, sorted"):
        SemanticAttestationV1.model_validate(
            {
                "schema_version": "1",
                "algorithm_id": SEMANTIC_ATTESTATION_ALGORITHM_V1,
                "closure_id": CLOSURE,
                "declared_modules": ("drift", "drift"),
                "module_digests": (digest.model_dump(mode="python"),),
                "attestation_hash": "0" * 64,
            }
        )


def test_attestation_rejects_an_empty_declaration() -> None:
    with pytest.raises(ValidationError, match="at least one module"):
        SemanticAttestationV1.model_validate(
            {
                "schema_version": "1",
                "algorithm_id": SEMANTIC_ATTESTATION_ALGORITHM_V1,
                "closure_id": CLOSURE,
                "declared_modules": (),
                "module_digests": (),
                "attestation_hash": "0" * 64,
            }
        )


def test_build_rejects_a_declared_module_that_is_absent(tmp_path: Path) -> None:
    root = _package(tmp_path, _BASE_FILES)
    with pytest.raises(SemanticAttestationError, match="drift.markets.ghost"):
        build_semantic_attestation(
            closure_id=CLOSURE,
            modules=(*_BASE_DECLARED, "drift.markets.ghost"),
            package_root=root,
        )


def test_build_rejects_a_module_name_outside_the_drift_package(
    tmp_path: Path,
) -> None:
    root = _package(tmp_path, _BASE_FILES)
    with pytest.raises(SemanticAttestationError, match="module name"):
        build_semantic_attestation(
            closure_id=CLOSURE,
            modules=("drift", "os.path"),
            package_root=root,
        )


def test_build_rejects_a_symlinked_declared_module(tmp_path: Path) -> None:
    root = _package(tmp_path, _BASE_FILES)
    target = tmp_path / "outside.py"
    target.write_text("VALUE = 3\n", encoding="utf-8")
    link = root / "domain" / "linked.py"
    link.symlink_to(target)
    with pytest.raises(SemanticAttestationError, match="must not be a symlink"):
        build_semantic_attestation(
            closure_id=CLOSURE,
            modules=tuple(sorted((*_BASE_DECLARED, "drift.domain.linked"))),
            package_root=root,
        )


def test_closure_guard_accepts_a_closed_declaration(tmp_path: Path) -> None:
    root = _package(tmp_path, _BASE_FILES)
    verify_semantic_closure(
        modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
    )


def test_closure_guard_detects_module_level_import_expansion(
    tmp_path: Path,
) -> None:
    root = _package(
        tmp_path,
        _with_entry(
            "from drift.domain.core import VALUE\n"
            "from drift.markets.extra import OTHER\n"
        ),
    )
    with pytest.raises(SemanticClosureError, match="drift.markets.extra"):
        verify_semantic_closure(
            modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
        )


def test_closure_guard_detects_function_local_import_expansion(
    tmp_path: Path,
) -> None:
    root = _package(
        tmp_path,
        _with_entry(
            "def run() -> int:\n"
            "    from drift.markets.extra import OTHER\n"
            "\n"
            "    return OTHER\n"
        ),
    )
    with pytest.raises(SemanticClosureError, match="drift.markets.extra"):
        verify_semantic_closure(
            modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
        )


def test_closure_guard_detects_plain_import_expansion(tmp_path: Path) -> None:
    root = _package(tmp_path, _with_entry("import drift.markets.extra\n"))
    with pytest.raises(SemanticClosureError, match="drift.markets.extra"):
        verify_semantic_closure(
            modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
        )


def test_closure_guard_detects_submodule_import_from_a_package(
    tmp_path: Path,
) -> None:
    root = _package(tmp_path, _with_entry("from drift.markets import extra\n"))
    with pytest.raises(SemanticClosureError, match="drift.markets.extra"):
        verify_semantic_closure(
            modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
        )


def test_closure_guard_detects_dynamic_import_expansion(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        _with_entry(
            'OTHER = __import__("drift.markets.extra", fromlist=["OTHER"]).OTHER\n'
        ),
    )
    with pytest.raises(SemanticClosureError, match="drift.markets.extra"):
        verify_semantic_closure(
            modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
        )


def test_closure_guard_detects_importlib_expansion(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        _with_entry(
            "import importlib\n"
            'MODULE = importlib.import_module("drift.markets.extra")\n'
        ),
    )
    with pytest.raises(SemanticClosureError, match="drift.markets.extra"):
        verify_semantic_closure(
            modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
        )


def test_closure_guard_rejects_an_unresolvable_dynamic_import(
    tmp_path: Path,
) -> None:
    root = _package(
        tmp_path,
        _with_entry("def run(name: str) -> object:\n    return __import__(name)\n"),
    )
    with pytest.raises(SemanticClosureError, match="non-literal"):
        verify_semantic_closure(
            modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
        )


def test_closure_guard_rejects_relative_imports(tmp_path: Path) -> None:
    root = _package(tmp_path, _with_entry("from .extra import OTHER\n"))
    with pytest.raises(SemanticClosureError, match="relative import"):
        verify_semantic_closure(
            modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
        )


def test_closure_guard_requires_the_seeds_to_be_declared(tmp_path: Path) -> None:
    root = _package(tmp_path, _BASE_FILES)
    with pytest.raises(SemanticClosureError, match="drift.markets.entry"):
        verify_semantic_closure(
            modules=("drift", "drift.domain", "drift.domain.core"),
            seeds=_BASE_SEEDS,
            package_root=root,
        )


def test_closure_guard_ignores_non_drift_imports(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        _with_entry("import json\nfrom pathlib import Path\n"),
    )
    verify_semantic_closure(
        modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
    )


def test_resolved_closure_walks_transitively(tmp_path: Path) -> None:
    files = dict(_BASE_FILES)
    files["markets/entry.py"] = "from drift.markets.extra import OTHER\n"
    files["markets/extra.py"] = "from drift.domain.core import VALUE\n"
    root = _package(tmp_path, files)
    assert resolve_semantic_closure(seeds=_BASE_SEEDS, package_root=root) == (
        "drift",
        "drift.domain",
        "drift.domain.core",
        "drift.markets",
        "drift.markets.entry",
        "drift.markets.extra",
    )


def test_declared_m1d_closure_is_exactly_the_resolved_closure() -> None:
    assert resolve_semantic_closure(seeds=M1D_VALIDATION_SEEDS) == tuple(
        M1D_VALIDATION_SEMANTIC_MODULES
    )


def test_m1d_closure_guard_accepts_the_installed_package() -> None:
    verify_semantic_closure(
        modules=M1D_VALIDATION_SEMANTIC_MODULES, seeds=M1D_VALIDATION_SEEDS
    )


def test_m1d_attestation_is_bounded_and_versioned() -> None:
    attestation = m1d_semantic_attestation()
    assert attestation.algorithm_id == SEMANTIC_ATTESTATION_ALGORITHM_V1
    assert attestation.schema_version == "1"
    assert attestation.closure_id == M1D_VALIDATION_CLOSURE_ID
    assert attestation.declared_modules == tuple(M1D_VALIDATION_SEMANTIC_MODULES)
    assert m1d_semantic_attestation_hash() == attestation.attestation_hash


def test_m1d_attestation_excludes_modules_outside_the_declared_closure() -> None:
    declared = set(M1D_VALIDATION_SEMANTIC_MODULES)
    assert "drift.markets.normalization" not in declared
    assert "drift.markets.observation_usability" not in declared
    assert "drift.ledger.sqlite" not in declared
    assert "drift.qualification.harness" not in declared


def test_m1d_validation_run_identity_uses_the_semantic_attestation() -> None:
    expected = m1d_semantic_attestation_hash()
    assert observation_validator_implementation_hash() == expected
    assert session_validator_implementation_hash() == expected


def test_semantic_attestation_is_not_the_whole_tree_provenance_hash() -> None:
    assert m1d_semantic_attestation_hash() != economic_implementation_hash()


def test_whole_tree_provenance_hash_is_retained() -> None:
    digest = economic_implementation_hash()
    assert len(digest) == 64
    assert digest == economic_implementation_hash()
