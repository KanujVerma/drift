"""Task 1 boundary checks before any M1e production source exists."""

from __future__ import annotations

import ast
import importlib.util
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).parents[2]
PINNED_M1D_COMMIT = "af75cce0f763de025f8ae3516577a9d0a1acead9"
TASK1_M1D_PIN_COMMIT = "1c647bfc8b7c2a61a83cef4468a5a8cd17e9a060"
ALLOWED_M1E_PRODUCTION_PATHS = frozenset(
    {
        "src/drift/domain/qualification.py",
        "src/drift/qualification/__init__.py",
        "src/drift/qualification/lifecycle.py",
        "src/drift/domain/rights.py",
        "src/drift/qualification/rights.py",
        "src/drift/domain/acquisition.py",
        "src/drift/qualification/acquisition.py",
        "src/drift/qualification/store.py",
        "src/drift/domain/source_snapshots.py",
        "src/drift/qualification/snapshots.py",
        "src/drift/domain/qualification_adapters.py",
        "src/drift/domain/golden_cases.py",
        "src/drift/qualification/adapters.py",
        "src/drift/qualification/golden_cases.py",
        "src/drift/qualification/harness.py",
        "src/drift/domain/environment_closure.py",
        "src/drift/domain/qualification_replay.py",
        "src/drift/qualification/environment.py",
        "src/drift/qualification/replay.py",
        "src/drift/qualification/pilot_adapter.py",
        "scripts/intake_m1e_truth.py",
        "scripts/capture_m1e_environment.py",
        "scripts/replay_m1e_offline.py",
        "scripts/acquire_m1e_pilot.py",
        "scripts/qualify_m1e_pilot.py",
    }
)
# Replay-identity source added under issue #32.  It is additive M1d validation
# support rather than M1e qualification source, so it is named here instead of
# in the M1e allowlist.  It is deliberately not exempted from the inertness
# scan: it is routed through the same production AST guard below.
M1D_REPLAY_IDENTITY_PATHS = frozenset(
    {
        "src/drift/domain/semantic_attestation.py",
    }
)
# M1d source added under issue #71: the closed-world session coverage record and
# its derivation, both declared in the m1d-evidence-v1 closure (decision D5-a).
# Like the replay-identity path above they are named rather than exempted, and
# are routed through the same production AST guard below, so neither may import
# a transport module, spawn a process, or define a network or credential symbol.
M1D_CLOSED_WORLD_SOURCE_PATHS = frozenset(
    {
        "src/drift/domain/session_closed_world.py",
        "src/drift/markets/session_closed_world.py",
    }
)
# M2 source added under issue #34.  It is additive under ADR 0012 like the
# evaluator modules, but it does not carry the "evaluator" prefix that
# _m1e_candidate_paths filters on, so it has to be named.  As with the
# replay-identity path above it is named rather than exempted, and is routed
# through the same production AST guard below.
M2_ADDITIVE_SOURCE_PATHS = frozenset(
    {
        "src/drift/domain/replay_provenance.py",
    }
)
# M2 Task 8 source added under issue #9.  The bounded Alpaca exploratory bridge
# is a provider adapter under ADR 0012, not M1e qualification source, so it is
# named here rather than added to the M1e allowlist.  It is deliberately not
# exempted from the inertness scan: it is routed through the same production
# AST guard as every other named addition, so it still may not import a
# transport module, spawn a process, or define a network or credential symbol.
M2_ALPACA_BRIDGE_SOURCE_PATHS = frozenset(
    {
        "src/drift/adapters/__init__.py",
        "src/drift/adapters/alpaca_exploratory.py",
    }
)
# The Task 8 acquisition CLI is the one place in the repository authorized to
# open a transport connection and to read an API key from the environment.
# M1e Task 1 deferred exactly these two capabilities "to Task 8", so the
# deferral is lifted here and only here.  Every other M1e script keeps the
# original prohibition, enforced by _assert_m1e_script_allowed below.
M2_ALPACA_BRIDGE_SCRIPT_PATHS = frozenset(
    {
        "scripts/intake_alpaca_exploratory.py",
    }
)
M1E_PRODUCTION_PATHS = frozenset(
    path for path in ALLOWED_M1E_PRODUCTION_PATHS if path.startswith("src/drift/")
)
INERT_SOURCE_PATHS = (
    ALLOWED_M1E_PRODUCTION_PATHS
    | M1D_REPLAY_IDENTITY_PATHS
    | M1D_CLOSED_WORLD_SOURCE_PATHS
    | M2_ADDITIVE_SOURCE_PATHS
    | M2_ALPACA_BRIDGE_SOURCE_PATHS
    | M2_ALPACA_BRIDGE_SCRIPT_PATHS
)
M1E_SCRIPT_PATHS = frozenset(
    path for path in ALLOWED_M1E_PRODUCTION_PATHS if path.startswith("scripts/")
)
PROCESS_ORCHESTRATION_SCRIPT_PATHS = frozenset(
    {
        "scripts/capture_m1e_environment.py",
        "scripts/replay_m1e_offline.py",
        "scripts/qualify_m1e_pilot.py",
    }
)
NETWORK_IMPORT_ROOTS = frozenset(
    {
        "boto3",
        "ftplib",
        "http",
        "httpx",
        "requests",
        "socket",
        "urllib",
        "webbrowser",
    }
)
PROCESS_IMPORT_ROOTS = frozenset({"asyncio", "multiprocessing", "subprocess"})
FORBIDDEN_PRODUCTION_IMPORT_ROOTS = NETWORK_IMPORT_ROOTS | PROCESS_IMPORT_ROOTS
FORBIDDEN_PROCESS_CALLS = frozenset(
    {
        "asyncio.create_subprocess_exec",
        "asyncio.create_subprocess_shell",
        "os.fork",
        "os.forkpty",
        "os.popen",
        "os.posix_spawn",
        "os.posix_spawnp",
        "os.spawnl",
        "os.spawnle",
        "os.spawnlp",
        "os.spawnlpe",
        "os.spawnv",
        "os.spawnve",
        "os.spawnvp",
        "os.spawnvpe",
        "os.system",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.run",
    }
)
FORBIDDEN_DYNAMIC_CALLS = frozenset(
    {
        "__import__",
        "builtins.exec",
        "builtins.eval",
        "compile",
        "exec",
        "execfile",
        "eval",
        "run_path",
    }
)
NETWORK_OR_CREDENTIAL_DEFINITION_TERMS = frozenset({"credential", "network"})
FORBIDDEN_DEFINITION_TERMS = frozenset(
    {"agent", "backtest", "broker", "evaluator", "portfolio", "trading"}
)
CREDENTIAL_READ_CALLS = frozenset(
    {"keyring.get_password", "os.environ.get", "os.getenv"}
)


@dataclass(frozen=True)
class BridgeCapabilityAllowlist:
    """Everything one Alpaca bridge source file may reach, stated positively.

    A denylist of credential and network calls is only as good as the list of
    spellings it anticipates, and an independent review executed a dozen
    spellings the earlier guards missed. This states the opposite: the import
    roots a file may use, the attributes it may read off each module it binds
    by a plain ``import``, and the exact environment variables it may read.
    Anything else is refused, whether or not anyone has thought of it yet.
    """

    import_roots: frozenset[str]
    #: Attributes that may be read off each module bound by a plain import. A
    #: module bound but absent here may have no attribute read off it at all.
    module_attributes: Mapping[str, frozenset[str]]
    #: Environment variables readable as ``os.environ.get(<one argument>)``.
    environment_reads: frozenset[str]
    dunder_attributes: frozenset[str]
    #: Builtins this file may not reach at all, even though they are ordinary
    #: elsewhere. The builtin ``open`` reads any path, including the process
    #: environment file, so a bridge file that needs none must name none.
    refused_builtins: frozenset[str] = frozenset()


#: Builtins that resolve a module, an attribute, or code from a runtime value,
#: so that no static scan can see what they reach.
DYNAMIC_ACCESS_NAMES = frozenset(
    {
        "__builtins__",
        "__import__",
        "breakpoint",
        "compile",
        "delattr",
        "eval",
        "exec",
        "getattr",
        "globals",
        "locals",
        "setattr",
        "vars",
    }
)
#: Attribute names that read the process environment or reach a module
#: registry or loader, refused off any object that is not an allowlisted module.
CAPABILITY_ATTRIBUTE_NAMES = frozenset(
    {
        "builtins",
        "environ",
        "environb",
        "getenv",
        "getenvb",
        "import_module",
        "importlib",
        "modules",
        "os",
        "putenv",
        "sys",
        "unsetenv",
    }
)
#: Substrings that name a file exposing the process environment. Reading one
#: is an environment read by another route (``/proc/self/environ`` exists on
#: the Linux CI runner), so no bridge source may name one at all.
ENVIRONMENT_FILE_MARKERS = ("/proc/", "/environ")
#: Modules from which ``from X import name`` is held to X's attribute
#: allowlist, because each imported name is itself a capability.
NAME_IMPORT_ALLOWLISTED_MODULES = frozenset({"builtins", "importlib", "os", "sys"})

#: Derived from the adapter's own source: every import root it uses, the only
#: attributes it reads off the three modules it binds, and no environment read
#: at all. The adapter opens no connection and reads no credential.
ALPACA_ADAPTER_ALLOWLIST = BridgeCapabilityAllowlist(
    import_roots=frozenset(
        {
            "ast",
            "collections",
            "dataclasses",
            "datetime",
            "decimal",
            "drift",
            "hashlib",
            "json",
            "os",
            "pathlib",
            "typing",
            "uuid",
        }
    ),
    module_attributes={
        "ast": frozenset({"Import", "ImportFrom", "parse", "walk"}),
        "json": frozenset({"dumps", "loads"}),
        "os": frozenset(
            {
                "O_CREAT",
                "O_EXCL",
                "O_WRONLY",
                "chmod",
                "close",
                "fsync",
                "open",
                "write",
            }
        ),
    },
    environment_reads=frozenset(),
    dunder_attributes=frozenset(),
    refused_builtins=frozenset({"open"}),
)
#: Derived from the acquisition CLI's own source. It is the one file allowed a
#: transport and an environment read, and the read is scoped to exactly the two
#: Alpaca key variables through ``os.environ.get``: no other variable, no other
#: spelling, and no other ``os`` attribute at all.
ALPACA_SCRIPT_ALLOWLIST = BridgeCapabilityAllowlist(
    import_roots=frozenset(
        {
            "argparse",
            "collections",
            "dataclasses",
            "datetime",
            "drift",
            "hashlib",
            "http",
            "json",
            "os",
            "pathlib",
            "sys",
            "typing",
            "urllib",
            "uuid",
        }
    ),
    module_attributes={
        "argparse": frozenset({"ArgumentParser"}),
        "http": frozenset({"client"}),
        "json": frozenset({"loads"}),
        "os": frozenset(),
        "sys": frozenset({"path"}),
        "urllib": frozenset({"error", "parse", "request"}),
    },
    environment_reads=frozenset({"APCA_API_KEY_ID", "APCA_API_SECRET_KEY"}),
    dunder_attributes=frozenset({"__init__", "__name__"}),
    refused_builtins=frozenset({"open"}),
)


def _git_paths(ref: str, prefix: str) -> set[str]:
    completed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ref, "--", prefix],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return set(filter(None, completed.stdout.splitlines()))


def _git_is_ancestor(older: str, newer: str) -> bool:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", older, newer],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode in {0, 1}, completed.stdout + completed.stderr
    return completed.returncode == 0


def _m1e_paths_on_disk() -> set[str]:
    candidates: set[str] = set()
    for root in (REPO_ROOT / "src", REPO_ROOT / "scripts"):
        if root.exists():
            candidates.update(
                path.relative_to(REPO_ROOT).as_posix()
                for path in root.rglob("*.py")
                if path.is_file()
            )
    baseline = _git_paths(PINNED_M1D_COMMIT, "src/drift") | _git_paths(
        PINNED_M1D_COMMIT, "scripts"
    )
    # M2 evaluator paths are additive under ADR 0012 and separate from
    # M1e qualification.
    m1e_candidates = {
        path
        for path in candidates
        if not path.startswith("src/drift/evaluator/")
        and not path.startswith("src/drift/domain/evaluator_")
    }
    return m1e_candidates - baseline


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".", maxsplit=1)[0]] = item.name
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            for item in node.names:
                aliases[item.asname or item.name] = f"{node.module}.{item.name}"
    return aliases


def _call_path(node: ast.AST, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        owner = _call_path(node.value, aliases)
        return f"{owner}.{node.attr}" if owner is not None else node.attr
    return None


def _assert_definition_allowed(name: str, relative: str, *, script: bool) -> None:
    lowered = name.lower()
    assert not any(term in lowered for term in FORBIDDEN_DEFINITION_TERMS), (
        f"forbidden M1e capability definition: {name}"
    )
    if "process" in lowered:
        assert script and relative in PROCESS_ORCHESTRATION_SCRIPT_PATHS, (
            f"process definition outside planned orchestration script: {name}"
        )
    if any(term in lowered for term in NETWORK_OR_CREDENTIAL_DEFINITION_TERMS):
        raise AssertionError(
            f"network or credential definition is deferred to Task 8: {name}"
        )


def _assert_m1e_production_module_allowed(source: str, label: str) -> None:
    """Hold production source to every prohibition its name implies.

    Credential reads were deferred to Task 8 for the *script* only.  Production
    modules never had that deferral lifted, so the same two checks the script
    guard applies -- the ``CREDENTIAL_READ_CALLS`` call set and the
    ``os.environ`` subscript -- are applied here as well.  Without them an
    ``os.getenv("ALPACA_API_KEY")`` injected into a production module, the
    Alpaca bridge included, left the whole suite green.
    """
    tree = ast.parse(source, label)
    aliases = _import_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            modules = []
        for module in modules:
            assert (
                module.split(".", maxsplit=1)[0]
                not in FORBIDDEN_PRODUCTION_IMPORT_ROOTS
            )
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            _assert_definition_allowed(node.name, label, script=False)
        if isinstance(node, ast.Call):
            call_path = _call_path(node.func, aliases)
            assert call_path not in FORBIDDEN_PROCESS_CALLS, (
                f"forbidden M1e process call {call_path} in {label}"
            )
            assert call_path not in FORBIDDEN_DYNAMIC_CALLS, (
                f"forbidden M1e dynamic call {call_path} in {label}"
            )
            assert call_path not in CREDENTIAL_READ_CALLS, (
                f"credential read {call_path} in production module {label}"
            )
        if isinstance(node, ast.Subscript):
            access_path = _call_path(node.value, aliases)
            assert access_path != "os.environ", (
                f"credential read os.environ in production module {label}"
            )


def _string_assignments(tree: ast.AST) -> dict[str, set[str] | None]:
    """Map every rebound name to the string constants it is ever bound to.

    ``None`` means the name is bound somewhere to something that is not a
    string constant, or rebound as a parameter or loop target, so its value
    cannot be known statically and it names no permitted variable.
    """
    parents = {
        child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }
    bound: dict[str, set[str] | None] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.arg):
            bound[node.arg] = None
        if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)):
            continue
        parent = parents.get(node)
        value = getattr(parent, "value", None)
        values = bound.setdefault(node.id, set())
        if (
            isinstance(parent, (ast.Assign, ast.AnnAssign))
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and values is not None
        ):
            values.add(value.value)
        else:
            bound[node.id] = None
    return bound


def _permitted_environment_read(
    node: ast.Call,
    modules: Mapping[str, str],
    bound: Mapping[str, set[str] | None],
    permitted: frozenset[str],
) -> ast.Attribute | None:
    """Return the ``os.environ`` node of one permitted read, or ``None``.

    The only permitted form is ``os.environ.get(X)`` with exactly one argument,
    where ``X`` is a string literal naming a permitted variable or a name only
    ever bound to such literals.
    """
    function = node.func
    if not (
        isinstance(function, ast.Attribute)
        and function.attr == "get"
        and isinstance(function.value, ast.Attribute)
        and function.value.attr == "environ"
        and isinstance(function.value.value, ast.Name)
        and modules.get(function.value.value.id) == "os"
        and len(node.args) == 1
        and not node.keywords
    ):
        return None
    argument = node.args[0]
    if isinstance(argument, ast.Constant) and argument.value in permitted:
        return function.value
    if isinstance(argument, ast.Name):
        values = bound.get(argument.id)
        if values and values <= permitted:
            return function.value
    return None


def _bridge_capability_violations(
    source: str, label: str, allowlist: BridgeCapabilityAllowlist
) -> list[str]:
    """List every capability one bridge source reaches outside its allowlist."""
    tree = ast.parse(source, label)
    parents = {
        child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }
    modules: dict[str, str] = {}
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", maxsplit=1)[0]
                if root not in allowlist.import_roots:
                    violations.append(
                        f"{label} imports {alias.name}, which is outside its "
                        "import allowlist"
                    )
                modules[alias.asname or root] = alias.name if alias.asname else root
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                violations.append(
                    f"{label} uses a relative import, which its import allowlist "
                    "cannot resolve"
                )
            elif module.split(".", maxsplit=1)[0] not in allowlist.import_roots:
                violations.append(
                    f"{label} imports from {module}, which is outside its import "
                    "allowlist"
                )
            if module in NAME_IMPORT_ALLOWLISTED_MODULES:
                permitted = allowlist.module_attributes.get(module, frozenset())
                for alias in node.names:
                    if alias.name not in permitted:
                        violations.append(
                            f"{label} imports {module}.{alias.name}, which is "
                            f"outside the {module} allowlist"
                        )

    bound = _string_assignments(tree)
    exempt: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            environ = _permitted_environment_read(
                node, modules, bound, allowlist.environment_reads
            )
            if environ is not None:
                exempt.add(id(environ))

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if any(marker in node.value for marker in ENVIRONMENT_FILE_MARKERS):
                violations.append(
                    f"{label} names the process-environment file "
                    f"{node.value!r}, an environment read by another route"
                )
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id in allowlist.refused_builtins and node.id not in modules:
                violations.append(
                    f"{label} reaches the builtin {node.id}, which is outside "
                    "its allowlist"
                )
            if node.id in DYNAMIC_ACCESS_NAMES:
                violations.append(
                    f"{label} reaches {node.id}, a builtin that resolves modules, "
                    "attributes, or code from a runtime value"
                )
            parent = parents.get(node)
            if node.id in modules and not (
                isinstance(parent, ast.Attribute) and parent.value is node
            ):
                violations.append(
                    f"{label} references the module {modules[node.id]} other than "
                    "as the owner of an allowlisted attribute"
                )
        if not isinstance(node, ast.Attribute) or id(node) in exempt:
            continue
        owner = node.value
        if isinstance(owner, ast.Name) and owner.id in modules:
            module = modules[owner.id]
            if node.attr not in allowlist.module_attributes.get(module, frozenset()):
                violations.append(
                    f"{label} uses {module}.{node.attr}, which is outside the "
                    f"{module} allowlist"
                )
        elif node.attr in CAPABILITY_ATTRIBUTE_NAMES:
            violations.append(
                f"{label} reads .{node.attr}, an environment or module registry "
                "attribute, off an object that is not an allowlisted module"
            )
        if (
            node.attr.startswith("__")
            and node.attr.endswith("__")
            and node.attr not in allowlist.dunder_attributes
        ):
            violations.append(f"{label} reads the dunder attribute {node.attr}")
    return violations


def _assert_alpaca_bridge_module_allowed(source: str, label: str) -> None:
    """Hold the Alpaca adapter to its allowlist, then to the production guard."""
    violations = _bridge_capability_violations(source, label, ALPACA_ADAPTER_ALLOWLIST)
    assert not violations, "alpaca bridge allowlist: " + "; ".join(violations)
    _assert_m1e_production_module_allowed(source, label)


def _assert_m2_bridge_script_allowed(relative: str, source: str) -> None:
    """Allow the Task 8 acquisition CLI its transport and its API key reads.

    Everything M1e Task 1 forbade for a different reason stays forbidden here:
    no process execution, no dynamic execution, and no definition named after a
    network or credential capability. Only the two capabilities M1e explicitly
    deferred "to Task 8" are permitted, and only for this one script.
    """
    assert relative in M2_ALPACA_BRIDGE_SCRIPT_PATHS, (
        f"unexpected M2 bridge script: {relative}"
    )
    tree = ast.parse(source, relative)
    aliases = _import_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            modules = []
        for module in modules:
            root = module.split(".", maxsplit=1)[0]
            assert root not in PROCESS_IMPORT_ROOTS, (
                f"process import in the M2 bridge script: {module}"
            )
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            _assert_definition_allowed(node.name, relative, script=True)
        if isinstance(node, ast.Call):
            call_path = _call_path(node.func, aliases)
            assert call_path not in FORBIDDEN_PROCESS_CALLS, (
                f"forbidden process call in the M2 bridge script: {call_path}"
            )
            assert call_path not in FORBIDDEN_DYNAMIC_CALLS, (
                f"forbidden dynamic call in the M2 bridge script: {call_path}"
            )
    # The transport and the key reads are lifted for this script, and only as
    # far as its allowlist states: two named variables through one spelling.
    violations = _bridge_capability_violations(
        source, relative, ALPACA_SCRIPT_ALLOWLIST
    )
    assert not violations, "alpaca bridge allowlist: " + "; ".join(violations)


def _assert_m1e_script_allowed(relative: str, source: str) -> None:
    assert relative in M1E_SCRIPT_PATHS, f"unexpected M1e script: {relative}"
    tree = ast.parse(source, relative)
    aliases = _import_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            modules = []
        for module in modules:
            root = module.split(".", maxsplit=1)[0]
            if root in NETWORK_IMPORT_ROOTS:
                raise AssertionError(f"network import is deferred to Task 8: {module}")
            if root in PROCESS_IMPORT_ROOTS:
                assert relative in PROCESS_ORCHESTRATION_SCRIPT_PATHS, (
                    f"process import outside planned orchestration script: {module}"
                )
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            _assert_definition_allowed(node.name, relative, script=True)
        if isinstance(node, ast.Call):
            call_path = _call_path(node.func, aliases)
            assert call_path not in FORBIDDEN_DYNAMIC_CALLS, (
                f"forbidden M1e dynamic call {call_path} in {relative}"
            )
            if call_path in FORBIDDEN_PROCESS_CALLS:
                assert relative in PROCESS_ORCHESTRATION_SCRIPT_PATHS, (
                    f"process call outside planned orchestration script: {call_path}"
                )
            if call_path in CREDENTIAL_READ_CALLS:
                raise AssertionError(
                    f"credential read is deferred to Task 8: {call_path}"
                )
        if isinstance(node, ast.Subscript):
            access_path = _call_path(node.value, aliases)
            if access_path == "os.environ":
                raise AssertionError(
                    "credential read is deferred to Task 8: os.environ"
                )


def _load_pinned_helper() -> ModuleType:
    helper_path = REPO_ROOT / "tests/_pinned_m1d.py"
    spec = importlib.util.spec_from_file_location("_m1e_pinned_m1d", helper_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_task1_pin_commit_precedes_live_m1e_source_additions() -> None:
    """M1e paths can be added later only after the historical M1d pin exists."""
    assert _git_is_ancestor(PINNED_M1D_COMMIT, TASK1_M1D_PIN_COMMIT)
    assert _git_is_ancestor(TASK1_M1D_PIN_COMMIT, "HEAD")
    pinned_paths = _git_paths(TASK1_M1D_PIN_COMMIT, "src/drift") | _git_paths(
        TASK1_M1D_PIN_COMMIT, "scripts"
    )
    assert not pinned_paths.intersection(ALLOWED_M1E_PRODUCTION_PATHS)


def test_m1e_additions_are_allowlisted_inert_and_leave_m1d_pins_unchanged() -> None:
    """Future M1e code is constrained separately from byte-pinned M1d history."""
    present = _m1e_paths_on_disk()
    assert present <= INERT_SOURCE_PATHS
    scanned_as_production = (
        M1E_PRODUCTION_PATHS
        | M1D_REPLAY_IDENTITY_PATHS
        | M1D_CLOSED_WORLD_SOURCE_PATHS
        | M2_ADDITIVE_SOURCE_PATHS
        | M2_ALPACA_BRIDGE_SOURCE_PATHS
    )
    assert present & scanned_as_production
    for relative in present:
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        if relative in M2_ALPACA_BRIDGE_SOURCE_PATHS:
            _assert_alpaca_bridge_module_allowed(source, relative)
        elif relative in scanned_as_production:
            _assert_m1e_production_module_allowed(source, relative)
        elif relative in M2_ALPACA_BRIDGE_SCRIPT_PATHS:
            _assert_m2_bridge_script_allowed(relative, source)
        else:
            _assert_m1e_script_allowed(relative, source)

    helper = _load_pinned_helper()
    helper.verify_m1d_protected_inputs(root=REPO_ROOT)
    assert (REPO_ROOT / "pyproject.toml").read_bytes() == subprocess.run(
        ["git", "show", f"{PINNED_M1D_COMMIT}:pyproject.toml"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    assert (REPO_ROOT / "uv.lock").read_bytes() == subprocess.run(
        ["git", "show", f"{PINNED_M1D_COMMIT}:uv.lock"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout


def test_production_ast_guard_rejects_alias_aware_process_and_dynamic_execution() -> (
    None
):
    """A future M1e module cannot hide local process execution behind aliases."""
    attacks = (
        "import os\nos.system('true')\n",
        "import os as platform\nplatform.system('true')\n",
        "import subprocess as sp\nsp.run(['true'])\n",
        "from os import system as shell\nshell('true')\n",
        "from builtins import exec as execute\nexecute('pass')\n",
        "def run_process() -> None:\n    pass\n",
    )
    for source in attacks:
        with pytest.raises(AssertionError):
            _assert_m1e_production_module_allowed(source, "negative-control.py")


def test_production_ast_guard_refuses_every_credential_read() -> None:
    """Production modules never had the Task 8 credential deferral lifted."""
    attacks = (
        "import os\nos.getenv('ALPACA_API_KEY')\n",
        "import os\nos.environ.get('ALPACA_API_KEY')\n",
        "import os\nos.environ['ALPACA_API_KEY']\n",
        "from os import getenv\ngetenv('ALPACA_API_KEY')\n",
        "import keyring\nkeyring.get_password('alpaca', 'key')\n",
    )
    for source in attacks:
        with pytest.raises(AssertionError):
            _assert_m1e_production_module_allowed(source, "negative-control.py")

    # The guard is specific: the file writing the adapter actually does is not
    # a credential read and must still pass.
    _assert_m1e_production_module_allowed(
        "import os\nos.open('/tmp/x', os.O_WRONLY)\n", "negative-control.py"
    )


def test_injecting_a_credential_read_into_the_alpaca_bridge_now_fails() -> None:
    """The bridge is scanned as production source, so the check binds to it."""
    relative = "src/drift/adapters/alpaca_exploratory.py"
    source = (REPO_ROOT / relative).read_text(encoding="utf-8")

    # Unmodified, the real adapter passes.
    _assert_m1e_production_module_allowed(source, relative)

    for injection in (
        '\n\n_LEAKED = os.getenv("ALPACA_API_KEY")\n',
        '\n\n_LEAKED = os.environ.get("ALPACA_API_KEY")\n',
        '\n\n_LEAKED = os.environ["ALPACA_API_KEY"]\n',
    ):
        with pytest.raises(AssertionError):
            _assert_m1e_production_module_allowed(source + injection, relative)


def test_script_ast_guard_partitions_process_and_defers_acquisition_capabilities() -> (
    None
):
    """Task 1 permits planned process work but no network or credential access."""
    with pytest.raises(AssertionError):
        _assert_m1e_script_allowed(
            "scripts/intake_m1e_truth.py",
            "import subprocess\nsubprocess.run(['true'])\n",
        )
    with pytest.raises(AssertionError):
        _assert_m1e_script_allowed(
            "scripts/qualify_m1e_pilot.py",
            "import requests\nrequests.get('https://example.invalid')\n",
        )
    with pytest.raises(AssertionError):
        _assert_m1e_script_allowed(
            "scripts/qualify_m1e_pilot.py",
            "import os\nos.getenv('M1E_TOKEN')\n",
        )
    with pytest.raises(AssertionError):
        _assert_m1e_script_allowed(
            "scripts/replay_m1e_offline.py",
            "import os\nos.environ['M1E_TOKEN']\n",
        )
    _assert_m1e_script_allowed(
        "scripts/capture_m1e_environment.py",
        "import subprocess\nsubprocess.run(['true'])\n",
    )
    with pytest.raises(AssertionError):
        _assert_m1e_script_allowed(
            "scripts/acquire_m1e_pilot.py",
            "import requests\nimport os\nrequests.get('https://example.invalid')\nos.getenv('M1E_TOKEN')\n",
        )


def test_m2_bridge_script_guard_lifts_only_the_two_deferred_capabilities() -> None:
    """Task 8 gets transport and API key reads; nothing else is relaxed."""
    allowed = "scripts/intake_alpaca_exploratory.py"

    _assert_m2_bridge_script_allowed(
        allowed,
        "import os\nimport urllib.request\nos.environ.get('APCA_API_KEY_ID')\n",
    )

    with pytest.raises(AssertionError):
        _assert_m2_bridge_script_allowed(allowed, "import subprocess\n")
    with pytest.raises(AssertionError):
        _assert_m2_bridge_script_allowed(allowed, "import os\nos.system('true')\n")
    with pytest.raises(AssertionError):
        _assert_m2_bridge_script_allowed(allowed, "exec('pass')\n")
    with pytest.raises(AssertionError):
        _assert_m2_bridge_script_allowed(
            allowed, "def read_credential_store() -> None:\n    pass\n"
        )
    with pytest.raises(AssertionError):
        _assert_m2_bridge_script_allowed("scripts/init_local_db.py", "x = 1\n")

    # Every M1e script keeps the original Task 1 prohibition.
    with pytest.raises(AssertionError):
        _assert_m1e_script_allowed(
            "scripts/acquire_m1e_pilot.py", "import urllib.request\n"
        )
    with pytest.raises(AssertionError):
        _assert_m1e_script_allowed(
            "scripts/acquire_m1e_pilot.py", "import os\nos.getenv('M1E_TOKEN')\n"
        )


ALPACA_ADAPTER_PATH = "src/drift/adapters/alpaca_exploratory.py"
ALPACA_SCRIPT_PATH = "scripts/intake_alpaca_exploratory.py"

#: Every spelling an independent review executed against the earlier guards,
#: each of which read the secret or reached a transport when injected into the
#: real adapter, plus the three module-reaching routes named alongside them.
#: Each is paired with the allowlist rule that must name it.
ADAPTER_BYPASSES: dict[str, tuple[str, str]] = {
    "proc-environ-via-path": (
        '_LEAK = Path("/proc/self/environ").read_bytes()\n',
        "names the process-environment file '/proc/self/environ'",
    ),
    "proc-environ-via-open": (
        '_LEAK = open("/proc/self/environ", "rb").read()\n',
        "reaches the builtin open, which is outside its allowlist",
    ),
    "getattr-on-os": (
        '_LEAK = getattr(os, "environ")["APCA_API_SECRET_KEY"]\n',
        "references the module os other than as the owner of an allowlisted",
    ),
    "os-getenvb": (
        '_LEAK = os.getenvb(b"APCA_API_SECRET_KEY")\n',
        "uses os.getenvb, which is outside the os allowlist",
    ),
    "os-environb": (
        '_LEAK = os.environb[b"APCA_API_SECRET_KEY"]\n',
        "uses os.environb, which is outside the os allowlist",
    ),
    "from-os-import-environ": (
        'from os import environ\n_LEAK = environ.get("APCA_API_SECRET_KEY")\n',
        "imports os.environ, which is outside the os allowlist",
    ),
    "aliased-environ": (
        '_E = os.environ\n_LEAK = _E.get("APCA_API_SECRET_KEY")\n',
        "uses os.environ, which is outside the os allowlist",
    ),
    "dict-of-environ": (
        '_LEAK = dict(os.environ)["APCA_API_SECRET_KEY"]\n',
        "uses os.environ, which is outside the os allowlist",
    ),
    "environ-copy": (
        '_LEAK = os.environ.copy()["APCA_API_SECRET_KEY"]\n',
        "uses os.environ, which is outside the os allowlist",
    ),
    "importlib-os": (
        "import importlib\n"
        '_LEAK = importlib.import_module("os").environ["APCA_API_SECRET_KEY"]\n',
        "imports importlib, which is outside its import allowlist",
    ),
    "from-os-import-getenv-aliased": (
        'from os import getenv as g\n_LEAK = g("APCA_API_SECRET_KEY")\n',
        "imports os.getenv, which is outside the os allowlist",
    ),
    "importlib-network": (
        'import importlib\n_NET = importlib.import_module("urllib.request")\n',
        "imports importlib, which is outside its import allowlist",
    ),
    "dunder-import-network": (
        '_NET = __import__("urllib.request")\n',
        "reaches __import__, a builtin that resolves modules",
    ),
    "sys-modules": (
        'import sys\n_LEAK = sys.modules["os"].environ["APCA_API_SECRET_KEY"]\n',
        "imports sys, which is outside its import allowlist",
    ),
    "function-globals": (
        "_LEAK = retain_native_bytes.__globals__"
        '["os"].environ["APCA_API_SECRET_KEY"]\n',
        "reads the dunder attribute __globals__",
    ),
}


def test_the_real_alpaca_bridge_sources_pass_their_allowlists() -> None:
    """The allowlist is derived from the real sources, so both must pass."""
    for relative in sorted(M2_ALPACA_BRIDGE_SOURCE_PATHS):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert (
            _bridge_capability_violations(source, relative, ALPACA_ADAPTER_ALLOWLIST)
            == []
        )
        _assert_alpaca_bridge_module_allowed(source, relative)
    script = (REPO_ROOT / ALPACA_SCRIPT_PATH).read_text(encoding="utf-8")
    assert (
        _bridge_capability_violations(
            script, ALPACA_SCRIPT_PATH, ALPACA_SCRIPT_ALLOWLIST
        )
        == []
    )
    _assert_m2_bridge_script_allowed(ALPACA_SCRIPT_PATH, script)


@pytest.mark.parametrize("bypass", sorted(ADAPTER_BYPASSES))
def test_every_known_credential_or_network_bypass_is_refused_in_the_adapter(
    bypass: str,
) -> None:
    injection, rule = ADAPTER_BYPASSES[bypass]
    source = (REPO_ROOT / ALPACA_ADAPTER_PATH).read_text(encoding="utf-8")

    with pytest.raises(AssertionError, match=re.escape(rule)):
        _assert_alpaca_bridge_module_allowed(
            source + "\n\n" + injection, ALPACA_ADAPTER_PATH
        )


#: The script may read two variables through one spelling. Every other
#: environment read, and every route to the environment that avoids
#: ``os.environ.get``, is refused even there.
SCRIPT_BYPASSES: dict[str, tuple[str, str]] = {
    "proc-environ-via-path": (
        '_LEAK = Path("/proc/self/environ").read_bytes()\n',
        "names the process-environment file '/proc/self/environ'",
    ),
    "builtin-open": (
        '_LEAK = open("/etc/hosts").read()\n',
        "reaches the builtin open, which is outside its allowlist",
    ),
    "getenv-of-a-key": (
        '_LEAK = os.getenv("APCA_API_SECRET_KEY")\n',
        "uses os.getenv, which is outside the os allowlist",
    ),
    "environ-subscript-of-a-key": (
        '_LEAK = os.environ["APCA_API_SECRET_KEY"]\n',
        "uses os.environ, which is outside the os allowlist",
    ),
    "a-third-variable": (
        '_LEAK = os.environ.get("AWS_SECRET_ACCESS_KEY")\n',
        "uses os.environ, which is outside the os allowlist",
    ),
    "a-key-read-with-a-default": (
        '_LEAK = os.environ.get("APCA_API_SECRET_KEY", "")\n',
        "uses os.environ, which is outside the os allowlist",
    ),
    "a-permitted-name-rebound": (
        'KEY_ID_VARIABLE = "HOME"\n',
        "uses os.environ, which is outside the os allowlist",
    ),
    "getattr-on-os": (
        '_LEAK = getattr(os, "environ")\n',
        "references the module os other than as the owner of an allowlisted",
    ),
    "from-os-import-environ": (
        "from os import environ\n",
        "imports os.environ, which is outside the os allowlist",
    ),
    "importlib": (
        "import importlib\n",
        "imports importlib, which is outside its import allowlist",
    ),
    "sys-modules": (
        '_LEAK = sys.modules["os"]\n',
        "uses sys.modules, which is outside the sys allowlist",
    ),
}


@pytest.mark.parametrize("bypass", sorted(SCRIPT_BYPASSES))
def test_the_script_may_read_only_the_two_alpaca_key_variables(bypass: str) -> None:
    injection, rule = SCRIPT_BYPASSES[bypass]
    source = (REPO_ROOT / ALPACA_SCRIPT_PATH).read_text(encoding="utf-8")

    with pytest.raises(AssertionError, match=re.escape(rule)):
        _assert_m2_bridge_script_allowed(
            ALPACA_SCRIPT_PATH, source + "\n\n" + injection
        )


#: The only production module allowed to mint measured-origin records. It is
#: the one module that performs the transfer the records describe.
ORIGIN_RECORD_MINTER = "retain_origin_observations"
ORIGIN_RECORD_MINTING_PATHS = frozenset({ALPACA_SCRIPT_PATH})


def _origin_record_minters(root: Path) -> set[str]:
    """Every production module under ``root`` that references the minter.

    The adapter's own definition is not a reference; any other name, attribute
    or import of it is.
    """
    found: set[str] = set()
    for base in (root / "src", root / "scripts"):
        for path in sorted(base.rglob("*.py")) if base.is_dir() else ():
            tree = ast.parse(path.read_bytes(), str(path))
            for node in ast.walk(tree):
                named = (
                    (isinstance(node, ast.Name) and node.id == ORIGIN_RECORD_MINTER)
                    or (
                        isinstance(node, ast.Attribute)
                        and node.attr == ORIGIN_RECORD_MINTER
                    )
                    or (
                        isinstance(node, ast.alias)
                        and node.name == ORIGIN_RECORD_MINTER
                    )
                )
                if named:
                    found.add(path.relative_to(root).as_posix())
    return found


def test_only_the_acquisition_cli_mints_origin_records() -> None:
    """A measured-origin record is minted only by what performed the transfer.

    `retain_origin_observations` binds a record to any bytes it is handed, so
    a caller that fetched nothing could certify bytes nothing measured. Only
    the acquisition CLI may reach it; tests are not production and are exempt.
    """
    assert _origin_record_minters(REPO_ROOT) == ORIGIN_RECORD_MINTING_PATHS


def test_a_second_origin_record_minter_is_detected(tmp_path: Path) -> None:
    """The scan is not vacuous: a new production caller is reported."""
    module = tmp_path / "src" / "drift" / "evaluator" / "sneaky.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "from drift.adapters.alpaca_exploratory import retain_origin_observations\n",
        encoding="utf-8",
    )
    assert _origin_record_minters(tmp_path) == {"src/drift/evaluator/sneaky.py"}
