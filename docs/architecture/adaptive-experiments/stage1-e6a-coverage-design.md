# E6A: Immutable synthetic checkpoint coverage and B/R pairing

## 0. Authority, owner decisions and status

- **Architecture and decision issue:** [#479](https://github.com/KanujVerma/drift/issues/479). Kanuj explicitly approved decision **E6A-A** on October 19, 2026: an expected slot with no submitted provenance snapshot is `MISSING_SNAPSHOT` and **must not** be replaced with a fabricated `UNOBSERVED` provenance snapshot.
- **Accountable owner:** Kanuj / `workstream:kanuj`. Design writer: ChatGPT under authenticated GitHub publisher `KanujVerma`. This is a one-file proposed docs-only change, not a product-code grant or G3 eligibility claim.
- **Exact docs write-set:** only this NEW file, `docs/architecture/adaptive-experiments/stage1-e6a-coverage-design.md`. Base when drafted: `ceef25ed4fd5f324628760c2e0e8c221f704f4d8`. Re-read live main before implementation.
- **Accepted foundations:** E1 immutable config [#462 / PR #463](https://github.com/KanujVerma/drift/pull/463); trial-event integrity [#448 / PR #455](https://github.com/KanujVerma/drift/pull/455); producer-neutral trial provenance TP-A to TP-E [#468 / PR #471](https://github.com/KanujVerma/drift/pull/471), runtime [#472 / PR #477](https://github.com/KanujVerma/drift/pull/477). Relevant accepted logic exists in `src/drift/experiments/stage1_campaign_config.py`, `stage1_trial_events.py`, `stage1_trial_provenance.py` and `drift.serialization.canonical.content_hash`.
- **Future broader integration:** [#383](https://github.com/KanujVerma/drift/issues/383) remains blocked on producer interfaces and accepted scientific/market policy. E6A's pair coverage is not a `TrialRecordV1`, trading ledger, real schedule or comparative performance report.

The Stage 1 primary comparison eventually concerns Arm B versus Arm R over the same fixed B3/B4/B5 choice menu. **This structural component stays general**: get the primary IDs from `CampaignSpecV1.primary_comparison` and cover all configured arms (including auxiliary controls) without replacing or authorizing a producer decision.

**Scientific separation:** An explicit checkpoint is merely a caller-declared synthetic slot, not an independently qualified market decision date, operational permission or the denominator `ScheduledArmCheckpointOpportunities` in the scientific methodology. The report may say "12 declared synthetic slots" or "six configured B/R pairs", not six actual research opportunities.

## 1. Decision E6A-A and rejected alternatives

Exactly three **synthetic audit slot** statuses:

| Coverage status | Actual supplied immutable provenance snapshot | Interpretation |
| --- | --- | --- |
| `MISSING_SNAPSHOT` | `None` | Expected slot declared but **no snapshot submitted** |
| `UNOBSERVED` | Exact valid snapshot with zero event envelopes | A submitted content-addressed structural record contains **zero recorded events** |
| `EVENTS_RECORDED` | Exact valid snapshot with one or more verified event envelopes | Events exist and hash-link correctly, but their producer payloads are **not authenticated** |

Do not populate `MISSING_SNAPSHOT` by calling `build_stage1_trial_provenance_snapshot(..., events=[])`. That would invent a hash/evidence artifact and erase an ingestion gap. This is the owner's rejected **Option B**. `MISSING_SNAPSHOT` does not alter `stage1_trial_provenance.PROVENANCE_STATES`; it exists only in the new coverage layer.

**Pairing tracks whether two snapshots were *submitted*, not event completion or trade success.** Four pair statuses are derived from missing slots: `BOTH_SUBMITTED`, `TEST_MISSING`, `COMPARATOR_MISSING`, `BOTH_MISSING`. A submitted `UNOBSERVED` counts as submitted even though it has zero events. An incoming `RESULT_BOUND` or `TRIAL_FINALIZED` event label does not convert this into a scientific `COMPLETE` / verified RESULT.

**Other rejected alternatives:** silently dropping missing slots; dynamically resolving arbitrary producer payloads; duplicate snapshot last-write-wins; hardcoded B/R-only arm universe; using ordinal run IDs as market calendar evidence; storing mutable slot dictionaries or empty zero-cost/zero-return defaults.

## 2. Exact proposed two-file implementation boundary, once separately authorized

- `src/drift/experiments/stage1_checkpoint_coverage.py`
- `tests/unit/test_stage1_checkpoint_coverage.py`

These paths are *reserved only in the future separate implementation issue*. No existing source, tests, `__init__.py`, Krish or Matthew producer modules, canonical serializer, interpreter pin, lockfile, CI files, strategy policies or data permissions may change. Only synthetic/offline, in-memory local evaluation and immutable value objects.

Use `from __future__ import annotations`, dataclasses with `frozen=True, slots=True`, exact built-in leaf types and immutable tuples, and only the already accepted `content_hash` for all canonical hashes. Existing public E1 and provenance verifiers must be reused without modification. No wall-clock defaults.

The exact public types, with **no defaults**:

```python
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from drift.experiments.stage1_campaign_config import (
    ArmSpecV1,
    CampaignSpecV1,
    RunAccountBindingV1,
)
from drift.experiments.stage1_trial_provenance import (
    Stage1TrialProvenanceSnapshotV1,
)

COVERAGE_SCHEMA_VERSION = "drift-stage1-coverage/1-draft"
CHECKPOINT_MANIFEST_SCHEMA_VERSION = "drift-stage1-checkpoint-manifest/1-draft"
COVERAGE_STATES = frozenset(
    {"MISSING_SNAPSHOT", "UNOBSERVED", "EVENTS_RECORDED"}
)
PAIR_STATES = frozenset(
    {"BOTH_SUBMITTED", "TEST_MISSING", "COMPARATOR_MISSING", "BOTH_MISSING"}
)


@dataclass(frozen=True, slots=True)
class Stage1RunCheckpointDeclarationV1:
    run_id: str
    checkpoint_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Stage1CoverageSlotV1:
    run_id: str
    checkpoint_id: str
    arm_id: str
    trial_id: str
    coverage_state: str
    provenance_snapshot: Stage1TrialProvenanceSnapshotV1 | None


@dataclass(frozen=True, slots=True)
class Stage1PairCoverageV1:
    run_id: str
    checkpoint_id: str
    test_arm_id: str
    comparator_arm_id: str
    pair_state: str


@dataclass(frozen=True, slots=True)
class Stage1CoverageCountsV1:
    declared_slots: int
    missing_snapshots: int
    unobserved_snapshots: int
    events_recorded_snapshots: int
    submitted_snapshots: int
    declared_pairs: int
    both_submitted_pairs: int


@dataclass(frozen=True, slots=True)
class Stage1CheckpointCoverageAuditV1:
    schema_version: str
    campaign_id: str
    campaign_spec_fingerprint: str
    complete_manifest_fingerprint: str
    checkpoint_manifest_fingerprint: str
    checkpoint_declarations: tuple[Stage1RunCheckpointDeclarationV1, ...]
    slots: tuple[Stage1CoverageSlotV1, ...]
    pairs: tuple[Stage1PairCoverageV1, ...]
    counts: Stage1CoverageCountsV1
    audit_fingerprint: str
```

No alternate public "verified schedule", "scientific completeness", PnL, cost, calendar, data grade or producer annotation fields. The immutable audit retains **complete validated detached provenance snapshots** in the slots, not just hashes, preserving future adapter inspection without editing older records.

## 3. Exact public APIs

```python
def build_stage1_checkpoint_coverage_audit(
    *,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
    checkpoint_declarations: Sequence[Stage1RunCheckpointDeclarationV1],
    submitted_snapshots: Sequence[Stage1TrialProvenanceSnapshotV1],
) -> Stage1CheckpointCoverageAuditV1: ...


def verify_stage1_checkpoint_coverage_audit(
    *,
    audit: Stage1CheckpointCoverageAuditV1,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
) -> bool: ...
```

`verify` returns exact Boolean `True` only on genuine structurally valid input; **all invalid originals raise `ValueError`**. It never silently normalizes corrupted stored data and never rewrites existing event/manifest/provenance fingerprints. Builder/verifier cannot claim authenticated external accounts or a scientific comparison.

No "append" API required: a future audit revision is built as a **new immutable audit** from the original declarations and updated sparse snapshot collection; existing audit and snapshot fingerprints remain stable.

## 4. Complete E1 run/arm/account and checkpoint-declaration admission

1. Invoke `verify_experiment_configuration(campaign=campaign, arms=arms, bindings=bindings, expected_run_ids=expected_run_ids)` before processing both new builds and stored audits. Every expected run must have exactly the complete set of configured arms and distinct local account identities. Reject incomplete, duplicate or added bindings as E1 already requires.
2. Compute the **full E1 manifest SHA** from already validated E1 records using the exact approved `drift-trial-manifest/1-draft` logical preimage from the merged [Stage 1 trial provenance design Section 5](stage1-trial-provenance-design.md). Include campaign fingerprint, lexicographically sorted complete expected-run IDs, lexicographically sorted complete arm spec fingerprints, and **every eight-field E1 binding** ordered by `(campaign_id, run_id, arm_id)`. Use `content_hash`; no second canonical serializer, and do NOT import the private provenance implementation helper (`_complete_manifest_fingerprint`).
3. **Reason for that narrow local manifest-preimage duplication:** an all-missing coverage audit has **no** trial snapshot from which to read an existing manifest digest. An E6A consumer therefore must compute identical public *contract data* independently while preserving the same canonical fingerprint. Reusing a private implementation helper would be fragile. Pin a test proving E6A's computed SHA equals every newly built/verified submitted provenance snapshot's `scope.complete_manifest_fingerprint` and the independent known E1 golden. Future change to this logical manifest is versioned, never silently altered.
4. Require `checkpoint_declarations` is a non-string, non-mapping `Sequence` of **exact** `Stage1RunCheckpointDeclarationV1` objects. Require `type(x.checkpoint_ids) is tuple` and each ID to be exact built-in `str` matching the existing ASCII scope-token regex `[A-Za-z0-9][A-Za-z0-9._-]*`. Each run declaration has **at least one** checkpoint; checkpoint IDs are unique **within a run** (reuse across runs is expected). No random, guessed or inferred dates.
5. Exactly one checkpoint declaration is required for **every** expected run ID, with no extra run, missing run or duplicate run. The input run declaration order is not semantically meaningful: **sort declarations by run ID** when building; preserved checkpoint tuple order within a run **is meaningful** and must not be sorted. A newly ordered checkpoint list is a *different declaration* with a different fingerprint, never a "repair".
6. Build the separately versioned **checkpoint declaration fingerprint** only after validation. A single-run or control-arm campaign remains structurally supported; two runs and three checkpoints are not universal constraints.
7. The checkpoint declaration is only syntactic/caller-declared; no statement here verifies a real trading calendar, market cutoff, source rights or scientific denominator. Requiring at least one declaration per expected run prevents an ostensibly complete synthetic run being hidden by an omitted/empty checkpoint list.

## 5. Submitted snapshot admission, identity and defensive value copy

1. Require `submitted_snapshots` is a non-string, non-mapping `Sequence`. Validate every member has exact type `Stage1TrialProvenanceSnapshotV1` and call the merged public `verify_stage1_trial_provenance_snapshot(snapshot=..., campaign=..., arms=..., bindings=..., expected_run_ids=expected_run_ids)` on **each original**. Do not skip or normalize an invalid snapshot even when another is valid.
2. Derive its slot key solely from `(snapshot.scope.run_id, snapshot.scope.checkpoint_id, snapshot.scope.arm_id)` after complete full-manifest verification. Its run, checkpoint and arm must be explicitly declared in the validated E1/checkpoint collections. An unlisted checkpoint or run, unexpected control arm, altered account, forged hash or duplicate key raises `ValueError`. A **duplicate scope key is rejected even when the two snapshots are byte-identical**, until separately accepted ingestion idempotency semantics exist.
3. For valid records, detach from caller objects by creating a **deep value copy of the known frozen dataclass tree**: new `Stage1TrialProvenanceSnapshotV1` containing a copied `Stage1TrialScopeV1`, itself containing a copied `RunAccountBindingV1`, and a new tuple containing separately copied `Stage1TrialEvent` objects. Use `dataclasses.replace` on these exact leaf/value types, not `copy.deepcopy` on arbitrary JSON or mutable extension bags. Reverify the detached copy with the public provenance verifier before placing it in the audit. A caller's later `object.__setattr__` on its own original event/binding/snapshot cannot mutate a previously built audit.
4. Populate the new coverage state from the verified submitted snapshot's exact existing `observation_state`: `UNOBSERVED` or `EVENTS_RECORDED`. Never assert authentic producer results from the event kinds.
5. The sparse submitted input order is irrelevant: output is canonically reconstructed by expected run/checkpoint/arm ordering. The audit's retained snapshot fingerprint proves its nested envelopes and complete manifest without reserializing the envelopes a second time.

## 6. Canonical slot matrix, pairs and counts

- Build **one slot per configured arm** for each declared checkpoint for each expected run. Output order is **run ID ascending**, then **checkpoint order exactly as declared** for that run, then **arm ID ascending**. The configured arms can include extra controls, which occupy their own slots but are never assigned a primary pair.
- For each expected slot, derive trial identity as `f"{campaign.campaign_id}:{run_id}:{arm_id}:{checkpoint_id}"`, exactly matching the existing provenance scope. If no submitted snapshot matches the key, create only a `Stage1CoverageSlotV1` with `coverage_state="MISSING_SNAPSHOT"` and `provenance_snapshot=None`. Do not call an event or snapshot builder for an absent slot.
- If a supplied snapshot matches, store the detached full snapshot object and derived `coverage_state`. Verify its complete trial ID, campaign/arm/binding identity and manifest hash using the merged public verifier. A valid snapshot whose arm is an extra declared control is accepted structurally.
- Build **one pair per run/checkpoint** using `campaign.primary_comparison.test_arm_id` and `.comparator_arm_id`. Output ordering follows run/checkpoint order. The IDs are checked by the E1 collection verifier. The pair states depend **only** on missing/submitted:
  - Neither submitted => `BOTH_MISSING`
  - Test missing only => `TEST_MISSING`
  - Comparator missing only => `COMPARATOR_MISSING`
  - Both submitted, including one or two `UNOBSERVED` snapshots => `BOTH_SUBMITTED`.
- Counters in `Stage1CoverageCountsV1`:
  - `declared_slots` is length of all slots, including controls.
  - `missing_snapshots`, `unobserved_snapshots`, `events_recorded_snapshots` are mutually exclusive and total `declared_slots`.
  - `submitted_snapshots = unobserved_snapshots + events_recorded_snapshots`, independent of event count.
  - `declared_pairs` is the number of per-run/checkpoint primary pairs; controls do not multiply pair counts.
  - `both_submitted_pairs` counts pairs with two actually submitted snapshots, not two event streams, results or trades.
- No percentages or success claims are needed. If displayed, any fraction must be explicitly described as **synthetic declaration submission coverage**, never a point-in-time market opportunity completion statistic.
- Require arithmetic counters to be actual non-Boolean `int` when verifying stored audit. No loose polymorphic equality on subclasses.

## 7. Exact versioned canonical hashing and golden preimages

Use existing `content_hash` directly on **plain named dict/list/str/int/None values**, canonical UTF-8 JSON. The output objects must not hold mutable dictionaries. There are three separate logical, domain-separated hashes:

**A. Complete E1 manifest:** `drift-trial-manifest/1-draft`. Reuse the exact preimage described in Section 4 and the existing provenance design. Required independent E1 fixture hashes:

- Campaign fingerprint: `2c9cad6f55847c20bf9c7f5a5eaa1ec6f828c7f107bc32ad8a1516a4b2e88be4`.
- Arm B: `84c4e89c1c1a06e4b3041f07fea316e051fd5b6b5502a5f8a3c17912db1fd831`.
- Arm R: `c958ea89ded96aa8aafad3eac1756083ec9145b041c6c6f1fae4afc9216278cd`.
- **One-run (2 binding) manifest:** `57a000a61c2cb64a64239d2e52249bbe1ddffe01fbaa2772cd03e162b5a50a29`.
- **Two-run (4 binding) manifest:** `7cd97e7e6884d608888497b8688053d51aab11edb4a43cce8c6437fa5ec16b56`.

The **two-run fixture** has expected runs `["RUN-001","RUN-002"]`, arms `["ARM-B","ARM-R"]`, four bindings sorted by (campaign, run, arm), account IDs `SYNTH-ACC-B-001`, `SYNTH-ACC-R-001`, `SYNTH-ACC-B-002`, `SYNTH-ACC-R-002`, exact cash text `"10000"` and bound timestamp `2026-10-19T00:00:02.000000Z` for each.

**B. Complete explicit checkpoint declaration:** `drift-stage1-checkpoint-manifest/1-draft`. Logical JSON preimage:

```json
{
  "schema_version": "drift-stage1-checkpoint-manifest/1-draft",
  "campaign_id": "CAMP-E1-SYNTH-001",
  "campaign_spec_fingerprint": "2c9cad6f55847c20bf9c7f5a5eaa1ec6f828c7f107bc32ad8a1516a4b2e88be4",
  "complete_manifest_fingerprint": "7cd97e7e6884d608888497b8688053d51aab11edb4a43cce8c6437fa5ec16b56",
  "runs": [
    {"run_id": "RUN-001", "checkpoint_ids": ["CKPT-001", "CKPT-002", "CKPT-003"]},
    {"run_id": "RUN-002", "checkpoint_ids": ["CKPT-001", "CKPT-002", "CKPT-003"]}
  ]
}
```

**Independent SHA-256:** `6e8ba6d836a02c0f27bc0bc67e253325c96d81a909972177f0bdb876450c79b5`. Store as `checkpoint_manifest_fingerprint` in the immutable audit. This identity binds the complete local checkpoint declaration, not venue admission.

**C. Immutable coverage audit:** `drift-stage1-coverage/1-draft`. Exact preimage keys and nested shapes:

```json
{
  "schema_version": "drift-stage1-coverage/1-draft",
  "campaign_id": "CAMP-E1-SYNTH-001",
  "campaign_spec_fingerprint": "2c9cad6f55847c20bf9c7f5a5eaa1ec6f828c7f107bc32ad8a1516a4b2e88be4",
  "complete_manifest_fingerprint": "7cd97e7e6884d608888497b8688053d51aab11edb4a43cce8c6437fa5ec16b56",
  "checkpoint_manifest_fingerprint": "6e8ba6d836a02c0f27bc0bc67e253325c96d81a909972177f0bdb876450c79b5",
  "slots": [
    {"trial_id": "CAMP-E1-SYNTH-001:RUN-001:ARM-B:CKPT-001", "coverage_state": "MISSING_SNAPSHOT", "snapshot_fingerprint": null},
    {"trial_id": "CAMP-E1-SYNTH-001:RUN-001:ARM-R:CKPT-001", "coverage_state": "MISSING_SNAPSHOT", "snapshot_fingerprint": null},
    {"trial_id": "CAMP-E1-SYNTH-001:RUN-001:ARM-B:CKPT-002", "coverage_state": "MISSING_SNAPSHOT", "snapshot_fingerprint": null},
    {"trial_id": "CAMP-E1-SYNTH-001:RUN-001:ARM-R:CKPT-002", "coverage_state": "MISSING_SNAPSHOT", "snapshot_fingerprint": null},
    {"trial_id": "CAMP-E1-SYNTH-001:RUN-001:ARM-B:CKPT-003", "coverage_state": "MISSING_SNAPSHOT", "snapshot_fingerprint": null},
    {"trial_id": "CAMP-E1-SYNTH-001:RUN-001:ARM-R:CKPT-003", "coverage_state": "MISSING_SNAPSHOT", "snapshot_fingerprint": null},
    {"trial_id": "CAMP-E1-SYNTH-001:RUN-002:ARM-B:CKPT-001", "coverage_state": "MISSING_SNAPSHOT", "snapshot_fingerprint": null},
    {"trial_id": "CAMP-E1-SYNTH-001:RUN-002:ARM-R:CKPT-001", "coverage_state": "MISSING_SNAPSHOT", "snapshot_fingerprint": null},
    {"trial_id": "CAMP-E1-SYNTH-001:RUN-002:ARM-B:CKPT-002", "coverage_state": "MISSING_SNAPSHOT", "snapshot_fingerprint": null},
    {"trial_id": "CAMP-E1-SYNTH-001:RUN-002:ARM-R:CKPT-002", "coverage_state": "MISSING_SNAPSHOT", "snapshot_fingerprint": null},
    {"trial_id": "CAMP-E1-SYNTH-001:RUN-002:ARM-B:CKPT-003", "coverage_state": "MISSING_SNAPSHOT", "snapshot_fingerprint": null},
    {"trial_id": "CAMP-E1-SYNTH-001:RUN-002:ARM-R:CKPT-003", "coverage_state": "MISSING_SNAPSHOT", "snapshot_fingerprint": null}
  ],
  "pairs": [
    {"run_id": "RUN-001", "checkpoint_id": "CKPT-001", "test_arm_id": "ARM-B", "comparator_arm_id": "ARM-R", "pair_state": "BOTH_MISSING"},
    {"run_id": "RUN-001", "checkpoint_id": "CKPT-002", "test_arm_id": "ARM-B", "comparator_arm_id": "ARM-R", "pair_state": "BOTH_MISSING"},
    {"run_id": "RUN-001", "checkpoint_id": "CKPT-003", "test_arm_id": "ARM-B", "comparator_arm_id": "ARM-R", "pair_state": "BOTH_MISSING"},
    {"run_id": "RUN-002", "checkpoint_id": "CKPT-001", "test_arm_id": "ARM-B", "comparator_arm_id": "ARM-R", "pair_state": "BOTH_MISSING"},
    {"run_id": "RUN-002", "checkpoint_id": "CKPT-002", "test_arm_id": "ARM-B", "comparator_arm_id": "ARM-R", "pair_state": "BOTH_MISSING"},
    {"run_id": "RUN-002", "checkpoint_id": "CKPT-003", "test_arm_id": "ARM-B", "comparator_arm_id": "ARM-R", "pair_state": "BOTH_MISSING"}
  ],
  "counts": {
    "declared_slots": 12,
    "missing_snapshots": 12,
    "unobserved_snapshots": 0,
    "events_recorded_snapshots": 0,
    "submitted_snapshots": 0,
    "declared_pairs": 6,
    "both_submitted_pairs": 0
  }
}
```

The audit SHA-256 **excludes its own `audit_fingerprint`**, and its `slots` entries reference only each already-verified `snapshot_fingerprint` or `null`, never the full nested envelope bytes a second time. The checkpoint manifest SHA commits the ordered checkpoint declaration while the audit retains its full frozen declaration objects.

**Independent GOLDEN A, 12 missing slots:** `4ba2fcc7cdfa78a3549efb8d7942fd70a9b5f5537db21906ea0c597ee2095ed3`.

**Independent GOLDEN B, two real submitted synthetic snapshots on RUN-001/CKPT-001:** Use a B root `Stage1TrialEvent` whose original standalone event hash is `2999edc6f859b6ef17a6b0c99728bab01d7d80cad65e28f59ffd3a5dd5a7f9f4` and an R zero-event `UNOBSERVED` snapshot. They must both bind the **two-run** manifest above, yielding:

- B `EVENTS_RECORDED` snapshot fingerprint `8e2b7a89d9c1aea9c1da6b35bebb995ae414c786c50ec6f0498c98e6c975e91a`.
- R `UNOBSERVED` snapshot fingerprint `271d5198d917597e3083f498e3c10f09871598022ebda6284f97e6a8ed033130`.

Keep the same complete 12-slot/6-pair ordering and top-level fields from GOLDEN A. Change ONLY first B slot to `{"coverage_state":"EVENTS_RECORDED","snapshot_fingerprint":"8e2b7a89d9c1aea9c1da6b35bebb995ae414c786c50ec6f0498c98e6c975e91a"}` and first R slot to `{"coverage_state":"UNOBSERVED","snapshot_fingerprint":"271d5198d917597e3083f498e3c10f09871598022ebda6284f97e6a8ed033130"}`, keeping their `trial_id` values. Change the first pair state to `BOTH_SUBMITTED`. Replace counts with `{"declared_slots":12,"missing_snapshots":10,"unobserved_snapshots":1,"events_recorded_snapshots":1,"submitted_snapshots":2,"declared_pairs":6,"both_submitted_pairs":1}`.

**Independent GOLDEN B audit SHA-256:** `87379a6e2147b3d9e1796cc90bf03fcfe32cec325c9b652b92add5270d6232da`.

The hashes above were independently computed from explicit named canonical JSON preimages using SHA-256, NOT from the proposed E6A implementation. Existing E1/provenance/event goldens must not be regenerated or modified to appease a wrong implementation hash.

## 8. Original stored audit verifier: fail closed, no repair

The verifier must validate the original supplied object, including:

- Exact type `Stage1CheckpointCoverageAuditV1`, exact schema-version built-in string, exact `Stage1CoverageCountsV1` type and all actual non-Boolean integer fields, tuple types and exact member dataclass types. Reject mutable list injection, subclasses and malformed strings.
- E1 full manifest verification against caller-supplied complete `campaign,arms,bindings,expected_run_ids`; recompute the exact E1 manifest SHA. A legitimate but different subset/superset must fail against the stored `complete_manifest_fingerprint`.
- Original `checkpoint_declarations` sorted by run ID, exact complete expected-run set, at least one checkpoint per run and order-preserving ID tuples. Recompute and match `checkpoint_manifest_fingerprint`. Do not sort a corrupted stored audit into validity.
- Every original non-null retained nested provenance snapshot verified through the public verifier against the same full E1 manifest. Its run/arm/checkpoint/trial identity must match the enclosing slot and checkpoint declaration; all actual original nested envelope/hash fields are verified, not just their stored top-level SHA.
- Original `slots` exactly in canonical matrix order, unique and complete; each has exact run/checkpoint/arm/trial ID/status and matching snapshot presence. No missing or extra slot is ignored.
- Original `pairs` exactly one per run/checkpoint in canonical order, using frozen campaign test/comparator IDs and correct derived `BOTH_SUBMITTED`/gap state. No pair based on accidental control arms.
- Original counts exactly arithmetic derived from the accepted canonical slots/pairs. No altered count/state/pair value may succeed just because attacker recomputed a matching top-level digest.
- Finally require `type(audit.audit_fingerprint) is str`, lowercase 64-hex and equal to `content_hash(_audit_preimage(audit))`.

It is permissible to construct a **temporary fully validated expected audit** to compare canonical layout **only after validating every original type and nested record**; any mismatch must raise `ValueError` instead of returning a silently normalized copy. No public mutator, writable ledger or asynchronous indexer.

## 9. Synthetic test matrix, expected outcomes and adversarial cases

**Positive:**

1. **12-all-missing golden:** 2 runs × 2 primary arms × 3 checkpoint IDs = 12 slots, 6 pairs, all `MISSING_SNAPSHOT`, exact GOLDEN A. Zero actual submitted snapshots, zero authenticated trading opportunities. Crucially, **no** provenance empty snapshot was fabricated.
2. **Mixed GOLDEN B:** B's valid one-event snapshot plus R's real valid zero-event snapshot on RUN-001/CKPT-001: states `EVENTS_RECORDED` and `UNOBSERVED`, pair `BOTH_SUBMITTED` despite zero R events; counts 10/1/1/2/6/1 and exact GOLDEN B. Existing full event envelopes remain present in B snapshot.
3. **Only B submitted, only R submitted, both missing, both submitted:** derive four pair statuses exactly, with a real zero-event snapshot considered submitted.
4. **Canonical input invariance:** reverse order of valid E1 arm/binding/run collections, checkpoint declarations by run, and sparse submitted snapshots; identical frozen audit/fingerprints. Preserve within-run checkpoint order. Changing ordered checkpoint IDs must **change checkpoint and audit fingerprints** when corresponding snapshot scopes are revalidated.
5. **Extra configured controls:** add a valid third arm/control and complete E1 bindings using existing E1 builders; total slots increase, primary B/R pairs do not multiply. The generic routine must not hardcode B/R, fixture IDs, three checkpoints or ten thousand.
6. **Unequal checkpoint sets by run:** e.g. RUN-001 has CKPT-001 and CKPT-002, RUN-002 has CKPT-001 only; exactly six slots and three B/R pairs for 2 arms. No date inference.
7. **Independent audit revisions:** previously immutable all-missing audit stays unchanged after building a new mixed/submitted audit. A caller mutating source list or original provenance/event/binding via `object.__setattr__` after construction cannot change the retained audit snapshot or hash. Rebuilding identical inputs produces identical hash.
8. **Contract matching:** full two-run manifest SHA equals approved E1 canonical hash and the submitted snapshots' stored `scope.complete_manifest_fingerprint`; a one-run separately valid manifest has its own different SHA and cannot reverify the two-run audit.

**Negative:**

1. Duplicate/unlisted/missing run declaration, empty declared checkpoint tuple for any expected run, duplicate checkpoint ID in a run, invalid colon/space/Unicode/str-subclass IDs, mutable list replacing required tuple; refuse.
2. Duplicate supplied snapshot for the same slot, including two exact identical instances; refuse without deduplication.
3. Submitted snapshot from undeclared checkpoint/run/arm/control or wrong campaign account, forged or recomputed-invalid underlying snapshot hash, invalid event chain, bad root/parent, altered manifest; refuse.
4. Legitimate E1 one-run *subset* substituted into an earlier two-run audit, or a newer valid added run, or altered nonselected account binding, even when the new manifest is self-consistent; refuse.
5. Changed frozen campaign or primary pair role, including swapped identities, without accepted updated campaign fingerprint; reject or produce distinct new audit, never reinterpret an earlier audit.
6. Original stored audit with forged `checkpoint_manifest_fingerprint`, `complete_manifest_fingerprint`, `audit_fingerprint`, reordered/omitted/duplicated slots or pairs, altered `MISSING_SNAPSHOT` into `UNOBSERVED` with `provenance_snapshot=None`, or pair status/count inconsistencies, including a recomputed top-level hash; refuse.
7. Unexpected `bool` or float in integer counters, str subclasses with lying equality in IDs/statuses/digests, dataclass subclasses and mutable injected lists; refuse with `ValueError`.
8. `RESULT_BOUND`, `COSTS_BOUND` and `TRIAL_FINALIZED` are allowed **only as integrity-verified event labels** inside real snapshots; never a reason to mark real investment performance complete or authorize scoring.
9. Reject source/campaign mutation without modifying prior audit objects; preserve correct original tuple order and all input objects on any failure.
10. No external data/broker/model request, wall clock, file persistence, producer schema or guessed market schedule is needed to run these tests.

Do not add a new `TrialRecordV1`, provider adapter, research optimizer, portfolio ledger or dynamic plugin registry. No baseline/strategy changes and no inconsistent "zero" financial results.

## 10. Implementation issue, separate PR and review gate

After this exact design doc PR passes Markdown/Ruff/link/whitespace checks, gets Codex exact-head feedback addressed, and is independently reviewed and accepted/merged, create/activate an **independently scoped implementation issue** reserving only the two proposed new Python files from Section 2.

The **architect** must encode all the classes, API signatures, canonical preimages, validation and ordering algorithms, pinned golden witnesses, adversarial test cases and current-source dependency SHA into the issue and self-contained Gemini prompt. Gemini may challenge evidence-backed contradictions without improvising new scientific/financial decisions.

For authorized implementation on accepted main:

```bash
uv run --locked --python 3.14.6 pytest -q tests/unit/test_stage1_checkpoint_coverage.py
uv run --locked --python 3.14.6 pytest -q tests/unit/test_stage1_trial_provenance.py tests/unit/test_stage1_trial_events.py tests/unit/test_stage1_campaign_config.py
uv run --locked --python 3.14.6 ruff check src/drift/experiments/stage1_checkpoint_coverage.py tests/unit/test_stage1_checkpoint_coverage.py
uv run --locked --python 3.14.6 ruff format --check src/drift/experiments/stage1_checkpoint_coverage.py tests/unit/test_stage1_checkpoint_coverage.py
uv run --locked --python 3.14.6 mypy src tests
uv build
git diff --check
```

Also run repo-required full pytest/replay, zero-new-U+2014, scope audit and hosted exact-HEAD CI. Publish a SINGLE draft PR, record exact HEAD, have architect review actual code and independent human review where appropriate, request completed Codex review at the final HEAD, then only merge with **separate owner authorization naming PR, HEAD and actor**. No auto-merge and no claim that green synthetic CI establishes market-data entitlement, G3, broker access, or producer compatibility.

## 11. Why E6A is deliberately small and future compatible

E1 ensures an isolated caller-declared campaign/run/arm/account manifest. Trial-event and provenance modules ensure a **single submitted** trial has a structurally verifiable immutable history. E6A audits the **space of declared trial slots**, separating submitted-empty from never-submitted data and making B/R pairing gaps visible. All producer-specific proposals, eligibility, mandate, data scheduling, fills, settled costs and authoritative portfolio `RESULT` remain independently versioned downstream evidence. A later E6B `TrialRecordV1` / comparative study report may consume authenticated producer-attached snapshots, but must not rewrite E6A audit fingerprints or interpret synthetic submission counts as investment evidence.
