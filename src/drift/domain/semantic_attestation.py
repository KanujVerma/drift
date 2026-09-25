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

The boundary is exactly this: a static import allowlist, backed by a byte
freeze over every declared module and an import-time trace, with the residual
named below.

The allowlist is the primary gate (issue #107, extended after the #106 review).
A denylist of import spellings cannot be complete, because dozens of standard
modules import a module from a string (``pydoc``, ``logging.config``,
``unittest``, ``pickle``, ``marshal``, ``ctypes``, ``timeit``, ``code``,
``gc``, ``warnings``, ``runpy``, ``zipimport``, ``pkgutil`` and more), so the
guard instead names what a declared module may import (``_ALLOWED_IMPORT_MODULES``,
``_ALLOWED_IMPORT_NAMES``) and refuses every other ``import``. Relative imports,
star imports and a ``fromlist`` of ``"*"`` fail closed. A name that imports a
module from a string, or evaluates a string as code, fails closed even from an
allowlisted module (``_STRING_IMPORT_NAMES``, pydantic ``ImportString``;
``_STRING_EVALUATION_NAMES``, the ``typing`` forward reference evaluators).
``typing`` is name-granular as well, so only the eleven inert names the closures
use are bindable. Out-of-process execution is refused the same way:
``subprocess`` is not allowlisted, and ``os`` is name-granular, so
``os.system``, ``os.exec*``, ``os.spawn*``, ``os.popen`` and ``os.fork`` fail
closed as imports, as attributes and as literal ``getattr`` names.

Once only the allowlist is importable, the guarded namespaces still reachable
are the few members of ``os``, ``sys``, ``typing`` and ``importlib`` and the
ambient builtins, so those are bound name by name:

* a loader (``import_module``, ``__import__``) only as the callee of a call
  whose target is one literal absolute ``drift`` name, plus at most a literal
  ``__import__`` ``fromlist``, never as a value, so an alias or a
  ``functools.partial`` over it fails closed; the reach builtins (``eval``,
  ``exec``, ``compile``, ``getattr``, ``vars``, ``globals``, ``locals``)
  likewise;
* of ``builtins``, ``importlib``, ``os``, ``sys`` and ``typing`` only the
  members in ``_BINDABLE_MACHINERY_PATHS``, so ``importlib.util``,
  ``importlib.machinery``, metadata entry points, ``sys.modules``, the ``os``
  process launchers and every ``typing`` member outside ``_TYPING_MEMBERS`` fail
  closed;
* a guarded namespace (``os``, ``sys``, ``importlib``, ``builtins``,
  ``pydantic``, ``typing``) only under its own imported name: from-importing it
  from another module, ``drift`` or not (``from os import sys``, ``from
  drift.domain.core import importlib``), or reading it as an attribute of any
  object (``pathlib.os``), fails closed;
* only the dunder names in ``_BINDABLE_DUNDER_ATTRIBUTES`` and
  ``_BINDABLE_DUNDER_NAMES``, from any base, so ``__builtins__``, ``__spec__``,
  ``__loader__``, ``__dict__``, ``__globals__``, ``__class__`` and object-graph
  reflection fail closed;
* no ``getattr`` with a computed attribute, and no ``vars``, over an imported,
  rebound or dynamically loaded module, and no whole-namespace read;
* binding a module object or the ``drift`` package to another name fails
  closed, so a rebound alias cannot launder a later traversal or lookup.

Residual, exactly: pydantic evaluates string annotations internally when it
builds a model, so a forward reference string in a model annotation is code the
guard does not read (no closure module has one today); and a computed
``getattr`` over a function parameter or an ordinary local is allowed, because
the guard cannot type the value, so a module object that another module passes
in as an argument is not seen. Two things back the guard up there: the byte
freeze over every declared module, whose links are reviewed, and the
import-trace test, which runs each closure's seeds in a fresh interpreter and
checks that no undeclared ``drift`` module is loaded at import time.

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

_CODE_EVALUATION_TARGETS = frozenset({"compile", "eval", "exec"})
"""Ambient builtins that can import anything from a string the guard cannot read.

They need no import, so they are named bare. ``import builtins`` is refused by
the allowlist, so ``builtins.eval`` and the like are unreachable and need no
entry here."""

_NAMESPACE_LOOKUP_TARGETS = frozenset({"getattr", "globals", "locals", "vars"})
"""Ambient builtins that can pull an arbitrary attribute out of a namespace.

As above, only the bare names are reachable; ``builtins`` cannot be imported."""

_WHOLE_NAMESPACE_READS = frozenset({"globals", "locals"})
"""Namespace lookups that hand out every name a module or frame binds."""

_ALLOWED_IMPORT_MODULES = frozenset(
    {
        "__future__",
        "ast",
        "collections",
        "collections.abc",
        "copy",
        "dataclasses",
        "datetime",
        "decimal",
        "enum",
        "fractions",
        "functools",
        "hashlib",
        "importlib.metadata",
        "io",
        "json",
        "math",
        "os",
        "pathlib",
        "pydantic",
        "re",
        "stat",
        "sys",
        "types",
        "typing",
        "urllib.parse",
        "uuid",
        "zoneinfo",
    }
)
"""Every non-``drift`` module a declared closure module may import.

Derived from what the M1d validation and evidence closures actually import (the
27 distinct non-``drift`` targets). A ``from X import Y`` base or a plain
``import X`` target whose root is not ``drift`` must be one of these, or a
name-granular surface below. Everything else fails closed by construction: a
denylist can never enumerate every module that can import (``pydoc``,
``logging.config``, ``unittest``, ``pickle``, ``marshal``, ``ctypes``,
``timeit``, ``code``, ``gc``, ``warnings``, ``runpy``, ``zipimport``,
``pkgutil``, ``_frozen_importlib``, ``_imp`` and more), so the guard names what
is allowed instead. A new declared import needs an entry here, justified."""

_OS_MEMBERS = frozenset(
    {
        "O_DIRECTORY",
        "O_NOFOLLOW",
        "O_NONBLOCK",
        "O_RDONLY",
        "close",
        "fdopen",
        "fstat",
        "open",
        "scandir",
    }
)
"""The ``os`` members the closures actually use: descriptor-level reads.

Everything else in ``os`` fails closed, notably process execution (``system``,
``exec*``, ``spawn*``, ``popen``, ``fork``, ``posix_spawn``), which can start an
interpreter that imports anything, and ``os.sys``."""

_TYPING_MEMBERS = frozenset(
    {
        "Annotated",
        "Any",
        "Generic",
        "Literal",
        "Never",
        "Protocol",
        "Self",
        "TYPE_CHECKING",
        "TypeVar",
        "TypedDict",
        "cast",
    }
)
"""The ``typing`` names the closures actually use, all of them inert.

Each is a static typing construct that never evaluates a string: ``Annotated``,
``Any``, ``Literal``, ``Never`` and ``Self`` are special forms; ``Generic``,
``Protocol`` and ``TypedDict`` are class bases; ``TypeVar`` makes a type
variable; ``TYPE_CHECKING`` is the constant ``False`` at run time; ``cast``
returns its value unchanged. Everything else in ``typing`` fails closed, so a
new string evaluator cannot slip in under an unlisted name."""

_ALLOWED_IMPORT_NAMES: dict[str, frozenset[str]] = {
    "importlib.metadata": frozenset({"version"}),
    "os": _OS_MEMBERS,
    "sys": frozenset({"implementation", "version_info"}),
    "typing": _TYPING_MEMBERS,
}
"""From-import surfaces allowed only at name granularity.

``importlib.metadata``, ``os``, ``sys`` and ``typing`` can reach the import
machinery, start a process or evaluate a string, so a plain ``import`` of them
is allowed (their member use is then policed by the reference rules, member by
member), but a ``from`` import may bind only these members, never a loader, a
registry, a namespace, a process launcher or a string evaluator."""

_STRING_IMPORT_NAMES: dict[str, frozenset[str]] = {
    "pydantic": frozenset({"ImportString"}),
}
"""Names an allowlisted module exposes that import a module from a string at run
time, refused even though the module itself is allowlisted. pydantic's only
string-import public name is ``ImportString``; ``PydanticImportError`` is an
exception, not a loader."""

_STRING_IMPORT_PATHS = frozenset(
    f"{owner}.{name}" for owner, names in _STRING_IMPORT_NAMES.items() for name in names
)
"""The dotted paths of the string-import names, refused as an attribute too."""

_STRING_EVALUATION_NAMES: dict[str, frozenset[str]] = {
    "typing": frozenset(
        {
            "ForwardRef",
            "_LazyAnnotationLib",
            "_eval_type",
            "_lazy_annotationlib",
            "_make_forward_ref",
            "_type_check",
            "_type_convert",
            "evaluate_forward_ref",
            "get_type_hints",
        }
    ),
}
"""Names an allowlisted module exposes that evaluate a string as code.

``typing`` evaluates a forward reference string with ``eval``, which can import
anything. Its public evaluators (``ForwardRef``, ``get_type_hints``,
``evaluate_forward_ref``), its private evaluator ``_eval_type``, the factories
that turn a string into an evaluable ``ForwardRef`` (``_type_check``,
``_type_convert``, ``_make_forward_ref``) and its gateway to ``annotationlib``
fail closed. The closures use none of them. ``typing`` is also name-granular
(``_TYPING_MEMBERS``), so these names are refused twice over, and the refusal
here holds even if the name-granular rule is widened."""

_STRING_EVALUATION_PATHS = frozenset(
    f"{owner}.{name}"
    for owner, names in _STRING_EVALUATION_NAMES.items()
    for name in names
)
"""The dotted paths of the string-evaluation names, refused as an attribute too."""

_IMPORT_MACHINERY_ROOTS = frozenset({"builtins", "importlib", "os", "sys", "typing"})
"""Guarded roots whose members are bound one by one.

``import`` of the wider machinery (``pkgutil``, ``runpy``, ``zipimport`` and the
rest) and of ``subprocess`` is already refused by the allowlist, so only the
roots that a declared module legitimately imports (``os``, ``sys``, ``typing``),
that a bound member can re-expose (``importlib`` through ``importlib.metadata``),
or that are ambient (``builtins``) can still be reached, and their non-bindable
members fail closed. ``os`` is guarded because it launches processes and exposes
``os.sys``; ``typing`` because several of its members evaluate strings."""

_REIMPORT_GUARDED_NAMES = (
    _IMPORT_MACHINERY_ROOTS
    | frozenset(_STRING_IMPORT_NAMES)
    | frozenset(_STRING_EVALUATION_NAMES)
)
"""Namespaces that may be reached only under their own imported name.

Once ``os``, ``sys``, ``importlib``, ``builtins``, ``pydantic`` or ``typing`` is
bound under another object's name (``from os import sys``, ``from
drift.domain.core import typing``, ``pathlib.os``), the member rules above would
judge the path by that object instead. So from-importing one of these names from
any module, or reading it as an attribute of any object, fails closed."""

_BINDABLE_MACHINERY_PATHS = frozenset(
    {
        "importlib.import_module",
        "importlib.metadata.PackageNotFoundError",
        "importlib.metadata.version",
        "sys.implementation",
        "sys.version_info",
        *(f"os.{member}" for member in _OS_MEMBERS),
        *(f"typing.{member}" for member in _TYPING_MEMBERS),
    }
)
"""The only members of the guarded roots a declared module may reach.

The literal loader call is resolved to its target; the metadata version lookup,
the interpreter identity and the descriptor-level ``os`` reads cannot load a
module. Everything else under those roots can find, load, execute or hand out a
module from a name the guard cannot read, or start a process that can, so it
fails closed: ``importlib.util``, ``importlib.machinery``,
``importlib.resources``, metadata entry points, ``sys.modules``, frame access,
``os.system`` and the other process launchers, and all of ``builtins``, whose
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
    imported_modules = _imported_module_names(tree, aliases, installed)
    callees = frozenset(
        id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)
    )
    owners = frozenset(
        id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    )
    lookup_owners = frozenset(
        id(node.args[0])
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and node.args
        and _dotted_path(node.func, aliases) in _NAMESPACE_LOOKUP_TARGETS
    )
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            _reject_disallowed_import(node, module)
            for alias in node.names:
                found |= _ancestor_modules(alias.name, installed)
        elif isinstance(node, ast.ImportFrom):
            found |= _import_from_references(node, module, installed)
        elif isinstance(node, ast.Assign | ast.AnnAssign | ast.NamedExpr):
            _reject_module_rebinding(node, module, aliases, installed, imported_modules)
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
                lookup_owner=id(node) in lookup_owners,
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


def _reject_disallowed_import(node: ast.Import, module: str) -> None:
    """Fail closed on ``import`` of a non-``drift`` module outside the allowlist.

    A ``drift`` import is a declared reference, resolved elsewhere. Any other
    plain import must name a module the allowlist permits, at its exact dotted
    name. Renaming is fine, because the reference rules resolve an alias back to
    its target; what a rename cannot do is smuggle in a module the allowlist
    does not already permit.
    """
    for alias in node.names:
        name = alias.name
        if name.split(".")[0] == "drift":
            continue
        if name not in _ALLOWED_IMPORT_MODULES and name not in _ALLOWED_IMPORT_NAMES:
            raise _closure_error(
                module,
                f"imports a module outside the closure import allowlist: {name}",
            )


def _imported_module_names(
    tree: ast.AST, aliases: dict[str, str], installed: frozenset[str]
) -> frozenset[str]:
    """Every local name that is bound to a module object by an import.

    ``import X``/``import X.Y``/``import X as Z`` always bind a module; a
    ``from P import M`` binds a module only when ``P.M`` is an installed
    ``drift`` module. This is narrower than ``_module_bound_names``, which also
    tracks non-module names such as ``version`` or ``BaseModel``.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(
                alias.asname or alias.name.split(".")[0] for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            for alias in node.names:
                if f"{node.module}.{alias.name}" in installed:
                    names.add(alias.asname or alias.name)
    return frozenset(names)


def _reject_module_rebinding(
    node: ast.Assign | ast.AnnAssign | ast.NamedExpr,
    module: str,
    aliases: dict[str, str],
    installed: frozenset[str],
    imported_modules: frozenset[str],
) -> None:
    """Fail closed on binding a module object or a loaded module to another name.

    ``_alias = os`` or ``_pkg = drift`` would let a later ``getattr`` or an
    attribute chain reach the machinery, or a ``drift`` submodule, under a name
    the traversal rules cannot follow. No declared module rebinds a module, so
    binding an imported module, an installed ``drift`` module, an import-machinery
    path, or the result of a loader call to a name fails closed.
    """
    value = node.value
    if value is None or not _is_module_valued(
        value, aliases, installed, imported_modules
    ):
        return
    targets: list[ast.expr] = (
        list(node.targets) if isinstance(node, ast.Assign) else [node.target]
    )
    if any(isinstance(target, ast.Name) for target in targets):
        raise _closure_error(module, "binds a module object to another name")


def _is_module_valued(
    value: ast.expr,
    aliases: dict[str, str],
    installed: frozenset[str],
    imported_modules: frozenset[str],
) -> bool:
    """Whether an expression evaluates to a module object the guard tracks."""
    if _is_loader_call(value, aliases):
        return True
    if isinstance(value, ast.Name) and value.id in imported_modules:
        return True
    if not isinstance(value, ast.Name | ast.Attribute):
        return False
    path = _dotted_path(value, aliases)
    if path is None:
        return False
    if path == "drift" or path in installed:
        return True
    return _is_machinery_path(path) and not _is_bindable_machinery_path(path)


def _reject_machinery_reference(
    node: ast.Name | ast.Attribute,
    module: str,
    aliases: dict[str, str],
    *,
    callee: bool,
    owner: bool,
    lookup_owner: bool,
) -> None:
    """Fail closed on a loaded name that reaches a guarded namespace.

    Every attribute is checked for a guarded namespace or an unbindable dunder,
    wherever it sits in a chain. The rest applies to the whole chain only, so
    ``importlib.util.find_spec`` is judged as that full path, and a loader or
    reach builtin is accepted only as the callee of a call, whose target the
    call guards resolve or refuse. The owner argument of a ``getattr`` or
    ``vars`` call is exempt from the guarded-path check alone, because the
    namespace lookup rule judges that owner together with its attribute (so
    ``getattr(os, "O_NOFOLLOW", 0)`` is bound, and ``getattr(os, name)`` is not).
    """
    if isinstance(node, ast.Attribute):
        if node.attr in _REIMPORT_GUARDED_NAMES:
            raise _closure_error(
                module,
                f"reaches a guarded namespace through another object: .{node.attr}",
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
    path = _dotted_path(node, aliases)
    if path in _STRING_IMPORT_PATHS:
        raise _closure_error(
            module, f"reaches a name that imports a module from a string: {path}"
        )
    if path in _STRING_EVALUATION_PATHS:
        raise _closure_error(
            module, f"reaches a name that evaluates a string as code: {path}"
        )
    if owner:
        return
    if not callee:
        if _loader_name(node, aliases) is not None:
            raise _closure_error(module, "uses a dynamic import loader as a value")
        if path in _CODE_EVALUATION_TARGETS | _NAMESPACE_LOOKUP_TARGETS or (
            path is None and _terminal_name(node) in _CODE_EVALUATION_TARGETS
        ):
            raise _closure_error(module, "uses a dynamic reach builtin as a value")
    if (
        path is not None
        and not lookup_owner
        and _is_machinery_path(path)
        and not _is_bindable_machinery_path(path)
    ):
        raise _closure_error(
            module,
            f"reaches a guarded namespace beyond what the closure guard binds: {path}",
        )


def _attribute_chain_references(
    node: ast.Attribute, installed: frozenset[str], aliases: dict[str, str]
) -> frozenset[str]:
    """Treat ``drift.a.b`` attribute traversal as a reference to ``drift.a.b``.

    ``import drift`` followed by ``drift.markets.normalization`` reaches a
    module without ever naming it in an import statement, so the chain itself
    has to count as a semantic reference. A chain over a loader call,
    ``__import__("drift").markets.extra``, is resolved the same way, with the
    loader's literal target as its base, so the traversal cannot escape the
    closure unseen.
    """
    path = _dotted_path(node, aliases)
    if path is None:
        path = _loader_rooted_path(node, aliases)
    if path is None or not path.startswith("drift."):
        return frozenset()
    return _ancestor_modules(path, installed)


def _loader_rooted_path(node: ast.Attribute, aliases: dict[str, str]) -> str | None:
    """Resolve an attribute chain rooted at a loader call to a dotted path.

    ``__import__("drift").markets.extra`` has the loader call as its root; the
    call's one literal target is the base and the attribute suffix extends it.
    """
    attrs: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        attrs.append(current.attr)
        current = current.value
    if not _is_loader_call(current, aliases):
        return None
    target = current.args[0] if isinstance(current, ast.Call) and current.args else None
    if not isinstance(target, ast.Constant) or not isinstance(target.value, str):
        return None
    return ".".join((target.value, *reversed(attrs)))


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

    ``getattr(item, name)`` over an ordinary object stays allowed, and so does a
    literal ``getattr`` of a bindable member of a guarded root, such as
    ``getattr(os, "O_NOFOLLOW", 0)``, which is the attribute ``os.O_NOFOLLOW``. A
    lookup fails closed when it reads a whole namespace (``globals``,
    ``locals``, ``vars()``); when its owner resolves to any other member of a
    guarded root or to an installed ``drift`` module; when its literal attribute
    names a loader, a guarded namespace, an unbindable dunder or a string-import
    or string-evaluation name; or when its attribute is computed, or it is
    ``vars``, over an imported or dynamically loaded name.
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
        or literal in _REIMPORT_GUARDED_NAMES
        or (_is_dunder(literal) and literal not in _BINDABLE_DUNDER_ATTRIBUTES)
        or (
            owner is not None
            and f"{owner}.{literal}" in _STRING_IMPORT_PATHS | _STRING_EVALUATION_PATHS
        )
    )
    binds_a_member = (
        owner is not None
        and literal is not None
        and _is_bindable_machinery_path(f"{owner}.{literal}")
    )
    owns_import_machinery = owner is not None and (
        (_is_machinery_path(owner) and not binds_a_member)
        or bool(_ancestor_modules(owner, installed))
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
    for alias in node.names:
        _reject_unbindable_imported_name(base, alias, module)
    if base.split(".")[0] != "drift":
        _reject_disallowed_from_import(base, node.names, module)
    found = set(_ancestor_modules(base, installed))
    for alias in node.names:
        found |= _ancestor_modules(f"{base}.{alias.name}", installed)
    return frozenset(found)


def _reject_unbindable_imported_name(base: str, alias: ast.alias, module: str) -> None:
    """Fail closed on a from-imported name no base, ``drift`` or not, may bind.

    A star binds names the guard cannot read. A guarded namespace name (``sys``,
    ``os``, ``importlib``, ``builtins``, ``pydantic``, ``typing``) bound from
    another module (``from os import sys``, ``from drift.domain.core import
    importlib``) would hide that root behind the other module's path, where the
    member rules no longer see it. An unbindable dunder (``__builtins__``) hands
    out interpreter internals, and every module has one. None of these depends
    on whether the base is allowlisted, so this runs for every base.
    """
    if alias.name == "*":
        raise _closure_error(module, f"performs a star import from {base}")
    if alias.name in _REIMPORT_GUARDED_NAMES:
        raise _closure_error(
            module,
            f"reaches a guarded namespace through another object: {base}.{alias.name}",
        )
    if _is_dunder(alias.name) and alias.name not in _BINDABLE_DUNDER_ATTRIBUTES:
        raise _closure_error(
            module,
            f"reaches interpreter internals through a dunder name: {base}.{alias.name}",
        )


def _reject_disallowed_from_import(
    base: str, names: Sequence[ast.alias], module: str
) -> None:
    """Fail closed on a ``from`` import outside the allowlist.

    A name that imports a module from a string (pydantic ``ImportString``) or
    evaluates a string as code (the ``typing`` forward reference evaluators) is
    refused first, whether or not its module is also name-granular. A
    name-granular surface (``sys``, ``os``, ``typing``, ``importlib.metadata``)
    then admits only its listed members, so a loader, a registry, a namespace,
    a process launcher or a string evaluator cannot be bound. A fully
    allowlisted module admits any other member. Any other base fails closed,
    which is what refuses ``pkgutil``, ``importlib.util``, ``builtins``,
    ``pydoc`` and every other importer.
    """
    denied = _STRING_IMPORT_NAMES.get(base, frozenset())
    evaluating = _STRING_EVALUATION_NAMES.get(base, frozenset())
    for alias in names:
        if alias.name in denied:
            raise _closure_error(
                module,
                "imports a name that imports a module from a string: "
                f"{base}.{alias.name}",
            )
        if alias.name in evaluating:
            raise _closure_error(
                module,
                f"imports a name that evaluates a string as code: {base}.{alias.name}",
            )
    allowed_names = _ALLOWED_IMPORT_NAMES.get(base)
    if allowed_names is not None:
        for alias in names:
            if alias.name not in allowed_names:
                raise _closure_error(
                    module,
                    "imports a name outside the closure import allowlist: "
                    f"{base}.{alias.name}",
                )
        return
    if base not in _ALLOWED_IMPORT_MODULES:
        raise _closure_error(
            module, f"imports a module outside the closure import allowlist: {base}"
        )


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
    for keyword in node.keywords:
        if keyword.arg == "fromlist" and isinstance(
            keyword.value, ast.List | ast.Tuple
        ):
            for element in keyword.value.elts:
                if isinstance(element, ast.Constant) and element.value == "*":
                    raise _closure_error(
                        module, f"performs a star dynamic import from {base}"
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
