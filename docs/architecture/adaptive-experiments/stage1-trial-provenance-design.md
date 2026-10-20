# Stage 1 immutable trial provenance: architect-approved design

## 0. Status, scope and authority

- **Architecture issue:** [#468](https://github.com/KanujVerma/drift/issues/468), owner Kanuj, decisions **TP-A through TP-E** approved on October 19, 2026.
- **Workstream:** `kanuj`, scientific experiment stewardship under ADR 0017 and issue-specific migration receipts.
- **Status:** an owner-approved design proposal in a **docs-only draft PR**. It is **not** an accepted external producer wire format, executable implementation grant, proof of G3 scientific freeze or permission to trade.
- **Predecessor 1:** [#462 / PR #463](https://github.com/KanujVerma/drift/pull/463), immutable E1 campaign/arm/run-account configuration, source `src/drift/experiments/stage1_campaign_config.py`. Observed review HEAD `a6358db8298c7ee01c6cce14ac86fb79fde0b30f`, still **unmerged** at design creation.
- **Predecessor 2:** [#448 / PR #455](https://github.com/KanujVerma/drift/pull/455), local synthetic trial event chain, source `src/drift/experiments/stage1_trial_events.py`. Observed review HEAD `44925ed2f203de75dca4e4fc6222eb21f128db1c`, still **unmerged** at design creation.
- **Merged logical requirements:** `docs/architecture/adaptive-experiments/contracts/experiment.md` Sections 3.1 to 3.4, accepted via PR #434. Section 3.4's complete `TrialRecordV1` remains a **later** scientific/producer-derived view. It is not implemented here.
- **Main at design creation:** `02cb29b9f2ba308e0c9d116e35b13ad0b2de9af2`. Always refresh GitHub acceptance, source APIs, writer claims and current main before implementation.

**One exclusive docs-only path in this proposal:** this file. No source, tests, account ledger, accepted schemas, workflow, dependencies or another agent's PR are touched.

## 1. Accepted architecture decisions and rejected alternatives

| Decision | Chosen | Rationale | Rejected |
| --- | --- | --- | --- |
| TP-A | Minimal reusable producer-neutral provenance **core**, not full scientific projection yet | Freeze stable trial identity and event integrity without guessing research/platform interfaces | B/R-only one-off object, mutable plugin bag, fabricated results |
| TP-B | Explicit zero-event `UNOBSERVED` structural snapshot | Preserve declared-but-unrecorded local checkpoints for later coverage audits | Dropping every empty checkpoint or treating it as independently scheduled |
| TP-C | Retain **full immutable ordered event envelopes** | Future adapters can read event metadata locally and replay it | Retain only hashes and require another event store now |
| TP-D | Bind snapshot to **campaign fingerprint, arm fingerprint, run/account binding, checkpoint and trial ID**, plus event lineage | Prevent accidental relabeling of a valid chain into another arm, account or frozen study | `trial_id` string alone |
| TP-E | Future Krish/Matthew evidence as **separate immutable versioned artifacts** referencing the snapshot fingerprint | Preserve earlier provenance bytes and support future producer contract revisions | In-place annotations, generic executable plugin registry, automatic `COMPLETE` |

**Scope of this module:** offline, deterministic local provenance construction and verification. It is arm-generic; B/R constraints remain in the **separate** `verify_stage1_synthetic_br_configuration` check. A structural proof never authenticates producer origin, permits execution, validates cost or scores a study.

## 2. Frozen data types, public functions and implementation file

When separately authorized, implement **only**:

1. `src/drift/experiments/stage1_trial_provenance.py`
2. `tests/unit/test_stage1_trial_provenance.py`

These paths are **proposed** until an implementation issue explicitly authorizes them. Do not modify either predecessor file.

Set the **local snapshot** schema to `drift-trial-provenance/1-draft`, distinct from upstream `drift-experiment/1-draft`. The name is a local immutable view version, **not** a producer-accepted wire release.

Use these exact classes (no defaults on public value-model fields):

```python
from dataclasses import dataclass

from drift.experiments.stage1_campaign_config import RunAccountBindingV1
from drift.experiments.stage1_trial_events import Stage1TrialEvent

PROVENANCE_SCHEMA_VERSION = "drift-trial-provenance/1-draft"
PROVENANCE_STATES = frozenset({"UNOBSERVED", "EVENTS_RECORDED"})

@dataclass(frozen=True, slots=True)
class Stage1TrialScopeV1:
    campaign_id: str
    run_id: str
    arm_id: str
    checkpoint_id: str
    trial_id: str
    campaign_spec_fingerprint: str
    arm_spec_fingerprint: str
    run_account_binding: RunAccountBindingV1

@dataclass(frozen=True, slots=True)
class Stage1TrialProvenanceSnapshotV1:
    schema_version: str
    scope: Stage1TrialScopeV1
    observation_state: str
    event_envelopes: tuple[Stage1TrialEvent, ...]
    event_count: int
    chain_head_event_hash: str | None
    snapshot_fingerprint: str
```

The scope is a versioned logical value **within** the versioned snapshot and has no independently invented digest. The complete upstream `RunAccountBindingV1` is stored by value, including all eight fields. `event_envelopes` are copies of the exact 11-field existing `Stage1TrialEvent` objects, not an extra event wire type. No `producer_verified` Boolean, clock, cost, NAV, dynamic memory state, data rights or arbitrary extension map.

Expose these exact APIs:

```python
from collections.abc import Sequence

from drift.experiments.stage1_campaign_config import (
    ArmSpecV1,
    CampaignSpecV1,
    RunAccountBindingV1,
)
from drift.experiments.stage1_trial_events import Stage1TrialEvent

def build_stage1_trial_provenance_snapshot(
    *,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
    run_id: str,
    arm_id: str,
    checkpoint_id: str,
    events: Sequence[Stage1TrialEvent],
) -> Stage1TrialProvenanceSnapshotV1:
    ...

def verify_stage1_trial_provenance_snapshot(
    *,
    snapshot: Stage1TrialProvenanceSnapshotV1,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
) -> bool:
    ...

def append_stage1_trial_provenance_event(
    *,
    snapshot: Stage1TrialProvenanceSnapshotV1,
    event: Stage1TrialEvent,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
) -> Stage1TrialProvenanceSnapshotV1:
    ...
```

All new verification failures raise `ValueError`. A valid verification returns `True`. Do not return a nominally verified false-positive snapshot or normalize a forged stored object into legitimacy.

## 3. Exact scope and account binding algorithm

**Generic E1 validation is mandatory before building OR independently verifying any snapshot**:

1. Call `verify_experiment_configuration(campaign=campaign, arms=arms, bindings=bindings, expected_run_ids=expected_run_ids)` on the original caller-supplied full collection. Do **not** merely verify one matching binding and silently ignore other run/account duplicates.
2. Require `run_id` and `arm_id` to be exact built-in strings obeying the existing E1 scope-token regex `[A-Za-z0-9][A-Za-z0-9._-]*`. Require the new `checkpoint_id` to obey the **same** ASCII regex, so `:` never appears within a component. No surrounding whitespace, subclassed strings, empty IDs, floating-point IDs or guessed checkpoint.
3. Require the supplied run and arm to be present in the verified **complete caller-declared** manifest. Select exactly one E1 `ArmSpecV1` for `arm_id` and exactly one `RunAccountBindingV1` for the tuple `(campaign_id,run_id,arm_id)`. Do not create or query a platform account.
4. Derive the scope's `trial_id` **only** by `f"{campaign.campaign_id}:{run_id}:{arm_id}:{checkpoint_id}"` and bind the already-verified campaign/arm fingerprints and complete selected binding, including its existing `binding_id`.
5. Make **defensive value copies** of the selected frozen binding and every verified event envelope rather than retaining caller-owned object references. `dataclasses.replace(binding)` and `dataclasses.replace(event)` after exact type and verifier checks are suitable for these already-immutable leaf records. Copy the caller's event list into a new tuple. Revalidate copied records/chain before fingerprinting. This prevents a caller from changing a snapshot indirectly by mutating an originally supplied event/list after construction.
6. Any forged stored scope or binding field, mismatch against supplied verified E1 originals, changed campaign/arm fingerprint, cross-run account binding, ambiguous colon-delimited component, duplicate or missing run, or mismatched `trial_id` raises `ValueError`. Do not use equality on an unvalidated user-subclassed field.
7. The E1 manifest is **caller declared** and does not certify all external historical producer accounts. Authentic account identity and global run/ledger reconciliation remain Matthew's job.

The scope is not limited to B/R IDs. A generic declared control arm can be represented structurally. Its actual scientific eligibility and strategy-family authorization remain separately gated by accepted producer contracts.

## 4. Event collection and state algorithm

- Require `events` to be a sequence (e.g. list/tuple), **not** `str`, `bytes`, a mapping or unexpected object. Do not silently drop duplicate entries.
- With **zero** events, do **not** call the existing `verify_stage1_trial_chain`, whose nonempty restriction must stay intact. Set `event_envelopes=()`, `event_count=0`, `chain_head_event_hash=None` and `observation_state="UNOBSERVED"`. This is a **structural** absence label only, not a certified scheduled opportunity, `TrialRecordV1` completeness state, or study denominator.
- With **one or more** events, require the existing `verify_stage1_trial_chain(trial_id=scope.trial_id, events=original_events)` to return true, ensure exact `Stage1TrialEvent` leaf types, copy the envelopes into a tuple, reverify their chain, set `event_count=len(tuple)`, `chain_head_event_hash=last_event.event_hash`, and `observation_state="EVENTS_RECORDED"`.
- Nonempty event history must be contiguous from index zero with the correct parent hash, original input order, event ID, trial identity and original payload/evidence fields. Never skip invalid events, silently sort events, rehash a forged event, backfill a root, infer timeline eligibility, or use \`RESULT_BOUND\` to claim producer confirmation.
- A snapshot with `EVENTS_RECORDED` may contain any existing recognized event kind, including `RESULT_BOUND`, `COSTS_BOUND`, or `TRIAL_FINALIZED`. These are **unverified event labels**, not actual fills, authoritative `RESULT`, settled cost or a scientifically `COMPLETE` record.
- For a **stored** snapshot, verify exact dataclass types and all canonical fields on the *original* object before fingerprint verification, reverify the original retained event chain, and compare the fully specified scope and matching binding against the supplied E1 manifest. If state/count/head and event tuple disagree, fail with `ValueError`.
- The new module does not impose causal `recorded_at` versus trade cutoff, exchange calendar, or producer event-kind state-machine transitions. Those require a future accepted eligibility clock and producer evidence.

## 5. Canonical fingerprint preimage and exact bytes

Use ONLY existing `drift.serialization.canonical.content_hash`, with the repository's canonical JSON (\`sort_keys=True\`, separators \`(",", ":")\`, \`ensure_ascii=False\`, \`allow_nan=False\`). Define one private `_provenance_preimage(snapshot) -> dict[str, object]` used by **both** builder and verifier, with this **exact** logical JSON shape:

```json
{
  "schema_version": "drift-trial-provenance/1-draft",
  "scope": {
    "campaign_id": "CAMP-E1-SYNTH-001",
    "run_id": "RUN-001",
    "arm_id": "ARM-B",
    "checkpoint_id": "CKPT-001",
    "trial_id": "CAMP-E1-SYNTH-001:RUN-001:ARM-B:CKPT-001",
    "campaign_spec_fingerprint": "2c9cad6f55847c20bf9c7f5a5eaa1ec6f828c7f107bc32ad8a1516a4b2e88be4",
    "arm_spec_fingerprint": "84c4e89c1c1a06e4b3041f07fea316e051fd5b6b5502a5f8a3c17912db1fd831",
    "run_account_binding": {
      "schema_version": "drift-experiment/1-draft",
      "binding_id": "CAMP-E1-SYNTH-001:RUN-001:ARM-B:BINDING",
      "campaign_id": "CAMP-E1-SYNTH-001",
      "run_id": "RUN-001",
      "arm_id": "ARM-B",
      "portfolio_account_id": "SYNTH-ACC-B-001",
      "initial_cash_allocated": "10000",
      "bound_at": "2026-10-19T00:00:02.000000Z"
    }
  },
  "observation_state": "UNOBSERVED",
  "event_count": 0,
  "chain_head_event_hash": null,
  "event_hashes": []
}
```

The ordered `event_hashes` array contains exactly one hash per retained verified envelope and **preserves their order**. Do not store full envelopes in this preimage a second time: the upstream verified `event_hash` already commits to each envelope's exact ten-field preimage. However, the snapshot value **must retain the full tuple** per TP-C. Include all eight run-binding fields, because E1 does not specify a binding-level fingerprint. Exclude `snapshot_fingerprint` from its own preimage. Arrays and nulls must not be silently normalized or replaced.

### Independently computed golden synthetic fixtures

Reuse **unchanged** complete E1 fixtures from PR #461 / PR #463:

- Campaign: `CAMP-E1-SYNTH-001`; campaign fingerprint `2c9cad6f55847c20bf9c7f5a5eaa1ec6f828c7f107bc32ad8a1516a4b2e88be4`.
- Arm B: `ARM-B`; arm fingerprint `84c4e89c1c1a06e4b3041f07fea316e051fd5b6b5502a5f8a3c17912db1fd831`.
- Run: `RUN-001`; Arm B binding: `CAMP-E1-SYNTH-001:RUN-001:ARM-B:BINDING`; account `SYNTH-ACC-B-001`, amount `"10000"`, bound at `2026-10-19T00:00:02.000000Z`.
- Explicit checkpoint: `CKPT-001`, derived trial ID `CAMP-E1-SYNTH-001:RUN-001:ARM-B:CKPT-001`. Manifest: `expected_run_ids=("RUN-001",)`, and **both** B and R bindings are supplied to E1's collection verifier.

**Golden 0: zero events.** The JSON preimage above, with `"UNOBSERVED"`, `0`, `null`, and `[]`, has independent SHA-256:

```text
4af22745881f33eb772db1d1d30c7b9f60c35089c741d89df303a9ddb465c13a
```

**Golden event 0:** Build using the existing `build_stage1_trial_event` with these exact arguments (the payload pointer is **inert**, never fetched):

```python
trial_id = "CAMP-E1-SYNTH-001:RUN-001:ARM-B:CKPT-001"
event_index = 0
previous_event_reference = "ROOT"
event_kind = "OPPORTUNITY_CREATED"
recorded_at = datetime(2026, 10, 19, 0, 0, 3, tzinfo=UTC)
producer_evidence_references = ["a" * 64, "f" * 64]
payload_reference = "fixture://local-provenance-payload-001"
payload_hash = "01f8a73080e754508a23c88172de3fe6cd77b76819e7768861b68ef90290b630"
```

This yields independent **event SHA-256**:

```text
2999edc6f859b6ef17a6b0c99728bab01d7d80cad65e28f59ffd3a5dd5a7f9f4
```

**Golden 1: one verified structural event.** Change only the preimage fields to:

```json
{
  "observation_state": "EVENTS_RECORDED",
  "event_count": 1,
  "chain_head_event_hash": "2999edc6f859b6ef17a6b0c99728bab01d7d80cad65e28f59ffd3a5dd5a7f9f4",
  "event_hashes": [
    "2999edc6f859b6ef17a6b0c99728bab01d7d80cad65e28f59ffd3a5dd5a7f9f4"
  ]
}
```

Retain `schema_version` and the **entire unchanged `scope` above**; this block shows only replaced fields, not a second complete standalone preimage. Independent **one-event snapshot SHA-256**:

```text
667c4927f703db79b3915810a34976230e86f42872882f0f8fa34933951bca0e
```

The three new witnesses (empty snapshot, event, one-event snapshot) were calculated separately from production code using `hashlib.sha256(json.dumps(..., sort_keys=True, separators=(",",":"), ensure_ascii=False, allow_nan=False).encode("utf-8"))`. Never edit goldens to match a failing implementation. Do not infer the `payload_hash` was authenticated by recalculating a referenced but unavailable payload.

## 6. Pure append behavior

Implement `append_stage1_trial_provenance_event`:

1. Fully verify the original immutable `snapshot` against the **same complete E1 manifest** and explicitly supplied campaign/arms/bindings.
2. Call the existing `append_stage1_trial_event(events=snapshot.event_envelopes, event=event)`. For a zero-event history, that existing helper accepts only index-zero/`ROOT`. For nonempty history it validates the entire chain, next index/parent and idempotent duplicate ID behavior. Do not rewrite/replace this helper.
3. Rebuild through `build_stage1_trial_provenance_snapshot` using the original verified scope's run, arm, checkpoint and the new tuple. Re-run verification on the newly created snapshot.
4. Exact duplicate replay that the existing append returns unchanged must return the **original unchanged snapshot** (or a content-identical one) with exactly the same fingerprint, not a new logical revision. A conflicting duplicate or unexpected event is `ValueError`. Successful append returns a *new* immutable snapshot; earlier snapshots remain bit-for-bit stable. There is no mutable history pointer or wall-clock revision.

This API does not persist data or publish a real study event; it is a deterministic local view builder.

## 7. Separate future producer adapters, not implemented in this slice

An authenticated producer annotation is a **separate immutable, versioned artifact** containing at minimum a binding to the exact `snapshot_fingerprint` plus whatever producer revisions, authorizations and signed/verified evidence **that producer's accepted contract eventually requires**. The producer may issue a new version of its attachment without changing the original snapshot; a later scientific projector may join it only through accepted eligibility rules.

**Do not write a generic adapter protocol class, arbitrary callback bus, placeholder `dict[str, Any]` or guessed producer record fields now.** This is an architecture boundary: future typed adapters and evidence receipts belong to Krish/Matthew, and the eventual scientific `TrialRecordV1`/`StudyReportV1` will consume only accepted authoritative producers. There is no automatic promotion from an `event_kind` string or payload hash to real result, cost, provenance qualification, account authorization, model confirmation, finality or economic return.

## 8. Exact synthetic acceptance matrix

**Positive cases:**

1. Golden 0 `UNOBSERVED`, no head; repeat identical scope yields exact hash `4af227...`; event chain verifier is **not** called on zero events.
2. Golden 1 full immutable envelope, `EVENTS_RECORDED`, head=event hash, exact golden `667c49...`. Replayed equivalent timezone input produces same event and snapshot hashes.
3. Add another sequential valid event using existing append helper: event count/head/hash change, old snapshot unchanged. Rebuilding from the same complete chain reproduces the new snapshot exactly.
4. Idempotent duplicate replay produces the same original snapshot identity/hash.
5. Event array order retained and caller list mutation cannot change previously built snapshot. Caller-provided event/binding instance tampering after construction must not mutate a detached snapshot.
6. A different valid checkpoint, account binding or campaign/arm spec yields a different snapshot fingerprint, even for zero events, using revalidated valid E1 collections. Different valid arms must remain structurally supportable (no generic B/R-only shortcut).
7. A test-only simulated *future consumer* can read the preserved full event envelopes but cannot derive producer-authenticated RESULT or alter the original snapshot.

**Negative/adversarial cases:**

1. Missing/empty/invalid/colon-containing checkpoint, non-string/subclassed ID, nonmatching arm/run/campaign, forged `trial_id`.
2. Missing, duplicate, or extra run/arm/binding in caller-declared E1 manifest, cash mismatch, reused account across different runs, wrong binding account/`bound_at`/`schema_version`.
3. Forged campaign/arm fingerprint, forged stored snapshot fingerprint (including recomputed hash over an invalid scope), malformed digest case, forged binding ID.
4. Nonempty event collection with broken root/parent chain, skipped index, duplicate/conflicting events, wrong trial ID, bad payload hash, mutated leaf with stale event hash, noncanonical recorded timestamp, unsorted evidence references, or fabricated output. Reject rather than normalize.
5. Stored observation state inconsistent with count/stream/head; zero events with non-null head or state `EVENTS_RECORDED`; nonempty events with state `UNOBSERVED` or null head.
6. `RESULT_BOUND` or `TRIAL_FINALIZED` event alone must **still** report `EVENTS_RECORDED` only, never a financial/scientific `COMPLETE`.
7. Unexpected mapping/string as events, event/record dataclass subtype, float/bool event count, stale/incorrect ordered event hashes.
8. Original input lists, binding records and event envelopes remain unchanged after any failure.
9. Claims that a local checkpoint automatically enters `ScheduledArmCheckpointOpportunities` or is an independently scheduled study opportunity are **out of scope and prohibited**.
10. All originally accepted E1 and trial-event golden hashes/tests remain unchanged; no replacement of their API or serialization.

Test all errors using `pytest.raises(ValueError)` and assert no mutation. No network, file-backed producer adapters, credentials, paid data, orders, actual accounts or stage-specific scoring.

## 9. Dependencies, acceptance and execution discipline

**Blocked code dependency at design publication:** #455 and #463 are still draft/unmerged, so the new module **must not import code that exists only in those draft PRs and then pretend main CI is self-contained**. The implementation issue is gated until exact accepted revisions are merged to the target base, or until the owner separately authorizes a stacked branch with an explicit dependency merge plan. Do not copy implementations or vendor duplicate E1/event contracts into the new file.

Once unblocked, create exactly one issue-specific branch from current accepted main, one draft PR for the two new files and perform:

```bash
uv run --locked --python 3.14.6 pytest -q tests/unit/test_stage1_trial_provenance.py
uv run --locked --python 3.14.6 pytest -q tests/unit/test_stage1_campaign_config.py tests/unit/test_stage1_trial_events.py
uv run --locked --python 3.14.6 pytest -q tests/unit/test_stage1_preparation.py tests/unit/test_stage1_metric_math.py tests/integration/test_stage1_reference_readiness.py
uv run --locked --python 3.14.6 ruff check src/drift/experiments/stage1_trial_provenance.py tests/unit/test_stage1_trial_provenance.py
uv run --locked --python 3.14.6 ruff format --check src/drift/experiments/stage1_trial_provenance.py tests/unit/test_stage1_trial_provenance.py
uv run --locked --python 3.14.6 mypy src tests
uv build
git diff --check
```

Also run the repo's actual required full test gate, Unicode U+2014 scan, staged-path audit and exact-HEAD hosted GitHub CI. Use `uv.lock` and `.python-version` untouched. Report any unavailable tests or dependency gate as **BLOCKED/NOT_RUN**, not passed. Use Codex `@codex review` at the exact current PR HEAD and wait for completed receipt; request Matthew's independent account/RESULT consumer review without treating him as the code writer. Independent acceptance and exact-PR/HEAD owner merge authorization remain separate, with no auto-merge.

## 10. Why this stops before full TrialRecordV1

The next phase may define authentic accepted adapters for Krish's matured proposals and cost receipts and Matthew's account, mandate, fills and authoritative RESULT. Those records require accepted producer-specific contracts, point-in-time validity and independent scientific review. A local `Stage1TrialProvenanceSnapshotV1` is a **content-addressed structural witness**, not evidence that an investment decision was valid, a transaction occurred, a score was calculable or a particular control strategy was allowed. This boundary must remain explicit in future documentation, API names and PR descriptions.
