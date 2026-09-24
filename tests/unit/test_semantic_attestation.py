"""Unit tests for the versioned semantic attestation and its closure guard."""

import ast
import hashlib
import importlib.util
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError

from drift.domain import semantic_attestation
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

_ESCAPE_TO_EXTRA = (
    r"escaped the declared attestation closure: "
    r"drift\.markets\.entry -> drift\.markets\.extra"
)
"""Full escape sentence, so no tmp_path component can satisfy the matcher."""


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


def test_closure_guard_detects_aliased_import_module_expansion(
    tmp_path: Path,
) -> None:
    """An alias for importlib.import_module cannot hide the imported module."""
    root = _package(
        tmp_path,
        _with_entry(
            "from importlib import import_module as _im\n"
            'MODULE = _im("drift.markets.extra")\n'
        ),
    )
    with pytest.raises(SemanticClosureError, match=_ESCAPE_TO_EXTRA):
        verify_semantic_closure(
            modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
        )


def test_closure_guard_rejects_getattr_reached_import_module(
    tmp_path: Path,
) -> None:
    """getattr on a module namespace is an import the guard cannot bind."""
    root = _package(
        tmp_path,
        _with_entry(
            "import importlib\n"
            'MODULE = getattr(importlib, "import_module")("drift.markets.extra")\n'
        ),
    )
    with pytest.raises(
        SemanticClosureError, match="reaches a module namespace indirectly"
    ):
        verify_semantic_closure(
            modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
        )


def test_closure_guard_rejects_getattr_on_the_import_machinery(
    tmp_path: Path,
) -> None:
    """A non-literal attribute of importlib is still an unbindable import."""
    root = _package(
        tmp_path,
        _with_entry(
            "import importlib\n"
            "\n"
            "\n"
            "def load(name: str) -> object:\n"
            "    return getattr(importlib, name)\n"
        ),
    )
    with pytest.raises(
        SemanticClosureError, match="reaches a module namespace indirectly"
    ):
        verify_semantic_closure(
            modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
        )


def test_closure_guard_rejects_getattr_that_names_a_dynamic_import(
    tmp_path: Path,
) -> None:
    """Naming import_module on an unknown owner must also fail closed."""
    root = _package(
        tmp_path,
        _with_entry(
            "def load(container: object) -> object:\n"
            '    return getattr(container, "import_module")\n'
        ),
    )
    with pytest.raises(
        SemanticClosureError, match="reaches a module namespace indirectly"
    ):
        verify_semantic_closure(
            modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
        )


def test_closure_guard_rejects_dynamic_calls_on_an_unresolvable_owner(
    tmp_path: Path,
) -> None:
    """A callee whose owner is itself a call cannot launder exec or import."""
    evaluation = _package(
        tmp_path / "evaluation",
        _with_entry(
            "def run(factory: object) -> None:\n"
            '    factory().exec("import drift.markets.extra")\n'
        ),
    )
    with pytest.raises(SemanticClosureError, match="evaluates code dynamically"):
        verify_semantic_closure(
            modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=evaluation
        )

    importer = _package(
        tmp_path / "importer",
        _with_entry(
            "def run(factory: object) -> object:\n"
            '    return factory().import_module("drift.markets.extra")\n'
        ),
    )
    with pytest.raises(SemanticClosureError, match=_ESCAPE_TO_EXTRA):
        verify_semantic_closure(
            modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=importer
        )


def test_closure_guard_rejects_further_dynamic_reach_spellings(
    tmp_path: Path,
) -> None:
    """Each alias of the same reach is rejected, not just the ones demoed."""
    cases = (
        ("eval", "VALUE = eval('1 + 1')\n", "evaluates code dynamically"),
        (
            "sys-root",
            "import sys\nREGISTRY = getattr(sys, 'modules')\n",
            "reaches a module namespace indirectly",
        ),
        (
            "drift-owner",
            "import drift\nNAMESPACE = vars(drift)\n",
            "reaches a module namespace indirectly",
        ),
    )
    assert len(cases) == 3
    for name, source, message in cases:
        root = _package(tmp_path / name, _with_entry(source))
        with pytest.raises(SemanticClosureError, match=message):
            verify_semantic_closure(
                modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
            )


def test_closure_guard_rejects_module_dict_reached_import_module(
    tmp_path: Path,
) -> None:
    """Indexing a module __dict__ is an import the guard cannot bind."""
    root = _package(
        tmp_path,
        _with_entry(
            "import importlib\n"
            'MODULE = importlib.__dict__["import_module"]("drift.markets.extra")\n'
        ),
    )
    with pytest.raises(SemanticClosureError, match="indexes a module registry"):
        verify_semantic_closure(
            modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
        )


def test_closure_guard_rejects_sys_modules_lookup(tmp_path: Path) -> None:
    """sys.modules reaches an already imported module without importing it."""
    root = _package(
        tmp_path,
        _with_entry('import sys\nMODULE = sys.modules["drift.markets.extra"]\n'),
    )
    with pytest.raises(SemanticClosureError, match="indexes a module registry"):
        verify_semantic_closure(
            modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
        )


def test_closure_guard_detects_attribute_traversal_from_the_package_root(
    tmp_path: Path,
) -> None:
    """Importing only the root package cannot launder a submodule reference."""
    root = _package(
        tmp_path,
        _with_entry("import drift\nOTHER = drift.markets.extra.OTHER\n"),
    )
    with pytest.raises(SemanticClosureError, match=_ESCAPE_TO_EXTRA):
        verify_semantic_closure(
            modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
        )


def test_closure_guard_rejects_exec_reached_import(tmp_path: Path) -> None:
    """Dynamic code evaluation can import anything, so it fails closed."""
    root = _package(
        tmp_path,
        _with_entry(
            "NAMESPACE: dict[str, object] = {}\n"
            'exec("import drift.markets.extra", NAMESPACE)\n'
        ),
    )
    with pytest.raises(SemanticClosureError, match="evaluates code dynamically"):
        verify_semantic_closure(
            modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
        )


def test_closure_guard_allows_non_module_getattr_and_regex_compilation(
    tmp_path: Path,
) -> None:
    """The indirection guards must not reject ordinary declared-module code."""
    root = _package(
        tmp_path,
        _with_entry(
            "import os\n"
            "import re\n"
            "from drift.domain.core import VALUE\n"
            "\n"
            "PATTERN = re.compile(r'^value$')\n"
            "FLAGS = getattr(os, 'O_NOFOLLOW', 0)\n"
            "\n"
            "\n"
            "def read(item: object, name: str) -> object:\n"
            "    return getattr(item, name)\n"
            "\n"
            "\n"
            "def total() -> int:\n"
            "    return VALUE + FLAGS\n"
        ),
    )
    verify_semantic_closure(
        modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
    )


def test_closure_guard_rejects_a_symlinked_source_directory(tmp_path: Path) -> None:
    """A symlinked package directory can redirect declared bytes off-tree."""
    root = _package(tmp_path, _BASE_FILES)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "planted.py").write_text("PLANTED = 1\n", encoding="utf-8")
    (root / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SemanticAttestationError, match="must not contain symlinks"):
        verify_semantic_closure(
            modules=_BASE_DECLARED, seeds=_BASE_SEEDS, package_root=root
        )


def test_default_package_root_reached_through_a_symlink_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The implicit package root must not be a symlinked directory either."""
    real = tmp_path / "real_package"
    (real / "domain").mkdir(parents=True)
    (real / "domain" / "semantic_attestation.py").write_text("", encoding="utf-8")
    source = tmp_path / "src"
    source.mkdir()
    (source / "drift").symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(
        semantic_attestation,
        "__file__",
        str(source / "drift" / "domain" / "semantic_attestation.py"),
    )
    with pytest.raises(
        SemanticAttestationError, match="must not be reached through a symlink"
    ):
        build_semantic_attestation(closure_id=CLOSURE, modules=("drift",))


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


# --- M1d evidence identity (issue 63, stage 1) --------------------------------

_M1D_EVIDENCE_POLICY_AUTHORS = frozenset({"drift.adapters.alpaca_exploratory"})
"""Modules that stamp the M1d evidence identity into a policy they author but
whose semantics M1d does not execute. The bridge authors a schedule generation
policy that ``drift.markets.session_generation`` (a seed) executes, and binds its
own lineage separately, so it is classified here instead of being a seed."""

_M1D_EVIDENCE_IDENTITY_DEFINERS = frozenset({"drift.domain.semantic_attestation"})
"""The module that defines the attestation behind the identity. It declares the
closure rather than deriving evidence, and it is itself a declared module."""

_M1D_EVIDENCE_IDENTITY_NAMES = frozenset(
    {
        "m1d_evidence_attestation",
        "m1d_evidence_attestation_hash",
        "m1d_implementation_hash",
    }
)
"""Every public name that yields the M1d evidence identity."""


def _package_root() -> Path:
    return Path(semantic_attestation.__file__).resolve().parents[1]


def _modules_binding_the_m1d_evidence_identity() -> frozenset[str]:
    """Every installed module that defines, stamps or checks the identity."""
    root = _package_root()
    found: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_bytes())
        for node in ast.walk(tree):
            names = (
                (node.id,)
                if isinstance(node, ast.Name)
                else (node.attr,)
                if isinstance(node, ast.Attribute)
                else (node.name,)
                if isinstance(node, ast.FunctionDef | ast.alias)
                else ()
            )
            if _M1D_EVIDENCE_IDENTITY_NAMES.intersection(names):
                parts = list(path.relative_to(root).with_suffix("").parts)
                if parts[-1] == "__init__":
                    parts.pop()
                found.add(".".join(("drift", *parts)))
                break
    return frozenset(found)


def _load_pinned_m1d() -> ModuleType:
    helper = Path(__file__).resolve().parents[1] / "_pinned_m1d.py"
    spec = importlib.util.spec_from_file_location("_attestation_pinned_m1d", helper)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_declared_m1d_evidence_closure_is_exactly_the_resolved_closure() -> None:
    assert resolve_semantic_closure(
        seeds=semantic_attestation.M1D_EVIDENCE_SEEDS
    ) == tuple(semantic_attestation.M1D_EVIDENCE_SEMANTIC_MODULES)


def test_m1d_evidence_closure_guard_accepts_the_installed_package() -> None:
    verify_semantic_closure(
        modules=semantic_attestation.M1D_EVIDENCE_SEMANTIC_MODULES,
        seeds=semantic_attestation.M1D_EVIDENCE_SEEDS,
    )


def test_m1d_evidence_attestation_is_bounded_and_versioned() -> None:
    attestation = semantic_attestation.m1d_evidence_attestation()
    assert attestation.algorithm_id == SEMANTIC_ATTESTATION_ALGORITHM_V1
    assert attestation.schema_version == "1"
    assert attestation.closure_id == "m1d-evidence-v1"
    assert attestation.closure_id == semantic_attestation.M1D_EVIDENCE_CLOSURE_ID
    assert attestation.declared_modules == tuple(
        semantic_attestation.M1D_EVIDENCE_SEMANTIC_MODULES
    )
    assert (
        semantic_attestation.m1d_evidence_attestation_hash()
        == attestation.attestation_hash
    )
    rebuilt = build_semantic_attestation(
        closure_id=semantic_attestation.M1D_EVIDENCE_CLOSURE_ID,
        modules=semantic_attestation.M1D_EVIDENCE_SEMANTIC_MODULES,
    )
    assert rebuilt == attestation


def test_m1d_evidence_closure_excludes_evaluator_adapter_ledger_and_qualification() -> (
    None
):
    """Consumers, collectors and storage cannot move the M1d evidence identity."""
    for module in semantic_attestation.M1D_EVIDENCE_SEMANTIC_MODULES:
        assert not module.startswith(
            (
                "drift.adapters",
                "drift.config",
                "drift.evaluator",
                "drift.ledger",
                "drift.qualification",
            )
        ), module
    declared = set(semantic_attestation.M1D_EVIDENCE_SEMANTIC_MODULES)
    assert "drift.evaluator.engine" not in declared
    assert "drift.domain.evaluator_bundles" not in declared


def test_m1d_evidence_identity_is_distinct_from_validation_and_whole_tree() -> None:
    evidence = semantic_attestation.m1d_evidence_attestation_hash()
    assert evidence != m1d_semantic_attestation_hash()
    assert evidence != economic_implementation_hash()
    assert semantic_attestation.M1D_EVIDENCE_CLOSURE_ID != M1D_VALIDATION_CLOSURE_ID
    # The validation closure is part of what the evidence depends on.
    assert set(M1D_VALIDATION_SEMANTIC_MODULES) < set(
        semantic_attestation.M1D_EVIDENCE_SEMANTIC_MODULES
    )


def test_m1d_evidence_attestation_fails_closed_on_an_incomplete_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The accessor runs the closure guard; it never attests a leaky declaration."""
    declared = tuple(
        module
        for module in semantic_attestation.M1D_EVIDENCE_SEMANTIC_MODULES
        if module != "drift.domain.economic_results"
    )
    semantic_attestation.m1d_evidence_attestation.cache_clear()
    monkeypatch.setattr(semantic_attestation, "M1D_EVIDENCE_SEMANTIC_MODULES", declared)
    try:
        with pytest.raises(
            SemanticClosureError,
            match=r"escaped the declared attestation closure: .*"
            r"-> drift\.domain\.economic_results",
        ):
            semantic_attestation.m1d_evidence_attestation()
    finally:
        semantic_attestation.m1d_evidence_attestation.cache_clear()


def test_every_module_binding_the_m1d_evidence_identity_is_a_seed() -> None:
    """A new producer or validator cannot bind the identity outside the closure."""
    binding = _modules_binding_the_m1d_evidence_identity()
    seeds = frozenset(semantic_attestation.M1D_EVIDENCE_SEEDS)
    assert binding == (
        seeds | _M1D_EVIDENCE_POLICY_AUTHORS | _M1D_EVIDENCE_IDENTITY_DEFINERS
    )
    declared = set(semantic_attestation.M1D_EVIDENCE_SEMANTIC_MODULES)
    assert not _M1D_EVIDENCE_POLICY_AUTHORS & declared
    assert _M1D_EVIDENCE_IDENTITY_DEFINERS <= declared


def test_every_m1d_evidence_closure_module_is_byte_pinned_by_the_current_freeze() -> (
    None
):
    """No declared module can move the identity while every byte freeze is green."""
    pins = _load_pinned_m1d().PROTECTED_M1D_SHA256
    root = _package_root()
    repository = root.parents[1]
    for module in semantic_attestation.M1D_EVIDENCE_SEMANTIC_MODULES:
        path = semantic_attestation._declared_module_path(root, module)
        relative = path.relative_to(repository).as_posix()
        assert relative in pins, module
        assert hashlib.sha256(path.read_bytes()).hexdigest() == pins[relative], module
