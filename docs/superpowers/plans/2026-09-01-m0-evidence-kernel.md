# Drift M0 Evidence Kernel Implementation Plan

**Status:** Completed. Historical plan, not active work.

**Completion:** M0 landed at commit `301dc9d`. The checkboxes below record the
completed execution sequence and must not be treated as pending tasks.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a typed, deterministic, append-only research evidence kernel with tamper detection and no trading capability.

**Architecture:** Frozen Pydantic models define research provenance. Canonical JSON and SHA-256 produce stable hashes. A standard-library SQLite adapter stores audit events with database-enforced append-only behavior, deterministic replay, and full-chain verification.

**Tech Stack:** Python 3.14, Pydantic 2, standard-library sqlite3/hashlib/json/uuid/datetime, pytest, Ruff, mypy

**Spec:** `docs/superpowers/specs/2026-09-01-m0-evidence-kernel-design.md`

## Global Constraints

- Implement M0 only.
- No broker connectivity, broker abstractions, MCP, OAuth, order management, live market data, agent orchestration, backtesting, strategies, portfolio construction, risk engine, Docker, cloud services, schedulers, Redis, vectors, or dashboards.
- Runtime dependencies are limited to Pydantic.
- All hash inputs use canonical serialization and SHA-256.
- All stored timestamps are timezone-aware and normalized to UTC.
- Historical audit events are append-only at both application and database levels.
- Research outputs remain untrusted and cannot affect future production state directly.

---

### Task 1: Project scaffold and developer contract

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/drift/__init__.py`
- Create: `src/drift/errors.py`
- Create: package `__init__.py` files under `domain`, `ledger`, `serialization`, and `config`
- Create: `tests/unit/test_project_contract.py`

**Interfaces:**
- Produces: installable `drift` package and shared exception classes `DriftError`, `DuplicateEventError`, `LedgerIntegrityError`, and `LedgerMutationError`.

- [x] **Step 1: Write the failing project-contract test**

```python
from importlib.metadata import version

import drift


def test_package_exposes_its_installed_version() -> None:
    assert drift.__version__ == version("drift")
```

- [x] **Step 2: Run the test and confirm the package is missing**

Run: `uv run pytest tests/unit/test_project_contract.py -v`

Expected: collection fails because `drift` is not installed.

- [x] **Step 3: Add minimal packaging and shared exceptions**

Configure Python `>=3.14`, Pydantic as the sole runtime dependency, and pytest/Ruff/mypy as development dependencies. Set strict mypy and Ruff rules. Implement `drift.__version__` using `importlib.metadata.version("drift")`.

- [x] **Step 4: Install and verify the scaffold**

Run: `uv sync --dev && uv run pytest tests/unit/test_project_contract.py -v && uv run ruff check . && uv run mypy src tests`

Expected: all commands exit 0.

- [x] **Step 5: Commit the scaffold**

```bash
git add pyproject.toml uv.lock .gitignore .env.example src tests docs/superpowers
git commit -m "chore: initialize drift project"
```

### Task 2: Canonical serialization and identifiers

**Files:**
- Create: `src/drift/domain/ids.py`
- Create: `src/drift/serialization/canonical.py`
- Create: `tests/unit/test_ids.py`
- Create: `tests/unit/test_canonical_serialization.py`

**Interfaces:**
- Produces: `new_entity_id() -> UUID`, `new_event_id() -> UUID`, `canonical_data(value: object) -> JSONValue`, `canonical_json(value: object) -> bytes`, and `content_hash(value: object) -> str`.

- [x] **Step 1: Write failing identifier and serialization tests**

```python
def test_generated_ids_are_uuid7() -> None:
    assert new_entity_id().version == 7


def test_mapping_order_does_not_change_canonical_bytes() -> None:
    assert canonical_json({"b": 2, "a": 1}) == b'{"a":1,"b":2}'


def test_datetime_is_normalized_to_utc() -> None:
    value = datetime(2026, 1, 1, 1, tzinfo=timezone(timedelta(hours=1)))
    assert canonical_json(value) == b'"2026-01-01T00:00:00.000000Z"'


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(CanonicalSerializationError):
        canonical_json(datetime(2026, 1, 1))
```

- [x] **Step 2: Run the tests and confirm missing functions fail**

Run: `uv run pytest tests/unit/test_ids.py tests/unit/test_canonical_serialization.py -v`

Expected: collection fails on missing modules or imports.

- [x] **Step 3: Implement UUIDv7 generation and canonical normalization**

Normalize Pydantic models through `model_dump(mode="python")`; mappings by sorted string keys; datetimes as UTC with six fractional digits and `Z`; dates as ISO strings; enums by value; UUIDs and paths as strings; sets as sorted canonical arrays; tuples and lists as arrays; Decimal values as strings; null as JSON null. Reject naive datetimes, non-string mapping keys, non-finite floats, bytes, and unsupported objects. Serialize with UTF-8, sorted keys, compact separators, and `allow_nan=False`.

- [x] **Step 4: Verify serialization and identifiers**

Run: `uv run pytest tests/unit/test_ids.py tests/unit/test_canonical_serialization.py -v`

Expected: all tests pass.

- [x] **Step 5: Commit deterministic primitives**

```bash
git add src/drift/domain/ids.py src/drift/serialization tests/unit/test_ids.py tests/unit/test_canonical_serialization.py
git commit -m "feat: add deterministic identifiers and serialization"
```

### Task 3: Immutable research domain models

**Files:**
- Create: `src/drift/domain/common.py`
- Create: `src/drift/domain/hypotheses.py`
- Create: `src/drift/domain/datasets.py`
- Create: `src/drift/domain/strategies.py`
- Create: `src/drift/domain/artifacts.py`
- Create: `src/drift/domain/experiments.py`
- Create: `src/drift/domain/evidence.py`
- Create: `tests/unit/test_domain_models.py`

**Interfaces:**
- Produces: `Hypothesis`, `DatasetReference`, `TemporalCoverage`, `StrategyReference`, `StrategyArtifact`, `ArtifactReference`, `ExperimentSpecification`, `ExperimentRun`, `EvidenceRecord`, and their enums.

- [x] **Step 1: Write failing domain validation tests**

```python
def test_models_are_frozen() -> None:
    hypothesis = valid_hypothesis()
    with pytest.raises(ValidationError):
        hypothesis.title = "changed"


def test_hypothesis_cannot_reference_itself() -> None:
    hypothesis_id = uuid7()
    with pytest.raises(ValidationError):
        valid_hypothesis(
            hypothesis_id=hypothesis_id,
            parent_hypothesis_ids=(hypothesis_id,),
        )


def test_completed_run_requires_completion_time() -> None:
    with pytest.raises(ValidationError):
        valid_run(status=ExperimentRunStatus.COMPLETED, completed_at=None)


def test_failed_run_preserves_error_details() -> None:
    run = valid_run(status=ExperimentRunStatus.FAILED, error_details="process exited 2")
    assert run.error_details == "process exited 2"
```

- [x] **Step 2: Run the domain tests and confirm models are missing**

Run: `uv run pytest tests/unit/test_domain_models.py -v`

Expected: collection fails on missing domain types.

- [x] **Step 3: Implement frozen strict models and cross-field validation**

Use a shared `FrozenModel` with `ConfigDict(frozen=True, strict=True, extra="forbid")`. Require UTC-aware timestamps, nonblank constrained strings, 64-character lowercase SHA-256 hashes, nonempty unique reference collections where required, valid temporal ranges, no self-parent relationships, and consistent run status fields. Store parameters, metrics, evaluation protocol, and cost assumptions as immutable JSON values accepted by canonical serialization.

- [x] **Step 4: Verify all domain behavior**

Run: `uv run pytest tests/unit/test_domain_models.py -v`

Expected: all tests pass.

- [x] **Step 5: Commit domain models**

```bash
git add src/drift/domain tests/unit/test_domain_models.py
git commit -m "feat: add immutable research domain models"
```

### Task 4: Audit event hashing

**Files:**
- Create: `src/drift/domain/events.py`
- Create: `src/drift/ledger/hashing.py`
- Create: `tests/unit/test_hashing.py`

**Interfaces:**
- Produces: `GENESIS_HASH`, `UnsignedAuditEvent`, `AuditEvent`, `compute_event_hash(event) -> str`, and `build_audit_event(unsigned_event) -> AuditEvent`.

- [x] **Step 1: Write failing hash behavior tests**

```python
def test_same_unsigned_event_produces_same_hash() -> None:
    unsigned = valid_unsigned_event()
    assert compute_event_hash(unsigned) == compute_event_hash(unsigned)


def test_payload_change_changes_event_hash() -> None:
    first = valid_unsigned_event(payload={"result": "accepted"})
    second = first.model_copy(update={"payload": {"result": "rejected"}})
    assert compute_event_hash(first) != compute_event_hash(second)


def test_builder_sets_computed_hash() -> None:
    unsigned = valid_unsigned_event(previous_event_hash=GENESIS_HASH)
    event = build_audit_event(unsigned)
    assert event.event_hash == compute_event_hash(unsigned)
```

- [x] **Step 2: Run tests and confirm event hashing is absent**

Run: `uv run pytest tests/unit/test_hashing.py -v`

Expected: collection fails on missing event and hashing types.

- [x] **Step 3: Implement the signed event envelope**

Hash every unsigned event field, including the previous hash and explicit null deduplication key. Validate `event_hash` and `previous_event_hash` as SHA-256 values. Exclude only `event_hash` from the hash input.

- [x] **Step 4: Verify event hashing**

Run: `uv run pytest tests/unit/test_hashing.py -v`

Expected: all tests pass.

- [x] **Step 5: Commit the audit envelope**

```bash
git add src/drift/domain/events.py src/drift/ledger/hashing.py tests/unit/test_hashing.py
git commit -m "feat: add hash-chained audit events"
```

### Task 5: Append-only SQLite ledger

**Files:**
- Create: `src/drift/ledger/interface.py`
- Create: `src/drift/ledger/sqlite.py`
- Create: `tests/unit/test_ledger.py`

**Interfaces:**
- Produces: `Ledger` protocol and `SQLiteLedger` with `append`, `get`, `events`, `events_for_entity`, `events_after`, and `verify_chain` methods.

- [x] **Step 1: Write failing ledger tests**

```python
def test_append_assigns_genesis_then_previous_hash(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "ledger.db")
    first = ledger.append(valid_event_input(deduplication_key="first"))
    second = ledger.append(valid_event_input(deduplication_key="second"))
    assert first.previous_event_hash == GENESIS_HASH
    assert second.previous_event_hash == first.event_hash


def test_duplicate_event_id_is_rejected(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "ledger.db")
    event = valid_event_input()
    ledger.append(event)
    with pytest.raises(DuplicateEventError):
        ledger.append(event)


def test_database_rejects_updates_and_deletes(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(path)
    event = ledger.append(valid_event_input())
    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE audit_events SET payload_json = '{}' WHERE event_id = ?",
                (str(event.event_id),),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM audit_events WHERE event_id = ?", (str(event.event_id),)
            )
```

- [x] **Step 2: Run tests and confirm the ledger is missing**

Run: `uv run pytest tests/unit/test_ledger.py -v`

Expected: collection fails on missing ledger classes.

- [x] **Step 3: Implement transactional append and queries**

Create one `audit_events` table with an integer sequence primary key, unique event ID, nullable unique deduplication key, canonical payload JSON, all hash envelope fields, and schema version. Create `BEFORE UPDATE` and `BEFORE DELETE` triggers that abort with `audit_events is append-only`. Use `BEGIN IMMEDIATE` so concurrent appenders serialize the read-last-hash and insert operation. Convert SQLite uniqueness failures to `DuplicateEventError`.

- [x] **Step 4: Verify ledger behavior**

Run: `uv run pytest tests/unit/test_ledger.py -v`

Expected: all tests pass.

- [x] **Step 5: Commit the ledger**

```bash
git add src/drift/ledger tests/unit/test_ledger.py
git commit -m "feat: add append-only SQLite research ledger"
```

### Task 6: Chain verification, replay, and useful scripts

**Files:**
- Create: `src/drift/ledger/replay.py`
- Create: `src/drift/config/settings.py`
- Create: `scripts/init_local_db.py`
- Create: `scripts/verify_ledger.py`
- Create: `tests/integration/test_replay.py`
- Create: `tests/integration/test_tamper_detection.py`
- Create: `tests/integration/test_scripts.py`

**Interfaces:**
- Produces: `replay_events(ledger) -> tuple[AuditEvent, ...]`, `LedgerSettings`, executable database initialization, and executable verification.

- [x] **Step 1: Write failing replay, tamper, and script tests**

```python
def test_same_ledger_replays_identically(tmp_path: Path) -> None:
    ledger = populated_ledger(tmp_path / "ledger.db")
    assert replay_events(ledger) == replay_events(ledger)


@pytest.mark.parametrize(
    "mutation", ["payload", "delete", "event_hash", "previous_hash", "sequence"]
)
def test_verify_chain_detects_direct_database_tampering(
    tmp_path: Path, mutation: str
) -> None:
    path = tmp_path / "ledger.db"
    ledger = populated_ledger(path)
    mutate_with_triggers_temporarily_removed(path, mutation)
    with pytest.raises(LedgerIntegrityError):
        ledger.verify_chain()


def test_init_and_verify_scripts_operate_on_requested_path(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    initialized = subprocess.run(
        [sys.executable, "scripts/init_local_db.py", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    verified = subprocess.run(
        [sys.executable, "scripts/verify_ledger.py", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert initialized.returncode == 0
    assert verified.returncode == 0
```

- [x] **Step 2: Run integration tests and confirm missing behavior fails**

Run: `uv run pytest tests/integration -v`

Expected: collection fails on missing replay, settings, or scripts.

- [x] **Step 3: Implement full verification and scripts**

Verify sequence contiguity, genesis previous hash, each previous-to-current link, and recomputed event hashes. Replay returns the immutable ordered event tuple after successful verification. Settings accept only a local filesystem ledger path. Scripts accept an optional path argument, create parent directories, initialize the database, verify the chain, print concise results, and return nonzero on integrity failure.

- [x] **Step 4: Verify integrations**

Run: `uv run pytest tests/integration -v`

Expected: all tests pass.

- [x] **Step 5: Commit replay and tamper detection**

```bash
git add src/drift/config src/drift/ledger/replay.py scripts tests/integration
git commit -m "test: add replay and tamper-detection coverage"
```

### Task 7: Architecture documentation and skeptical final review

**Files:**
- Create: `README.md`
- Create: `AGENTS.md`
- Create: `docs/architecture/overview.md`
- Create: `docs/architecture/trust-boundaries.md`
- Create: `docs/architecture/roadmap.md`
- Create: `docs/adr/0001-evidence-first-architecture.md`
- Create: `docs/adr/0002-broker-neutral-core.md`
- Create: `docs/adr/0003-append-only-research-ledger.md`
- Create: `docs/adr/0004-research-production-separation.md`

**Interfaces:**
- Consumes: the implemented package commands and guarantees.
- Produces: maintainer instructions, setup documentation, trust-boundary documentation, retention policy, and roadmap through M1 without implementing M1.

- [x] **Step 1: Write documentation against verified commands**

Document `uv sync --dev`, `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src tests`, `uv run python scripts/init_local_db.py`, and `uv run python scripts/verify_ledger.py`. State explicitly that M0 has no trading, broker, market-data, backtesting, strategy, or agent capability.

- [x] **Step 2: Run a forbidden-capability audit**

Run a repository search excluding the specification, plan, architecture, ADR, README, AGENTS, and lock files. Inspect every match for `Robinhood`, `Alpaca`, `MCP`, `OAuth`, `place_order`, `broker`, `OPENAI`, `LANGGRAPH`, and network client packages. Expected: no implementation or configuration capability matches.

- [x] **Step 3: Run the full verification suite**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv build`

Expected: every command exits 0 with no failures.

- [x] **Step 4: Review the diff and repository tree**

Run: `git status --short && git diff --check && git diff --stat && find . -path ./.git -prune -o -type f -print | sort`

Expected: only intentional M0 files, no whitespace errors, no database files, no credentials, and no empty placeholder modules.

- [x] **Step 5: Commit documentation**

```bash
git add README.md AGENTS.md docs
git commit -m "docs: define drift architecture and trust boundaries"
```

- [x] **Step 6: Re-run fresh final verification and inspect Git history**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv build && git status --short && git log --oneline --decorate -8`

Expected: all checks exit 0, the worktree is clean, and commits correspond to independently useful milestones.
