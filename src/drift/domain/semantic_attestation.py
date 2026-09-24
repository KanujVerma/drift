"""Versioned semantic attestation over an explicitly declared module closure.

The whole-tree inventory produced by ``economic_implementation_hash`` remains
the build and repository provenance identity: it answers "which repository
state produced this artifact". It cannot answer "which code decided this
validation", because every Python file in the package contributes to it, so an
edit anywhere invalidates every recorded replay identity.

This module provides the narrower identity. A semantic attestation binds a
versioned algorithm identifier, an explicitly declared and canonically ordered
set of semantic modules, the exact SHA-256 of each declared module, and the
declaration itself, into one content hash. Modules outside the declaration
cannot change that hash.

An explicit declaration is only trustworthy while it stays complete, so
``verify_semantic_closure`` re-derives every ``drift`` module reference that the
declared modules actually make, including function-local imports, literal
dynamic imports resolved through their local alias, and attribute traversal
from the package root, and fails loudly when a reference escapes the
declaration. Every remaining way to reach a module that cannot be bound to an
exact name statically -- dynamic code evaluation, a ``getattr`` aimed at the
import machinery, and indexing ``sys.modules`` or a module ``__dict__`` -- fails
closed instead of being ignored.

Two closures are declared here. ``m1d-source-validation-v1`` identifies the M1d
validator runs (issue #32). ``m1d-evidence-v1`` identifies the code that
derives, stamps and checks M1d evidence (issue #63, stage 1): every M1d
normalization, action-session, session-binding, session-generation, selection
and usability record binds it as ``implementation_hash``. Values that arrive as
data, such as the M1c whole-tree identities inside composed economic history,
are not attested by either closure.
"""

import ast
import os
import re
import stat
from collections.abc import Sequence
from functools import cache
from hashlib import sha256
from pathlib import Path
from typing import Literal, Self

from pydantic import field_validator, model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash
from drift.errors import DriftError
from drift.serialization.canonical import content_hash

SEMANTIC_ATTESTATION_ALGORITHM_V1 = "drift-semantic-attestation-v1"
"""Identifier for version 1 of the semantic attestation preimage algorithm."""

M1D_VALIDATION_CLOSURE_ID = "m1d-source-validation-v1"
"""Identifier for the M1d source-observation and session validation closure."""

M1D_VALIDATION_SEEDS: tuple[str, ...] = (
    "drift.markets.observation_validation",
    "drift.markets.session_validation",
)
"""Entry points whose semantics the M1d validation closure must cover."""

M1D_VALIDATION_SEMANTIC_MODULES: tuple[str, ...] = (
    "drift",
    "drift.datasets",
    "drift.datasets.assertions",
    "drift.datasets.hashing",
    "drift.datasets.resolver",
    "drift.domain",
    "drift.domain.artifacts",
    "drift.domain.assertions",
    "drift.domain.common",
    "drift.domain.dataset_validation",
    "drift.domain.datasets",
    "drift.domain.economic_common",
    "drift.domain.economic_coverage",
    "drift.domain.economic_events",
    "drift.domain.manifests",
    "drift.domain.observation_query",
    "drift.domain.observations",
    "drift.domain.provenance_references",
    "drift.domain.revisions",
    "drift.domain.securities",
    "drift.domain.semantic_attestation",
    "drift.domain.sessions",
    "drift.domain.temporal",
    "drift.domain.universes",
    "drift.errors",
    "drift.markets",
    "drift.markets.economic_validation",
    "drift.markets.identity",
    "drift.markets.observation_validation",
    "drift.markets.session_validation",
    "drift.markets.universes",
    "drift.markets.validation",
    "drift.serialization",
    "drift.serialization.canonical",
)
"""The declared semantic closure of the M1d validation entry points."""

M1D_EVIDENCE_CLOSURE_ID = "m1d-evidence-v1"
"""Identifier for the M1d evidence identity closure."""

M1D_EVIDENCE_SEEDS: tuple[str, ...] = (
    "drift.domain.action_sessions",
    "drift.domain.normalization",
    "drift.domain.observation_query",
    "drift.markets.action_sessions",
    "drift.markets.normalization",
    "drift.markets.observation_selection",
    "drift.markets.observation_usability",
    "drift.markets.session_binding",
    "drift.markets.session_generation",
)
"""Every module that defines, stamps or checks the M1d evidence identity."""

M1D_EVIDENCE_SEMANTIC_MODULES: tuple[str, ...] = (
    "drift",
    "drift.datasets",
    "drift.datasets.assertions",
    "drift.datasets.hashing",
    "drift.datasets.resolver",
    "drift.domain",
    "drift.domain.action_sessions",
    "drift.domain.artifacts",
    "drift.domain.assertions",
    "drift.domain.common",
    "drift.domain.dataset_validation",
    "drift.domain.datasets",
    "drift.domain.economic_common",
    "drift.domain.economic_coverage",
    "drift.domain.economic_events",
    "drift.domain.economic_queries",
    "drift.domain.economic_results",
    "drift.domain.manifests",
    "drift.domain.normalization",
    "drift.domain.observation_query",
    "drift.domain.observation_usability",
    "drift.domain.observations",
    "drift.domain.provenance_references",
    "drift.domain.revisions",
    "drift.domain.securities",
    "drift.domain.semantic_attestation",
    "drift.domain.sessions",
    "drift.domain.temporal",
    "drift.domain.universes",
    "drift.errors",
    "drift.markets",
    "drift.markets.action_sessions",
    "drift.markets.economic_outcomes",
    "drift.markets.economic_selection",
    "drift.markets.economic_validation",
    "drift.markets.identity",
    "drift.markets.normalization",
    "drift.markets.observation_selection",
    "drift.markets.observation_usability",
    "drift.markets.observation_validation",
    "drift.markets.session_binding",
    "drift.markets.session_generation",
    "drift.markets.session_validation",
    "drift.markets.universes",
    "drift.markets.validation",
    "drift.serialization",
    "drift.serialization.canonical",
)
"""The declared semantic closure of the M1d evidence identity."""

_MODULE_NAME_PATTERN = re.compile(r"^drift(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_DYNAMIC_IMPORT_NAMES = frozenset({"__import__", "import_module"})
_CODE_EVALUATION_TARGETS = frozenset(
    {
        "builtins.compile",
        "builtins.eval",
        "builtins.exec",
        "compile",
        "eval",
        "exec",
    }
)
"""Call targets that can import anything from a string the guard cannot read."""

_NAMESPACE_LOOKUP_TARGETS = frozenset(
    {"builtins.getattr", "builtins.vars", "getattr", "vars"}
)
"""Call targets that can pull an arbitrary attribute out of a namespace."""

_IMPORT_MACHINERY_ROOTS = frozenset({"builtins", "importlib", "sys"})
"""Non-``drift`` roots whose namespaces expose the import machinery itself."""

_MODULE_REGISTRY_PATHS = frozenset({"sys.modules"})
"""Subscriptable namespaces that hand out already imported module objects."""


class SemanticAttestationError(DriftError):
    """Raised when declared semantic source cannot be read exactly."""


class SemanticClosureError(SemanticAttestationError):
    """Raised when semantic dependencies escape the declared closure."""


def semantic_attestation_hash(attestation: SemanticAttestationV1) -> SHA256Hash:
    """Compute the canonical content hash for SemanticAttestationV1."""
    dump = attestation.model_dump(mode="python")
    dump.pop("attestation_hash", None)
    return content_hash(dump)


class SemanticModuleDigestV1(FrozenModel):
    """One declared semantic module bound to the exact bytes of its source."""

    schema_version: Literal["1"] = "1"
    module: NonBlankStr
    source_sha256: SHA256Hash


class SemanticAttestationV1(FrozenModel):
    """A versioned replay identity over an explicitly declared module closure."""

    schema_version: Literal["1"] = "1"
    algorithm_id: Literal["drift-semantic-attestation-v1"] = (
        "drift-semantic-attestation-v1"
    )
    closure_id: NonBlankStr
    declared_modules: tuple[NonBlankStr, ...]
    module_digests: tuple[SemanticModuleDigestV1, ...]
    attestation_hash: SHA256Hash

    @field_validator("declared_modules")
    @classmethod
    def canonicalize_declared_modules(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("semantic attestation requires at least one module")
        if tuple(sorted(set(values))) != tuple(values):
            raise ValueError("semantic attestation modules must be unique, sorted")
        return tuple(values)

    @model_validator(mode="after")
    def validate_attestation(self) -> Self:
        covered = tuple(item.module for item in self.module_digests)
        if covered != self.declared_modules:
            raise ValueError(
                "semantic attestation digests must cover exactly the "
                "declared modules in declared order"
            )
        expected = semantic_attestation_hash(self)
        if self.attestation_hash != expected:
            raise ValueError(
                f"attestation hash mismatch: expected {expected}, "
                f"got {self.attestation_hash}"
            )
        return self


def build_semantic_attestation(
    *,
    closure_id: str,
    modules: Sequence[str],
    package_root: Path | None = None,
) -> SemanticAttestationV1:
    """Attest the exact bytes of one canonically declared semantic closure."""
    root = _resolved_package_root(package_root)
    declared = _canonical_declaration(modules)
    digests = tuple(
        SemanticModuleDigestV1(
            module=module,
            source_sha256=sha256(
                _read_module_bytes(_declared_module_path(root, module))
            ).hexdigest(),
        )
        for module in declared
    )
    provisional = SemanticAttestationV1.model_construct(
        schema_version="1",
        algorithm_id=SEMANTIC_ATTESTATION_ALGORITHM_V1,
        closure_id=closure_id,
        declared_modules=declared,
        module_digests=digests,
        attestation_hash="0" * 64,
    )
    return SemanticAttestationV1(
        closure_id=closure_id,
        declared_modules=declared,
        module_digests=digests,
        attestation_hash=semantic_attestation_hash(provisional),
    )


def verify_semantic_closure(
    *,
    modules: Sequence[str],
    seeds: Sequence[str],
    package_root: Path | None = None,
) -> None:
    """Reject a declaration that a declared module's own imports escape.

    The guard enforces the safety direction only: every ``drift`` module that a
    declared module imports must itself be declared. A declaration that is
    wider than the reachable closure stays accepted here, because narrowing is
    not a soundness failure; the exactness of the declaration is asserted
    against ``resolve_semantic_closure`` in the test suite instead.
    """
    root = _resolved_package_root(package_root)
    declared = _canonical_declaration(modules)
    declared_set = frozenset(declared)
    missing_seeds = tuple(sorted(frozenset(seeds) - declared_set))
    if missing_seeds:
        raise SemanticClosureError(
            f"declared semantic closure omits entry points: {missing_seeds}"
        )
    index = _installed_module_index(root)
    installed = frozenset(index)
    absent = tuple(sorted(declared_set - installed))
    if absent:
        raise SemanticClosureError(
            f"declared semantic modules are not installed: {absent}"
        )
    escapes: list[str] = []
    for module in declared:
        references = _semantic_references(
            module, _read_module_bytes(index[module]), installed
        )
        escaped = tuple(sorted(references - declared_set))
        if escaped:
            escapes.append(f"{module} -> {', '.join(escaped)}")
    if escapes:
        raise SemanticClosureError(
            "semantic dependencies escaped the declared attestation closure: "
            + "; ".join(escapes)
        )


def resolve_semantic_closure(
    *,
    seeds: Sequence[str],
    package_root: Path | None = None,
) -> tuple[str, ...]:
    """Walk the exact transitive ``drift`` module closure of the given seeds."""
    root = _resolved_package_root(package_root)
    index = _installed_module_index(root)
    installed = frozenset(index)
    pending: list[str] = []
    for seed in seeds:
        if seed not in installed:
            raise SemanticClosureError(
                f"semantic closure seed is not installed: {seed}"
            )
        pending.extend(_ancestor_modules(seed, installed))
    reached: set[str] = set()
    while pending:
        module = pending.pop()
        if module in reached:
            continue
        reached.add(module)
        references = _semantic_references(
            module, _read_module_bytes(index[module]), installed
        )
        pending.extend(name for name in references if name not in reached)
    return tuple(sorted(reached))


@cache
def m1d_semantic_attestation() -> SemanticAttestationV1:
    """Return the guarded, bounded M1d source-validation replay identity."""
    verify_semantic_closure(
        modules=M1D_VALIDATION_SEMANTIC_MODULES, seeds=M1D_VALIDATION_SEEDS
    )
    return build_semantic_attestation(
        closure_id=M1D_VALIDATION_CLOSURE_ID,
        modules=M1D_VALIDATION_SEMANTIC_MODULES,
    )


def m1d_semantic_attestation_hash() -> SHA256Hash:
    """Return the M1d semantic replay identity as a bare content hash."""
    return m1d_semantic_attestation().attestation_hash


@cache
def m1d_evidence_attestation() -> SemanticAttestationV1:
    """Return the guarded, bounded identity of the code deriving M1d evidence."""
    verify_semantic_closure(
        modules=M1D_EVIDENCE_SEMANTIC_MODULES, seeds=M1D_EVIDENCE_SEEDS
    )
    return build_semantic_attestation(
        closure_id=M1D_EVIDENCE_CLOSURE_ID,
        modules=M1D_EVIDENCE_SEMANTIC_MODULES,
    )


def m1d_evidence_attestation_hash() -> SHA256Hash:
    """Return the M1d evidence identity as a bare content hash."""
    return m1d_evidence_attestation().attestation_hash


def _canonical_declaration(modules: Sequence[str]) -> tuple[str, ...]:
    declared = tuple(modules)
    if not declared:
        raise SemanticAttestationError(
            "semantic attestation requires at least one module"
        )
    for module in declared:
        if _MODULE_NAME_PATTERN.fullmatch(module) is None:
            raise SemanticAttestationError(
                f"invalid semantic module name outside the drift package: {module}"
            )
    if tuple(sorted(set(declared))) != declared:
        raise SemanticAttestationError(
            "semantic attestation modules must be unique, sorted"
        )
    return declared


def _resolved_package_root(package_root: Path | None) -> Path:
    if package_root is not None:
        return package_root
    module_path = Path(__file__).absolute()
    root = module_path.parent.parent
    if module_path.is_symlink() or root.is_symlink():
        raise SemanticAttestationError(
            "semantic package root must not be reached through a symlink"
        )
    if not root.is_dir():
        raise SemanticAttestationError("semantic package root must be a real directory")
    return root


def _declared_module_path(package_root: Path, module: str) -> Path:
    parts = module.split(".")[1:]
    package_init = package_root.joinpath(*parts, "__init__.py")
    if package_init.is_file():
        return package_init
    if parts:
        leaf = package_root.joinpath(*parts[:-1], f"{parts[-1]}.py")
        if leaf.is_file():
            return leaf
    raise SemanticAttestationError(
        f"declared semantic module is not installed: {module}"
    )


def _installed_module_index(package_root: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    pending = [package_root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as scanner:
                entries = sorted(scanner, key=lambda entry: entry.name)
        except OSError as error:
            raise SemanticAttestationError(
                f"semantic source directory is unreadable: {directory}"
            ) from error
        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink():
                raise SemanticAttestationError(
                    f"semantic source tree must not contain symlinks: {path}"
                )
            if entry.is_dir(follow_symlinks=False):
                pending.append(path)
            elif entry.is_file(follow_symlinks=False) and path.suffix == ".py":
                index[_installed_module_name(package_root, path)] = path
    return index


def _installed_module_name(package_root: Path, path: Path) -> str:
    parts = list(path.relative_to(package_root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(("drift", *parts))


def _read_module_bytes(path: Path) -> bytes:
    if path.is_symlink():
        raise SemanticAttestationError(
            f"declared semantic module must not be a symlink: {path}"
        )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise SemanticAttestationError(
            f"declared semantic module is unreadable: {path}"
        ) from error
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise SemanticAttestationError(
                f"declared semantic module must be a regular file: {path}"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            return source.read()
    except OSError as error:
        raise SemanticAttestationError(
            f"declared semantic module is unreadable: {path}"
        ) from error
    finally:
        os.close(descriptor)


def _ancestor_modules(candidate: str, installed: frozenset[str]) -> frozenset[str]:
    if candidate != "drift" and not candidate.startswith("drift."):
        return frozenset()
    parts = candidate.split(".")
    names = (".".join(parts[: index + 1]) for index in range(len(parts)))
    return frozenset(name for name in names if name in installed)


def _semantic_references(
    module: str, source: bytes, installed: frozenset[str]
) -> frozenset[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        raise SemanticAttestationError(
            f"declared semantic module does not parse: {module}"
        ) from error
    aliases = _module_aliases(tree)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found |= _ancestor_modules(alias.name, installed)
        elif isinstance(node, ast.ImportFrom):
            found |= _import_from_references(node, module, installed)
        elif isinstance(node, ast.Call):
            found |= _call_references(node, module, installed, aliases)
        elif isinstance(node, ast.Subscript):
            _reject_module_registry_subscript(node, module, aliases)
        elif isinstance(node, ast.Attribute):
            found |= _attribute_chain_references(node, installed, aliases)
    return frozenset(found)


def _module_aliases(tree: ast.AST) -> dict[str, str]:
    """Bind every locally visible import name to its fully qualified target.

    ``import a.b as c`` binds ``c`` to ``a.b``; ``from a.b import c as d``
    binds ``d`` to ``a.b.c``. A plain ``import a.b`` needs no entry because an
    unaliased name already resolves to itself. Resolving through this map is
    what stops an alias from hiding a module reference.
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _dotted_path(node: ast.AST, aliases: dict[str, str]) -> str | None:
    """Resolve a name or attribute chain to a dotted path, or ``None``."""
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        owner = _dotted_path(node.value, aliases)
        return None if owner is None else f"{owner}.{node.attr}"
    return None


def _terminal_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _attribute_chain_references(
    node: ast.Attribute, installed: frozenset[str], aliases: dict[str, str]
) -> frozenset[str]:
    """Treat ``drift.a.b`` attribute traversal as a reference to ``drift.a.b``.

    ``import drift`` followed by ``drift.markets.normalization`` reaches a
    module without ever naming it in an import statement, so the chain itself
    has to count as a semantic reference.
    """
    path = _dotted_path(node, aliases)
    if path is None or not path.startswith("drift."):
        return frozenset()
    return _ancestor_modules(path, installed)


def _reject_module_registry_subscript(
    node: ast.Subscript, module: str, aliases: dict[str, str]
) -> None:
    """Fail closed on ``sys.modules[...]`` and on any module ``__dict__[...]``."""
    container = _dotted_path(node.value, aliases)
    if container is None:
        return
    if container in _MODULE_REGISTRY_PATHS or container.split(".")[-1] == "__dict__":
        raise SemanticClosureError(
            f"declared semantic module {module} indexes a module registry, "
            "which the closure guard cannot bind to an exact module"
        )


def _call_references(
    node: ast.Call, module: str, installed: frozenset[str], aliases: dict[str, str]
) -> frozenset[str]:
    """Resolve or reject every call that can reach a module at run time."""
    resolved = _dotted_path(node.func, aliases)
    terminal = _terminal_name(node.func)
    if resolved in _CODE_EVALUATION_TARGETS or (
        resolved is None and terminal in _CODE_EVALUATION_TARGETS
    ):
        raise SemanticClosureError(
            f"declared semantic module {module} evaluates code dynamically, "
            "which the closure guard cannot bind to an exact module"
        )
    if resolved in _NAMESPACE_LOOKUP_TARGETS:
        _reject_import_machinery_lookup(node, module, installed, aliases)
        return frozenset()
    effective = resolved if resolved is not None else terminal
    if effective is None or effective.split(".")[-1] not in _DYNAMIC_IMPORT_NAMES:
        return frozenset()
    return _dynamic_import_references(node, module, installed)


def _reject_import_machinery_lookup(
    node: ast.Call, module: str, installed: frozenset[str], aliases: dict[str, str]
) -> None:
    """Fail closed on ``getattr``/``vars`` aimed at an importable namespace.

    ``getattr(item, name)`` over an ordinary object stays allowed: only a
    lookup whose owner resolves to the import machinery or to an installed
    ``drift`` module, or whose attribute literally names a dynamic import,
    can produce a module the guard cannot otherwise see.
    """
    owner = _dotted_path(node.args[0], aliases) if node.args else None
    attribute = node.args[1] if len(node.args) > 1 else None
    names_dynamic_import = (
        isinstance(attribute, ast.Constant)
        and isinstance(attribute.value, str)
        and attribute.value in _DYNAMIC_IMPORT_NAMES
    )
    owns_import_machinery = owner is not None and (
        owner.split(".")[0] in _IMPORT_MACHINERY_ROOTS
        or bool(_ancestor_modules(owner, installed))
    )
    if names_dynamic_import or owns_import_machinery:
        raise SemanticClosureError(
            f"declared semantic module {module} reaches a module namespace "
            "indirectly, which the closure guard cannot bind to an exact module"
        )


def _import_from_references(
    node: ast.ImportFrom, module: str, installed: frozenset[str]
) -> frozenset[str]:
    if node.level:
        raise SemanticClosureError(
            f"declared semantic module {module} uses a relative import, which "
            "the closure guard cannot bind to an exact installed module"
        )
    base = node.module or ""
    found = set(_ancestor_modules(base, installed))
    for alias in node.names:
        found |= _ancestor_modules(f"{base}.{alias.name}", installed)
    return frozenset(found)


def _dynamic_import_references(
    node: ast.Call, module: str, installed: frozenset[str]
) -> frozenset[str]:
    target = node.args[0] if node.args else None
    if not isinstance(target, ast.Constant) or not isinstance(target.value, str):
        raise SemanticClosureError(
            f"declared semantic module {module} performs a non-literal dynamic "
            "import, which the closure guard cannot bind to an exact module"
        )
    base = target.value
    found = set(_ancestor_modules(base, installed))
    for keyword in node.keywords:
        if keyword.arg != "fromlist" or not isinstance(
            keyword.value, ast.List | ast.Tuple
        ):
            continue
        for element in keyword.value.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                found |= _ancestor_modules(f"{base}.{element.value}", installed)
    return frozenset(found)
