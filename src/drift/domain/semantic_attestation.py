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
dynamic imports of an absolute ``drift`` name, and attribute traversal from the
package root, and fails loudly when a reference escapes the declaration.

A way to reach a module that cannot be bound to an exact name statically fails
closed instead of being ignored (issue #107 extended this after the #106
review). The guard recognizes the import machinery by name, so every name that
denotes it may appear only in a shape the guard can bind:

* a loader (``import_module``, ``__import__``) only as the callee of a call
  whose target is one literal absolute ``drift`` name, plus at most a literal
  ``__import__`` ``fromlist``, never as a value, so an alias or a
  ``functools.partial`` over it fails closed; the reach builtins (``eval``,
  ``exec``, ``compile``, ``getattr``, ``vars``, ``globals``, ``locals``)
  likewise;
* of ``builtins``, ``importlib``, ``pkgutil``, ``runpy``, ``sys`` and
  ``zipimport`` only the members in ``_BINDABLE_MACHINERY_PATHS``, so
  ``importlib.util``, ``importlib.machinery``, metadata entry points,
  ``pkgutil.resolve_name``, ``runpy`` and ``sys.modules`` fail closed, and none
  of them may be imported under another name, passed as a value or read as an
  attribute of another object;
* only the dunder names in ``_BINDABLE_DUNDER_ATTRIBUTES`` and
  ``_BINDABLE_DUNDER_NAMES``, so ``__builtins__``, ``__spec__``,
  ``__loader__``, ``__dict__`` and object-graph reflection fail closed;
* no ``getattr`` with a computed attribute, and no ``vars``, over an imported
  or dynamically loaded name, and no whole-namespace read.

What a static reading cannot bind stays outside this guard: a module object
that reaches a computed ``getattr`` as an ordinary argument, reflection helpers
over such a value (``operator.attrgetter``, ``inspect``, frame introspection),
and annotation strings that ``typing`` or pydantic evaluate. Two things back
the guard up there: the byte freeze over every declared module, whose links
are reviewed, and the import-trace test, which runs each closure's seeds and
checks that no undeclared ``drift`` module is loaded.

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
"""Loader names. Only a direct call with a literal target can be bound."""

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
    {
        "builtins.getattr",
        "builtins.globals",
        "builtins.locals",
        "builtins.vars",
        "getattr",
        "globals",
        "locals",
        "vars",
    }
)
"""Call targets that can pull an arbitrary attribute out of a namespace."""

_WHOLE_NAMESPACE_READS = frozenset({"globals", "locals"})
"""Namespace lookups that hand out every name a module or frame binds."""

_IMPORT_MACHINERY_ROOTS = frozenset(
    {"builtins", "importlib", "pkgutil", "runpy", "sys", "zipimport"}
)
"""Non-``drift`` roots whose namespaces expose the import machinery itself."""

_BINDABLE_MACHINERY_PATHS = frozenset(
    {
        "importlib.import_module",
        "importlib.metadata.PackageNotFoundError",
        "importlib.metadata.version",
        "sys.implementation",
        "sys.version_info",
    }
)
"""The only members of the import machinery roots a declared module may reach.

The literal loader call is resolved to its target; the metadata version lookup
and the interpreter identity cannot load a module. Everything else under those
roots can find, load, execute or hand out a module from a name the guard cannot
read, so it fails closed: ``importlib.util``, ``importlib.machinery``,
``importlib.resources``, metadata entry points, ``pkgutil``, ``runpy``,
``zipimport``, ``sys.modules``, frame access and all of ``builtins``, whose
reach functions are ambient anyway."""

_BINDABLE_DUNDER_ATTRIBUTES = frozenset(
    {"__import__", "__init__", "__name__", "__setattr__"}
)
"""Dunder attributes that expose no namespace, loader or object graph.

``__import__`` is listed so that the loader rules, not this one, decide it."""

_BINDABLE_DUNDER_NAMES = frozenset({"__file__", "__import__", "__name__"})
"""Dunder names a declared module may read. ``__builtins__``, ``__spec__`` and
``__loader__`` are the import machinery of the module itself."""

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
    module_bound = _module_bound_names(tree, aliases)
    callees = frozenset(
        id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)
    )
    owners = frozenset(
        id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    )
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            _reject_machinery_import(node, module)
            for alias in node.names:
                found |= _ancestor_modules(alias.name, installed)
        elif isinstance(node, ast.ImportFrom):
            found |= _import_from_references(node, module, installed)
        elif isinstance(node, ast.Call):
            found |= _call_references(node, module, installed, aliases, module_bound)
        elif isinstance(node, ast.Subscript):
            _reject_module_registry_subscript(node, module, aliases)
        elif isinstance(node, ast.Attribute):
            found |= _attribute_chain_references(node, installed, aliases)
        if isinstance(node, ast.Name | ast.Attribute) and isinstance(
            node.ctx, ast.Load
        ):
            _reject_machinery_reference(
                node,
                module,
                aliases,
                callee=id(node) in callees,
                owner=id(node) in owners,
            )
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


def _root_name(node: ast.AST) -> str | None:
    """Return the name an attribute chain starts from, or ``None``."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _loader_name(node: ast.AST, aliases: dict[str, str]) -> str | None:
    """Return the loader a name or attribute denotes, through any alias."""
    path = _dotted_path(node, aliases)
    leaf = path.split(".")[-1] if path is not None else _terminal_name(node)
    return leaf if leaf in _DYNAMIC_IMPORT_NAMES else None


def _is_loader_call(node: ast.AST | None, aliases: dict[str, str]) -> bool:
    return isinstance(node, ast.Call) and _loader_name(node.func, aliases) is not None


def _is_dunder(name: str) -> bool:
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def _is_machinery_path(path: str) -> bool:
    return path.split(".")[0] in _IMPORT_MACHINERY_ROOTS


def _is_bindable_machinery_path(path: str) -> bool:
    """Whether a machinery path is a bindable member or lies inside one."""
    return any(
        path == member or path.startswith(f"{member}.")
        for member in _BINDABLE_MACHINERY_PATHS
    )


def _module_bound_names(tree: ast.AST, aliases: dict[str, str]) -> frozenset[str]:
    """Every name bound to an imported object or to a dynamically loaded module.

    A computed ``getattr`` over one of these can reach anything the object
    holds, such as ``os.sys`` or the imports of a loaded ``drift`` module, so
    the namespace lookup guard treats them as module namespaces.
    """
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bound.update(
                alias.asname or alias.name.split(".")[0] for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            bound.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Assign | ast.AnnAssign | ast.NamedExpr):
            if not _is_loader_call(node.value, aliases):
                continue
            targets: list[ast.expr] = (
                list(node.targets) if isinstance(node, ast.Assign) else [node.target]
            )
            bound.update(item.id for item in targets if isinstance(item, ast.Name))
    return frozenset(bound)


def _closure_error(module: str, reach: str) -> SemanticClosureError:
    return SemanticClosureError(
        f"declared semantic module {module} {reach}, which the closure guard "
        "cannot bind to an exact module"
    )


def _reject_machinery_import(node: ast.Import, module: str) -> None:
    """Fail closed on ``import`` of machinery the guard cannot bind.

    ``import importlib`` and ``import sys`` bind only their root name, whose
    later use is checked member by member. A rename would hide that name from
    the guard in any module that imports it, so it fails closed.
    """
    for alias in node.names:
        if not _is_machinery_path(alias.name):
            continue
        if alias.asname is not None:
            raise _closure_error(
                module,
                "binds the import machinery under another name: "
                f"{alias.name} as {alias.asname}",
            )
        if not any(
            member.startswith(f"{alias.name}.") for member in _BINDABLE_MACHINERY_PATHS
        ):
            raise _closure_error(
                module,
                "imports the import machinery beyond what the closure guard "
                f"binds: {alias.name}",
            )


def _reject_machinery_from_import(base: str, alias: ast.alias, module: str) -> None:
    """Fail closed on a ``from`` import that binds machinery under a plain name.

    Another declared module can import that plain name, and there the guard
    would no longer know it denotes a loader, a namespace or a registry.
    """
    target = f"{base}.{alias.name}"
    renamed = alias.asname is not None and alias.asname != alias.name
    if _is_machinery_path(base):
        if renamed:
            raise _closure_error(
                module,
                "binds the import machinery under another name: "
                f"{target} as {alias.asname}",
            )
        if target not in _BINDABLE_MACHINERY_PATHS:
            raise _closure_error(
                module,
                "imports the import machinery beyond what the closure guard "
                f"binds: {target}",
            )
        return
    if alias.name in _DYNAMIC_IMPORT_NAMES and renamed:
        raise _closure_error(
            module,
            "binds the import machinery under another name: "
            f"{target} as {alias.asname}",
        )
    if alias.name in _IMPORT_MACHINERY_ROOTS:
        raise _closure_error(
            module,
            f"reaches an import machinery namespace through another object: {target}",
        )
    if _is_dunder(alias.name) and alias.name not in _BINDABLE_DUNDER_ATTRIBUTES:
        raise _closure_error(
            module, f"reaches interpreter internals through a dunder name: {target}"
        )


def _reject_machinery_reference(
    node: ast.Name | ast.Attribute,
    module: str,
    aliases: dict[str, str],
    *,
    callee: bool,
    owner: bool,
) -> None:
    """Fail closed on a loaded name that reaches the import machinery.

    Every attribute is checked for a machinery namespace or an unbindable
    dunder, wherever it sits in a chain. The rest applies to the whole chain
    only, so ``importlib.util.find_spec`` is judged as that full path, and a
    loader or reach builtin is accepted only as the callee of a call, whose
    target the call guards resolve or refuse.
    """
    if isinstance(node, ast.Attribute):
        if node.attr in _IMPORT_MACHINERY_ROOTS:
            raise _closure_error(
                module,
                "reaches an import machinery namespace through another object: "
                f".{node.attr}",
            )
        if _is_dunder(node.attr) and node.attr not in _BINDABLE_DUNDER_ATTRIBUTES:
            raise _closure_error(
                module,
                f"reaches interpreter internals through a dunder name: .{node.attr}",
            )
    elif _is_dunder(node.id) and node.id not in _BINDABLE_DUNDER_NAMES:
        raise _closure_error(
            module, f"reaches interpreter internals through a dunder name: {node.id}"
        )
    if owner:
        return
    path = _dotted_path(node, aliases)
    if not callee:
        if _loader_name(node, aliases) is not None:
            raise _closure_error(module, "uses a dynamic import loader as a value")
        if path in _CODE_EVALUATION_TARGETS | _NAMESPACE_LOOKUP_TARGETS or (
            path is None and _terminal_name(node) in _CODE_EVALUATION_TARGETS
        ):
            raise _closure_error(module, "uses a dynamic reach builtin as a value")
    if (
        path is not None
        and _is_machinery_path(path)
        and not _is_bindable_machinery_path(path)
    ):
        raise _closure_error(
            module,
            f"reaches the import machinery beyond what the closure guard binds: {path}",
        )


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
    node: ast.Call,
    module: str,
    installed: frozenset[str],
    aliases: dict[str, str],
    module_bound: frozenset[str],
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
        _reject_import_machinery_lookup(
            node, module, installed, aliases, module_bound, resolved
        )
        return frozenset()
    loader = _loader_name(node.func, aliases)
    if loader is None:
        return frozenset()
    return _dynamic_import_references(node, loader, module, installed)


def _reject_import_machinery_lookup(
    node: ast.Call,
    module: str,
    installed: frozenset[str],
    aliases: dict[str, str],
    module_bound: frozenset[str],
    function: str,
) -> None:
    """Fail closed on ``getattr``/``vars`` aimed at an importable namespace.

    ``getattr(item, name)`` over an ordinary object stays allowed. A lookup
    fails closed when it reads a whole namespace (``globals``, ``locals``,
    ``vars()``); when its owner resolves to the import machinery or to an
    installed ``drift`` module; when its literal attribute names a loader, a
    machinery namespace or an unbindable dunder; or when its attribute is
    computed, or it is ``vars``, over an imported or dynamically loaded name.
    """
    owner_node = node.args[0] if node.args else None
    owner = _dotted_path(owner_node, aliases) if owner_node is not None else None
    attribute = node.args[1] if len(node.args) > 1 else None
    literal = (
        attribute.value
        if isinstance(attribute, ast.Constant) and isinstance(attribute.value, str)
        else None
    )
    reads_whole_namespace = (
        function.split(".")[-1] in _WHOLE_NAMESPACE_READS or owner_node is None
    )
    names_machinery = literal is not None and (
        literal in _DYNAMIC_IMPORT_NAMES
        or literal in _IMPORT_MACHINERY_ROOTS
        or (_is_dunder(literal) and literal not in _BINDABLE_DUNDER_ATTRIBUTES)
    )
    owns_import_machinery = owner is not None and (
        _is_machinery_path(owner) or bool(_ancestor_modules(owner, installed))
    )
    computed_over_module = (
        literal is None
        and owner_node is not None
        and _is_module_bound(owner_node, aliases, module_bound)
    )
    if (
        reads_whole_namespace
        or names_machinery
        or owns_import_machinery
        or computed_over_module
    ):
        raise SemanticClosureError(
            f"declared semantic module {module} reaches a module namespace "
            "indirectly, which the closure guard cannot bind to an exact module"
        )


def _is_module_bound(
    owner: ast.AST, aliases: dict[str, str], module_bound: frozenset[str]
) -> bool:
    """Whether a lookup owner is an imported or dynamically loaded object."""
    if isinstance(owner, ast.Call):
        return _is_loader_call(owner, aliases)
    root = _root_name(owner)
    return root is not None and root in module_bound


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
        _reject_machinery_from_import(base, alias, module)
        found |= _ancestor_modules(f"{base}.{alias.name}", installed)
    return frozenset(found)


def _dynamic_import_references(
    node: ast.Call, loader: str, module: str, installed: frozenset[str]
) -> frozenset[str]:
    """Resolve a loader call whose target is one literal absolute drift name.

    A relative target, a target outside ``drift`` (whose module object would
    then be an unguarded namespace, such as ``importlib.util``), or any
    argument besides a literal ``__import__`` ``fromlist`` of literal names
    could import a module the guard cannot name, so each fails closed.
    """
    target = node.args[0] if node.args else None
    if not isinstance(target, ast.Constant) or not isinstance(target.value, str):
        raise SemanticClosureError(
            f"declared semantic module {module} performs a non-literal dynamic "
            "import, which the closure guard cannot bind to an exact module"
        )
    base = target.value
    if base.startswith("."):
        raise _closure_error(module, f"performs a relative dynamic import: {base}")
    if base != "drift" and not base.startswith("drift."):
        raise _closure_error(
            module, f"dynamically imports a module outside the drift package: {base}"
        )
    if len(node.args) > 1 or any(
        keyword.arg != "fromlist"
        or loader != "__import__"
        or not _is_literal_name_list(keyword.value)
        for keyword in node.keywords
    ):
        raise SemanticClosureError(
            f"declared semantic module {module} passes dynamic import arguments "
            "the closure guard cannot bind to an exact module"
        )
    found = set(_ancestor_modules(base, installed))
    for keyword in node.keywords:
        if isinstance(keyword.value, ast.List | ast.Tuple):
            for element in keyword.value.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    found |= _ancestor_modules(f"{base}.{element.value}", installed)
    return frozenset(found)


def _is_literal_name_list(node: ast.AST) -> bool:
    return isinstance(node, ast.List | ast.Tuple) and all(
        isinstance(element, ast.Constant) and isinstance(element.value, str)
        for element in node.elts
    )
