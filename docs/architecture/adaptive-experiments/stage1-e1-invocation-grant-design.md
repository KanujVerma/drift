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
public **provenance verifier** correction was completed through merged
[#504](https://github.com/KanujVerma/drift/pull/504), alongside
[#503](https://github.com/KanujVerma/drift/issues/503). Those two issues
closed on October 21, 2026. Merged
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
  In particular, a trusted `receipt_observed_available_by_at`
  witness from a bounded synthetic host proves the provisioning
  receipt was available **by** that observed instant; it does
  not establish an exact first-visibility instant, cash funding
  or an account creation event. #508 must accept the actual
  receipt/witness semantics before the grant can claim the
  required evidence was available to its issuer at issuance.
  No consumer may silently rename the witness into stronger
  original availability evidence.
- **Scheduled research intent:** `logical_request_id`,
  `request_kind`, `method_or_selector_policy_ref`,
  `allowed_strategy_refs`, `context_policy_ref`,
  `decision_cutoff` and `decision_deadline`.
  The original retained `AttemptRecord.logical_request_id` must
  equal the grant's logical request. Resolve its `method_ref`,
  `ResearchContext.method_ref`, any applicable
  `ModelReplayRecord.method_ref`, and every original retained
  `ResearchCandidate.method_ref` to the granted method via the
  same accepted #507 producer mapping. A completed nontrading
  candidate also retains its actual method; only an absent candidate
  on a genuinely failed/rejected attempt skips this candidate check. The original attempt's
  `context_ref` must reference that retained context, with the
  same decision cutoff by instant and the same E1 arm/account.
  A retained attempt is not admitted merely by matching IDs.
  The proposed cross-producer intent verification MUST additionally:
  - Bind `request_kind` through a #507 issuer-verified mapping to the
    original `ResearchContext.review_reason` and applicable
    `trigger_ref`/scheduling evidence. Those K1 fields are not
    themselves a canonical request-kind enum; absent accepted mapping
    is `UNAVAILABLE`, not an assumed string equivalence.
  - Resolve `method_or_selector_policy_ref` against the original
    `ResearchContext.method_ref`, both `AttemptRecord.method_ref`
    records, any `ModelReplayRecord.method_ref`, and any retained
    `ResearchCandidate.method_ref` (including nontrading
    dispositions). Refuse an authentic candidate-method mismatch
    even if the attempt, context and replay methods agree. For an
    actual proposed selection also verify its original
    `ResearchCandidate.strategy.envelope_ref` and
    `eligibility_ref` against the issuer-verified selector-policy
    mapping. A valid method alone does not approve another selector.
  - Freeze the meaning of `allowed_strategy_refs` as full,
    versioned `ArtifactReference` identities for concrete proposed
    strategies, not a family-ID string or caller-created name. For
    `disposition="propose"`, the original
    `ResearchCandidate.strategy.strategy_ref` must exactly match
    one granted `(id, version, sha256)` reference, and its
    `family_id` must also belong to the verified E1 arm's
    `eligible_strategy_references` and campaign strategy pool.
    Retained `hold`/ `abstain`/ `unavailable` or failed/rejected
    no-proposal attempts do not invent a candidate strategy to
    satisfy that membership check. `hold` separately requires
    verified incumbent selection and original state.
  - Resolve `context_policy_ref` through an accepted #507 mapping
    to the retained `ResearchContext.clock_policy_ref` and
    applicable original input/memory/feedback policy lineage.
    The same original issuer mapping must also bind the grant
    to the exact frozen E1 `ArmSpecV1.information_visibility_policy`
    and `feedback_policy_reference`, and to the campaign's
    `source_eligibility_policy_reference` and
    `learning_and_feedback_policy_reference`. Add the proposed
    `context_e1_policy_binding_ref` to the retained grant.
    These campaign and arm policies have distinct meanings;
    compare via a versioned issuer-verified translation rather
    than asserting that all four strings are equal. Verify
    original K1 input/memory/feedback lineage, cutoff and
    available evidence against both the grant's context
    policy and those frozen E1 policy revisions.
    Matching grant and K1 refs under a DIFFERENT frozen
    arm visibility, feedback or campaign source/learning
    policy is `INVALID`; missing authentic E1-to-K1
    translation is `UNAVAILABLE`, even if K1 and grant
    hashes independently match. Merely matching a free-form
    `review_reason` or a caller ref does not authenticate
    this policy.
  Every comparison consumes original retained K1 evidence and the
  same authenticated original grant revision. An authenticated
  mismatch is `INVALID`; an absent producer mapping or original
  policy/selector proof is `UNAVAILABLE` and blocked on #507.
  An account/checkpoint string match alone cannot grant a different
  method, request kind, context policy or strategy permission.
- **Frozen producer and model treatment:** retain the exact
  `ArmSpecV1.selector_type`, `model_configuration_reference`,
  `deterministic_seed_reference`,
  `frozen_configuration_reference`, campaign
  `model_and_prompt_policy_reference`, and a proposed
  `producer_model_policy_binding_ref` naming the versioned, original
  #507 issuer-verified mapping. This does not assert that the scheduler
  itself verifies raw provider calls, or that the two model-policy refs
  are interchangeable in a real deployment.
  - The synthetic ARM-B `ADAPTIVE_AI` lane requires an originally
    authorized `producer="ai"` for a model-produced attempt/candidate,
    plus the correct frozen model/prompt configuration. The synthetic
    ARM-R `DETERMINISTIC_COMPARATOR` lane uses
    `producer="conventional_r"` and has
    `model_configuration_reference="NONE"`; it must not gain AI
    treatment via a matching method, account or strategy hash.
    `producer="scripted_fixture"` is allowed only in an explicitly
    separately scoped structural fixture, never silently substituted
    into a claimed original ARM-B or ARM-R result. Future producer lanes
    require separately accepted policy, not a default enum coercion.
  - An original #507 producer-owned mapping must verify both
    `AttemptRecord.producer` on its start and terminal events and
    `ResearchCandidate.producer` when a candidate exists. A genuine
    missing-candidate refusal retains its original attempt producer
    without inventing a candidate; candidate existence alone does not
    prove that producer. Contradictory authentic producer values are
    `INVALID` even when every method and policy ref matches.
  - For actual AI calls, resolve the original
    `ModelReplayRecord.provider_identity`, `requested_model`,
    `resolved_model_revision` (or the exact accepted unknown-revision
    limitation), `adapter_ref`, `parser_schema_ref`,
    `method_ref` and original raw request/configuration evidence
    through that same accepted mapping to the arm's frozen model
    configuration, campaign model/prompt policy and K1 method.
    The mapping's original revision and effective scope must be
    verified as of invocation, not inferred from a current model name
    or rewritten after execution. A changed provider/model, adapter,
    parser, prompt/method or unauthorized producer is `INVALID`;
    a missing original replay, issuer-verifiable policy mapping or
    required model-resolution evidence is `UNAVAILABLE`, never
    an implicit match. If the accepted frozen policy explicitly
    permits unknown model revision, preserve its limitations instead
    of claiming identical known model weights.
  - The same original producer-owned mapping must bind the frozen
    `deterministic_seed_reference` and
    `frozen_configuration_reference` to the actual method,
    strategy/algorithm implementation, normalized parameters
    and applicable replay-generation seed/options. For ARM-R,
    the exact comparator algorithm/configuration revision must
    match the frozen value despite having no model replay.
    For ARM-B, verify the declared original model/algorithm
    seed where the frozen method supports it; a model/provider
    that cannot guarantee reproducible seeding requires an
    explicit originally accepted limitation and may not claim
    a verified deterministic seed. A genuine seed or comparator
    algorithm mismatch is `INVALID`; absent authorized
    configuration-to-original mapping is `UNAVAILABLE`,
    never an implicit match because the method ref or result
    hash happens to agree.
  - Genuine preflight and no-call refusals require original negative
    call evidence and do not fabricate a model replay; a scripted
    offline source is not evidence of a provider call. A real AI
    model-produced candidate without its required original replay
    remains `UNAVAILABLE`, not an admitted selection.
- **Frozen research-budget policy:** the grant must bind the exact
  `ArmSpecV1.research_budget_reference` from the verified full E1
  manifest and a proposed `budget_policy_binding_ref` for the
  original #507 issuer-approved budget policy, including its
  version, effective scope, currency, allowed resource categories,
  per-attempt ceiling and applicable run/arm aggregate limits.
  These are references to future accepted producer evidence, not
  invented budget amounts, credential allocations or new K1 fields.
  The scheduler cannot expand the arm's frozen spending permission.
  - Independently resolve and require both original retained
    `ResearchContext.budget_ref` and the start/terminal
    `AttemptRecord.budget_ref` to map to that same frozen
    `research_budget_reference` and versioned budget policy,
    under the same arm/account/run/trial and original attempt.
    Similar labels or independently rehashed refs are not enough.
  - Before any potentially costly work, verify the actual original
    `AttemptRecord.budget_authorization_ref` through #507's
    trusted per-attempt reservation issuer, binding its original
    attempt ID, logical request, effective issuance/availability
    clock, scope, allowed resource categories and amounts to the
    frozen policy. The authorization must be available by the
    first chargeable action and cannot authorize a greater or
    different budget than the frozen arm permits. Compare
    supported amounts as exact decimal values in the original
    currency; unknown conversions or remaining balance cannot
    silently establish authority.
  - Independently join **all** original attributable
    `CostReceipt` records, including `cost_receipt_ids`
    on the attempt and candidate, late receipts, corrections via
    `supersedes_receipt_id` and shared work via
    `shared_work_ref`, under the accepted #507 allocation rule.
    Verify actual attempt/scope, billing identity/category,
    currency, `amount_basis` and exact decimal amount against
    the original per-attempt authorization and the arm's
    aggregate remaining capacity. A correctly scoped reservation
    cannot make a USD 100 charge valid under a USD 10 ceiling.
    Nor may an otherwise affordable receipt use an unauthorized
    category or a different arm's shared-work entitlement.
    A proven actual overrun or prohibited category is `INVALID`
    for grant-dependent scientific admission even if the original
    attempt completed; preserve the original cost and failed
    admission, never conceal or rewrite it. Missing original
    receipt completeness, verified shared-work allocation,
    currency/FX basis, actual-versus-estimate basis or later
    unsettled cost is `UNAVAILABLE` until accepted evidence
    supports the budget-compliance conclusion. A late correction
    can revise eligibility with immutable lineage, but cannot
    backdate a grant or erase incurred cost.
  - A verified *direct preflight refusal* with no chargeable work
    may have a null budget authorization only under the accepted
    #507 exception, with original reason and failure evidence.
    That exception never admits a costly attempt or treats
    unknown later charges as verified zero. Actual `CostReceipt`
    and late correction/shared-work receipts remain evidence of
    incurred spending, not retroactive spending permission.
  - Conflicting original policy, wrong-arm authorization, excessive
    ceiling, exhausted run/arm quota, late reservation or
    off-policy work is `INVALID` for scheduler admission while
    retaining actual attempts and costs. Missing original budget
    mapping, reservation/verifier, currency conversion or trusted
    remaining-capacity proof is `UNAVAILABLE`; the consumer
    cannot compute a larger authorization from nominal account
    cash or assume a no-spend outcome.
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
  For **scientific decision admission**, the accepted K1 original
  `AttemptRecord.completed_at` on the verified terminal event is the
  conservative decision-ready classification clock, **not** the raw
  provider response timestamp. Require that trusted terminal
  `completed_at <= decision_deadline`. For a model call, independently
  verify the original `ModelReplayRecord.response_received_at`,
  `parse_completed_at`, and the retained validator's actual first
  availability against that terminal; none may establish a usable
  candidate later than the deadline. Their precise producer issuer
  remains pending #507. Completion after deadline must refuse the
  checkpoint's decision admission as `DEADLINE_EXPIRED`, retaining
  original attempt/evidence/cost. Missing or unverifiable required
  clocks mean `UNAVAILABLE`, not fabricated timely completion.
  A raw response before deadline with a parser/terminal event after
  deadline is **not** an eligible decision for that checkpoint.
  No timestamps may be backdated or mistaken for future source input.
- For an actual model call, verify original retained instants:
  `AttemptRecord.started_at <= ModelReplayRecord.request_sent_at
  <= ModelReplayRecord.response_received_at
  <= ModelReplayRecord.parse_completed_at
  <= original_validation_first_available_at
  <= AttemptRecord.completed_at <= decision_deadline`.
  Validation availability remains an **unaccepted #507 issuer
  fact**, not a new source field invented by the consumer.
  Missing trusted clock proof yields `UNAVAILABLE`; present
  but causally impossible chronology is `INVALID`, even
  if all timestamps are before the deadline. Verified
  no-model-call terminal refusals do not need invented replay
  response or parse clocks.
- The accepted `ResearchContext` internally orders cutoff,
  build and review, but this cross-record verifier also needs
  `ResearchContext.review_started_at <= AttemptRecord.started_at`.
  A K1 attempt cannot use a context whose original review began
  only after invocation. Authentic contradiction is `INVALID`,
  independent of the eventual context content hash.
- The original account/scheduler issuance chain requires
  `allocation_first_available_at <= grant_issued_at
  <= grant_first_available_at <= AttemptRecord.started_at`,
  with times independently retained by the authentic Matthew
  account and Kanuj scheduler issuers. Original grant issuance
  before the original account-provisioning receipt was first
  available, or grant availability before issuance, is `INVALID`,
  not rescued by a matching E1 string or hash. This receipt clock
  establishes when trusted evidence was available to the scheduler,
  not when the account was actually assigned or capital was funded.
- Original scheduler grant issuance and verified availability must
  precede its designated logical K1 invocation. A grant first issued
  after the attempt cannot be accepted retroactively. Also require
  `AttemptRecord.started_at >= invocation_not_before_at`, using the
  original verified timezone-aware K1 start event, not a new field.
  Prior issuer availability alone does not
  authorize a research attempt before its scheduled start.
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
- For chargeable research, the original #507 per-attempt budget
  authorization must be issued and independently available before
  the first chargeable action, with the scope and ceiling of the
  frozen E1 arm's research budget. A timely scheduler grant alone
  does not authorize paid provider calls, and an after-the-fact
  cost receipt cannot backdate spending permission. If accepted
  #507 evidence cannot establish the authorization-before-work
  ordering, classify `UNAVAILABLE` rather than inventing a
  reservation clock. Verified contrary ordering is `INVALID`;
  a real no-work preflight refusal follows its separately proved
  null-authorization exception. Unknown incurred costs remain
  unknown and are still retained.
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
   through the accepted single-view APIs. The #511 single-view
   provenance correction is merged under #504; it is structural
   verification only, not accepted original account issuance.
2. Verify **Matthew's original account allocation issuer and retained
   receipt** independently, including account, arm, run, cutoff and
   full manifest. Refuse arbitrary matching caller account strings.
3. Retrieve the original scheduler grant from the approved issuer;
   check original bytes, issuer and version, issuance and availability,
   and original **invocation/attempt-start timestamp**. Verify
   the account provisioner receipt was genuinely first available
   no later than grant issuance, and grant first availability was
   not earlier than the original grant issuance. Confirm the
   original K1 `ResearchContext.review_started_at` was not
   later than its `AttemptRecord.started_at`. Require the
   attempt start at/after `invocation_not_before_at` and before the
   exclusive `grant_expires_at` when present. Evaluate revocation
   as of that original start, using independently verified effective,
   recorded and first-available instants. Retain any subsequent
   revocation without retroactive validity changes.
4. Krish independently verifies his original K1 context, attempt
   start/terminal, retained validator decision, candidate or absence,
   model replay and raw research costs. For a checkpoint's decision
   deadline use the actual retained terminal
   `AttemptRecord.completed_at` as the conservative ready clock,
   with verified response/parse/validation clocks where applicable.
   Missing required issuer clocks are unavailable; late terminal
   classification cannot be backdated by timely raw responses.
   Match the original `AttemptRecord.logical_request_id` against
   the grant, original `method_ref` and the referenced retained
   `ResearchContext.method_ref` against the accepted #507 granted
   method mapping, and its original context cutoff and E1
   arm/account scope against the SAME grant. Resolve and verify
   `request_kind` using original K1 review/trigger evidence and
   the explicit #507 mapping. Verify the granted selector policy
   against the original method, every retained
   `ResearchCandidate.method_ref` where a candidate exists, and,
   for proposals, retained strategy envelope/eligibility evidence. Verify exact full
   `ResearchCandidate.strategy.strategy_ref` membership in the
   grant's `allowed_strategy_refs` and its family in the frozen
   E1 arm/campaign pools; do not invent a strategy for genuine
   nontrading or failed attempts. Verify `context_policy_ref`
   through #507's original K1 clock/input/memory/feedback policy
   mapping.
   **Verify the frozen producer/model lane independently:** check
   the original E1 `ArmSpecV1.selector_type`,
   `model_configuration_reference` and campaign
   `model_and_prompt_policy_reference` against the exact granted
   `producer_model_policy_binding_ref` and #507 issuer-verified
   producer mapping. Compare both original start/terminal
   `AttemptRecord.producer` values and the original
   `ResearchCandidate.producer` whenever a candidate exists.
   ARM-B `ADAPTIVE_AI` and ARM-R
   `DETERMINISTIC_COMPARATOR` may not swap `ai`,
   `conventional_r` or `scripted_fixture` under a matching
   method/strategy hash. For genuine model calls, check
   original replay method, provider, requested and resolved
   model identity/limitation, adapter, parser, and raw
   request/configuration against the arm and campaign's frozen
   policies. No authentic mapping means `UNAVAILABLE`;
   an authenticated wrong producer, model or configuration
   means `INVALID`. Do not invent replay evidence for
   no-call terminal refusal.
   **Verify the frozen research budget independently:** bind
   the exact arm `research_budget_reference` through the
   granted `budget_policy_binding_ref` to both the retained
   `ResearchContext.budget_ref` and start/terminal
   `AttemptRecord.budget_ref`. For potentially costly work,
   resolve the original per-attempt
   `AttemptRecord.budget_authorization_ref` through the #507
   reservation issuer and verify original scope, effective time,
   permitted categories, currency, per-attempt ceiling and
   applicable run/arm remaining capacity before that work.
   An authorization under a different or larger budget must
   refuse `INVALID` even if actual spending was lower. A
   missing producer mapping, trusted reservation or cap proof
   means `UNAVAILABLE`. Only a proven no-work preflight
   refusal can lack the authorization, retaining its reason
   and any unknown cost evidence. Do not replace authorization
   with a billing or M2 cash receipt.
   For model calls, verify request/response/parse/
   original-validation/terminal order before declaring
   decision readiness. Refuse independently verifiable
   contradictions even when every clock precedes the
   deadline. Never promote a grant into an accepted
   research output.
5. Matthew separately verifies actual M0/M2 admission, result/trace,
   account book, order/fill/refusal/UNKNOWN, valuation and posted
   trading costs without reinterpreting its original hashes.
6. E6B joins only **two verified producer associations** agreeing
   on full original E1 scope. Missing or contradictory evidence
   prevents a completed scientific result, but does not erase
   the attempted/opportunity denominator.

Missing original issuer or producer evidence is `UNAVAILABLE` with
a reason. Forged, conflicting or scope-mismatched evidence, a grant
revoked or expired **at/before its original attempt start**, or
an invocation starting **before `invocation_not_before_at`** is
`INVALID`. A later revocation does not invalidate the earlier
original grant-at-start check. Genuine future input is lookahead,
not a normal after-cutoff model completion. No generic `dict[str, Any]`
evidence resolver or second financial ledger is allowed.

## 6. Forty-nine synthetic original-grant test vectors

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
  rehashed. **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER**.
- **G04, crossed account:** ARM-B grant references ARM-R's actual
  original allocation. Reject.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER**.
- **G05, self-claimed trust:** valid hash without original scheduler
  issuance/accepted independent verifier. Unavailable, no admitted
  grant. **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER**.
- **G06a, historical valid replay:** original valid grant and attempt
  started before its expiry/revocation-effective time, then genuine
  later revocation before replay verification. Retain historical
  grant-at-start validity and appended revocation lineage; never
  infer a new attempt or independent sample.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G06b, new attempt after revocation:** an original attempt or retry
  starts at/after effective revocation or exclusive expiry. Refuse
  the new invocation without changing the earlier accepted attempt.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G06c, forged issuer/conflicting grant:** same ID with changed
  original bytes, unverifiable revocation origin or fabricated
  retroactive effective time. Refuse invalid original proof, and
  retain the earlier immutable record.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER**.
- **G07, backdated request:** grant was issued or first available
  after logical K1 invocation. Refuse.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G08, K1-only future-input control:** source first available at
  `21:00:01Z` consumed under `21:00:00Z` input cutoff. Invalid
  causal lookahead independently of whether a grant exists.
  **BLOCKED_ON_507**.
- **G09, valid completion:** no future input, original allowed
  grant; all logical request, request kind, method/selector,
  allowed strategy (for `propose`), context-policy and cutoff
  restrictions are originally verified. Verify
  `ModelReplayRecord.response_received_at`,
  `parse_completed_at`, original retained validator availability,
  and terminal `AttemptRecord.completed_at` are all authentic
  and at/before the decision deadline, although after input cutoff.
  Preserve an eligible completion only with verified issuer/receipt.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G10a, valid hold:** completed K1 research disposition `hold`,
  independently verified matching current incumbent and valid
  selection state. Retain actual attempt/reason; no executable
  target supplied by this attempt. A mismatched or unresolved
  incumbent must be refused, not assumed.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G10b, abstain:** disposition `abstain`, distinct terminal
  reason and no proposed allocation; retain attempt and actual
  research cost. Do not infer platform-wide no-order state.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G10c, unavailable:** disposition `unavailable` because a
  required eligible research input is missing. Retain the precise
  missing-input reason and attempt, not a fabricated hold/abstain.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G10d, failed attempt:** genuinely terminal `failed` original
  K1 attempt, retained failure/validation evidence, nullable
  candidate and actual or explicitly unknown research cost.
  Never mark `VALID` or infer an executable allocation.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G10e, rejected attempt:** genuinely terminal `rejected` with
  independently retained rejection reason/validation evidence,
  nullable candidate and its actual/unknown costs, separately
  asserted from `failed` and never `VALID`.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G11, replay/conflict:** exact identical original grant replay
  idempotent; same grant ID and different original bytes invalid.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER**.
- **G12, repeated M2 result:** identical deterministic result hash
  but another operational ID. Retain genuine association lineage;
  never add independent scientific sample from ID alone.
  **BLOCKED_ON_508**.
- **G13, premature invocation:** an original grant is valid and
  already available, but the K1 attempt started before
  `invocation_not_before_at`. Refuse the early attempt with its
  original timestamp and reason even if all account/scope hashes match.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G14a, late raw model response:** eligible original input/grant,
  but trusted `ModelReplayRecord.response_received_at` is after
  `decision_deadline`. Refuse checkpoint decision admission as
  `DEADLINE_EXPIRED`; retain genuine replay, attempt and cost.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G14b, timely response but late validated decision:** raw
  `response_received_at` is at/before deadline, but
  `parse_completed_at`, original validation availability or the
  terminal `AttemptRecord.completed_at` is later. Refuse the
  checkpoint decision as `DEADLINE_EXPIRED` even though a raw
  model response arrived on time. Do not backdate validation.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G14c, unknown terminal/validation clock:** an otherwise valid
  grant has no independently verified `AttemptRecord.completed_at`
  or original retained validation availability. Report
  `UNAVAILABLE` with exact cause, never a phantom timely decision.
  Preserve the attempted denominator.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G14d, unknown model response clock:** a model-call attempt has
  valid grant, terminal and validation records but no authentic
  `ModelReplayRecord.response_received_at` (or its original issuer
  is unverifiable). Mark checkpoint decision `UNAVAILABLE`,
  not within-deadline, while retaining original attempt and costs.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G14e, unknown model parsing clock:** a model-call attempt has
  valid grant, terminal, validation and response clocks but no
  independently verified `ModelReplayRecord.parse_completed_at`.
  Mark checkpoint decision `UNAVAILABLE`, not timely success.
  Do not impose model-replay fields on a verified no-call terminal
  refusal. Retain attempted denominator and original cost basis.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.

- **G15a, wrong logical request:** authentic
  `AttemptRecord.logical_request_id` differs from the grant
  despite matching E1 account/arm/checkpoint. Refuse; one
  request cannot reuse another request's original grant.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G15b, wrong research method:** independently retained
  `AttemptRecord.method_ref`, `ResearchContext.method_ref`,
  applicable `ModelReplayRecord.method_ref`, or any retained
  `ResearchCandidate.method_ref` differs from the grant through
  the same #507 accepted mapping. Refuse rather than trusting
  a method string or copied hash.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G15c, mismatched original context:** retained
  `AttemptRecord.context_ref` references another context,
  the original `ResearchContext.decision_cutoff` differs
  from the grant by instant, or context account/arm scope
  disagrees. Refuse this grant/attempt association.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G15d, wrong scheduled request kind:** attempt/context
  appear otherwise valid but original K1 review/trigger evidence
  maps to a different `request_kind`. Refuse `INVALID`, not
  caller-declared kind equality.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G15e, strategy outside granted set:** a valid `propose`
  returns a `ResearchCandidate.strategy.strategy_ref` with
  `(id, version, sha256)` not in the original grant's
  `allowed_strategy_refs`, or an unapproved E1 arm/campaign
  family. Refuse even when method and scope are authentic.
  Non-proposal dispositions must not invent a strategy.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G15f, wrong context policy:** otherwise authentic
  `ResearchContext.clock_policy_ref`/original input or
  memory policy lineage does not map to the grant's
  `context_policy_ref`. Refuse the conflicting policy.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G15g, no original producer policy mapping:** matching
  account, method and candidate hashes but no verified #507
  request-kind, selector or context-policy mapping. Report
  `UNAVAILABLE` with the precise missing mapping, never
  default to a valid grant. Retain the attempt denominator.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G15h, wrong selector authorization:** `propose` selects
  a granted strategy, but its retained `CandidateStrategy`
  `envelope_ref` or `eligibility_ref` belongs to a different
  selector-policy lineage than the granted method/selector.
  Refuse `INVALID`; strategy membership alone is insufficient.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G15i, candidate method differs from granted method:** original
  K1 context, both attempt records and any model replay all have
  the verified granted `method_ref`, but retained
  `ResearchCandidate.method_ref` resolves to a different method.
  Refuse `INVALID` even for a `hold`, `abstain` or
  `unavailable` candidate; do not manufacture a candidate on a
  genuinely failed/rejected original attempt.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G15j, wrong feedback-policy lineage:** original context clock,
  input and memory policies are valid, but the actual
  `ResearchContext.feedback_refs` and original feedback producer
  lineage resolve under #507 to a policy conflicting with the
  grant's `context_policy_ref`. Refuse `INVALID` with the
  feedback mismatch reason, even though all other policy checks
  succeed. Missing authentic feedback-policy mapping is
  `UNAVAILABLE` under G15g, not a fabricated match.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G16a, response predates request:** original authentic
  `ModelReplayRecord.response_received_at` precedes
  `request_sent_at`, or request precedes the actual
  `AttemptRecord.started_at`. Refuse `INVALID` chronology
  even if all clock values are before decision deadline.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G16b, parsing predates response:** authentic
  `ModelReplayRecord.parse_completed_at` precedes the
  original `response_received_at`. Refuse `INVALID`
  chronology; a deadline alone cannot validate it.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G16c, terminal predates validation:** original
  `AttemptRecord.completed_at` predates retained
  validator first availability, though both precede
  the decision deadline. Refuse `INVALID` chronology,
  preserve original terminal and cost receipts, and never
  backdate validation to claim timely eligibility.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.

- **G16d, context reviewed after attempt start:** original
  `ResearchContext.built_at` precedes `review_started_at`
  internally, but authentic `review_started_at` occurs
  AFTER original `AttemptRecord.started_at`. Refuse
  `INVALID` cross-record chronology despite matching
  grant/account/attempt and other model timestamps.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G17a, grant issued before provisioning evidence was available:**
  trusted `allocation_first_available_at` of Matthew's retained
  original account-provisioning receipt is after `grant_issued_at`,
  even though both precede K1 invocation. Refuse `INVALID`
  ordering: the scheduler did not yet have the required original
  receipt. This does not establish whether underlying account
  assignment or capital funding had already occurred.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER**.
- **G17b, grant available before grant issuance:** authentic
  original `grant_first_available_at` precedes actual
  `grant_issued_at`. Refuse `INVALID` chronology, not a
  backdated grant with valid appearance.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER**.
- **G18a, crossed producer lane:** frozen ARM-B is
  `ADAPTIVE_AI`, but its authentic started/terminal
  `AttemptRecord.producer` or normalized
  `ResearchCandidate.producer` is `conventional_r` or
  `scripted_fixture`. Separately inject `ai` into genuine
  `DETERMINISTIC_COMPARATOR` ARM-R; keep method and all
  strategy refs matching to prove the producer check itself
  rejects `INVALID`.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G18b, wrong original model configuration:** an ARM-B
  attempt has authentic `producer="ai"` and matching grant
  method, but the original `ModelReplayRecord` uses a
  different provider/requested or resolved model revision,
  `adapter_ref`, `parser_schema_ref`, or raw prompt/config
  than the frozen arm/campaign policy and issuer mapping.
  Each changed dimension independently refuses `INVALID`;
  the raw result hash and matching strategy cannot bypass
  that comparison.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G18c, no authenticated producer/model mapping:** original
  attempt/candidate/model replay are individually well formed,
  but #507 cannot independently resolve the frozen selector
  or arm-model-policy-to-replay configuration and effective
  revision. Expect `UNAVAILABLE`, with missing producer
  evidence named; never infer authentic matching from the
  literal model string or a caller-signed blob. A required
  missing original AI replay is also `UNAVAILABLE`.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G18d, verified B/R producer positive:** independently
  verify an original ARM-B `ADAPTIVE_AI` model call with
  issuer-bound `producer="ai"` and matching replay policy;
  separately verify an original ARM-R conventional
  `producer="conventional_r"` and its frozen
  `model_configuration_reference` set to `NONE`, with no
  invented AI replay. Both retain their
  original source clocks, grant scope and distinct account
  proofs, not identical models or science-scored observations.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G19a, wrong frozen budget policy:** grant is for ARM-B
  with `research_budget_reference="fixture://budget-B"`,
  but original `ResearchContext.budget_ref` or started/
  terminal `AttemptRecord.budget_ref` resolves to the
  authentic ARM-R budget or another policy revision. Refuse
  `INVALID`, even when the attempt's cost receipt shows zero.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G19b, excessive or crossed authorization:** original
  `AttemptRecord.budget_ref` matches ARM-B, but its actual
  `budget_authorization_ref` resolves to a different arm,
  a larger per-attempt ceiling, an exceeded run/arm aggregate
  cap, or a wrong spending category or currency. Each
  independently refuses `INVALID`; a cheap actual call
  cannot validate an overly permissive authorization.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G19c, absent trusted budget reservation:** otherwise
  coherent attempt has no verifiable #507 budget-policy
  mapping, original per-attempt authorization, remaining-cap
  proof or authentic authorization-first-available clock.
  Expect `UNAVAILABLE`, retain actual or unknown incurred
  cost and the attempted denominator; do not synthesize
  a permission from the grant or nominal portfolio cash.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G19d, verified bounded authorization positive:** the
  original #507 budget issuer independently attests both
  context and start/terminal budget refs under the frozen
  B (or separately R) arm budget; one actual per-attempt
  reservation was effective and available before costly work,
  with verified unexceeded per-call and aggregate limits.
  Accept only this spending-policy precondition, not a
  candidate's risk, fill, profitability or G3 status.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.
- **G19e, no-work preflight exception:** original rejected
  preflight attempt has no cost-bearing action and records
  its original failure/reason and verifiable no-work
  evidence. Null `budget_authorization_ref` is permitted
  only by the accepted #507 policy for this refused attempt;
  no strategy or RESULT becomes eligible, and an unknown
  later cost cannot be recorded as verified zero.
  **BLOCKED_ON_508 + BLOCKED_ON_SCHEDULER + BLOCKED_ON_507**.

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

**Krish #507:** Independently ACCEPT/NARROW/REJECT the versioned
producer/model treatment mapping for original start/terminal
`AttemptRecord.producer`, optional `ResearchCandidate.producer`
and any genuine `ModelReplayRecord` provider/model/adapter/parser
configuration under the frozen E1 `selector_type` and model policy.
Also accept the budget policy and per-attempt authorization issuer
mapping for `ResearchContext.budget_ref`,
`AttemptRecord.budget_ref` and `budget_authorization_ref`,
including original effective times, currency/categories and
remaining-capacity proof or direct no-work preflight exception.
Confirm original grant consumption, `logical_request_id`,
attempt/retained validation origin and no-candidate outcomes.
His proposed `ResearchE1DecisionAssociationV1` remains
provisional until account + scheduler grant and both mappings
are independently verifiable.

**E6B B2/B3:** A final typed trial-record design and implementation
can only import accepted public producer types after these
independent proofs. Historical G1/G3, paper/live orders, paid data
and actual comparative investment advantage remain separately gated.

This file introduces no runtime grant, account, financial book,
source provider, secret, trading permission or claimed historical return.
