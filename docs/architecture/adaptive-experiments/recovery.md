# Recovery: three targets and separate evidence

Revision R2. Proposed documentation for [#395](https://github.com/KanujVerma/drift/issues/395).
Matthew produces recovery mechanisms. Harsha's
[#397](https://github.com/KanujVerma/drift/issues/397) coordinates independent
acceptance evidence; the mechanism author cannot be its sole accepter. This
specification performs no backup, restore, revert, private-state read or runtime
launch. A reviewed document, matching manifest or green CI is not a recovery
receipt, a safety certification or deployment permission.

## 1. Foundation and honest baseline

Read [D01-D17](decisions.md), [design](design.md),
[requirements crosswalk](requirements-crosswalk.md), [onboarding](onboarding.md),
[workstreams](../workstreams.md), [workflow](../agent-workflow.md),
[trust boundaries](../trust-boundaries.md),
[ADR 0012](../../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md),
[ADR 0015](../../adr/0015-three-feature-workstreams-and-explicit-writer-handoffs.md)
and [ADR 0016](../../adr/0016-controlled-adaptive-research-with-versioned-execution.md).
Public repository evidence is pinned to main
`5583f112dfb45b8f6e8bc652de1cc4334ef8a247`; decisions blob
`2604dbb34d4bedeb6888342f336d2e62dedd4513`.

The [execution safety audit](../execution-safety-audit.md) retains known
S1/S3/S4 limitations. That main revision is not certified as the corrected safe
runtime required below. Before a future fallback/control run, identify the
accepted corrected kernel commit and its independent verification explicitly.
Do not silently designate an old release or the latest green docs head as safe.
[#411](https://github.com/KanujVerma/drift/issues/411) remains a proposed
uncertainty/hold/resumption contract, not an implemented restoration mechanism.

The private original archive and retained original runtime/state are not verified
by this documentation task. A code commit can be located independently of those
materials; it proves neither their existence nor their consistency or custody.
No private manifest, database, credential or archive is opened to fill a gap.
Record unavailable evidence honestly and block only the dependent operation.

## 2. Target F: feature-off on the corrected current kernel

Purpose: retain a supported present-day kernel while disabling the adaptive
feature through an accepted versioned configuration. This is not a code rollback
or recreation of original private state. Keep current accounting, source grades,
corporate-action/identity corrections and mandatory safety gates intact.

Require the exact corrected kernel/tree and feature/configuration revision,
supported schema/dependencies, complete relevant account/open-order/hold state
and an accepted permission boundary. Feature-off must not select a legacy
dispatch path with optional safeguards or clear paused/uncertain obligations.
If a safe current kernel or compatible feature-off path is unavailable, this
target is blocked; old unsafe behavior is not a convenient fallback.

Keep all later trials, proposals, losses, costs and audit receipts. Append the
configuration transition and causal reason instead of deleting adaptive history.
Specify the last affected operation and how pending work is quiesced/fenced and
reconciled under the accepted #411 contract. Feature-off is not cancellation or
liquidation and grants no broker-connected operation.

Evidence separates code/configuration identity, state compatibility and runtime
behavior. A config flag alone is not proof the feature is disabled at every
entry point. Future accepted offline positive/negative controls must establish
the supported current-kernel behavior and refusal of forbidden paths. No control
or feature switch is exercised by writing this proposal.

## 3. Target O: isolated original-state restoration

Purpose: reconstruct only the original scope declared in an exact accepted
manifest, in a fresh isolated destination, without replacing current working
trees, databases or audit history. An old checkout is at most the code portion.
It is neither verified private-state recovery nor a safe active deployment.

Before any operation, obtain a separately scoped grant naming the actual
custodian, original sources, allowed reads/copies, destination, execution/network
limits, expenditure if any and independent acceptance requirements. Never point
old code at a current database, borrow another writer's worktree/index or copy
credentials because a historical environment used them.

### Custodian and isolated destination

Named accountable producer: Matthew. Actual documentation actor:
`matthew-philip`. Neither role establishes custody or permission to inspect the
original private archive. No operational recovery custodian or restore destination
has been authorized by this docs-only goal. These are explicit unresolved fields,
not implicit permissions assigned to Matthew, Harsha or a shared GitHub login.

The future grant/manifest must name a verified individual/service custodian and
an exact absolute isolated destination with approved root/volume, ownership,
ACL/mount/network policy and retention/disposal scope. A candidate destination
is a fresh recovery-run directory on a separately authorized isolated volume,
identified by the manifest/run IDs; no machine path is selected or created here.
Do not use production/current data paths, another active worktree or a relative
path whose final resolved target is unknown. Bind canonical resolved paths and
check symlink/junction/reparse-point escapes before any permitted future copy.
Missing custodian or destination evidence blocks Target O execution.

### Manifest obligations

The immutable manifest and its trusted custody/approval evidence must bind:

- Recovery target, exact historical scope/date and exclusions; original versus
  later artifacts; manifest ID/version/hash; source provenance and custodian;
  grant and independent reviewer references. A digest alone is not provenance.
- Code commit/tree plus all required Git objects/submodules/LFS/artifact bytes;
  tracked, modified, untracked and relevant ignored-file inventory with safe
  content identities. A commit omits uncommitted/ignored state and local config.
- Private-state artifact identities and exact covered stores: database snapshots,
  schema/user versions and migration history, journal/checkpoint lineage,
  retained source/model/replay inputs and configuration. Sensitive bytes and
  filesystem locations remain in authorized private records, not public GitHub.
- Snapshot transaction/consistency boundary and mutually consistent store set;
  relevant SQLite WAL/checkpoint state captured through an accepted method;
  integrity/foreign-key/application invariants and source snapshot timestamps.
  A copied database file without its required transactional state is not proof.
- Runtime: pinned interpreter implementation/version/build and artifact identity,
  lockfile and package/source identities, native libraries, OS/architecture,
  required system/timezone/locale configuration and declared nonsecret env values.
  Hooks/plugins/tool/network capabilities affecting execution are part of scope.
- Exact data/schema/code compatibility, availability of historical replay bytes,
  rights/retention basis, expected deterministic outputs and permitted limitations.
  Exclusions must explain which claims cannot then be established.
- Destination isolation and grant expiry, allowed verification commands/probes,
  positive/negative controls, evidence handling and cleanup custodian. No command
  is authorized merely because it appears as a future verification requirement.

Never embed secrets, raw private state or credential hashes in a public manifest.
Use access-controlled safe references to custody/secret requirements; any future
secret provisioning requires its own grant. Runtime reconstruction starts with
network/operational capability denied unless explicitly and narrowly authorized.
No production credential, provider call or real broker session is a default.

### Verification and stop conditions

Verify code, private state and runtime independently against the accepted manifest.
Original code may match while state is missing; a database may match bytes but
be incompatible with the selected code/schema; dependencies may be unavailable
even when code and state are intact. Preserve all three results rather than
collapsing them into a single misleading restored flag.

Only after all required components and isolation controls pass may a separately
authorized offline replay establish the declared behavior for that manifest.
Retain actual command/version/input/output and complete exit/log evidence. A
fallback interpreter is a labelled diagnostic, not proof under the pinned runtime.
Do not change pins, locks, fixture hashes, source grades or expected values to
make reconstruction pass. Missing original bytes/rights or unsupported schema
means unavailable/blocked, not permission to fetch replacements or repair history.

A manifest-scoped restoration receipt establishes only its stated scope. It does
not prove omitted stores, a different machine/run, original data authenticity,
unrecorded state, business performance or safety for current external operation.
Restoring an old defect for forensic comparison never authorizes active use.

## 4. Target C: frozen scientific control on the same corrected kernel

Recovery Target C is a target label, not scientific campaign arm C. The frozen
policy arm is A, adaptive AI is B, and campaign arm C remains the passive
benchmark. Recovery terminology never remaps those accepted arm meanings.

Purpose: compare a frozen policy with adaptive research while keeping the same
accepted corrected evaluator/accounting/safety/source boundaries. Freeze the
candidate/selection rule, parameters and permitted learning state under the
campaign contract, not an older vulnerable codebase. A frozen policy may still
produce later rule-eligible trades; it is not a claim that nothing can change.

Use matched declared source availability, opportunity/fill/cost and mandate
rules, equivalent initial account/arm state and isolated journals/learning state.
Any intentionally different information, review cadence, budget or execution
policy is a named experimental condition. Do not relabel an old-code run as the
control merely because it predates adaptation. Retain actual requests/responses
and temporal feedback boundaries where replay depends on them.

Target C needs the accepted corrected code/configuration, frozen campaign/policy
and state manifest, qualified or explicitly exploratory inputs, and runtime/replay
evidence for that run. No pristine holdout, source upgrade or independent investment
result follows from deterministic replay. Harsha owns scientific acceptance;
Matthew supplies the one account RESULT, not a second analysis engine.

## 5. Evidence results, lineage and irreversible boundaries

For each target record three evidence dimensions separately: CODE, PRIVATE_STATE
and RUNTIME. Each has exact revision/manifest/grant/run/environment, scope,
supporting receipts, independent verifier and result. Distinguish passed, failed,
pending, cancelled, blocked, not run and unavailable. A component not required for
a target is explicitly not applicable with a reason, not silently passed.
Superseded/older successes cannot certify a newer revision or broader scope.

Later trials, costs, losses, source receipts, permissions and audit lineage must
remain intact and attributable. Restore to a new namespace/destination; append
new manifests/results and relationships to originals. A rewind of code does not
rewind costs or erase failed research. Do not overwrite current files, rewrite
journal history, truncate databases or regenerate old golden expectations.

Contemporaneous data/decision provenance stays immutable. Source corrections
append versions; exploratory artifacts remain non-promotable. Recovery access
does not create redistribution/replay rights that were absent. The existing
[ledger](../../../src/drift/ledger/) integrity model detects inconsistencies;
it is not proof against an actor able to replace an entire store and recompute
hashes. Retain trusted independent custody/checkpoint anchors where required.

Feature-off, restore and frozen-control receipts never clear an operational hold
or enable external execution. Resume requires accepted account/order reconciliation,
authority and effective executor fencing under #411 and the mandate/EXEC contracts.
A restored stale mandate or historical ALLOWED verdict is not a fresh grant.
Separate broker/provider/host permissions remain necessary even after perfect
offline reconstruction. There is no automatic rollout/revert/cleanup authority.

## 6. Synthetic acceptance and refusal cases

These are specification cases, not performed operations or verification results.
All manifests/identities/stores mentioned are synthetic; no original private
artifact or actual recovery destination is inspected.

- A01 feature-off: accepted corrected kernel K2 and config F2 disable adaptation
  while retaining current compatible state. Hypothetical expected CODE=passed
  only with verified K2/F2; PRIVATE_STATE=passed only for the verified compatible
  current state (original-archive restoration is not applicable to this target);
  RUNTIME=passed only with actual authorized supported-path controls/replay.
  Until those checks occur, the corresponding actual result is not run/blocked,
  never an assumed pass. Later trials/costs remain.
  Without K2 verification or an accepted supported path, Target F is blocked.
- A02 manifest-scoped original: code C1 matches, original state S1 is absent,
  runtime R1 is not provisioned. CODE may pass its exact scope; PRIVATE_STATE is
  unavailable and RUNTIME not run/blocked. Do not call the whole system restored.
- A03 incompatible database: original C1 expects schema v1; only a later v3
  database is available. Refuse attachment/execution; do not downgrade it in place,
  point old code at it or substitute a fresh empty database as original state.
- A04 missing dependency: code/state manifest identities match but the pinned
  interpreter/package artifact cannot be provisioned under the grant. Keep those
  dimensions' evidence; runtime is unavailable. A different Python passing a
  smoke test remains diagnostic, not canonical reconstruction.
- A05 preserve later evidence: current store contains later losing trial T9 and
  its costs. A permitted isolated restoration of an earlier manifest cannot
  delete T9 or overwrite current account/audit state; retain both lineages.
- A06 frozen control: scientific arms A and adaptive B use corrected kernel K2 and declared
  comparable account/source/execution rules. Freeze A's policy revision, retain
  later rule-driven outcomes and complete costs. Hypothetical expected CODE=passed
  only with verified K2 and frozen A-policy/configuration; PRIVATE_STATE=passed
  only for the consistent isolated arm-A initialization and comparison-state
  evidence; RUNTIME=passed only with the authorized actual offline execution/replay
  receipts. Original-archive restoration is not applicable; this task's actual
  operation/test statuses remain not run. An old unsafe kernel is refused
  as the implementation of that control, even if it replays deterministically.
- A07 incomplete tree/snapshot: commit matches but required untracked config,
  LFS object or transactional database component is missing. Code/state scope is
  incomplete; matching some hashes is not a full original-state receipt.
- A08 authorization/isolation: archive exists but custodian grant is absent,
  expired or destination resolves into current/private state through a junction.
  Refuse the operation before access/copy/execution. Do not test the escape by
  touching original data; future inert containment controls need separate scope.
- A09 independence: the mechanism author signs its own recovery receipt without
  independent accepted evidence. That is self-review, not #397 acceptance.
- A10 corrected-kernel hold: feature-off or restore succeeds for its own scope
  while a prior possible order remains unresolved. Keep the hold; recovery does
  not authorize a new placement, cancellation success claim or automatic resume.

## 7. Decisions and completion evidence

Criteria map: three targets in2-4 (A01/A02/A06); separate code/state/runtime and
manifest/tree/database/schema/dependency/replay evidence in3/5 (A02-A04/A07);
custodian/destination and access boundaries in3 (A08); later trial/cost/loss/audit
preservation in5 (A05); independence and operational refusal in5/6 (A09/A10).

Matthew must produce an evidence-backed manifest/grant request before any future
recovery operation. The actual private-state custodian, original manifest scope,
corrected-kernel acceptance, isolated destination and permitted runtime/probes
remain explicit unresolved operational decisions. Missing decisions block the
operation, not this independent specification. No role is silently assigned an
authority it has not received.

Harsha's #397 defines acceptance evidence and conflict rules; an authorized
independent reviewer verifies Matthew's mechanisms and does not replace actual
code/state/runtime evidence with an assertion. Accepted source rights, contract
revisions and operational permission remain separate. The author cannot claim
full restoration, safety or release from this document's CI or AI critique.

Document checks cover relative links/anchors, UTF-8/EOF/whitespace/fences/noU+2014,
cases/mapping and the exact sole tracked/untracked file. No backup/restore/revert,
dependency installation, source acquisition, private-state inspection or runtime
test is run for prose. Future verification requires its own accepted scope and
exact-head checks. Live claims/checkpoints/review/CI belong in GitHub; no second
status database, automatic merge/closure, credential copying or path release.
