# Stage 1 original research invocation grant (proposed design)

**Status:** Kanuj-owned scientific scheduling proposal only. No accepted
producer schema, original issuer, implementation, account-provisioning
receipt, retained validation evidence, platform RESULT or execution authority.

**Owner issue:** [#512](https://github.com/KanujVerma/drift/issues/512).
**Dependent producers:** [Krish #507](https://github.com/KanujVerma/drift/issues/507)
and [Matthew #508](https://github.com/KanujVerma/drift/issues/508).
**Scientific consumer:** [E6B #485](https://github.com/KanujVerma/drift/issues/485).
**Existing evidence:** [experiment contract](contracts/experiment.md),
[merged 28-case fixture plan](stage1-e6b-contract-fixtures.md) and
[merged E6A single-view fix](https://github.com/KanujVerma/drift/pull/506).
**Code baseline inspected:** `main` at
`49767fc61c6037fb9f921aefc83bd1df976a7e34` on October 20, 2026.

## 1. Why this is missing

The accepted E1 `CampaignSpecV1`, `ArmSpecV1` and
`RunAccountBindingV1` validate one immutable run/account manifest.
Provenance and E6A bind structurally correct checkpoint and trial hashes.
They **do not authenticate the original account allocation or who initiated
a research request**. The separate [#511](https://github.com/KanujVerma/drift/issues/511)
public **provenance verifier** correction is implemented in still-open
[#504](https://github.com/KanujVerma/drift/pull/504), whereas merged
[#506](https://github.com/KanujVerma/drift/pull/506) repairs the different
E6A checkpoint-audit caller boundary. Neither is an original issuer proof.

Merged K1 `Scope(experiment_id, arm_id, account_id, campaign_ref)` lacks
the exact E1 run/checkpoint. `TrustedInvocationBinding` is a caller wrapper,
and `ValidationResult` is not yet an original retained authenticated
validation receipt. Krish's [producer NARROW response](https://github.com/KanujVerma/drift/issues/507#issuecomment-6302653579)
identifies an independently verifiable E1 invocation grant as missing.

M0 `ExperimentRun`, M2 `EvaluationRunIdentityV1/V2` and
`PortfolioStateV1/V2` do not authenticate E1 account/checkpoint allocation.
Matthew's [#508](https://github.com/KanujVerma/drift/issues/508)
must separately identify the **original platform account provisioner**.
A hash of a caller-composed account ID is not that proof.

## 2. Required issuer boundary

The **future accepted Stage 1 scientific scheduler** under Kanuj's
workstream may authorize *one logical research invocation*. The grant
must originate from a retained, independently verifiable scheduler
issuance operation before the specific K1 logical request begins.

The scheduler grant is **not** an account creation, accepted research
candidate, risk approval, order, fill, finalized RESULT, independent
statistical sample or paper/live trading permission. The AI model,
research candidate, E6B projector and a generic caller may not issue
or self-certify original scheduler grants.

The proposed issuance order is:

1. E1 campaign is frozen; full arm/run/account manifest and declared
   checkpoint are structurally verified.
2. **Matthew's trusted account provisioner** provides an original
   account allocation/assignment receipt and verifier matching the
   E1 binding. If absent, stop with `BLOCKED_ON_508`.
3. The authorized scheduler checks original account proof, policy,
   checkpoint, request identity and cutoff; it emits and durably
   retains the original scheduler grant before K1 invocation.
4. **Krish** verifies the grant and records K1 context, attempt,
   original validation outcome, candidate or valid absence, replay,
   costs and terminal state under [#507](https://github.com/KanujVerma/drift/issues/507).
5. **Matthew** separately proves original M0/M2 result, book/trace,
   execution/UNKNOWN/finality and the same E1 account under #508.
6. Only after both original associations are accepted can a Kanuj
   E6B projector derive a trial revision, with the originals unchanged.

**Current state:** The accepted public code does not yet implement
a trusted scheduler grant issuer or verify original Matthew account
provisioning. This file proposes a logical contract, not an available import.

## 3. Minimal proposed immutable grant fields

**Provisional name only:** `Stage1ResearchInvocationGrantV1`.
**Provisional profile:** `drift-stage1-invocation-grant/1-proposed`.
Neither is an accepted Python class or wire revision.

- **Identity and version:** `schema_version`, `grant_id`, `revision`,
  `predecessor_grant_ref?` and `grant_record_hash`.
- **Complete E1 binding:** `campaign_id`,
  `campaign_spec_fingerprint`, `complete_manifest_fingerprint`,
  `arm_spec_fingerprint`, original `RunAccountBindingV1.binding_id`,
  `run_id`, `arm_id`, `portfolio_account_id`, `checkpoint_id`
  and `trial_id`. Verify against the *entire* manifest, not one row.
- **Platform account origin:** `account_provisioning_receipt_ref`,
  `account_issuer_ref` and `allocation_first_available_at`,
  independently verified under Matthew's accepted issuer. These
  field names are placeholders until #508 settles actual types.
- **Scheduled research intent:** `logical_request_id`,
  `request_kind`, `method_or_selector_policy_ref`,
  `allowed_strategy_refs`, `context_policy_ref`,
  `decision_cutoff` and `decision_deadline`.
- **Original scheduler authority:** `scheduler_issuer_id`,
  `issuer_version`, `original_issuance_ref` and
  `issuer_proof_ref`. The verifier must retrieve the actual
  retained issuance, not trust a caller's asserted URL or boolean.
- **Issuance and corrections:** `grant_issued_at`,
  `grant_first_available_at`, `invocation_not_before_at`,
  `grant_expires_at?`, `revocation_effective_at?`,
  `revocation_recorded_at?`, `revocation_first_available_at?`,
  `revocation_proof_ref?` and `supersedes_grant_ref?`.

Original bytes and a content hash prove consistency only. Issuer
authenticity additionally requires an authorized scheduler identity,
durable original issuance/retention and an independently accepted
verifier. This plan chooses **no signature scheme, secret, credential,
new network service, executor identity or source-file implementation**.

## 4. Causal clocks and replay safety

- `decision_cutoff` bounds **consumed data/context/feedback** first
  availability. A post-cutoff input consumed as past knowledge must fail.
- Grant issuance and candidate completion may occur after the input
  cutoff if separately permitted by the authentic scheduler deadline.
  They must not be backdated or misclassified as future input.
- Original scheduler grant issuance and verified availability must
  precede its designated logical K1 invocation. A grant first issued
  after the attempt cannot be accepted retroactively.
- A stable grant and request identity can have multiple genuine
  linked attempts. Duplicate identical replay is idempotent, not
  an independent trial. Same grant ID with changed original bytes
  refuses; an accepted correction/revocation adds a retained version.
- **Grant validity is assessed as of the original, independently
  authenticated invocation/attempt start**, not when a replay verifier
  happens to run. Issuance and first availability must precede that start.
  Expiry is exclusive: an attempt starting at or after
  `grant_expires_at` cannot use that grant. A later expiry does not
  invalidate an already started historical attempt.
- A revocation has its own issuer-verified original record,
  `revocation_effective_at`, `revocation_recorded_at`, and
  `revocation_first_available_at`. Under the default prospective
  policy, it cannot become effective before its independently proven
  original issuance/first availability. An attempt starting at or after
  the effective instant is refused; an attempt that started earlier
  remains valid **for its original grant-at-start check**. A later
  revocation does not silently reclassify that historical attempt.
  Any extraordinary retroactive invalidation requires a separate,
  explicitly accepted owner policy and immutable correction lineage.
  None is authorized by this proposal.
- A later revocation never authorizes a new retry or additional order.
  A still-running model completion remains subject to its separate
  decision deadline, context, risk and containment policies; grant
  validity at start alone does not certify the final candidate or RESULT.
- A `hold` requires verified matching incumbent and current
  account/risk state. `abstain`, `unavailable`, failed and rejected
  attempts remain distinct, retain reason/cost, and authorize no
  new order on their own. Existing pending and independently authorized
  protective orders remain part of Matthew's verified account state.
- Two M0 operational run IDs or a repeated deterministic `result_hash`
  do not determine independent scored sample count. The approved
  scientific trial/replication protocol owns that identity.
- An absent or invalid platform allocation or grant **already invalid
  at the attempt-start instant** cannot be rehabilitated by computing
  a new local E1 hash. Preserve later revocation facts without
  rewriting a previously valid retained attempt.

## 5. Proposed consumer verification order

1. Capture E1 caller collections once. Verify full campaign/arms/run
   account binding, checkpoint and provenance/E6A original fingerprints
   through the accepted single-view APIs. #511 must be accepted
   before integrated account-binding claims.
2. Verify **Matthew's original account allocation issuer and retained
   receipt** independently, including account, arm, run, cutoff and
   full manifest. Refuse arbitrary matching caller account strings.
3. Retrieve the original scheduler grant from the approved issuer;
   check original bytes, issuer and version, issuance and availability,
   and original **invocation/attempt-start timestamp**. Evaluate
   expiry and revocation as of that start, using independently verified
   original effective/recorded/first-available times. Retain any
   subsequent revocation without retroactive validity changes.
4. Krish independently verifies his original K1 context, attempt
   start/terminal, retained validator decision, candidate or absence,
   model replay and raw research costs. Never promote a grant into
   an accepted research output.
5. Matthew separately verifies actual M0/M2 admission, result/trace,
   account book, order/fill/refusal/UNKNOWN, valuation and posted
   trading costs without reinterpreting its original hashes.
6. E6B joins only **two verified producer associations** agreeing
   on full original E1 scope. Missing or contradictory evidence
   prevents a completed scientific result, but does not erase
   the attempted/opportunity denominator.

Missing original issuer or producer evidence is `UNAVAILABLE` with
a reason. Forged, revoked, conflicting or scope-mismatched evidence
is `INVALID`. Genuine future input consumption is causal lookahead,
not a normal after-cutoff model completion. No generic `dict[str, Any]`
evidence resolver or second financial ledger is allowed.

## 6. Fourteen synthetic original-grant test vectors

Each vector is a **design expectation, not an executed test**.
`READY_STRUCTURAL` has accepted E1 fixture verification only.
`BLOCKED_ON_SCHEDULER` requires the new original issuer and verifier.
`BLOCKED_ON_508` requires a real Matthew provisioning proof.
`BLOCKED_ON_507` requires retained K1 research association.

- **G01, positive B/R:** `CAMP-E1-SYNTH-001`, `RUN-001`,
  `CKPT-001`, `ARM-B`/`SYNTH-ACC-B-001` and
  `ARM-R`/`SYNTH-ACC-R-001`. Expect two separately retained
  grants only if original account allocation and scheduler issuance
  are verifiable. **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER**.
- **G02, internal fixture:** verify original E1 campaign/account
  and submitted E6A B/R checkpoint identities without any
  issuance claim. **READY_STRUCTURAL**.
- **G03, wrong scope:** mutate run, checkpoint or full E1 manifest
  while retaining original grant. Reject, even if a wrapper was
  rehashed. **BLOCKED_ON_SCHEDULER**.
- **G04, crossed account:** ARM-B grant references ARM-R's actual
  original allocation. Reject. **BLOCKED_ON_508**.
- **G05, self-claimed trust:** valid hash without original scheduler
  issuance/accepted independent verifier. Unavailable, no admitted
  grant. **BLOCKED_ON_SCHEDULER**.
- **G06a, historical valid replay:** original valid grant and attempt
  started before its expiry/revocation-effective time, then genuine
  later revocation before replay verification. Retain historical
  grant-at-start validity and appended revocation lineage; never
  infer a new attempt or independent sample.
  **BLOCKED_ON_SCHEDULER**.
- **G06b, new attempt after revocation:** an original attempt or retry
  starts at/after effective revocation or exclusive expiry. Refuse
  the new invocation without changing the earlier accepted attempt.
  **BLOCKED_ON_SCHEDULER**.
- **G06c, forged issuer/conflicting grant:** same ID with changed
  original bytes, unverifiable revocation origin or fabricated
  retroactive effective time. Refuse invalid original proof, and
  retain the earlier immutable record. **BLOCKED_ON_SCHEDULER**.
- **G07, backdated request:** grant was issued or first available
  after logical K1 invocation. Refuse. **BLOCKED_ON_SCHEDULER**.
- **G08, K1-only future-input control:** source first available at
  `21:00:01Z` consumed under `21:00:00Z` input cutoff. Invalid
  causal lookahead independently of whether a grant exists.
  **BLOCKED_ON_507**.
- **G09, valid completion:** no future input, original allowed
  grant, model completes after cutoff but within decision deadline.
  Do not reject solely for completion time.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G10, terminal absence:** hold, abstain, unavailable or failed
  K1 attempt under original grant. Preserve distinct outcomes,
  costs and denominator. That research attempt authorizes no new
  order, and cannot erase pending/protective orders or assert RESULT.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G11, replay/conflict:** exact identical original grant replay
  idempotent; same grant ID and different original bytes invalid.
  **BLOCKED_ON_SCHEDULER**.
- **G12, repeated M2 result:** identical deterministic result hash
  but another operational ID. Retain genuine association lineage;
  never add independent scientific sample from ID alone.
  **BLOCKED_ON_508**.

For each issuer-dependent positive case, the eventual producer test
must independently prove a forged or missing original issuer **fails**.
A syntactically valid user-created grant object is insufficient evidence.

## 7. Owner decisions and activation gates

**Kanuj:** This document proposes the scheduler's logical issuer
boundary, fields, immutability, clocks and refusal cases. The actual
scheduler original issuance/retention site is **not implemented**.
Only after cross-owner review and a separate exact issue/write-set
may a trusted original issuer be built.

**Matthew #508:** Supply and accept a genuine account provisioner
receipt/original issuer/retention verifier. Confirm whether that
primitive exists now or must be separately built for synthetic use;
then define original M0/M2 account/result association.

**Krish #507:** Confirm grant consumption and `logical_request_id`,
original attempt/retained validation origin and no-candidate
outcomes. His proposed `ResearchE1DecisionAssociationV1` is
still provisional until account + scheduler grant are verifiable.

**E6B B2/B3:** A final typed trial-record design and implementation
can only import accepted public producer types after these
independent proofs. Historical G1/G3, paper/live orders, paid data
and actual comparative investment advantage remain separately gated.

This file introduces no runtime grant, account, financial book,
source provider, secret, trading permission or claimed historical return.
