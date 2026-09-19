# M1e License-Gated Real-Source Qualification and Replay Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Qualify one exact real-source pilot profile against Drift's M1b-M1d semantics, rights, acquisition-completeness, and offline-replay gates without building an evaluator or general data platform.

**Architecture:** Preserve accepted M1d replay before adding source, then implement provider-independent qualification, rights, acquisition, snapshot, adapter, golden-case, and environment contracts. Freeze one provider/product scope only after external evidence exists; acquire at most one authorized bounded pilot and complete each purpose-specific qualification positively or with an evidenced negative result.

**Tech Stack:** Existing Python 3.14+, Pydantic, pytest, Ruff, mypy, uv, and Python standard library only. No new dependency, database, object store, provider SDK, evaluator, broker, or trading capability.

**Execution status:** Tasks 1 through 7 complete, verified across 1,882 tests, and accepted at commit `4b343f77a0cb60d0c4ba56f066dc33ac538a9b8d`. Provider empirical screening is complete across algoseek, Databento free tier, and Alpaca Basic. Paid promotion-grade source qualification under Task 8 is paused/deferred until economically justified by exploratory research. Task 8 remains open. Under [ADR 0012](../../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md), exploratory M2 evaluator architecture is authorized while Task 8 is deferred. Promotion-grade evaluation remains strictly gated on positive M1e qualification.

**Spec:** [M1e License-Gated Real-Source Qualification and Replay Closure Pilot](../specs/2026-09-12-license-gated-real-source-qualification-replay-closure-design.md), [ADR 0010](../../adr/0010-qualify-real-source-rights-and-replay-before-evaluation.md), and the completed [M1d execution record](2026-09-07-m1d-source-observations-sessions-normalization.md).

## Global Constraints

- Work in `/Users/kanuj/Documents/projects/drift`, never the ChatGPT project mirror.
- Planning baseline: `f67dc3981458293aa33d19c64947f805402b1528` on `main`. Accepted M1d code/fixture baseline: `af75cce0f763de025f8ae3516577a9d0a1acead9`.
- M0 through M1d are complete. Do not modify their persisted models, algorithms, source files, canonical bytes, fixtures, or accepted hashes. Add M1e beside them.
- Before the first M1e source file is added, Task 1 must preserve M1d v3 through genuine archived execution at `af75cce0f763de025f8ae3516577a9d0a1acead9`. Never narrow `m1d_implementation_hash()`, regenerate v3, or re-sign its expected hashes.
- The pilot groups exactly two purpose-specific profiles: `historical_decision_input` and `retrospective_audit`. Evidence may be shared when rights permit, but a status for one purpose never transfers to the other.
- A profile freezes provider, product, subscriber, infrastructure, requested source scope, and one consumer purpose before acquisition. A later target binds the profile to an actual snapshot. A pre-acquisition negative result records `NOT_ACQUIRED` and has no snapshot.
- Default execution scope is one user, one local machine, no contractors, shared account, real-data CI, cloud processing, or third-party byte access. Provider-defined professional, business, display, and non-display classifications remain unresolved until exact evidence decides them.
- Real source, grading, contract, and environment bytes use an explicitly approved private content-addressed root outside Git. Public Git fixtures remain synthetic. Restricted or confidential bytes never enter Git, ordinary CI, logs, or agent prompts.
- The first platform target is macOS/arm64. Docker/OCI is not part of the initial path. A native restore failure creates a material user-review stop before any OCI work.
- `uv --offline` and `--no-index` are package-manager controls only. Replay may return `MATCH` only with a separately verified system-level offline attestation and fresh-target attestation.
- Use existing `FrozenModel`, `canonical_json`, `content_hash`, `ArtifactReference`, `VerifiedArtifactBytes`, `DatasetManifestV2`, validation decisions/bundles, M1a availability, M1b resolvers, M1c resolution/replay, and M1d validation/replay. `ArtifactKind.OTHER` is sufficient; do not expand old persisted enums merely to label M1e evidence.
- `ValidationResult` remains the binary dataset-validation result. M1e owns a separate four-state `QualificationStatus`; never overload or modify the old enum.
- Physical paths and storage roots never enter scientific identity. Canonical artifact references use `drift+sha256://<sha256>` and bind exact bytes independently of location.
- No weighted vendor score and no vendor-wide acceptance. Every result is exact-profile, exact-snapshot, exact-purpose, exact-policy evidence.
- Do not fabricate provider PASS evidence with synthetic fixtures. Synthetic fixtures prove machinery and fail-closed behavior only.
- Do not purchase anything, contact vendors, or acquire paid/restricted data without new explicit user authority. Implementation code cannot decide legal meaning; it validates externally adjudicated evidence.
- No evaluator/backtester, returns, holdings, cash, costs, slippage, optimizer, risk, strategy, ML, recursive research, broker, Robinhood, Alpaca, orders, live trading, real-time feed, recurring ingestion, provider orchestration, production agent runtime, or cloud deployment.
- No new dependency, database, object-store service, secret manager, or OCI requirement without a material user-review stop.
- Do not touch `.DS_Store`, `.superpowers/`, or historical handoffs. Never stage a directory wholesale.
- Use meaningful RED/GREEN tests, a fresh reviewer for every slice, controller verification against the actual repository, one final full gate per accepted task boundary, and Checkpoint after each commit. A full gate is not rerun during ordinary edit iterations.
- Use U+002D hyphen, never U+2014 em dash, in every new artifact.

---

## 1. Planning rulings and execution epochs

M1e remains one milestone with eight independently reviewable tasks. Tasks 1
through 7 are provider-independent and can complete without entitlement or
vendor response. Task 8 is the only real-provider task. It begins only after the
missing external evidence exists and may close the exact pilot negatively at
any reached gate.

The pilot is overall `COMPLETED_POSITIVE` only when both requested purposes pass.
If one purpose passes and the other is blocked, the overall completion is
evidenced-negative while preserving the usable purpose's PASS report and
purpose-scoped handoff. A retrospective-audit PASS never authorizes historical
decision input.

### 1.1 Bounded clarifications to the accepted design

| Seam | Repository/spec evidence | Ruling |
|---|---|---|
| Profile versus delivered snapshot | Profile freeze must precede authorization and acquisition, so delivered bytes do not yet exist | `QualificationProfileV1` is snapshot-free. `QualificationTargetV1` later binds one profile hash to `snapshot_hash` or `NOT_ACQUIRED`. |
| Two consumer purposes | Consumer purpose is part of qualification identity; the user requires separate historical-decision and retrospective-audit decisions | `PilotProfileSetV1` contains exactly two otherwise scope-aligned profiles. Reports and completion are purpose-specific. |
| Offline proof on macOS | `uv --offline` blocks uv network access, not arbitrary process networking | `MATCH` requires `SystemOfflineAttestationV1` plus `FreshRestoreAttestationV1`. Without them, replay cannot pass. |
| M1d v3 compatibility | `m1d_implementation_hash()` delegates to the whole-installed-package fingerprint; any new `src/drift/**/*.py` changes it | Task 1 pins genuine v3 execution at `af75cce`. Old fixture bytes and source fingerprints are never rebound to M1e code. |
| Unknown provider schema | Exact provider-native layers and mappings do not exist until a product and delivered schema are evidenced | Tasks 1-7 freeze the boundary. Task 8 implements one fixed `pilot_adapter.py` only after the exact profile/schema gate. |

### 1.2 Execution and external pause flow

```text
Tasks 1-7: provider-independent source and synthetic verification
        |
        v
Checkpoint with external-evidence request
        |
        +--> evidence PENDING: minimal Session Handoff, stop
        +--> evidence-backed DECLINED/WITHDRAWN/INQUIRY_EXHAUSTED/UNAVAILABLE
             before profile freeze: ABANDONED_PRE_PROFILE record, stop
        |
        v
Task 8 profile set frozen
        |
        +--> rights denied/unknown: NOT_ACQUIRED negative completion
        |
        v
explicit acquisition authorization
        |
        +--> incomplete/unsafe acquisition: reached-stage negative completion
        |
        v
one offline profile-specific adapter + real golden cases
        |
        +--> semantic/coverage failure: reached-stage negative completion
        |
        v
replay-time authorization + fresh isolated macOS/arm64 replay
        |
        +--> non-MATCH: reached-stage negative completion
        |
        v
purpose-specific positive completion
```

Waiting is not a scientific state transition. When the next action needs a user
classification, entitlement record, executed agreement, provider response,
delivered file, legal adjudication, private-root approval, or isolation
attestation, update this plan's execution record, commit any accepted work,
Checkpoint, create only the minimal Session Handoff required for the unfinished
milestone, and stop. A later Sol High root runs Resume after the artifact exists.

## 2. File ownership

All paths below are future implementation targets. No file listed here is
created by the planning task except this plan and the separately identified
lifecycle/design clarifications.

| Task | Production or script paths | Test and evidence paths |
|---|---|---|
| 1 | none | `tests/_pinned_m1d.py`; `tests/integration/test_m1d_pinned_replay.py`; `tests/integration/test_m1e_compatibility.py`; `tests/fixtures/m1e-compatibility/m1d-v3-protected-sha256.json`; modify `tests/conftest.py`, `tests/integration/test_m1d_compatibility.py` |
| 2 | `src/drift/domain/qualification.py`; `src/drift/qualification/__init__.py`; `src/drift/qualification/lifecycle.py` | `tests/unit/test_qualification_contracts.py`; `tests/unit/test_m1e_lifecycle.py` |
| 3 | `src/drift/domain/rights.py`; `src/drift/qualification/rights.py` | `tests/unit/test_rights_assessment.py`; `tests/unit/test_replay_authorization.py` |
| 4 | `src/drift/domain/acquisition.py`; `src/drift/qualification/acquisition.py`; `src/drift/qualification/store.py` | `tests/unit/test_acquisition_receipts.py`; `tests/unit/test_acquisition_reconciliation.py`; `tests/unit/test_private_content_store.py` |
| 5 | `src/drift/domain/source_snapshots.py`; `src/drift/qualification/snapshots.py` | `tests/unit/test_source_snapshots.py`; `tests/unit/test_cross_component_consistency.py` |
| 6 | `src/drift/domain/qualification_adapters.py`; `src/drift/domain/golden_cases.py`; `src/drift/qualification/adapters.py`; `src/drift/qualification/golden_cases.py`; `src/drift/qualification/harness.py`; `scripts/intake_m1e_truth.py` | `tests/unit/test_qualification_adapter_boundary.py`; `tests/unit/test_golden_case_contracts.py`; `tests/unit/test_truth_evidence.py`; `tests/unit/test_qualification_harness.py` |
| 7 | `src/drift/domain/environment_closure.py`; `src/drift/domain/qualification_replay.py`; `src/drift/qualification/environment.py`; `src/drift/qualification/replay.py`; `scripts/capture_m1e_environment.py`; `scripts/replay_m1e_offline.py` | `tests/unit/test_environment_closure.py`; extend `tests/unit/test_replay_authorization.py`; `tests/integration/test_m1e_offline_replay.py` |
| 8 | conditional `src/drift/qualification/pilot_adapter.py`; conditional `scripts/acquire_m1e_pilot.py`; `scripts/qualify_m1e_pilot.py` | `tests/unit/test_pilot_adapter.py`; `tests/integration/test_m1e_adversarial_matrix.py`; modify `tests/integration/test_m1e_compatibility.py`; `tests/unit/test_documentation_links.py`; `docs/qualification/m1e/pilot-record.md`; lifecycle docs and this plan's execution record |

Do not modify `src/drift/config/settings.py`, any M0-M1d domain or runtime
module, `src/drift/ledger/replay.py`, `pyproject.toml`, `uv.lock`, or accepted
M1a-M1d fixture bytes. The M1e package imports concrete old owners; old packages
do not import M1e.

## 3. Shared contract conventions

All persisted M1e models extend `FrozenModel`, use `extra="forbid"`, and include
`schema_version: Literal["1"] = "1"`. IDs use `UUID7`, digests use
`SHA256Hash`, instants use `UTCDateTime`, required strings use `NonBlankStr`, and
free-form JSON uses `ImmutableJSON`. Unordered semantic collections validate as
sorted unique tuples. Models reject unknown enum values; an explicit `UNKNOWN`
member represents supported uncertainty.

Canonical identity is `content_hash(model)`. A model with a stored self-hash
uses a named body function that removes only that self-hash before hashing.
Never exclude IDs, original timestamps, policies, limitations, or dependency
hashes from an accepted historical artifact. New replay-attempt metadata belongs
only to `ReplayAttemptEnvelopeV1`.

Low-level malformed objects, unsafe paths, hash mismatch, nonregular files, and
secret-bearing canonical input raise typed errors. Valid but incomplete,
unsupported, contradictory, or legally unresolved evidence produces the
appropriate `PARTIAL`, `FAIL`, or `UNKNOWN` result instead of a crash.

Ellipses in signature blocks denote type-only interface declarations in this
plan. They are not implementation stubs or unresolved names.

### Task 1: Pin accepted M1d v3 before any M1e source

**Files:**

- Create: `tests/_pinned_m1d.py`
- Create: `tests/integration/test_m1d_pinned_replay.py`
- Create: `tests/integration/test_m1e_compatibility.py`
- Create: `tests/fixtures/m1e-compatibility/m1d-v3-protected-sha256.json`
- Modify: `tests/conftest.py`
- Modify: `tests/integration/test_m1d_compatibility.py`

**Interfaces:**

```python
class PinnedM1dReplayError(RuntimeError):
    """Exact archived M1d replay could not be authenticated or executed."""


@dataclass(frozen=True, slots=True)
class PinnedM1dReplayResult:
    commit: str
    nodeid: str
    returncode: int
    output: str


def verify_m1d_protected_inputs(
    *,
    root: Path,
    expected: Mapping[str, str] | None = None,
) -> None: ...


def is_pinned_m1d_node(nodeid: str) -> bool: ...


def run_archived_m1d_node(nodeid: str) -> PinnedM1dReplayResult: ...


class PinnedM1dArchiveCache:
    root: Path

    def close(self) -> None: ...
```

`PINNED_M1D_COMMIT` is the literal full `af75cce0f763de025f8ae3516577a9d0a1acead9`.
The protected JSON records literal SHA-256 values for all 62 Python source files
and all 480 M1d v1/v2/v3 fixture files at that commit, plus `pyproject.toml` and
`uv.lock`. Generate it once from the pinned commit, review it, and never derive
expected digests from the mutable working tree.

`tests/conftest.py` preserves the existing M1c hook and additionally routes every
node from `tests/integration/test_m1d_adversarial_matrix.py` plus
`test_m1d_compatibility.py::test_c02_current_code_composes_m1c_into_fixture_only_m1d_replay`
through the authenticated archived tree. The child receives an exact
`PYTHONPATH` for the archive, `PYTHONNOUSERSITE=1`,
`PYTHONDONTWRITEBYTECODE=1`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, no inherited
`PYTEST_ADDOPTS`, no cache provider, and a recursion marker. It verifies
`drift.__file__` is inside the archive before running the identical selected
node. Child failure is parent failure.

Revise the current C03 assertion to protect the exact 14 accepted M1d runtime
additions and all older source bytes instead of asserting that the repository
can never add a fifteenth source file. The new M1e compatibility gate separately
inventories every allowed M1e addition. Do not weaken the forbidden
import/dynamic-execution checks for old M1d source.

Create `test_m1e_compatibility.py` now with a literal allowlist of every M1e
source and script path in section 2. At every intermediate task it requires all
new source paths to be a subset of that list, scans present M1e production
modules for forbidden network/process/evaluator/trading imports and definitions,
protects all `af75cce` source/fixture bytes, and requires unchanged
`pyproject.toml`/`uv.lock`. Scripts receive separate narrow rules: no acquisition
network or credential read exists before Task 8, and only
`scripts/acquire_m1e_pilot.py` may contain the eventual authorized boundary.

- [x] **Step 1: Capture meaningful RED evidence without modifying the checkout**

Create a temporary `git archive` of `af75cce`, add one harmless Python file only
inside that temporary archive, and run the v3 exact replay node with that archive
first on `PYTHONPATH`.

```text
Expected: FAIL because the whole-package M1d implementation fingerprint changes.
```

- [x] **Step 2: Write the pinned-lane tests**

Tests must fail because `_pinned_m1d.py` and the literal inventory do not yet
exist. Add attacks for a changed source byte, changed v3 byte, re-signed index,
wrong commit, missing node, new/renamed test definition, inherited current
package import, and archived-child failure.

- [x] **Step 3: Implement authenticated archived execution**

Use bounded `git archive` extraction into `TemporaryDirectory`, reject absolute
or parent-traversing tar members, and cache one archive per parent pytest
session. Do not copy current imported Drift objects into the child.

- [x] **Step 4: Run focused GREEN and compatibility**

```text
uv run pytest tests/integration/test_m1d_pinned_replay.py tests/integration/test_m1d_compatibility.py tests/integration/test_m1d_adversarial_matrix.py tests/integration/test_m1c_pinned_replay.py -q
```

Expected: archived v3 executes, v1/v2 and M1c archived replay remain green, and
the current checkout contains no M1e production source.

- [x] **Step 5: Fresh compatibility review and full gate**

Terra implements. A fresh Sol reviewer checks archive authentication, exact-node
routing, no fake PASS/skip, no fixture rebinding, and current-suite coverage.
Fix all genuine Important/Critical findings. Run the repository full gate once.

- [x] **Step 6: Commit and Checkpoint**

Stage only the six Task 1 paths and commit:

```text
test: pin accepted M1d v3 replay
```

Run Checkpoint. Do not begin Task 2 unless Task 1 is accepted.

### Task 2: Add purpose-specific profiles, dimension results, and pilot lifecycle

**Files:**

- Create: `src/drift/domain/qualification.py`
- Create: `src/drift/qualification/__init__.py`
- Create: `src/drift/qualification/lifecycle.py`
- Create: `tests/unit/test_qualification_contracts.py`
- Create: `tests/unit/test_m1e_lifecycle.py`

**Interfaces and exact values:**

```python
class ConsumerPurpose(StrEnum):
    HISTORICAL_DECISION_INPUT = "historical_decision_input"
    RETROSPECTIVE_AUDIT = "retrospective_audit"


class QualificationStatus(StrEnum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    UNKNOWN = "unknown"


class ExecutionReachability(StrEnum):
    REACHED = "reached"
    NOT_REACHED = "not_reached"


class AcquisitionState(StrEnum):
    NOT_ACQUIRED = "not_acquired"
    ACQUIRED_UNSNAPSHOTTED = "acquired_unsnapshotted"
    SNAPSHOT_BOUND = "snapshot_bound"


class PilotStage(StrEnum):
    PROFILE_FROZEN = "profile_frozen"
    RIGHTS_ASSESSED = "rights_assessed"
    ACQUISITION_AUTHORIZED = "acquisition_authorized"
    ACQUIRED = "acquired"
    SNAPSHOT_FROZEN = "snapshot_frozen"
    QUALIFIED = "qualified"
    REPLAY_AUTHORIZED = "replay_authorized"
    REPLAYED = "replayed"
    COMPLETED_POSITIVE = "completed_positive"
    COMPLETED_NEGATIVE = "completed_negative"
```

`QualificationDimension` has exactly the 12 design values:
`security_listing_identity`, `universe_lifecycle`, `corporate_action_terms`,
`occurred_effects`, `settlements_terminal_outcomes`,
`observations_methodologies`, `scheduled_realized_sessions`,
`revisions_point_in_time`, `coverage_omission`, `licensing_retention`,
`acquisition_snapshot`, and `offline_replay`.

Persist these models:

- `ProviderProductScopeV1`: provider legal name/ID, product and dataset IDs,
  publishers, declared fields, methodology references, and schema references.
- `SubscriberUseScopeV1`: subscriber legal entity, one authorized user, requested
  model-development/trading-support uses, provider classification label or
  unresolved status, and classification evidence hashes.
- `InfrastructureScopeV1`: machine identity, user IDs, contractors, shared
  account, real-data CI, cloud, service providers, private-store policy hash,
  and backup locations.
- `QualificationDataScopeV1`: US daily-equity scope, explicit security/universe
  selection, inclusive dates, requested fields, revision cutoff, maximum 100
  securities, maximum two continuous years, maximum 20 event windows, and
  maximum 20 sessions on either side of an event.
- `QualificationProfileV1`: one immutable provider/subscriber/infrastructure/data
  scope, one consumer purpose, critical dimensions, required golden-case IDs,
  frozen `GoldenCaseInstanceManifestV1` hash, adjudication-policy hash, ID, and
  version. It has no snapshot field.
- `PilotProfileSetV1`: one pilot ID/version and exactly two profiles whose
  provider, subscriber, infrastructure, data, policy, and case scopes match;
  their purposes are exactly the two `ConsumerPurpose` values.
- `QualificationTargetV1`: profile hash, `AcquisitionState`, receipt hashes,
  optional snapshot hash, and failure evidence. `NOT_ACQUIRED` has no receipts
  or snapshot; `ACQUIRED_UNSNAPSHOTTED` requires receipts, no snapshot, and a
  blocker; `SNAPSHOT_BOUND` requires receipts and one snapshot.
- `DimensionQualificationResultV1`: one dimension, one purpose, status,
  reachability, evidence hashes, tested golden-case IDs, admitted-purpose flag,
  limitations, and adjudication-policy hash.
- `PreReplayQualificationReportV1`: a snapshot-bound target and exact 11-result
  tuple containing every dimension except `offline_replay`. This is the only
  qualification report admitted into a replay request.
- `PurposeQualificationReportV1`: the final target and exact 12-result tuple,
  report ID/version/time, and pre-replay report hash when replay was reached.
  A replay result adds the twelfth dimension; the final report is never a replay
  input.
- `ExternalDependencyResolutionV1`: dependency kind, responsible party,
  `PENDING`, `SATISFIED`, `DECLINED`, `WITHDRAWN`, `INQUIRY_EXHAUSTED`, or
  `UNAVAILABLE`, evidence, decision time, and limitations. Only `PENDING` pauses;
  an evidence-backed terminal state may block negative completion.
- `PreProfileAttemptRecordV1`: attempted candidate discovery, terminal external
  evidence, reasons, and `ABANDONED_PRE_PROFILE`. It is not an M1e completion
  record and carries no profile, purpose result, or provider-wide conclusion.
- `ContentDispositionRecordV1`: exact content/backup hash, contractual duty,
  `RETAINED`, `DELETED`, `CERTIFIED_DELETED`, or `PENDING`, evidence, and time.
  An unresolved mandatory disposition prevents terminal completion.
- `PurposeStageStateV1`: one profile hash, exact stage, ordered reached-stage
  artifact hashes, and optional terminal blocker.
- `M1ePilotStateV1`, `M1eTransitionV1`, and `M1eCompletionRecordV1`: profile-set
  hash, exactly two purpose stage states, shared artifact hashes, optional
  blocking dimensions/evidence, purpose reports, content dispositions,
  completion kind, and no vendor-wide status.

```python
def qualification_profile_hash(
    profile: QualificationProfileV1,
) -> SHA256Hash: ...


def transition_pilot(
    state: M1ePilotStateV1,
    transition: M1eTransitionV1,
) -> M1ePilotStateV1: ...


def build_negative_report(
    target: QualificationTargetV1,
    reached_results: tuple[DimensionQualificationResultV1, ...],
    blocker_dimension: QualificationDimension,
) -> PurposeQualificationReportV1: ...
```

Task 2 does not expose terminal pilot completion. Task 7 adds one unified
finalizer only after typed replay results exist. Negative reports preserve genuine PASS/PARTIAL results,
records later dimensions as `UNKNOWN` plus `NOT_REACHED`, and never invents a
receipt, snapshot, mapping, or replay output. It also rejects `PENDING` mandatory
content dispositions and a `PENDING` external dependency offered as terminal
evidence.

The transition table is normative. Each row applies independently to one
purpose profile; shared receipts may advance only profiles named by the exact
authorization. No other edge is valid.

| From | To | Required evidence guard |
|---|---|---|
| initial | `PROFILE_FROZEN` | matching `PilotProfileSetV1`, exact purpose profile, frozen golden-case instance manifest, no receipt/snapshot |
| `PROFILE_FROZEN` | `RIGHTS_ASSESSED` | current `ValidatedRightsAssessment` for the exact profile with complete hash-resolved contract-topology evidence |
| `RIGHTS_ASSESSED` | `ACQUISITION_AUTHORIZED` | profile named by `AcquisitionEligibilityV1`, external `AcquisitionApprovalV1`, and resulting authorization |
| `ACQUISITION_AUTHORIZED` | `ACQUIRED` | pre-request `AcquisitionPlanV1`, receipt, native byte graph, and reconciliation result; failed/unknown completeness may only enter negative completion |
| `ACQUIRED` | `SNAPSHOT_FROZEN` | `SNAPSHOT_BOUND` target, exact receipts, validated candidate contexts, consistency decision, replay inputs, expected M1b-M1d outputs, and snapshot |
| `SNAPSHOT_FROZEN` | `QUALIFIED` | exact golden-case results and `PreReplayQualificationReportV1` for the profile |
| `QUALIFIED` | `REPLAY_AUTHORIZED` | new current `ReplayAuthorizationDecisionV1` with `AUTHORIZED` status |
| `REPLAY_AUTHORIZED` | `REPLAYED` | `ReplayExecutionRecordV1`, post-run offline/fresh attestations, and finalized `ReplayResultV1` |
| `REPLAYED` | `COMPLETED_POSITIVE` | typed verified `MATCH`, final 12-dimension report with every critical dimension PASS, and all mandatory content dispositions resolved |
| any reached nonterminal stage after `PROFILE_FROZEN` | `COMPLETED_NEGATIVE` through the Task 7 finalizer | exact blocker or terminal external-dependency record, truthful reached/not-reached results, lawful retained/deleted inventory, and no pending mandatory disposition |

Prohibited skips, regressions, repeated terminal transitions, purpose/hash
substitution, and an acquisition artifact applied to an unauthorized sibling
profile raise `ValueError`. `PENDING` external evidence is not a transition.
`transition_pilot` cannot construct either terminal state; the Task 7 finalizer
does so only after verifying both purpose bundles.

- [x] **Step 1: Write contract RED tests**

Add dump/load, canonical hash, ordering, duplication, bound-size, and mutation
tests. Assert that one purpose's PASS cannot authorize the other, a pre-replay
report contains exactly 11 non-replay dimensions, a final report contains all
12, and a profile cannot contain delivered-byte identity.

- [x] **Step 2: Write lifecycle RED tests**

Table-test every legal transition and every prohibited skip/backtrack. Include
rights-negative before acquisition, acquired-unsnapshotted negative,
semantics-negative, terminal external evidence, and a rejected attempt to claim
positive completion without the later typed replay API. Tests initially fail
because the models and state functions do not exist.

- [x] **Step 3: Implement minimal frozen contracts and transitions**

Implement only the types and pure functions above. Do not import provider,
network, evaluator, ledger, or storage code. Do not add a generic score.

- [x] **Step 4: Run focused GREEN**

```text
uv run pytest tests/unit/test_qualification_contracts.py tests/unit/test_m1e_lifecycle.py tests/unit/test_canonical_serialization.py -q
```

- [x] **Step 5: Fresh lifecycle/adversarial review and full gate**

Sol owns the difficult implementation. A fresh Sol reviewer attacks purpose
confusion, fake reachability, missing dimensions, invented negative outputs,
critical non-PASS positive completion, and vendor-wide generalization. Fix all
genuine Important/Critical findings, then run the full repository gate once.

- [x] **Step 6: Commit and Checkpoint**

Stage only Task 2 paths and the accurate execution-record update. Commit:

```text
feat: add M1e qualification lifecycle
```

Run Checkpoint, then continue to Task 3 when no external evidence is needed.

### Task 3: Add rights topology and separate acquisition/replay authorization

**Files:**

- Create: `src/drift/domain/rights.py`
- Create: `src/drift/qualification/rights.py`
- Create: `tests/unit/test_rights_assessment.py`
- Create: `tests/unit/test_replay_authorization.py`

**Interfaces and ownership:**

```python
class RightsDisposition(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    UNKNOWN = "unknown"


class AuthorizationStatus(StrEnum):
    AUTHORIZED = "authorized"
    DENIED = "denied"
    UNKNOWN = "unknown"


class EntitlementState(StrEnum):
    ACTIVE = "active"
    TERMINATED = "terminated"
    EXPIRED = "expired"
    UNKNOWN = "unknown"
```

`RightsQuestion` is closed over these exact questions:

```text
internal_automated_research
display_use
non_display_use
model_development
future_trading_support
local_storage
private_git_storage
real_data_ci
cloud_processing
third_party_service_access
backup_storage
raw_byte_retention
post_subscription_raw_use
normalized_row_retention
derived_artifact_retention
model_parameter_retention
metric_report_retention
private_fixture_use
public_fixture_use
publication
redistribution
deletion_and_certification
upstream_publisher_restrictions
```

Persist these models:

- `LegalPartyV1`: exact legal name, role, jurisdiction or explicit unknown, and
  evidence references.
- `UseClassificationV1`: provider-defined classification label, status, exact
  definition evidence, assessed use, and no Drift-invented professional/display
  classification.
- `AuthorizedUserV1` and `ServiceProviderScopeV1`: stable nonsensitive IDs,
  access purpose, and evidence. Do not place personal contact data in canonical
  records.
- `ContractDocumentNodeV1`: node ID, document kind, title, version, effective and
  expiry bounds, exact `ArtifactReference`, publisher/party IDs, assent/signature
  evidence, confidentiality class, and applicability status.
- `ContractPrecedenceEdgeV1`: controlling node, subordinate/incorporated node,
  relationship, and exact precedence evidence.
- `ContractTopologyV1`: complete nodes/edges, root agreement IDs, topology
  version, assessed product/publisher scope, and missing-node declarations.
- `RightsAnswerV1`: one `RightsQuestion`, `RightsDisposition`, exact controlling
  node/evidence hashes, scope, validity bounds, limitations, and adjudicator
  identity. Marketing copy alone cannot produce `ALLOWED`.
- `ContentRightsPolicyV1`: prospective provider contractual class/object scope,
  controlling provisions, purposes, users, locations, retention horizon,
  termination/deletion/certification duty, backup rule, and policy hash. It has
  no future content hash or reverse assessment reference.
- `ContentRightsBindingV1`: one later content hash, applicable
  `ContentRightsPolicyV1` hash, provider contractual class,
  controlling provisions, purposes, users, locations, retention horizon,
  termination/deletion/certification duty, backup rule, and frozen assessment hash.
  `DatasetKind` is never used as a legal classification.
- `RightsAssessmentV1`: one profile hash, topology hash, assessment/validity
  times, entitlement state, all required answers, notice evidence, prospective
  content-rights policies, reassessment triggers, policy
  hash, assessor identity, and result per consumer purpose. It does not contain
  resulting `ContentRightsBindingV1` values; those are created only after the
  assessment hash and content bytes exist.
- `RightsEvidenceContext`: exact `ContractTopologyV1`, hash-resolved contract,
  assent, amendment, schedule, policy, notice, classification, and adjudication
  `VerifiedArtifactBytes`.
- `ValidatedRightsAssessment`: runtime pair of the exact assessment, profile,
  topology, and verified evidence snapshot. Only this wrapper enters eligibility.
- `AcquisitionEligibilityV1`: profile-set hash, assessment hashes, exact eligible,
  denied, and unresolved profile hashes, product/scope, validity bounds, private-
  store policy hash, reasons, and policy identity. It is a rights result, not
  user approval.
- `AcquisitionApprovalV1`: exact eligibility hash and approved profile/product/
  request scope, approval evidence, authorizer identity, decision time, expiry,
  and explicit no-purchase/no-terms-acceptance boundaries.
- `ApprovalEvidenceContext`: hash-resolved approval evidence bytes, authorizer
  scope, and exact decision/expiry evidence.
- `AcquisitionAuthorizationV1`: exact eligibility and approval hashes,
  authorized profile hashes, product/request scope, time bounds, private-store
  policy hash, status, reasons, and authorization identity.
- `ReplayAuthorizationRequestV1`: purpose-profile hash, snapshot hash,
  environment-closure hash, requested users/infrastructure, current time,
  current entitlement/termination/notice evidence, and replay purpose.
- `ReplayAuthorizationDecisionV1`: request hash, new assessment hash,
  `AuthorizationStatus`, evidence, reasons, policy hash, decision ID, and
  decision time. It is never inferred from acquisition authorization.
- `ReplayAuthorizationEvidenceContext`: hash-resolved current contract,
  entitlement, termination, notice, user/infrastructure, request, and decision
  evidence. It is snapshotted independently for each purpose.

Runtime verification bundles keep every authority referent available:

```python
@dataclass(frozen=True, slots=True)
class AcquisitionAuthorizationVerificationBundle:
    profiles: PilotProfileSetV1
    assessments: tuple[ValidatedRightsAssessment, ...]
    eligibility: AcquisitionEligibilityV1
    approval: AcquisitionApprovalV1
    approval_evidence: ApprovalEvidenceContext
    authorization: AcquisitionAuthorizationV1


@dataclass(frozen=True, slots=True)
class ReplayAuthorizationVerificationBundle:
    request: ReplayAuthorizationRequestV1
    decision: ReplayAuthorizationDecisionV1
    current_assessment: ValidatedRightsAssessment
    profile: QualificationProfileV1
    evidence: ReplayAuthorizationEvidenceContext
```

```python
def validate_contract_topology(
    topology: ContractTopologyV1,
) -> tuple[ValidationFindingV1, ...]: ...


def validate_rights_assessment(
    profile: QualificationProfileV1,
    assessment: RightsAssessmentV1,
    evidence: RightsEvidenceContext,
) -> ValidatedRightsAssessment: ...


def assess_acquisition_eligibility(
    profiles: PilotProfileSetV1,
    assessments: tuple[ValidatedRightsAssessment, ...],
) -> AcquisitionEligibilityV1: ...


def authorize_acquisition(
    eligibility: AcquisitionEligibilityV1,
    approval: AcquisitionApprovalV1,
    evidence: ApprovalEvidenceContext,
) -> AcquisitionAuthorizationV1: ...


def verify_acquisition_authorization(
    bundle: AcquisitionAuthorizationVerificationBundle,
) -> None: ...


def verify_replay_authorization(
    bundle: ReplayAuthorizationVerificationBundle,
) -> None: ...
```

The functions verify consistency of externally supplied human/legal
adjudications. No function converts provider marketing, account access, a
download, missing bytes, or a syntactically valid hash into `ALLOWED`.
Every topology, answer, assent, notice, and approval reference is resolved and
hash-verified before authority is returned. Eligibility evaluates each purpose
profile independently. Authorization additionally requires the externally
supplied approval; rights `ALLOWED` alone is never acquisition authority. A
shared acquisition may proceed only if at least one profile explicitly permits
that acquisition/retention scope; bytes cannot be used for a denied sibling
purpose. Replay performs a new purpose-specific decision using current
entitlement and notices.

- [x] **Step 1: Write contract-topology RED tests**

Cover duplicate/cyclic precedence, missing incorporated agreement, unknown
applicability, unmatched product/publisher, absent assent, confidential evidence
in a public reference, acyclic construction of assessment then per-object rights
binding, and a complete lawful synthetic topology. A missing
applicable node forces the affected answer to `UNKNOWN`.

- [x] **Step 2: Write rights and authorization RED tests**

Cover unresolved classification, marketing-only claims, denied raw retention,
denied backup, post-term deletion, purpose mismatch, unauthorized service
provider, expired validity, changed users/infrastructure, new termination
notice, nonexistent/mismatched contract or approval evidence hashes, and replay
using only an old acquisition-time PASS.

- [x] **Step 3: Implement validation without legal inference**

Implement the models and pure validators. The only route to `ALLOWED` is an
explicit `RightsAnswerV1` with complete applicable contract evidence and the
exact requested scope. Preserve `DENIED` and `UNKNOWN` independently.

- [x] **Step 4: Run focused GREEN**

```text
uv run pytest tests/unit/test_rights_assessment.py tests/unit/test_replay_authorization.py tests/unit/test_provenance_references.py -q
```

- [x] **Step 5: Independent rights review and full gate**

A fresh Sol reviewer owns licensing/negative-completion review. Verify contract
topology closure, current authorization, per-object rights, purpose separation,
and that confidential evidence cannot leak into Git-facing records. Fix genuine
Important/Critical findings, then run the full repository gate once.

- [x] **Step 6: Commit and Checkpoint**

Stage only Task 3 files plus the execution-record update. Commit:

```text
feat: gate M1e data rights
```

Run Checkpoint. No provider or user is classified by these synthetic tests.

### Task 4: Add exact acquisition receipts, closed-world reconciliation, and private storage

**Files:**

- Create: `src/drift/domain/acquisition.py`
- Create: `src/drift/qualification/acquisition.py`
- Create: `src/drift/qualification/store.py`
- Create: `tests/unit/test_acquisition_receipts.py`
- Create: `tests/unit/test_acquisition_reconciliation.py`
- Create: `tests/unit/test_private_content_store.py`

**Byte and acquisition contracts:**

```python
class ByteLayerKind(StrEnum):
    TRANSPORT_ENTITY = "transport_entity"
    STORED_ARCHIVE_OR_FILE = "stored_archive_or_file"
    DECOMPRESSED_PAYLOAD = "decompressed_payload"
    ARCHIVE_MEMBER = "archive_member"
    DECODED_PROVIDER_NATIVE_RECORD = "decoded_provider_native_record"
    DRIFT_CANONICAL_RECORD = "drift_canonical_record"


class AcquisitionCompleteness(StrEnum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    UNKNOWN = "unknown"


class OriginStatus(StrEnum):
    VERIFIED = "verified"
    UNKNOWN = "unknown"
```

Persist these models:

- `ByteObjectV1`: layer, `ArtifactReference`, exact length/hash/media type,
  content encoding, archive/member identity, and object descriptor hash. Two
  layers with equal bytes still have distinct descriptor hashes.
- `ByteTransformationV1`: input and output `ByteObjectV1` descriptor hashes,
  closed operation, tool/source implementation hash, parameters, and
  lossless/lossy declaration.
- `NativeByteGraphV1`: all byte objects and transformations, retained
  transport/published roots, provider-native leaves, graph hash, and proof of a
  complete acyclic lineage. Bare content hashes are not graph edges.
- `ProviderNativeLayerRuleV1`: profile-set hash, exact supported profile hashes,
  product/schema/methodology
  hashes, authoritative native layer, and exclusions. The provider-native layer
  is product-specific and always precedes Drift normalization.
- `RequestIdentityV1`: credential-free method, authenticated provider host,
  route template, canonical parameters, requested fields/universe/dates/cutoff,
  request start/end, and client request ID. Provider response/object IDs belong
  to page/object origin evidence. It stores no headers or values outside an
  explicit safe allowlist.
- `OriginEvidenceV1`: origin status, request/object IDs, safe response metadata,
  TLS endpoint identity when retained, provider checksums/signatures/manifests,
  and exact evidence references. A local hash alone leaves origin `UNKNOWN`.
- `PageReceiptV1` and `RetryReceiptV1`: page/file identity, order, cursor in/out,
  byte-object descriptor hashes, attempt identity, result, duplicates, and
  failure evidence.
- `ExpectedObjectV1` and `ExpectedInventoryV1`: exact product objects/endpoints,
  as-of universe rule, fields, dates, partitions, expected keys/counts, source of
  enumeration, and justification. Unknown closed-world scope cannot pass.
- `AcquisitionPlanV1`: exact authorization hash, credential-free request scope,
  expected-inventory hash, planned native-layer rule hash, maximum byte/object/
  page counts, frozen time, and plan hash. It exists before the first request.
  If inventory enumeration itself needs provider access, that discovery is a
  separately authorized and receipted acquisition plan whose observed output
  cannot silently become the final expected inventory.
- `ObservedObjectV1`: expected key if matched, provider object identity, page,
  byte objects, origin evidence, and observation status.
- `AcquisitionReconciliationV1`: expected/received/missing/duplicate/extra keys,
  cursor-cycle evidence, count reconciliation, snapshot-token consistency,
  result, and reasons.
- `AcquisitionReceiptV1`: acquisition plan/authorization/profile-set hashes,
  request, native-layer rule, complete byte-graph hash, pages, retries, observed
  objects, expected inventory and reconciliation hashes, schema/methodology/
  license evidence, collector source/version hash, receipt ID/version, and time.
  `AcquisitionPlanV1.frozen_at <= RequestIdentityV1.request_start` is mandatory.
- `AcquisitionExecutionContextV1`: collector ID/version/source hash, invocation
  ID, exact executable evidence, receipt UUID/version/creation time, and safe
  execution metadata. No builder reads these from hidden filesystem or global
  state.
- `PrivateStorePolicyV1`: approved root identifier, access-control/encryption
  evidence hashes, allowed object classes, backup locations, maximum object and
  total pilot bytes, and policy version. The physical root path is excluded.
- `PrivateStoreInventoryV1`: pilot ID, committed transaction IDs, object and
  descriptor hashes, cumulative unique bytes, quota, inventory version, and
  inventory hash.
- `StoredContentObjectV1`: content hash, byte size, safe `drift+sha256` reference,
  rights-binding hash, object class, and store-policy hash.

`PrivateStoreSession` is a noncanonical runtime object holding the resolved
`Path`, externally approved root-binding evidence, policy, and an exclusive
`fcntl` inventory lock. It verifies that the supplied path matches the approved
operational binding without adding that path to scientific identity.

```python
def validate_secret_free_acquisition_payload(value: object) -> None: ...


def reconcile_acquisition(
    expected: ExpectedInventoryV1,
    pages: tuple[PageReceiptV1, ...],
    observed: tuple[ObservedObjectV1, ...],
) -> AcquisitionReconciliationV1: ...


def build_acquisition_receipt(
    plan: AcquisitionPlanV1,
    authorization: AcquisitionAuthorizationV1,
    request: RequestIdentityV1,
    native_layer_rule: ProviderNativeLayerRuleV1,
    byte_graph: NativeByteGraphV1,
    pages: tuple[PageReceiptV1, ...],
    retries: tuple[RetryReceiptV1, ...],
    observed: tuple[ObservedObjectV1, ...],
    expected: ExpectedInventoryV1,
    reconciliation: AcquisitionReconciliationV1,
    execution: AcquisitionExecutionContextV1,
) -> AcquisitionReceiptV1: ...


def verify_acquisition_receipt(
    receipt: AcquisitionReceiptV1,
    artifacts: Mapping[str, VerifiedArtifactBytes],
) -> None: ...


def store_content_object(
    session: PrivateStoreSession,
    artifact: VerifiedArtifactBytes,
    rights_binding: ContentRightsBindingV1,
) -> StoredContentObjectV1: ...


def read_content_object(
    session: PrivateStoreSession,
    stored: StoredContentObjectV1,
    limits: ResolverLimits,
) -> VerifiedArtifactBytes: ...
```

The private layout is fixed and location-neutral:

```text
<approved-root>/objects/sha256/<first-two>/<sha256>
<approved-root>/object-rights/<sha256>/<rights-binding-hash>.json
<approved-root>/descriptors/<kind>/<descriptor-hash>.json
<approved-root>/attempts/<pilot-id>/<attempt-id>.json
<approved-root>/inventories/<pilot-id>/current.json
<approved-root>/locks/<pilot-id>.lock
<approved-root>/transactions/<pilot-id>/<transaction-id>/manifest.json
<approved-root>/transactions/<pilot-id>/<transaction-id>/COMMITTED
<approved-root>/quarantine/<pilot-id>/<transaction-id>/manifest.json
<approved-root>/dispositions/<content-hash>/<disposition-hash>.json
```

Writes are root-confined, no-follow, `0600`, locked, fsynced, and re-read for
hash verification. A transaction writes/fsyncs temporary object, rights,
descriptor, and manifest files; renames the components; fsyncs their
directories; and publishes a commit marker last. Readers accept only committed
transactions and verify every component. Recovery quarantines incomplete
transactions and records `PENDING` disposition instead of deleting them
automatically. Existing objects are never overwritten; equal hashes reuse bytes
only after the existing object and rights transaction verify. The locked
inventory enforces the cumulative pilot quota. Encryption is an externally
evidenced storage-control precondition, not a new encryption implementation.

- [ ] **Step 1: Write acquisition RED matrix**

Cover missing page/object, duplicate page, conflicting duplicate, cursor loop,
reordering, exact retry, partial endpoint success, changed object under one URL,
missing origin proof, incomplete expected inventory, inconsistent snapshot token,
and archive/member/decompressed-byte conflation.

Expected dispositions are fixed: missing expected content or cursor cycle is
`FAIL`; lack of an authoritative closed-world inventory or origin is `UNKNOWN`;
an exact declared retry may reconcile; result ordering remains receipt identity
even when a separate set-equivalence check succeeds.

| Condition | Acquisition result | Required record |
|---|---|---|
| expected inventory absent, unjustified, or not frozen before request | `UNKNOWN` | missing/freeze evidence and no completeness claim |
| acquisition plan frozen after request start or scope differs | `FAIL` | plan/request mismatch |
| any expected key/page/object missing | `FAIL` | exact missing set |
| extra object outside authorized request scope | `FAIL` | exact extra set and rights disposition |
| exact duplicate caused by a declared retry, identical descriptor graph | may `PASS` | both attempts and retry link retained |
| duplicate page without retry identity, or conflicting duplicate bytes | `FAIL` | duplicate/conflict set |
| cursor loop, discontinuity, or inconsistent terminal marker | `FAIL` | complete cursor chain |
| all expected objects present in different response order | completeness may `PASS`; receipt identity changes | native order plus separate set-equivalence decision |
| endpoint reports partial success and any expected object is unresolved | `FAIL`; `UNKNOWN` if expected scope itself is unknown | response and missing-scope evidence |
| authenticated/provider origin missing | `UNKNOWN` | local hashes retained without origin PASS |
| shared snapshot/release token conflicts | `FAIL` | conflicting tokens and affected objects |
| token absent where product gives no other consistency proof | `UNKNOWN` | explicit absence and methodology evidence |
| provider count conflicts with received inventory | `FAIL` | expected/observed counts |
| provider count absent but independent closed-world inventory reconciles | may `PASS` | independent enumeration evidence |
| byte graph has missing root/leaf, cycle, ambiguous layer, or undeclared transform | `FAIL` | rejected graph and findings |
| failed retries followed by exact complete final acquisition | may `PASS` | all attempts retained; no failed bytes treated as source |

- [ ] **Step 2: Write secret and store RED tests**

Reject API-key/token/signature parameters, authorization/cookie headers,
userinfo, bearer/basic credentials, signed URLs, and credential-bearing errors.
Attack absolute paths, parent traversal, symlinks, FIFOs, oversize content,
wrong existing bytes, permission widening, wrong approved-root binding,
cumulative quota races, and a crash before each component rename, commit marker,
or inventory update. Readers reject uncommitted transactions; recovery produces
quarantine plus `PENDING` disposition, never silent deletion.

- [ ] **Step 3: Implement minimal receipt, reconciliation, and store behavior**

Terra may implement these bounded mechanical contracts. Reuse
`VerifiedArtifactBytes`, `ResolverLimits`, safe provenance-reference checks, and
canonical hashing. Do not add a network client, provider SDK, database, or
default store root.

- [ ] **Step 4: Run focused GREEN**

```text
uv run pytest tests/unit/test_acquisition_receipts.py tests/unit/test_acquisition_reconciliation.py tests/unit/test_private_content_store.py tests/unit/test_dataset_resolver.py tests/unit/test_manifest_v2.py -q
```

- [ ] **Step 5: Independent acquisition review and full gate**

A fresh Sol reviewer attacks closed-world completeness, byte-layer identity,
origin claims, retry/order semantics, path confinement, atomicity, and rights
association. Fix all genuine Important/Critical findings, then run the full
repository gate once.

- [ ] **Step 6: Commit and Checkpoint**

Stage only Task 4 files and the execution-record update. Commit:

```text
feat: bind exact M1e acquisition evidence
```

Run Checkpoint. No provider access occurs in this task.

### Task 5: Freeze exact real-source snapshots and replay-input closure

**Files:**

- Create: `src/drift/domain/source_snapshots.py`
- Create: `src/drift/qualification/snapshots.py`
- Create: `tests/unit/test_source_snapshots.py`
- Create: `tests/unit/test_cross_component_consistency.py`

**Interfaces and models:**

```python
class SourceComponentRole(StrEnum):
    IDENTITY_UNIVERSE = "identity_universe"
    ACTION_TERMS = "action_terms"
    OCCURRED_EFFECTS = "occurred_effects"
    SETTLEMENT_OUTCOMES = "settlement_outcomes"
    OBSERVATIONS = "observations"
    SCHEDULED_SESSIONS = "scheduled_sessions"
    REALIZED_SESSIONS = "realized_sessions"
    GRADING_TRUTH = "grading_truth"


class ConsistencyStatus(StrEnum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    UNKNOWN = "unknown"
```

`ReplayInputKind` closes over exact native artifacts, grading evidence,
methodology/schema, rights, manifests, validation run/decision/bundle, M1a
availability evidence/policy, M1b queries/contexts/results, M1c
queries/policies/contexts/results, M1d queries/policies/contexts/results, adapter
mapping, and qualification policy. `ExpectedOutputKind` closes over selected
source records, M1b resolution, M1c outcome/reference, and M1d
schedule/mapping/derivation/view/reference. Qualification reports and
limitations are later replay-closure inputs, not source-snapshot outputs.

Persist:

- `ProviderReleaseEvidenceV1`: component role, provider release/object IDs,
  native state label, exact/bounded/unknown `TemporalBoundaryClaimV1`, M1a
  availability-evidence hashes, acquisition receipt hash, and evidence
  references. It never invents UTC precision absent from the source.
- `CoordinatedCutoffRuleV1`: profile-set hash, per-component cutoff rule,
  revision horizon, ordering rule, semantic hash, and evidence.
- `CrossComponentConsistencyDecisionV1`: all component release hashes,
  coordinated-rule hash, result, conflicts/gaps, decision policy/hash, ID, and
  time. Merely hashing components together cannot produce PASS. Coordinated
  consistency evaluates exact/bounded overlap under the declared cutoff rule;
  it does not require fabricated timestamp equality.
- `RawReplayInputEntryV1`: discriminator `raw_bytes`, kind, exact artifact
  hash/reference, `ByteObjectV1` descriptor hash, media/schema descriptors,
  purpose profile, component role, and rights binding; canonical model fields
  are forbidden.
- `CanonicalReplayInputEntryV1`: discriminator `canonical_model`, kind, exact
  artifact hash/reference, canonical model type/version, purpose profile,
  component role, and original identity. Raw byte-layer fields are forbidden.
- `ReplayInputEntryV1`: discriminated union of those two entries. Original IDs
  and timestamps remain in canonical retained bytes.
- `ExpectedOutputV1`: kind, purpose profile, canonical output hash, semantic
  owner, query hash, input-context hash, and original identity.
- `RealSourceSnapshotV1`: profile-set hash, individual profile hashes, and the
  exact authorized-profile subset,
  rights-assessment hashes, receipt hashes, native/grading artifact hashes,
  release evidence, consistency decision, cutoff and coverage assertions,
  methodology/schema, adapter semantic/source hashes, existing manifests,
  validation decisions/bundles, M1a policy, complete replay inputs, expected
  outputs, snapshot ID/version/time, and self-excluding snapshot hash.

The adapter first maps authorized native inputs using one frozen profile. The
existing validators then produce the exact pre-evaluator records/results needed
to build `RealSourceSnapshotV1`. Only after the snapshot hash exists does
`QualificationTargetV1` bind each purpose profile to it. Dimension grading and
qualification reports occur after that target binding. The snapshot contains no
target hash or qualification-report hash, preventing an identity cycle.

```python
@dataclass(frozen=True, slots=True)
class ExistingContractContexts:
    m1b_contexts: tuple[StructuralResolutionContext, ...]
    m1c_context: EconomicResolutionContext
    m1d_context: M1dResolutionContext


def build_real_source_snapshot(
    profiles: PilotProfileSetV1,
    authorization: AcquisitionAuthorizationVerificationBundle,
    receipts: tuple[AcquisitionReceiptV1, ...],
    consistency: CrossComponentConsistencyDecisionV1,
    replay_inputs: tuple[ReplayInputEntryV1, ...],
    expected_outputs: tuple[ExpectedOutputV1, ...],
) -> RealSourceSnapshotV1: ...


def verify_real_source_snapshot(
    snapshot: RealSourceSnapshotV1,
    artifacts: Mapping[str, VerifiedArtifactBytes],
    contexts: ExistingContractContexts,
) -> None: ...
```

The verifier rebuilds existing validation decisions and bundles from exact bytes,
then invokes unchanged M1b/M1c/M1d public verification. It does not trust a
caller-supplied PASS or reconstruct a query from a digest. `DatasetManifestV2`,
`AcquisitionDescriptorV1`, and `LicenseDescriptorV1` continue to own dataset
lineage; the snapshot indexes, rather than replaces, those objects.

- [x] **Step 1: Write snapshot-identity RED tests**

Mutate rights, receipt ordering, one byte layer, release ID, source-state time,
cutoff rule, coverage, schema/methodology, adapter identity, validation decision,
query, context, grading evidence, limitation, and expected output. Every semantic
mutation changes identity or fails verification. Relocating the private root does
not.

- [x] **Step 2: Write consistency and closure RED tests**

Combine identity, actions, and observations from different uncoordinated
vintages. Assert `UNKNOWN` or `PARTIAL`, never PASS. Omit each replay input family
one at a time and assert closure rejection. A retained hash without retrievable
bytes cannot close replay.

- [x] **Step 3: Implement builder and verifier through old public APIs**

Do not modify or duplicate M1a-M1d query, context, decision, bundle, or reference
models. The verifier loads their exact canonical bytes and replays their existing
owners.

- [x] **Step 4: Run focused GREEN**

```text
uv run pytest tests/unit/test_source_snapshots.py tests/unit/test_cross_component_consistency.py tests/unit/test_temporal.py tests/unit/test_security_identity.py tests/unit/test_economic_outcomes.py tests/unit/test_normalization.py -q
```

- [x] **Step 5: Independent temporal/snapshot review and full gate**

Terra may implement plumbing. A fresh Sol reviewer attacks current-vintage
fallback, cross-component inconsistency, missing replay inputs, substituted old
contexts, location identity, and duplicate provenance. Fix genuine
Important/Critical findings, then run the full repository gate once.

- [x] **Step 6: Commit and Checkpoint**

Stage only Task 5 files and the execution-record update. Commit:

```text
feat: freeze M1e source snapshots
```

Run Checkpoint and continue to Task 6.

### Task 6: Add the provider-neutral adapter boundary, qualification harness, and golden cases

**Files:**

- Create: `src/drift/domain/qualification_adapters.py`
- Create: `src/drift/domain/golden_cases.py`
- Create: `src/drift/qualification/adapters.py`
- Create: `src/drift/qualification/golden_cases.py`
- Create: `src/drift/qualification/harness.py`
- Create: `scripts/intake_m1e_truth.py`
- Create: `tests/unit/test_qualification_adapter_boundary.py`
- Create: `tests/unit/test_golden_case_contracts.py`
- Create: `tests/unit/test_truth_evidence.py`
- Create: `tests/unit/test_qualification_harness.py`

**Adapter contracts:**

```python
class MappingDisposition(StrEnum):
    MAPPED = "mapped"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    CONFLICTING = "conflicting"


@dataclass(frozen=True, slots=True)
class QualificationAdapterInput:
    profile_set: PilotProfileSetV1
    receipts: tuple[AcquisitionReceiptV1, ...]
    acquisition_authority: AcquisitionAuthorizationVerificationBundle
    native_artifacts: Mapping[str, VerifiedArtifactBytes]
    methodology_artifacts: Mapping[str, VerifiedArtifactBytes]
    schema_artifacts: Mapping[str, VerifiedArtifactBytes]


@dataclass(frozen=True, slots=True)
class CandidateDatasetInput:
    manifest: DatasetManifestV2
    validation_run: ValidationRunContextV1
    artifacts: Mapping[str, VerifiedArtifactBytes]
    supporting_artifacts: Mapping[str, VerifiedArtifactBytes]
    blueprint_hash: SHA256Hash


@dataclass(frozen=True, slots=True)
class CandidateFactSet:
    blueprint: CandidateContextBlueprintV1
    m1b_datasets: tuple[CandidateDatasetInput, ...]
    m1c_datasets: tuple[CandidateDatasetInput, ...]
    m1d_datasets: tuple[CandidateDatasetInput, ...]
    mapping_report: ProviderMappingReportV1


@dataclass(frozen=True, slots=True)
class ValidatedCandidateFactSet:
    mapping_report: ProviderMappingReportV1
    validation_decisions: tuple[DatasetValidationDecisionV2, ...]
    bundles: tuple[ValidatedDatasetBundleV1, ...]
    records_by_role: Mapping[str, tuple[FrozenModel, ...]]
    contexts: ExistingContractContexts
```

Persist:

- `AdapterIdentityV1`: adapter ID/version, supported profile-set hash and exact
  supported profile hashes, provider/product/schema/methodology hashes,
  semantic-policy hash, and installed source hash.
- `NativeRecordReferenceV1`: exact provider-native byte and decoded-record hashes,
  native key/locator, byte-layer rule hash, and source availability evidence.
- `FieldMappingDecisionV1`: target Drift role/field, source native field/code,
  `MappingDisposition`, exact rule/evidence hashes, availability rule, lossy flag,
  limitations, and affected dimension.
- `EmittedRecordMappingV1`: one emitted canonical record hash, exact native
  record descriptor hashes, field-mapping decision hashes, declared one-to-one
  or one-to-many operation, and transformation evidence. Every emitted and
  consumed record is covered exactly once unless an explicit supported fan-out
  rule proves otherwise.
- `ProviderMappingReportV1`: adapter identity, profile-set/profile and receipt hashes,
  complete native-field inventory, all field decisions, retained unsupported
  values, emitted-record mappings, emitted candidate dataset hashes,
  native/emitted coverage reconciliation, limitations, and report hash.
- `CandidateRecordModel` closes over the ten M1b role/model pairs plus existing
  M1c economic, M1d observation, and M1d session unions. The M1b role names are
  `identity_assignment`, `identity_relationship`,
  `external_identifier_mapping`, `security_classification`, `listing_role`,
  `listing_lifecycle`, `listing_termination`, `listing_history_coverage`,
  `source_universe_definition`, and `universe_membership`.
- `CandidateContextBlueprintV1`: each dataset's role, closed record-model ID,
  partition-object hashes, supporting artifacts, validation-run hash, bundle
  group, M1b structural group, M1c identity/dataset group, M1d observation/
  session group, availability policy/evidence, source-selection policies, and
  all cross-context links. No caller-supplied context is trusted.
- `QualifiedSourceHandoffV1`: one purpose-specific completion/report/target,
  accepted M1b universe/resolution references, M1c outcome references, M1d
  observation/session/view references, missingness/usability, snapshot, rights,
  environment and replay identities, and limitations. It has no API client,
  provider cursor, raw adjusted dataframe, returns, or evaluator object.

```python
class QualificationAdapter(Protocol):
    identity: AdapterIdentityV1

    def map(self, value: QualificationAdapterInput) -> CandidateFactSet: ...


@dataclass(frozen=True, slots=True)
class CandidateValidationContext:
    profiles: PilotProfileSetV1
    receipts: tuple[AcquisitionReceiptV1, ...]
    acquisition_authority: AcquisitionAuthorizationVerificationBundle
    native_artifacts: Mapping[str, VerifiedArtifactBytes]
    adjudication_policy_artifacts: Mapping[str, VerifiedArtifactBytes]


@dataclass(frozen=True, slots=True)
class QualificationExecutionContext:
    validation: CandidateValidationContext
    validated_candidate: ValidatedCandidateFactSet
    snapshot: RealSourceSnapshotV1
    targets: tuple[QualificationTargetV1, ...]
    golden_case_plans: tuple[GoldenCasePlanV1, ...]
    golden_case_results: tuple[GoldenCaseResultV1, ...]
    grading_context: GoldenCaseGradingContext


def validate_candidate_facts(
    candidate: CandidateFactSet,
    context: CandidateValidationContext,
) -> ValidatedCandidateFactSet: ...


def qualify_source(
    target: QualificationTargetV1,
    adapter: QualificationAdapter,
    context: QualificationExecutionContext,
) -> PreReplayQualificationReportV1: ...


def verify_qualification_report(
    report: PreReplayQualificationReportV1,
    adapter: QualificationAdapter,
    context: QualificationExecutionContext,
) -> None: ...
```

`validate_candidate_facts` dispatches by existing `DatasetRoleV1` to unchanged
`validate_identity_dataset`, `validate_economic_dataset`,
`validate_observation_dataset`, and `validate_session_dataset`, then constructs
the exact existing M1b, M1c, and M1d contexts. M1b returns only a decision, so
M1e separately parses the already validated canonical envelope through the
closed `CandidateRecordModel` map and verifies record/payload hashes before
constructing `ValidatedRecords`. M1c/M1d typed records come from their public
validator returns. Exact bundle-group and context edges come only from the
validated `CandidateContextBlueprintV1`. The harness reruns those
validators and public resolvers; a caller-supplied decision or status is not
authority.

The validator verifies `content_hash(candidate.blueprint)` equals every dataset
`blueprint_hash`; its canonical bytes are a required
`CanonicalReplayInputEntryV1` in the snapshot. No registry or hidden lookup may
recover a blueprint from a digest.

The adapter has no network, credential, filesystem-root selection, evaluator,
or return-calculation authority. It may decode and map only when exact retained
methodology/schema evidence supports the mapping. Current ticker cannot mint
permanent identity; terms cannot mint occurrence; pay date cannot mint
settlement; `daily` cannot mint regular-session meaning; missing row or zero
cannot mint no-trade; successful response cannot mint completeness.

Adapter input, receipts, emitted datasets, snapshot authorized-profile subset,
targets, pre-replay reports, and replay requests must name the same exact
authorized profile subset. A denied or unlisted profile cannot receive native
bytes, candidate outputs, a snapshot-bound target, or replay authority.

**Golden-case contracts:**

`GoldenCaseId` has exactly `G01` through `G18`. The closed predicate operators are
`EQUAL`, `NOT_EQUAL`, `SAME_IDENTITY`, `DISTINCT_IDENTITY`, `ORDERED_BEFORE`,
`EXACT_RATIO`, `REQUIRED_PRESENT`, `REQUIRED_ABSENT`, and
`PROHIBITED_INFERENCE`. Predicate evaluation is `TRUE`, `FALSE`, `UNSUPPORTED`,
or `UNKNOWN`.

Persist:

- `TruthIntakeReceiptV1`: profile-independent source/publisher identity,
  credential-free request or manual-delivery description, exact byte-graph hash,
  origin evidence, rights binding, availability evidence, optional pre-frozen
  expected inventory and acquisition reconciliation, completeness status,
  collector ID/version/source hash, receipt ID/time, and secret-free metadata.
  It has no provider-candidate profile or native-layer claim. Claims based on
  absence or aggregate reconstruction require `PASS` truth completeness.
- `TruthEvidenceEntryV1`: independent publisher/source identity, artifact hash,
  `TruthIntakeReceiptV1` and origin-evidence hashes, M1a availability evidence,
  contractual rights binding, retention status, and independence declaration.
- `TruthExtractionDecisionV1`: exact input byte hash, structured field or page/
  section locator, extraction method (`structured_primary` or
  `human_adjudicated`), canonical typed extracted value and temporal precision,
  adjudicator, policy/source hashes, and decision time. It has no future claim
  hash. Drift does not ask an LLM or generic PDF parser to decide legal/market
  truth.
- `IndependentTruthClaimV1`: stable claim ID, exact issuer/security/listing/event/
  session subject, claim kind, canonical typed value, exact/bounded/unknown
  temporal claims, evidence and prior extraction-decision hashes, and
  limitations. Verification requires the claim value/precision to equal the
  retained extraction decision.
- `CandidateClaimSelectorSpecV1`: validated dataset role, exact subject/logical-
  key criteria known before acquisition, target Drift field ID, required
  cardinality, and selection-policy hash. It contains no future record or
  mapping hash and is not a free-form object path.
- `CandidateClaimBindingV1`: created after mapping; selector-spec hash, zero or
  more matched canonical record hashes, emitted-mapping hashes, coverage/
  completeness evidence, and binding policy hash. Zero matches are valid input
  for an absence predicate and are not a missing selector.
- `TruthClaimSelectorV1`: exact `IndependentTruthClaimV1` ID and value kind.
- `GoldenCasePredicateV1`: candidate selector specification, operator, truth selector or exact
  canonical constant, required flag, affected dimension, and predicate semantic
  hash. The predicate body is retained, not only its hash.
- `GoldenCaseDefinitionV1`: case ID/version, invariant, required evidence kinds,
  exact predicate tuple, Drift layers/dimensions, substitution policy, status
  policy, and retention requirements.
- `GoldenCaseInstanceV1`: exact real subject/event/session identifiers, date
  window, candidate fields, truth claim IDs, approved definition hash, and
  optional evidence-backed substitute-for ID.
- `GoldenCaseInstanceManifestV1`: all 18 exact instances, definition hashes,
  selection evidence, frozen time, and manifest hash. It freezes before any
  candidate acquisition and is bound by both qualification profiles.
- `GoldenCasePlanV1`: definition/instance, profile/target, exact post-mapping
  `CandidateClaimBindingV1` values, truth claims, and evidence entries. It
  verifies every binding against the unchanged pre-acquisition selector spec.
- `GoldenCaseResultV1`: reachability, status, every predicate evaluation, exact
  compared claims, evidence hashes, policy hashes, limitations, and substitution.
- `GoldenCaseGradingContext`: verified truth bytes plus their receipt, origin,
  rights, availability, retention, extraction, and claim records.

```python
def grade_golden_case(
    plan: GoldenCasePlanV1,
    candidate: ValidatedCandidateFactSet,
    context: GoldenCaseGradingContext,
) -> GoldenCaseResultV1: ...


def verify_golden_case_result(
    result: GoldenCaseResultV1,
    plan: GoldenCasePlanV1,
    candidate: ValidatedCandidateFactSet,
    context: GoldenCaseGradingContext,
) -> None: ...
```

For every case, `PASS` means every required predicate is `TRUE` and all candidate
and independent evidence closures verify. `FAIL` means at least one required
predicate is `FALSE` under complete authority. `PARTIAL` means no predicate is
false, at least one is true, and a required provider subcapability is explicitly
`UNSUPPORTED`. `UNKNOWN` means no predicate is false and at least one required
predicate or evidence closure is `UNKNOWN`/unavailable/conflicting. An
unavailable case is `NOT_REACHED`/`UNKNOWN`, never PASS. A substitution must use
the same definition/predicates and equivalent independently retained evidence.
Any absence claim or reconstructed aggregate, including G14 and G17 raw-trade
truth, requires a pre-frozen expected inventory and `PASS` truth-intake
reconciliation. Exact but partial truth bytes cannot grade PASS.

`scripts/intake_m1e_truth.py` is a local-only intake boundary for externally
obtained SEC, issuer, exchange, FINRA, or raw-trade truth files. It accepts an
explicit private input path, profile-independent source/request/manual-delivery
metadata, origin evidence, availability evidence, rights binding, collector
identity, and store root; it produces `TruthIntakeReceiptV1`, performs no network
request, and creates no truth claim. A human adjudicator later supplies
`TruthExtractionDecisionV1`.

Predicate semantics are closed:

- `EQUAL`/`NOT_EQUAL` compare exact canonical typed values; coercion is forbidden.
- `SAME_IDENTITY`/`DISTINCT_IDENTITY` compare proven `IdentityReferenceV1`
  kind/UUID values, never tickers or names.
- `ORDERED_BEFORE` is true only when exact boundaries or disjoint bounded ranges
  prove ordering; overlapping/unknown bounds yield `UNKNOWN`.
- `EXACT_RATIO` compares reduced integer numerator/positive denominator pairs;
  decimals and binary floats are not ratios.
- `REQUIRED_PRESENT` is true only for the declared cardinality with complete
  mapping/coverage; no row under incomplete coverage is `UNKNOWN`, and
  conflicting multiples are `FALSE`.
- `REQUIRED_ABSENT` is true only under PASS expected-inventory/coverage evidence;
  presence is `FALSE`, otherwise absence is `UNKNOWN`.
- `PROHIBITED_INFERENCE` is `FALSE` if a forbidden canonical value was emitted
  without exact native-record and field-decision lineage; it is `TRUE` only when
  the complete mapping report explicitly preserves the value as
  `UNSUPPORTED`/`UNKNOWN` and emits no invented value. Incomplete lineage is
  `UNKNOWN`.

Every operator has table-driven tests for zero, one, multiple-equal,
multiple-conflicting, unsupported, and unknown inputs, plus mapping-lineage
mutation where applicable.

| ID | Provider evidence required | Independent primary truth | Exact PASS invariant |
|---|---|---|---|
| G01 | Native identity/listing history around FB to META | Meta SEC-filed release plus exchange change record | One security/listing and unchanged CUSIP continue through ticker/name change; no new security is minted |
| G02 | Native histories for Roundhill META/METV and Meta FB/META | Roundhill issuer record, Meta filing, exchange records | Reused ticker does not join unrelated securities and does not make the ETF eligible |
| G03 | Native primary-listing/venue history for Linde LIN | Linde Form 8-K and issuer/exchange transfer record | Same security/ticker persists while primary listing changes NYSE to Nasdaq on 2023-11-07 |
| G04 | Native listing termination and any OTC continuation | SEC Form 25, FINRA Daily List, issuer/bankruptcy filing | Exchange delisting is distinct from security/claim extinction |
| G05 | Native NVIDIA split terms/effect and relevant sessions | NVIDIA 8-K plus exchange action record | Exact 10-for-1 ratio, occurrence and first trading-basis session remain distinct from announcement |
| G06 | Native GE reverse-split terms/effect and fractional rule | GE filing, issuer notice, exchange record | Exact 1-for-8 ratio and fractional treatment map to the first proven post-basis session |
| G07 | Native ordinary-dividend event versions | Issuer IR release and exchange ex-date record | Declaration, ex, record and payable dates remain distinct; payment is not inferred |
| G08 | Native special distribution and due-bill fields | FINRA UPC notice, Nasdaq Daily List/Ex-Date, issuer filing | Due-bill period and delayed ex-date are preserved without conventional-date fallback |
| G09 | Native Twitter/X merger, delisting and settlement claims | Merger agreement, closing 8-K, NYSE notice | Fixed cash terms, occurrence, delisting and reported settlement remain separate facts |
| G10 | Native fixed-share or mixed merger components | S-4/14A, closing filing, successor listing | Every consideration component and successor identity is exact; no component is dropped or duplicated |
| G11 | Native GE Vernova spinoff and parent history | Information statement/8-K and exchange notice | New claim/security and parent continuity are retained without making excluded property investable |
| G12 | Native BBBY listing, OTC, bankruptcy and cancellation history | Court/issuer filings, Form 25, FINRA notices | Delisting, continuation, cancellation and unknown recovery are distinct; unknown is not zero |
| G13 | Native old and corrected action versions | Provider correction notice plus issuer/exchange truth | Earlier cutoff selects old evidence; later cutoff selects correction without rewriting history |
| G14 | Native old and corrected daily aggregate versions | Original/corrected receipts plus eligible-trade reconstruction | Final corrected bar is not treated as originally available |
| G15 | Native observation/session claims for a standard early close | Official exchange calendar plus first-party trade/status evidence | Schedule, realized bounds and aggregation interval agree for the exact venue/date |
| G16 | Native 2018-12-05 session/omission claims | Exchange closure notice and SEC/exchange records | Scheduled versus realized national closure is explicit; no bar omission is guessed |
| G17 | Native halt/suspension, row presence and activity claims | Exchange halt/status, SEC/issuer notice, raw eligible trades | Lifecycle interruption, omission and no-qualifying-trade are independently evidenced |
| G18 | Native Berkshire class identifiers and symbols | Issuer filing, exchange security master, stable external IDs | Share classes remain distinct under suffix normalization and historical symbol mapping |

- [ ] **Step 1: Write adapter-boundary RED tests**

Use a deliberately malformed synthetic adapter to attempt every forbidden
inference above, emit a current-symbol identity, hide an unsupported field,
mislabel adjusted data, provide a mismatched profile, and include evaluator-like
output. Mutate an emitted value while retaining the old field/record mapping,
omit one consumed native record, and reuse a receipt not authorized for the
profile set. Each attempt must fail or remain explicitly unqualified.

- [ ] **Step 2: Write the exact G01-G18 contract matrix**

Create the 18 definitions and tests for uniqueness, required evidence,
substitution invariants, purpose binding, rights binding, and unavailable-case
behavior. Add acyclic extraction-decision-then-claim construction and reject a
claim whose value differs from the retained extraction value. Luna verifies the
finite inventory and pointers.

Prove definitions and the instance manifest construct before any candidate
record exists. After mapping, bind zero/multiple exact matches and test absence,
cardinality, mapping-lineage, and coverage behavior without rewriting the
selector specification.

- [ ] **Step 3: Write harness RED tests**

Cover all 11 pre-replay dimensions exactly once, purpose independence, no weighted score,
real evidence unable to grade itself, caller-supplied PASS substitution,
unsupported mappings, partial coverage, and a candidate whose individual
datasets validate but whose cross-layer join conflicts.

- [ ] **Step 4: Implement the minimal protocol, graders, and harness**

Use in-memory and temporary-directory synthetic builders only. Do not freeze a
Task 6 fixture containing whole-package implementation hashes because Task 7
still adds source modules. Generated cases include profile, receipt, snapshot,
context, truth claim, predicate, and negative result objects, with no vendor
name presented as accepted and no real source byte, contract, or credential.

- [ ] **Step 5: Run focused GREEN**

```text
uv run pytest tests/unit/test_qualification_adapter_boundary.py tests/unit/test_golden_case_contracts.py tests/unit/test_truth_evidence.py tests/unit/test_qualification_harness.py tests/unit/test_security_identity.py tests/integration/test_m1c_action_matrix.py tests/integration/test_m1d_observation_history.py tests/integration/test_m1d_action_normalization.py -q
```

- [ ] **Step 6: Independent adapter, semantics, and leakage review**

A fresh Sol reviewer covers provider semantics and M1b-M1d compatibility. A
separate reviewer covers evaluator/scope leakage. Fix every genuine
Important/Critical finding. The controller reruns counterexamples against the
actual code.

- [ ] **Step 7: Full gate, commit, and Checkpoint**

Run the full repository gate once. Stage only Task 6 files and execution record.
Commit:

```text
feat: add bounded M1e qualification harness
```

Run Checkpoint and continue to Task 7.

### Task 7: Add macOS/arm64 environment closure, offline attestations, and replay

**Files:**

- Create: `src/drift/domain/environment_closure.py`
- Create: `src/drift/domain/qualification_replay.py`
- Create: `src/drift/qualification/environment.py`
- Create: `src/drift/qualification/replay.py`
- Create: `scripts/capture_m1e_environment.py`
- Create: `scripts/replay_m1e_offline.py`
- Create: `tests/unit/test_environment_closure.py`
- Modify: `tests/unit/test_replay_authorization.py`
- Create: `tests/integration/test_m1e_offline_replay.py`

**Environment identities:**

Persist separate identities rather than one opaque environment hash:

- `EnvironmentArtifactV1`: artifact kind, exact reference/hash/size/media type,
  platform applicability, origin, and rights binding.
- `PythonRuntimeIdentityV1`: implementation, exact version/build, executable,
  standard-library inventory, distribution artifact, and native-library links.
- `PackageArtifactV1`: normalized package/version, wheel or sdist filename, hash,
  index/origin, compatible tags, build-toolchain hashes when applicable, and
  installed-file inventory hash.
- `SystemLibraryIdentityV1`: path-independent library identity, version/build,
  architecture, digest, and relevance.
- `PlatformIdentityV1`: `macos`, `arm64`, OS build, kernel/runtime compatibility,
  hardware/virtualization class, and declared host assumptions.
- `EnvironmentClosureV1`: semantic policy hashes, Git commit/tree/archive,
  Drift wheel/sdist, `pyproject.toml`, `uv.lock`, exported `pylock.toml`, uv,
  Python, all package and build artifacts, native libraries, TZif, source
  snapshots, restore recipe, platform, vulnerability evidence, security lane,
  closure ID/version/time, and closure hash.

`EnvironmentArtifactKind` has exact members for Git archive, Drift sdist/wheel,
project metadata, uv lock, pylock, uv executable/installer, Python distribution,
package wheel/sdist, build toolchain, standard library, system library, TZif,
source snapshot, restore recipe, vulnerability evidence, offline evidence, and
fresh-target evidence.

**Offline and replay contracts:**

```python
class OfflineControlStatus(StrEnum):
    ENFORCED = "enforced"
    NOT_ENFORCED = "not_enforced"
    UNKNOWN = "unknown"


class ReplayOutcome(StrEnum):
    MATCH = "MATCH"
    SOURCE_BYTES_UNAVAILABLE = "SOURCE_BYTES_UNAVAILABLE"
    USE_DENIED_BY_RIGHTS = "USE_DENIED_BY_RIGHTS"
    ENVIRONMENT_ARTIFACT_UNAVAILABLE = "ENVIRONMENT_ARTIFACT_UNAVAILABLE"
    PLATFORM_INCOMPATIBLE = "PLATFORM_INCOMPATIBLE"
    SEMANTIC_IDENTITY_MISMATCH = "SEMANTIC_IDENTITY_MISMATCH"
    OUTPUT_HASH_MISMATCH = "OUTPUT_HASH_MISMATCH"
```

- `OfflineProbeResultV1`: named DNS/connectivity probe, destination class,
  attempted time, result, exit status, and exact log evidence. It contains no
  credential or production endpoint.
- `IsolationExecutionPlanV1`: pre-run exact OS/VM isolation mechanism, expected
  VM/boot identity, network-interface/control configuration, safe probe set,
  control owner, and policy hash.
- `CleanTargetPlanV1`: pre-run target identity rule, empty-base requirements,
  permitted mounts/paths, environment allowlist, disposal rule, and policy hash.
- `SystemOfflineAttestationV1`: post-run request/attempt/VM/boot/process-tree
  identity, enforced OS/VM mechanism, actual control interval, configuration
  evidence, probe results, status, attestor, and policy hash. Package-manager
  flags alone cannot set `ENFORCED`.
- `FreshRestoreAttestationV1`: post-run request/attempt/target identity, base
  state, absence of inherited `.venv`/package cache/source checkout, creation,
  process use, and disposal evidence, attestor, and policy hash.
- `ReplayComparisonPolicyV1`: exact canonical artifacts compared and the small
  replay-envelope-only exclusion list.
- `ReplayRequestV1`: purpose-profile/target/snapshot/closure hashes, exact
  `PreReplayQualificationReportV1` hash, expected limitations, replay-time
  authorization, isolation plan, clean-target plan, comparison policy, and
  requested output inventory. It contains no post-run attestation.
- `ReplayAttemptEnvelopeV1`: new attempt ID, start/end, process IDs, temporary
  paths, cache layout, diagnostics, and host observations. None is historical
  equality input.
- `ReplayExecutionRecordV1`: request/authorization/attempt hashes, exact verified
  inputs, `NOT_STARTED` or `EXECUTED` status, optional preflight outcome, actual
  outputs, process-tree and target identities, start/end, and raw outcome
  evidence. A denied authorization or unavailable input returns `NOT_STARTED`
  without launching a process. It exists before post-run attestations and final
  outcome.
- `ReplayResultV1`: request and authorization hashes, outcome, verified input and
  actual output hashes, offline/fresh attestation hashes, mismatch
  classifications, limitations, attempt envelope, replay implementation/policy
  hashes, and result ID/time.

```python
def build_environment_closure(
    artifacts: Mapping[str, VerifiedArtifactBytes],
    platform: PlatformIdentityV1,
    restore_recipe_hash: SHA256Hash,
) -> EnvironmentClosureV1: ...


def verify_environment_closure(
    closure: EnvironmentClosureV1,
    artifacts: Mapping[str, VerifiedArtifactBytes],
) -> None: ...


def verify_system_offline_attestation(
    attestation: SystemOfflineAttestationV1,
    artifacts: Mapping[str, VerifiedArtifactBytes],
) -> None: ...


def execute_replay(
    request: ReplayRequestV1,
    authorization: ReplayAuthorizationVerificationBundle,
    snapshot: RealSourceSnapshotV1,
    closure: EnvironmentClosureV1,
    context: QualificationExecutionContext,
) -> ReplayExecutionRecordV1: ...


def finalize_replay_result(
    execution: ReplayExecutionRecordV1,
    offline: SystemOfflineAttestationV1 | None,
    fresh: FreshRestoreAttestationV1 | None,
    expected: tuple[ExpectedOutputV1, ...],
    actual: tuple[ExpectedOutputV1, ...],
    policy: ReplayComparisonPolicyV1,
) -> ReplayResultV1: ...


def compare_replay_outputs(
    expected: tuple[ExpectedOutputV1, ...],
    actual: tuple[ExpectedOutputV1, ...],
    policy: ReplayComparisonPolicyV1,
) -> ReplayOutcome: ...


def finalize_qualification_report(
    pre_replay: PreReplayQualificationReportV1,
    replay: ReplayResultV1,
) -> PurposeQualificationReportV1: ...


@dataclass(frozen=True, slots=True)
class PositivePurposeTerminalBundle:
    profile: QualificationProfileV1
    target: QualificationTargetV1
    pre_replay_report: PreReplayQualificationReportV1
    final_report: PurposeQualificationReportV1
    snapshot: RealSourceSnapshotV1
    closure: EnvironmentClosureV1
    request: ReplayRequestV1
    acquisition_authority: AcquisitionAuthorizationVerificationBundle
    replay_authority: ReplayAuthorizationVerificationBundle
    execution: ReplayExecutionRecordV1
    offline: SystemOfflineAttestationV1
    fresh: FreshRestoreAttestationV1
    replay: ReplayResultV1
    qualification_context: QualificationExecutionContext
    artifacts: Mapping[str, VerifiedArtifactBytes]
    dispositions: tuple[ContentDispositionRecordV1, ...]


@dataclass(frozen=True, slots=True)
class ProfileExternalNegativeEvidence:
    profile: QualificationProfileV1
    external_dependency: ExternalDependencyResolutionV1
    evidence: Mapping[str, VerifiedArtifactBytes]


@dataclass(frozen=True, slots=True)
class RightsNegativeEvidence:
    assessment: ValidatedRightsAssessment
    evidence: RightsEvidenceContext


@dataclass(frozen=True, slots=True)
class AcquisitionNegativeEvidence:
    acquisition_authority: AcquisitionAuthorizationVerificationBundle
    plan: AcquisitionPlanV1
    receipts: tuple[AcquisitionReceiptV1, ...]
    reconciliations: tuple[AcquisitionReconciliationV1, ...]
    artifacts: Mapping[str, VerifiedArtifactBytes]


@dataclass(frozen=True, slots=True)
class SnapshotNegativeEvidence:
    acquisition_authority: AcquisitionAuthorizationVerificationBundle
    receipts: tuple[AcquisitionReceiptV1, ...]
    validation_context: CandidateValidationContext
    validated_candidate: ValidatedCandidateFactSet | None
    consistency: CrossComponentConsistencyDecisionV1 | None
    artifacts: Mapping[str, VerifiedArtifactBytes]


@dataclass(frozen=True, slots=True)
class QualificationNegativeEvidence:
    context: QualificationExecutionContext
    pre_replay_report: PreReplayQualificationReportV1 | None
    golden_case_results: tuple[GoldenCaseResultV1, ...]


@dataclass(frozen=True, slots=True)
class ReplayNegativeEvidence:
    snapshot: RealSourceSnapshotV1
    closure: EnvironmentClosureV1
    request: ReplayRequestV1
    acquisition_authority: AcquisitionAuthorizationVerificationBundle
    replay_authority: ReplayAuthorizationVerificationBundle
    execution: ReplayExecutionRecordV1
    qualification_context: QualificationExecutionContext
    pre_replay_report: PreReplayQualificationReportV1
    offline: SystemOfflineAttestationV1 | None
    fresh: FreshRestoreAttestationV1 | None
    replay: ReplayResultV1
    artifacts: Mapping[str, VerifiedArtifactBytes]


@dataclass(frozen=True, slots=True)
class ReplayAuthorizationNegativeEvidence:
    snapshot: RealSourceSnapshotV1
    closure: EnvironmentClosureV1
    pre_replay_report: PreReplayQualificationReportV1
    qualification_context: QualificationExecutionContext
    replay_authority: ReplayAuthorizationVerificationBundle
    artifacts: Mapping[str, VerifiedArtifactBytes]


type NegativeStageEvidence = (
    ProfileExternalNegativeEvidence
    | RightsNegativeEvidence
    | AcquisitionNegativeEvidence
    | SnapshotNegativeEvidence
    | QualificationNegativeEvidence
    | ReplayAuthorizationNegativeEvidence
    | ReplayNegativeEvidence
)


@dataclass(frozen=True, slots=True)
class NegativePurposeTerminalBundle:
    profile: QualificationProfileV1
    target: QualificationTargetV1
    final_report: PurposeQualificationReportV1
    blocker_dimension: QualificationDimension
    blocker_evidence: Mapping[str, VerifiedArtifactBytes]
    stage_evidence: NegativeStageEvidence
    dispositions: tuple[ContentDispositionRecordV1, ...]
    disposition_evidence: Mapping[str, VerifiedArtifactBytes]
    external_dependency: ExternalDependencyResolutionV1 | None


type PurposeTerminalBundle = (
    PositivePurposeTerminalBundle | NegativePurposeTerminalBundle
)


def finalize_pilot(
    state: M1ePilotStateV1,
    bundles: tuple[PurposeTerminalBundle, PurposeTerminalBundle],
) -> M1eCompletionRecordV1: ...


def require_qualified_purpose(
    completion: M1eCompletionRecordV1,
    purpose: ConsumerPurpose,
    bundle: PositivePurposeTerminalBundle,
) -> PurposeQualificationReportV1: ...


def build_qualified_source_handoff(
    completion: M1eCompletionRecordV1,
    purpose: ConsumerPurpose,
    bundle: PositivePurposeTerminalBundle,
) -> QualifiedSourceHandoffV1: ...


def derive_qualified_reference_inventory(
    bundle: PositivePurposeTerminalBundle,
) -> tuple[ArtifactReference, ...]: ...
```

The finalizer verifies the attestations cover the exact request, attempt ID,
VM/boot identity, target, process tree, and execution interval. It applies the
following table top to bottom and returns the first matching outcome. Rights are
checked before any source-byte access. No implementation chooses a convenient
outcome.

| Evidence condition | Replay outcome | Offline dimension |
|---|---|---|
| replay-time authorization is denied or unknown | `USE_DENIED_BY_RIGHTS` | `NOT_REACHED`/`UNKNOWN` |
| source object required by snapshot is missing or hash-invalid after authorization | `SOURCE_BYTES_UNAVAILABLE` | `FAIL` when contradicted, otherwise `UNKNOWN` |
| closure object, isolation plan, fresh-target plan, or post-run attestation is missing/unverifiable | `ENVIRONMENT_ARTIFACT_UNAVAILABLE` | `UNKNOWN` |
| OS/architecture/ABI is wrong or the retained runtime cannot restore on the declared supported platform | `PLATFORM_INCOMPATIBLE` | `FAIL` or `UNKNOWN` according to evidence |
| offline control is `NOT_ENFORCED`, a probe reaches the network, target is not fresh, or disposal/process binding contradicts the plan | `ENVIRONMENT_ARTIFACT_UNAVAILABLE` | `FAIL` |
| source/code/query/policy/context identity differs before output comparison | `SEMANTIC_IDENTITY_MISMATCH` | `FAIL` |
| all inputs and environment identities verify but an expected canonical output differs | `OUTPUT_HASH_MISMATCH` | `FAIL` |
| every required input, authorization, control, attestation, and exact output verifies | `MATCH` | `PASS` |

`finalize_qualification_report` derives the twelfth dimension from this typed
result; the final report cannot be part of its own replay request.
`finalize_pilot` requires exactly one bundle for each profile in the profile set.
It re-verifies every hash-resolved positive referent, recomputes the finalized
replay and final report, and accepts a positive bundle only when the typed result
is `MATCH`. A negative bundle carries its blocker, correctly discriminated
reached-stage evidence, and hash-resolved dispositions. The finalizer reruns
rights, acquisition, qualification, or replay verification for every reached
dimension and synthesizes only later `UNKNOWN`/`NOT_REACHED` dimensions. It does
not preserve a caller-asserted status, and no mandatory deletion/certification
reference may remain unresolved.
Overall completion is positive only when both bundles are positive; a mixed pair
is overall evidenced-negative while preserving the verified purpose-scoped
positive handoff. A syntactically valid hash or caller-created MATCH object has
no authority.

The handoff reference inventory is derived, never caller-supplied. It is exactly
the purpose-authorized M1b resolution/universe, M1c outcome/reference, M1d
observation/session/missingness/usability/view/reference outputs in the
replay-verified snapshot plus the profile/report/snapshot/rights/closure/replay
identities. It rejects raw provider/grading/contract/environment bytes, private
locations, acquisition cursors, adjusted dataframes, and any evaluator-like
object. Tests require exact set equality and reject missing or extra references.

The current development `.venv/bin/python` is an absolute symlink to Homebrew's
`/opt/homebrew/opt/python@3.14/bin/python3.14`; `otool -L` binds it to the
Homebrew 3.14.5 framework. It is evidence about the current environment, not a
restorable closure. The accepted path uses a separately staged relocatable
macOS/arm64 Python 3.14.5 distribution selected by the retained uv download
metadata. The exact distribution archive, metadata, URL, published hash, and
installed-tree hash must all be retained. If the archive cannot be retained or
restored without `/opt/homebrew`, the native closure is
`ENVIRONMENT_ARTIFACT_UNAVAILABLE` and cannot MATCH.

`capture_m1e_environment.py` accepts only explicit `--staging-root`,
`--store-root`, `--platform-evidence`, and `--output` paths. The staging root
is prepared in the current safe-development lane, where package-network access
is allowed but provider credentials/data are absent. Use a fresh task-specific
uv cache and Python install directory, retain the exact downloaded Python
archive before extraction, build Drift's sdist/wheel, export the standard lock,
and populate the cache from `uv.lock`. The capture script inventories and stores
those bytes; it does not itself download packages. Generate the standards lock:

```text
uv export --format pylock.toml --locked --no-emit-project --output-file <staging-root>/pylock.toml
```

The future implementation replaces `<staging-root>` with the explicit private
path supplied for that run; the angle-bracket notation is command documentation,
not a persisted filename or unfinished interface.

The capture procedure must also:

1. hash the Git tree/archive after all source for the replayed target exists;
2. retain uv's executable/installer and Python-download metadata;
3. retain every wheel/sdist/cache object and package/index origin needed by
   `uv sync --frozen --offline`, including hatchling/build inputs;
4. retain `otool -L` evidence for Python, `pydantic-core`, and every non-system
   Mach-O extension, plus the referenced non-system library bytes;
5. retain the exact TZif and other external deterministic input bytes;
6. test relocation into a fresh directory whose absolute path differs from
   staging; and
7. recapture the final closure in Task 8 after conditional `pilot_adapter.py`
   exists, because adding that source changes code and validator identities.

`replay_m1e_offline.py` accepts explicit `--request`, `--store-root`, and
`--work-root`. It creates a new target below `--work-root`, restores only from
the retained Python/uv/package/source objects, verifies imported `drift.__file__`
and every environment identity, loads the snapshot, reruns qualification, and
compares exact outputs. It never uses the development `.venv`, global uv cache,
provider access, credentials, or mutable package index. The system/VM operator,
not Drift, supplies the enforced offline and fresh-target attestations.

The child environment is rebuilt from an explicit allowlist containing only the
closure-local `PATH`, task `TMPDIR`, locale, `PYTHONNOUSERSITE=1`,
`PYTHONDONTWRITEBYTECODE=1`, fixed `PYTHONHASHSEED`, closure-local
`UV_CACHE_DIR`, `UV_OFFLINE=1`, `UV_NO_CONFIG=1`,
`UV_PYTHON_DOWNLOADS=never`, and the new target's `VIRTUAL_ENV`. Proxy, index,
credential, user-site, and inherited Python variables are absent. The script
verifies `sys.executable`, `sys.prefix`, `sys.path`, `drift.__file__`, installed
file hashes, `otool -L`, and captured dynamic-library evidence before replay.

- [x] **Step 1: Write environment-identity RED tests**

Mutate the Git tree, built artifact, uv lock, pylock, uv, Python executable,
stdlib, wheel, sdist toolchain, native library, platform, TZif, source snapshot,
restore recipe, and vulnerability evidence. Each changes closure identity or
fails verification. A copied `.venv` is never an accepted artifact class.

- [x] **Step 2: Write offline and replay-result RED tests**

Reject `uv --offline` as system proof, a nonfresh target, mutable tag, absent
wheel, wrong interpreter, unavailable source bytes, expired rights, changed
policy/code, and changed expected output. Assert every explicit `ReplayOutcome`
and that original canonical IDs/timestamps remain exact while only the attempt
envelope differs. Prove a final report cannot be used as its own replay input,
post-run attestations cannot predate or target a different attempt, and a hash
of a non-MATCH result cannot complete positively. Table-test every
`NegativeStageEvidence` variant from post-profile external failure through replay
failure, and reject a variant whose supplied artifacts belong to another stage.

- [x] **Step 3: Implement pure closure and replay verification**

Keep process creation and filesystem orchestration in scripts. Production
modules validate immutable artifacts and run deterministic in-process replay
through the Task 6 harness. Do not add a downloader, container engine,
vulnerability scanner, credential provider, or network control mechanism.

- [x] **Step 4: Prove a synthetic clean-prefix restore**

Stage only current public build/dependency artifacts in a temporary private
root, restore to a fresh temporary prefix with package/provider access disabled,
and replay a runtime-generated synthetic M1e corpus. This proves closure mechanics, not
system-level offline acceptance and not a real-provider `MATCH`.

- [x] **Step 5: Run focused GREEN**

```text
uv run pytest tests/unit/test_environment_closure.py tests/unit/test_replay_authorization.py tests/integration/test_m1e_offline_replay.py tests/integration/test_m1c_pinned_replay.py tests/integration/test_m1d_pinned_replay.py -q
```

- [x] **Step 6: Independent environment/replay review**

A fresh Sol reviewer checks restore completeness, process boundaries,
system-offline truth, fresh-target truth, old-vulnerability isolation,
comparison exclusions, failure classification, and OCI nonadoption. Fix every
genuine Important/Critical finding.

- [x] **Step 7: Full gate, commit, and Checkpoint**

Run the full repository gate once. Stage only Task 7 files and the execution
record. Commit:

```text
feat: add M1e offline replay closure
```

Run Checkpoint. If Task 8 evidence is absent, update the execution record with
the exact missing artifacts, commit that record if needed, create a minimal
Session Handoff pointing to Git and this plan, and stop. Do not poll a vendor or
user inbox.

### Task 8: Execute one profile-specific real-source pilot and close M1e

**Files:**

- Create after profile/schema freeze: `src/drift/qualification/pilot_adapter.py`
- Create after acquisition authorization: `scripts/acquire_m1e_pilot.py`
- Create: `scripts/qualify_m1e_pilot.py`
- Create: `tests/unit/test_pilot_adapter.py`
- Create: `tests/integration/test_m1e_adversarial_matrix.py`
- Modify: `tests/integration/test_m1e_compatibility.py`
- Create: `tests/unit/test_documentation_links.py`
- Create: `docs/qualification/m1e/pilot-record.md`
- Modify after acceptance: `README.md`
- Modify after acceptance: `AGENTS.md`
- Modify after acceptance: `docs/architecture/overview.md`
- Modify after acceptance: `docs/architecture/roadmap.md`
- Modify only if execution proves a bounded clarification: M1e spec and ADR 0010
- Modify throughout: this plan's execution record

`pilot_adapter.py` supports exactly one frozen profile set and its two profile
hashes through a literal `SUPPORTED_PROFILE_SET_HASH`. It accepts only the
ordered authorized receipt tuple and refuses every other profile or receipt. It stays offline,
deterministic, and separate from `acquire_m1e_pilot.py`. The acquisition script
is the only permitted provider-network/credential boundary and is created only
for the authorized product. It uses the fixed external environment variable
`DRIFT_M1E_PROVIDER_CREDENTIAL`; the value never appears in arguments,
canonical records, logs, exceptions, fixtures, or subprocess environment dumps.
If the selected product needs a provider SDK or other new dependency, stop for
user review before implementation.

**First provider/profile selection procedure:**

1. Obtain the subscriber legal entity, actual provider-defined use
   classification, one-user/infrastructure inventory, entitlement evidence,
   approved private store/root controls, backup scope, both consumer purposes,
   required retention horizon, and externally supplied truth-evidence package.
2. Inventory existing entitlements first. A currently usable institutional
   CRSP/WRDS, exchange, Databento, or other entitlement is evidence, not assumed
   authority. Prefer an already authorized product only if exact terms and
   technical semantics satisfy the same gates.
3. If no qualifying entitlement exists, Databento remains the first contract
   inquiry candidate. The user or counsel contacts the provider; Drift records
   the returned exact documents. The implementation agent does not impersonate
   the user or accept terms.
4. Before profile freeze, use retained primary evidence and human extraction
   decisions to select concrete instances for G01-G18. The generic G04, G07,
   G08, G10, G13, G14, G15, and G17 categories must name exact subjects,
   events/dates, typed claims, and predicates. Freeze the complete
   `GoldenCaseInstanceManifestV1`; after-the-fact selection is forbidden.
5. Freeze one provider/product/data scope and two otherwise identical
   purpose-specific profiles that bind the instance manifest. No provider
   hopping occurs inside the frozen profile. A failed profile is preserved
   before any alternate pilot is proposed.
6. Build the exact contract topology and human/legal rights assessments. A
   purpose with a critical `DENIED` or evidentially `UNKNOWN` right closes
   negatively. If neither purpose is authorized, record `NOT_ACQUIRED`, commit
   only the lawful sanitized record, Checkpoint, and stop. If exactly one is
   authorized, acquisition and later use are restricted to that profile.
7. If at least one profile is authorized, obtain explicit user approval for the exact bounded
   acquisition before running the acquisition script. Technical access is not
   approval.

**Bounded acquisition and mapping:**

1. Freeze `ProviderNativeLayerRuleV1` from retained product schema/methodology,
   then freeze `AcquisitionPlanV1` with that rule, the authorized request, and
   exact `ExpectedInventoryV1` hash before the first request. Inventory discovery that
   requires provider access uses a separate approved/receipted plan and cannot
   be backfilled from the final response.
2. Acquire at most 100 securities, at most two continuous years, and at most 20
   event windows normally spanning 20 sessions on each side. Do not acquire a
   full 2001-present corpus.
3. Store transport entity, archive/file, decompressed payload, members, and
   decoded native records separately. Reconcile every expected object, page,
   cursor, count, retry, duplicate, and provider snapshot/release token before
   parsing. `FAIL`/`UNKNOWN` completeness ends the exact profile negatively.
4. Retain exact product schema/methodology and independently sourced truth bytes
   under their own receipts and rights bindings.
5. Freeze every `FieldMappingDecisionV1` before implementing
   `pilot_adapter.py`. If delivered encoding/layers contradict the pre-frozen
   native-layer rule, the receipt fails and a new plan requires new
   authorization; never backfill the old rule. Unsupported native fields and undocumented
   availability, identity, occurrence, settlement, session, omission, and
   revision meanings remain `UNSUPPORTED` or `UNKNOWN`.
6. RED/GREEN the adapter with legally retainable private bytes plus committed
   synthetic attacks. Real/private data never enters ordinary pytest fixtures or
   CI. The controller inspects Git for raw bytes and secrets before staging.
7. Run the adapter and existing M1b-M1d validators, freeze the exact source
   snapshot with the authorized-profile subset, then create snapshot-bound
   targets only for profiles named by the acquisition authorization. A denied
   sibling retains its earlier `NOT_ACQUIRED` negative report and terminal
   purpose state and never receives the snapshot bytes.
8. Execute all G01-G18 cases or pre-frozen invariant-equivalent substitutions with
   retained primary evidence. An unavailable case remains non-PASS.
9. Build independent 11-dimension pre-replay reports only for snapshot-bound
   authorized profiles. Preserve an unauthorized sibling's final negative
   report; never request replay authorization for it. One purpose may pass while
   the other fails; neither transfers authority.

**Real replay and completion:**

1. Recapture and verify `EnvironmentClosureV1` from the clean final
   adapter/source commit.
2. Freeze `IsolationExecutionPlanV1` and `CleanTargetPlanV1` for the
   macOS/arm64 target. The mechanism must be enforced outside the replayed
   process, such as an isolated VM with its virtual NIC disabled or a separately
   evidenced host-level network block.
3. Obtain a new replay-time authorization for each snapshot-bound,
   replay-eligible purpose, binding that exact closure and infrastructure.
4. Build `ReplayRequestV1`, then restore solely from retained objects and reproduce exact source selections,
   M1b resolutions, M1c outcomes/references, M1d
   sessions/mappings/derivations/views/references, qualification results, and
   limitations.
5. After execution/disposal, create `SystemOfflineAttestationV1` and
   `FreshRestoreAttestationV1` bound to the exact request/attempt/VM/target/
   process tree, then finalize typed `ReplayResultV1` and the 12-dimension report.
6. Complete positively only for a purpose whose critical dimensions all PASS
   and whose replay is `MATCH`. Otherwise preserve reached PASS/PARTIAL results
   and close negatively with the exact blocker and non-MATCH outcome.
7. Verify every content and backup disposition before terminal completion.
   Mandatory `PENDING` deletion/certification pauses for exact file-specific user
   approval and cannot be called complete.
8. `docs/qualification/m1e/pilot-record.md` contains only nonsensitive profile
   and evidence hashes, per-purpose dimension statuses, reachability,
   limitations, completion class, replay result, private-store recovery
   requirement, and explicit nonauthorization of other vendors/scopes. No
   contract bytes, provider data, personal identifiers, credentials, or private
   paths are committed.

**Command shapes after external values are supplied:**

```text
uv run python scripts/acquire_m1e_pilot.py --profile-set /private/profile-set.json --rights /private/rights.json --store-root /approved/private/root
uv run python scripts/qualify_m1e_pilot.py --profile-set /private/profile-set.json --store-root /approved/private/root
uv run python scripts/replay_m1e_offline.py --request /private/replay-request.json --store-root /approved/private/root --work-root /approved/isolated/work
```

The concrete absolute paths are operational inputs excluded from canonical
identity. Credentials are never command arguments.

- [ ] **Step 1: Gather external evidence or stop cleanly**

Complete the seven selection inputs above. If a required artifact is still
`PENDING`, update the execution record with its exact type and responsible
human/provider, Checkpoint, create a minimal handoff, and stop. If the user,
counsel, or provider supplies evidence-backed `DECLINED`, `WITHDRAWN`,
`INQUIRY_EXHAUSTED`, or `UNAVAILABLE` before a profile set can be frozen, record
`ABANDONED_PRE_PROFILE` and stop without claiming M1e completion. After profile
freeze, the same terminal evidence may be exact negative blocker evidence. Do
not wait asynchronously.

- [ ] **Step 2: Freeze profiles and adjudicate rights**

Write and independently verify the truth-evidence intake, extraction decisions,
G01-G18 instance manifest, private profile set, topology, rights assessments,
content rules, acquisition eligibility, external approval, and authorization.
Exercise the pre-acquisition negative branch before any provider request.

- [ ] **Step 3: Write acquisition RED attacks, then acquire only if authorized**

Add synthetic failures for late-frozen inventory, pagination, object mutation,
partial success, origin, secret redaction, and rights mismatch. Freeze the
acquisition plan before request start. Only after the attacks fail correctly and
the user has approved the exact request may the bounded acquisition run.

- [ ] **Step 4: Reconcile, freeze mapping, and RED/GREEN one adapter**

No mapping code precedes the exact native schema/methodology and byte-layer
decision. Test each mapping, unsupported field, availability rule, correction,
and forbidden inference. Stop for user review if a new dependency or old
M1b-M1d contract change appears necessary.

- [ ] **Step 5: Execute golden cases and both pre-replay purpose reports**

Luna maintains the finite G01-G18 inventory. A fresh Sol reviewer verifies real
candidate and independent-truth evidence, exact predicates, substitutions,
coverage, and the eleven non-replay dimensions. Fix same-scope findings or
close negatively.

- [ ] **Step 6: Freeze the replay-eligible source tree**

If at least one purpose reaches replay, run the focused tests, source/fixture/
secret inspection, independent pre-replay review, and one full gate. Commit the
stable Task 8 source/tests/scripts before environment capture:

```text
feat: qualify M1e source candidate
```

Checkpoint and record that commit as the environment source identity. Do not
change runtime source after capture. If all purposes closed negatively before
replay, skip this intermediate commit and continue to terminal review.

- [ ] **Step 7: Capture and execute replay or record the exact non-MATCH**

Recapture the environment from the clean pre-replay commit, freeze the
isolation/clean-target plans, then obtain current replay authorization bound to
that closure before building the replay request. Execute under the external
controls and collect attempt-bound post-run attestations. Never call
`uv --offline` alone proof of isolation. A native macOS restore failure triggers
the material OCI review stop rather than container implementation.

- [ ] **Step 8: Run focused terminal acceptance**

```text
uv run pytest tests/unit/test_pilot_adapter.py tests/integration/test_m1e_adversarial_matrix.py tests/integration/test_m1e_compatibility.py tests/unit/test_documentation_links.py -q
```

The default test suite uses only synthetic data. The private real-pilot commands
and their result hashes are recorded separately in the execution record.

- [ ] **Step 9: Seven-lens review and final Astra audit**

Use fresh independent review across: rights/negative completion;
acquisition/snapshot; adapter/M1b-M1d; environment/offline replay; real golden
evidence; evaluator/scope leakage; and implementation practicality/external
pauses. Root Sol verifies every Important/Critical finding against repository
and evidence. After fixes and Sol acceptance, use Astra once for a bounded
whole-M1e audit. Astra is not the persistent implementation root.

- [ ] **Step 10: Run final gates**

```text
uv run pytest
uv run pytest tests/integration/test_replay.py tests/integration/test_m1_m0_compatibility.py tests/integration/test_m1b_m1a_compatibility.py tests/integration/test_m1c_pinned_replay.py tests/integration/test_m1d_pinned_replay.py tests/integration/test_m1e_compatibility.py -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv build
git diff --check
```

Also verify local documentation links, lifecycle/stale-plan state, U+2014
absence, no real/private bytes or secret patterns in Git, no unexpected
dependency/lock change, and the exact planned-path allowlist.

- [ ] **Step 11: Commit the accepted terminal record and Checkpoint**

For a replayed positive or negative completion after the source commit, stage
only terminal tests/nonsensitive docs and commit:

```text
docs: complete M1e source qualification pilot
```

For a post-acquisition negative completion that did not reach the intermediate
source commit, stage only accepted Task 8 source/tests/scripts/nonsensitive docs
and commit:

```text
feat: close M1e source qualification pilot
```

For pre-acquisition rights-negative completion with no Task 8 runtime, commit:

```text
docs: record evidenced-negative M1e pilot
```

Run Checkpoint. A clean canonical completion needs no Session Handoff. Stop
without beginning evaluator/provider expansion work.

## 4. Task acceptance and review matrix

| Task | Provider-independent | Required fresh review | Full-gate boundary | External stop |
|---|---|---|---|---|
| 1 | yes | Sol compatibility/adversarial | yes, before first M1e source | none |
| 2 | yes | Sol lifecycle/negative completion | yes | none |
| 3 | yes | Sol rights/replay authorization | yes | no real rights PASS attempted |
| 4 | yes | Sol acquisition/store security | yes | no provider access attempted |
| 5 | yes | Sol temporal/snapshot consistency | yes | no real snapshot claimed |
| 6 | yes | Sol adapter semantics plus separate scope reviewer | yes | no real provider PASS claimed |
| 7 | engineering yes | Sol environment/replay | yes | real `MATCH` waits for isolation/fresh-target evidence |
| 8 | no | seven lenses plus one final Astra audit | yes | every missing external artifact pauses explicitly |

For Tasks 1-7, use Terra for ordinary typed/plumbing work and Luna for finite
inventories where useful; Sol owns difficult temporal, rights, completeness,
adapter, and replay semantics. Use fresh/minimal child contexts and no overlapping
file ownership. Do not poll workers frequently. The Sol High root reads reviewer
evidence and verifies material claims itself before accepting a task.

## 5. Compatibility and forbidden-scope gates

Every accepted task runs the current full repository gate exactly once after
review. Task-focused iterations precede it. The following compatibility tests
must stay green throughout:

```text
tests/integration/test_replay.py
tests/integration/test_m1_m0_compatibility.py
tests/integration/test_m1b_m1a_compatibility.py
tests/integration/test_m1c_pinned_replay.py
tests/integration/test_m1d_pinned_replay.py
tests/integration/test_m1d_compatibility.py
```

Task 1 adds `tests/integration/test_m1e_compatibility.py`; Task 8 completes its
terminal-state assertions. It must verify:

- literal M0-M1d protected source/fixture identities;
- actual archived M1c and M1d execution, not hash-only or skipped tests;
- no old fixture rebind, narrowed fingerprint, monkeypatch, or regenerated hash;
- only the exact M1e module/test/script allowlist was added;
- `pyproject.toml` and `uv.lock` remain at the planning baseline unless a
  separately approved dependency change exists;
- provider networking and credential reads exist only in the exact conditional
  acquisition script, never under `src/drift` or the adapter;
- no evaluator, backtester, returns, holdings, cash, costs, slippage, portfolio,
  optimizer, risk, broker, order, trading, ML, agent, stream, recurring ETL,
  database, object-store service, or cloud-deployment capability;
- no real/private bytes, confidential contract, credential, auth header, cookie,
  signed URL, private root, or personal identifier is tracked;
- M1e outputs cannot satisfy old M1b-M1d references without exact replay;
- lifecycle docs, this plan, spec, and ADR agree on completion state.

Search hits are inspected by behavior; names in documentation, enums, negative
tests, or forbidden lists are not runtime capabilities.

## 6. Material implementation stop conditions

Stop, preserve verified work, and request user review if implementation finds:

1. M1e must split into multiple milestones;
2. any persisted M0-M1d contract/source/fixture must change;
3. rights requirements conflict with exact replay;
4. the chosen source requires semantics incompatible with M1b-M1d;
5. database or service object storage becomes necessary;
6. OCI/containerization becomes required rather than optional fallback;
7. any new runtime or provider dependency is required;
8. two materially different source-composition choices remain tied;
9. evaluator semantics are needed to decide M1e correctness;
10. scope must expand beyond the bounded pilot;
11. destructive deletion is legally required.

For item 11, identify the exact files and legal evidence, obtain file-specific
user approval, prefer recoverable handling when permitted, record deletion and
certification evidence, and never issue a broad recursive delete.

A normal provider/profile `FAIL`, `PARTIAL`, or `UNKNOWN` is not an architecture
stop. Preserve it and follow the evidenced-negative completion branch.

## 7. Planning-to-implementation handoff

A fresh implementation root must first run Resume and verify the planning commit,
then use `superpowers:subagent-driven-development` or
`superpowers:executing-plans`. The implementation authorization must say whether
to continue automatically through Tasks 1-7 and must not imply permission to
purchase, accept terms, contact vendors, acquire restricted data, or run Task 8
without its explicit gates.

The external evidence package required before Task 8 can fully execute is:

1. subscriber legal entity and provider-defined user/use classification;
2. actual authorized user, machine, service-provider, CI/cloud, backup, and
   storage inventory;
3. entitlement evidence for any candidate;
4. exact executed agreement topology and human/legal adjudication;
5. explicit approved private store and storage-control evidence;
6. exact independent truth bytes, receipts, origin, rights, availability,
   extraction decisions, typed claims, and frozen G01-G18 instance manifest;
7. selected provider product, publisher, schema, methodology, scope, and native
   delivery mechanism;
8. pre-request expected inventory, acquisition plan, and explicit approval for
   the exact bounded acquisition;
9. provider-native delivered bytes, byte graph, origin, and completeness
   evidence;
10. system-level macOS/arm64 isolation and clean-target plans;
11. post-run attempt-bound offline/fresh-target attestations;
12. new replay-time entitlement/rights evidence;
13. terminal or `PENDING` `ExternalDependencyResolutionV1` for each unavailable
   human/provider artifact.

## 8. Execution record

Planning status at publication: all eight tasks are unstarted. No provider is
selected; no entitlement, rights PASS, acquisition authorization, real snapshot,
adapter, environment closure, replay result, or evaluator authorization exists.
Future task acceptance entries must record exact commit, focused RED/GREEN
evidence, full gate, reviewer findings/fixes, external artifacts used, and
Checkpoint result. Do not duplicate the plan into a continuity database.

### Task 1 accepted, 2026-09-13

Task 1 pinned accepted M1d v3 replay before any M1e production source. Its
implementation commits are `1c647bf` (`test: pin accepted M1d v3 replay`),
`8aa74a0` (`test: harden M1e compatibility guard`), and `333f142`
(`test: defer M1e acquisition boundary`). No provider, entitlement, rights
PASS, acquisition, real snapshot, environment closure, replay result, or
evaluator capability was introduced.

- RED evidence: a temporary `af75cce` archive with one harmless added Python
  file failed M1d v3 replay because the whole-package implementation fingerprint
  changed; the initial pinned-lane tests failed while the helper and literal
  inventory were absent. Review fix round 1 then failed for absent history and
  partitioned-guard behavior; fix round 2 failed because the acquisition script
  still allowed network and credential access before Task 8.
- GREEN evidence: the required Task 1 focused gate passed `43` tests. The final
  full repository gate passed `1,657` tests in `1,240.02` seconds. `uv run ruff
  check .`, `uv run ruff format --check .`, `uv run mypy src tests`, and `uv
  build` passed. The focused review-fix checks also passed. Post-acceptance fix
  round 3 mechanically formatted the M1e compatibility guard; its 10 affected
  tests passed, Ruff passed, `uv run ruff format --check .` reported 157 files
  already formatted, and mypy passed for the touched test.
- Review and closure: three review-fix rounds hardened future-source history,
  script partitioning, alias-aware process and dynamic-execution rejection, and
  the pre-Task-8 network and credential boundary, then closed the formatter gap.
  Final review found no open Critical or Important finding. The deferred Minor
  remains noted and was not changed in Task 1.
- External artifacts: none. The archived M1d input inventory binds
  `af75cce0f763de025f8ae3516577a9d0a1acead9`; M1e production source remains
  absent. Task 2 remains unstarted.

### Task 2 accepted, 2026-09-13

Task 2 added immutable purpose-specific qualification profiles, bounded scope,
dimension results, truthful target states, negative reports, external dependency
and content disposition records, and the initial two-purpose pilot state. Its
implementation commits are `1c25708` (`feat: add M1e qualification lifecycle`),
`5878d1d` (`fix: restrict M1e lifecycle authority`), and `01ba5fe` (`fix:
restrict M1e persisted stages`). No provider, entitlement, rights PASS,
acquisition, real snapshot, environment closure, replay result, evaluator, or
trading capability was introduced.

- RED evidence: initial contract and lifecycle collection failed with two
  missing-module errors before production code existed. The first adversarial
  review added uncovered scope, purpose, reachability, and receipt-continuity
  cases and produced `9 failed, 27 passed`. Fix round 1 then produced `10 failed,
  21 passed`, proving generic caller-labeled future-stage advancement, direct
  terminal construction, incomplete replay reachability, and nondeterministic
  report metadata. Fix round 2 produced `14 failed, 8 deselected`, proving every
  direct `RIGHTS_ASSESSED`-through-`REPLAYED` purpose state and aggregate pilot
  state was still constructible without typed verifier output.
- GREEN evidence: the final Task 2 focused gate passed `62` tests, and Task 1
  M1e compatibility plus pinned M1d replay passed `10` tests. The independently
  run final full repository gate passed `1,704` tests. `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run mypy src tests`, `uv build`, and `git
  diff --check` passed; formatting reported `162` files and mypy reported no
  issues in `127` source files.
- Review and closure: fix round 1 removed generic stage-artifact labels and
  future-stage transition authority, rejected Task 2 terminal state and
  completion construction, required all first 11 dimensions to be reached
  before replay is reached, removed the incorrect all-12-dimensions-PASS rule,
  and made negative report metadata explicit and deterministic. Fix round 2
  independently rejected later-stage values embedded directly or through an
  unchecked nested purpose state. Final independent review found no open
  Critical or Important finding.
- Controller ruling: Task 2 exposes only verified `PROFILE_FROZEN` advancement
  using the actual `PilotProfileSetV1`, exact purpose profile, and frozen
  golden-case manifest identity. Tasks 3 through 7 add only their own typed
  verifier-backed transitions. Task 7 alone owns terminal completion.
- External artifacts: none. Task 3 is next and remains unstarted. Task 3 must own
  the typed `RIGHTS_ASSESSED` advancement and may not reuse generic Task 2
  transition authority.

### Task 3 accepted, 2026-09-14

Task 3 added the rights topology (contract documents, precedence,
classification, parties and service providers), per-question rights
assessments, prospective content-rights policies with later per-object
bindings, purpose-separated acquisition eligibility, externally evidenced
acquisition approval and authorization, and independent per-purpose replay
authorization. Its implementation commits are `4364e9b` (`feat: gate M1e
data rights`), `10fecd9` (`fix: close M1e rights authority gaps`), and
`8e15531` (`fix: preserve M1e rights topology continuity`). No provider,
credential, acquisition adapter, network access, real byte, evaluator, or
trading capability was introduced. No function converts marketing, account
access, a download, or a syntactically valid hash into `ALLOWED`.

- RED evidence: Step 1 and Step 2 tests failed before the Task 3 modules
  existed (missing `drift.domain.rights` and `drift.qualification.rights`).
  Subsequent focused runs reproduced seven material rights/authority defects
  from the first independent review (denied-purpose bindings, scope widening,
  legal-party substitution, adjudication substitution between stages,
  hash-only object binding, unsafe confidential locators, and unresolved
  negative-answer evidence) and three residual defects (party validation too
  strict for upstream publishers, sibling assessment substitution escaping
  continuity checks, and confidential locator validation skipping
  not-applicable nodes).
- GREEN evidence: the final focused gate passed `91` tests
  (`test_rights_assessment.py`, `test_replay_authorization.py`,
  `test_provenance_references.py`). The final full repository gate passed
  `1,740` tests in 2,671.01 seconds. `uv run ruff check .`, `uv run ruff
  format --check .` (`166` files), `uv run mypy src tests` (no issues in
  `131` source files), `uv build`, and `git diff --check` passed. The final
  gate ran against the reviewed Task 3 implementation at `8e15531` with no
  tracked working-tree changes.
- Review and closure: a fresh independent rights reviewer found seven
  material Critical/Important findings; fix round 1 (`10fecd9`) closed four
  and fix round 2 (`8e15531`) closed the remaining three. The final
  independent review reported the implementation clean with no open Critical
  or Important finding.
- Controller ruling: Task 3 owns the typed `RIGHTS_ASSESSED` advancement.
  Acquisition authority requires `AcquisitionEligibilityV1` plus externally
  evidenced `AcquisitionApprovalV1`; replay authority is a separate
  purpose-specific decision never inferred from acquisition-time authority.
  Task 4 next adds only typed acquisition/evidence-gathering behavior.
- External artifacts: none. Task 4 is next and remains unstarted. Task 4 must
  own the typed `ACQUIRED` advancement and may not reuse Task 3 rights
  authority.

### Task 4 accepted, 2026-09-14

Task 4 added exact acquisition receipts, byte-layer identity (`ByteLayerKind`,
`ByteObjectV1`, `ByteTransformationV1`, `NativeByteGraphV1`), provider-native
layer rules, request and origin evidence, page and retry receipts, expected
vs observed inventory reconciliation, secret screening, transactional private
content storage (`PrivateStoreSession`, directory fsync, quarantine, and recovery),
and the typed verifier-backed transition to `PilotStage.ACQUIRED`.
No external network, provider credentials, provider SDKs, real market data,
evaluator, or trading capability was introduced.

- RED evidence: Initial imports failed before domain and qualification modules
  existed. Dedicated tests proved closed-world completeness failures on missing
  or undeclared objects, cursor loops, unclosed pagination, duplicate objects,
  secret/credential leakage, symlink escapes, uncommitted transaction leakage,
  and unauthorized lifecycle advancement. Subsequent adversarial review caught
  ast-forbidden network imports in production (`urllib`), in-place mutation of
  in-degrees during Kahn's topological sort causing false graph rejection, and
  lifecycle stage classification inconsistencies.
- GREEN evidence: The focused gate passed 83 tests (`test_acquisition_receipts.py`,
  `test_acquisition_reconciliation.py`, `test_private_content_store.py`,
  `test_m1e_lifecycle.py`, and `test_m1e_compatibility.py`). The full repository gate
  passed 1,797 tests in 1,210.73 seconds. `uv run ruff check .`, `uv run ruff format --check .`
  (172 files), `uv run mypy src tests` (no issues in 137 source files),
  `uv build --offline`, and `git diff --check` passed. No em dashes (U+2014) exist in
  the tree.
- Review and closure: An independent adversarial review verified the byte-layer
  identity invariants, closed-world reconciliation completeness, path confinement,
  fsync commit order, quarantine recovery, and lifecycle gating. All findings
  were remediated, verified against the repository, and proven by passing tests.
- Controller ruling: Task 4 owns the typed `ACQUIRED` advancement. Advancement
  strictly requires `AcquisitionReconciliationV1` with completeness `PASS`, matching
  authorization and inventory hashes, native layer rules matching profile set hash,
  request scope consistency, and limits enforcement. Task 5 next adds exact real-source
  snapshots and replay-input closure.
- External artifacts: none. Task 5 is complete. Task 6 is next and remains unstarted.

### Task 5 accepted, 2026-09-14

Task 5 added exact real-source snapshot contracts (`RealSourceSnapshotV1`,
`real_source_snapshot_hash`), closed-world replay-input closure (`ReplayInputKind`
across all 12 closed categories, `CanonicalReplayInputEntryV1`, `RawReplayInputEntryV1`),
cross-component temporal consistency rules (`SourceComponentRole`, `ConsistencyStatus`,
`TemporalBoundaryClaimV1`, `ProviderReleaseEvidenceV1`, `CoordinatedCutoffRuleV1`,
`CrossComponentConsistencyDecisionV1`), safe content-addressed artifact reference
binding (`drift+sha256://<hash>`), snapshot builders, location-neutral verifiers
executing public M1b/M1c/M1d contract validators, and the typed verifier-backed
transition to `PilotStage.SNAPSHOT_FROZEN`.
No external network, provider credentials, provider SDKs, real market data,
evaluator, or trading capability was introduced.

- RED evidence: Snapshot identity tests proved that any semantic mutation (rights,
  receipt ordering, byte layers, release ID, source times, cutoff rules, coverage
  assertions, schema/methodology, adapter identity, validation decisions, queries,
  contexts, grading evidence, expected outputs) changes snapshot hash or fails
  verification. Cross-component consistency tests proved fail-closed behavior on
  uncoordinated vintages, malformed ISO cutoffs, undeclared component roles, and
  decision hash tampering. Context integrity tests proved that dummy or mutated M1b,
  M1c, and M1d contexts fail verification without trusting caller-supplied claims.
- GREEN evidence: The focused gate passed 51 tests (`test_source_snapshots.py`,
  `test_cross_component_consistency.py`, `test_m1e_lifecycle.py`) and 178 tests in
  adjacent unit suites. The full repository gate passed 1,828 tests in 1,214.68
  seconds. `uv run ruff check .`, `uv run ruff format --check .` (176 files),
  `uv run mypy src tests` (no issues in 141 source files), `uv build --offline`,
  and `git diff --check` passed. No em dashes (U+2014) exist in the tree.
- Review and closure: A fresh independent adversarial reviewer attacked snapshot
  identity, location neutrality, cross-component temporal consistency, closed-world
  replay closure, context integrity, and lifecycle gating. The review produced 4
  Critical, 5 Important, and 3 Minor findings (SEC-M1E-01 through SEC-M1E-12) and
  test suite gaps (SEC-M1E-T1). All findings were remediated: self-excluding decision
  hashing, location URI format enforcement, strict temporal string parsing,
  full 12-category replay closure, authentic context validation via existing public
  verifiers, grading evidence separation, and lifecycle receipt provenance binding.
  All remediations were verified against the repository and proven by passing tests.
- Controller ruling: Task 5 owns the typed `SNAPSHOT_FROZEN` advancement. Advancement
  strictly requires `RealSourceSnapshotV1` verification against exact retained bytes,
  re-evaluation of cross-component temporal consistency, closed-world replay closure,
  public validation of authentic M1b, M1c, and M1d resolution contexts, and matching
  profile set and receipt provenance in pilot state. Task 6 next adds the provider-neutral
  adapter boundary, qualification harness, and golden cases.
- External artifacts: none. Task 5 is complete.

### Task 6 accepted, 2026-09-14

Task 6 added the provider-neutral adapter boundary (`AdapterIdentityV1`,
`FieldMappingDecisionV1`, `ProviderMappingReportV1`, `CandidateContextBlueprintV1`,
`QualifiedSourceHandoffV1`), candidate validation dispatcher executing unchanged
public M1b/M1c/M1d contract validators (`validate_candidate_facts`), golden case
domain contracts and exact predicate operators covering Table 1401 G01 through G18
(`GoldenCaseDefinitionV1`, `IndependentTruthClaimV1`, `TruthIntakeReceiptV1`,
`TruthExtractionDecisionV1`, `PredicateOperator`, `evaluate_predicate`), the
independent golden case grader and verifier (`grade_golden_case`, `verify_golden_case_result`),
the qualification harness evaluating all 11 pre-replay dimensions (`qualify_source`,
`verify_qualification_report`), and the local-only truth intake script
(`scripts/intake_m1e_truth.py`).
No external network, provider credentials, provider SDKs, real market data,
evaluator, or trading capability was introduced.

- RED evidence: Golden case predicate tests proved fail-closed behavior across all
  9 predicate operators: non-matching values return FALSE; unreached records or
  missing coverage on REQUIRED_ABSENT return UNKNOWN; unsupported native types return
  UNSUPPORTED; and status determination strictly follows FAIL > UNKNOWN > PARTIAL > PASS.
  Tampering with golden case results or report content hashes fails verification.
  Forbidden inferences (ticker minting identity, daily minting regular session, etc.)
  cannot be mapped as clean lossless mappings. Candidate datasets failing public
  M1b/M1c/M1d validators are rejected.
- GREEN evidence: The focused gate passed 29 tests (`test_qualification_adapter_boundary.py`,
  `test_golden_case_contracts.py`, `test_truth_evidence.py`, `test_qualification_harness.py`).
  The full repository gate passed 1,857 tests in 1,245.04 seconds. `uv run ruff check .`,
  `uv run ruff format --check .` (186 files), `uv run mypy src tests` (no issues in
  150 source files), `uv build --offline`, and `git diff --check` passed. No em dashes
  (U+2014) exist in the tree.
- Review and closure: Two independent adversarial reviews attacked provider semantics,
  golden cases G01-G18, Table 1401 predicate mapping, truth intake provenance, evaluator
  leakage, harness integrity, and scope confinement. The review identified 5 Critical,
  5 Important, and 4 Minor findings across domain models, adapter validation, harness
  dimension coverage, golden case predicate extraction, and truth intake scripts.
  All findings were remediated: explicit truth claim selectors and expected constants
  on G01-G18; canonical domain field alignment; required coverage passing checks on
  absence predicates; safe cross-format instant comparisons; candidate record extraction
  bound via claim bindings; canonical PreReplayQualificationReportV1 evaluation covering
  all 11 pre-replay dimensions; snapshot-bound enforcement and snapshot hash verification;
  profile set hash binding; expected inventory hash enforcement on truth receipts; and
  local-only script execution. All remediations were verified against the repository
  and proven by passing tests.
- Controller ruling: Task 6 owns the qualification harness and adapter boundary.
  The qualification report evaluates all 11 pre-replay dimensions, requiring passing
  public contract validation, matching snapshot hashes, and verified golden cases.
  Task 7 next adds the macOS/arm64 environment closure, offline attestations, and replay.
- External artifacts: none. Task 7 is complete below.

### Task 7 accepted, 2026-09-15

Task 7 added the macOS/arm64 environment closure contracts and verifiers
(`EnvironmentArtifactKind`, `EnvironmentArtifactV1`, `PythonRuntimeIdentityV1`,
`PackageArtifactV1`, `SystemLibraryIdentityV1`, `PlatformIdentityV1`,
`EnvironmentClosureV1`, `build_environment_closure`, `verify_environment_closure`),
the offline and replay contracts (`OfflineControlStatus`, `ReplayOutcome`,
`OfflineProbeResultV1`, `IsolationExecutionPlanV1`, `CleanTargetPlanV1`,
`SystemOfflineAttestationV1`, `FreshRestoreAttestationV1`,
`ReplayComparisonPolicyV1`, `ReplayRequestV1`, `ReplayAttemptEnvelopeV1`,
`ReplayExecutionRecordV1`, `ReplayResultV1`, `verify_system_offline_attestation`,
`verify_fresh_restore_attestation`, `execute_replay`, `finalize_replay_result`,
`compare_replay_outputs`, `finalize_qualification_report`), the terminal
completion and negative evidence framework (`PositivePurposeTerminalBundle`,
`ProfileExternalNegativeEvidence`, `RightsNegativeEvidence`,
`AcquisitionNegativeEvidence`, `SnapshotNegativeEvidence`,
`QualificationNegativeEvidence`, `ReplayAuthorizationNegativeEvidence`,
`ReplayNegativeEvidence`, `NegativePurposeTerminalBundle`, `finalize_pilot`,
`require_qualified_purpose`, `build_qualified_source_handoff`,
`derive_qualified_reference_inventory`), and the local-only scripts
(`scripts/capture_m1e_environment.py`, `scripts/replay_m1e_offline.py`).
No external network, provider credentials, provider SDKs, real market data,
evaluator, or trading capability was introduced.

- RED evidence: Mutation tests proved fail-closed behavior across all 19
  `EnvironmentArtifactKind` categories and every `EnvironmentClosureV1` field.
  `SystemOfflineAttestationV1` rejects package-manager flags alone.
  `FreshRestoreAttestationV1` rejects inherited state. `finalize_replay_result`
  enforces Table 1775 outcome hierarchy and rejects mismatched or predated
  attestations. `finalize_pilot` rejects non-MATCH outcomes in positive bundles,
  requires two distinct purpose bundles, and table-tests all 7
  `NegativeStageEvidence` variants against their mandatory blocker dimensions.
  `execute_replay` enforces rights, platform compatibility, semantic identity,
  and source byte availability before process execution.
- GREEN evidence: Focused suite passed 49 tests (`test_environment_closure.py`,
  `test_replay_authorization.py`, `test_m1e_offline_replay.py`,
  `test_m1c_pinned_replay.py`, `test_m1d_pinned_replay.py`). The full repository
  gate passed 1,882 tests in 1,232.90 seconds. `uv run ruff check .`,
  `uv run ruff format --check .` (194 files), `uv run mypy src tests` (no issues in
  156 source files), `uv build --offline` (sdist and wheel built), and
  `git diff --check` passed. Zero em dashes (U+2014) exist in the diff.
- Review and closure: An independent adversarial review attacked environment closure
  completeness, system offline truth, fresh target truth, process boundaries,
  evaluator confinement, replay outcome hierarchy, and terminal completion.
  All findings were resolved and verified: `finalize_pilot` correctly validates
  both positive and negative bundles; `derive_qualified_reference_inventory`
  uses deterministic UUIDv7 and strictly filters for purpose-authorized canonical
  inputs while rejecting raw input bytes; `build_qualified_source_handoff` sets
  target hash from target content hash; Table 1775 outcome hierarchy evaluates
  probe results, process tree identity, and target identity; child process
  environment is strictly confined to `ALLOWED_ENV_VARS`; and verification
  functions require verified evidence backing.
- Controller ruling: Task 7 completes the macOS/arm64 environment closure, offline
  attestations, and deterministic replay harness. Task 8 (license-gated pilot
  execution) requires explicit user authorization and external inputs and remains
  unstarted.
- External artifacts: none. Task 8 is license-gated and unstarted.

## 9. Planning review and publication verification

Sol High owned the architecture/decomposition pass. A Terra repository mapper
and Luna inventory pass checked real module, fixture, test, and golden-case
conventions. Three fresh Sol reviews covered all seven mandated lenses: rights
and negative completion; acquisition and snapshot identity; adapter/M1b-M1d;
environment and offline replay; real golden evidence; evaluator/scope leakage;
and implementation practicality/external pauses. The controller verified each
finding against the actual repository.

The review loop corrected: the M1d whole-package fingerprint seam; profile/
snapshot and report/replay cycles; purpose cardinality; true offline evidence;
pre-request expected inventory; acquired-unsnapshotted state; legal/approval
evidence resolution; mixed-purpose finalization; stage-specific negative
evidence; content disposition; byte-layer graphs; transactional store recovery;
candidate context reconstruction; per-record mapping lineage; truth receipts,
claims and predicate semantics; authorized-profile propagation; final environment
recapture; handoff reference derivation; and three remaining canonical cycles in
golden selectors, rights bindings, and truth extraction. The final bounded Astra
audit approved the repaired plan with no open Critical or Important finding.

Publication verification on 2026-09-13:

- `uv run pytest`: 1,649 passed in 1,203.70 seconds.
- Explicit M0-M1d compatibility plus M1c pinned and M1d archived/current replay
  selection: 43 passed in 412.03 seconds. The dedicated M1d v3 pinned lane does
  not exist yet; Task 1 creates it before any M1e source. The present gate runs
  the repository's accepted v1/v2 archived and current authenticated v3 paths.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: 154 files formatted after one plan-only blank-
  line correction.
- `uv run mypy src tests`: passed with no issues in 119 source files.
- `uv build`: source distribution and wheel built.
- `git diff --check`, local documentation links, single-M1e-plan inventory,
  lifecycle/stale-text, U+2014, and planned-path scope checks passed.
- No runtime, test, fixture, script, dependency, lockfile, provider data,
  credential, environment bundle, or evaluator change exists in the planning
  diff.
