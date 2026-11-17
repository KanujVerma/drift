# E6B synthetic producer-to-trial acceptance vectors (precontract)

**Status:** B1.5 owner-scoped test design, not an accepted Krish or Matthew wire
revision, B2 typed attachment design, B3 implementation, scored evaluation or
execution permission.

**Accountable owner:** Kanuj, issue [#509](https://github.com/KanujVerma/drift/issues/509).
**Producer dependencies:** Krish [#507](https://github.com/KanujVerma/drift/issues/507)
and Matthew [#508](https://github.com/KanujVerma/drift/issues/508).
**Parent:** [E6B #485](https://github.com/KanujVerma/drift/issues/485).
**Source readback:** accepted `main` at
`fcb53d3683e6d01a1a5a5cd0bdd2dbdbe0b096d6`, on October 20, 2026.

## 1. Acceptance boundary

This file defines **consumer test inputs and expected refusal rules**, not a new
producer type, issuer, signature, ledger, event format or qualified result. A
synthetic artifact in this plan is illustrative unless it is constructed by an
existing accepted public builder and verified by that builder's actual tests.

The [experiment contract](contracts/experiment.md), especially sections 3.3
through 3.6, is authoritative for trial event and derived `TrialRecordV1`
semantics. E1 campaign and arm constructors are implemented in
`src/drift/experiments/stage1_campaign_config.py`; immutable event/provenance
and checkpoint audit structures live in
`src/drift/experiments/stage1_trial_events.py`,
`src/drift/experiments/stage1_trial_provenance.py` and
`src/drift/experiments/stage1_checkpoint_coverage.py`.

The merged [#500 cross-layer fixture](https://github.com/KanujVerma/drift/pull/500)
is the executable **structural-only** baseline. It does not source platform
RESULT, financial orders or authenticated provider data. The bounded
[#504](https://github.com/KanujVerma/drift/pull/504) and
[#506](https://github.com/KanujVerma/drift/pull/506) hardening PRs are
independent and must not silently supply missing producer authority.
Matthew's executed [#511](https://github.com/KanujVerma/drift/issues/511)
provenance account-binding defect is a separate prerequisite for any trial
projection claiming a fully consistent E1 account/manifest join. #504's
event-sequence fix does not repair #511.

## 2. Fixed accepted synthetic fixture identity

Use the actual builders and values from
`tests/integration/test_stage1_science_foundation_contract.py`.
The one-run, one-checkpoint positive case narrows the general fixture as follows:

| Field | Accepted synthetic fixture |
| --- | --- |
| `campaign_id` | `CAMP-E1-SYNTH-001` |
| `campaign_spec_fingerprint` | `2c9cad6f55847c20bf9c7f5a5eaa1ec6f828c7f107bc32ad8a1516a4b2e88be4` |
| `run_id` | `RUN-001` |
| AI arm / account | `ARM-B` / `SYNTH-ACC-B-001` |
| Conventional arm / account | `ARM-R` / `SYNTH-ACC-R-001` |
| `checkpoint_id` | `CKPT-001` |
| B event kind and canonical root hash | `OPPORTUNITY_CREATED`, `2999edc6f859b6ef17a6b0c99728bab01d7d80cad65e28f59ffd3a5dd5a7f9f4` |
| E6A B state | `EVENTS_RECORDED` |
| E6A R state | `UNOBSERVED` from a **submitted** zero-event snapshot |
| E6A pair state | `BOTH_SUBMITTED` |

Recompute the one-run `complete_manifest_fingerprint`, each immutable
`snapshot_fingerprint` and `audit_fingerprint` using the **existing accepted**
public builders. Do not type an invented SHA into a fixture, backfill missing
snapshots or regenerate original known golden hashes when a mismatch appears.
In particular, a submitted zero-event snapshot is not a missing snapshot.

## 3. Producer proof obligations: no inferred binding

**Krish research [#507](https://github.com/KanujVerma/drift/issues/507).**
The merged `drift.intelligence.contracts.Scope` carries
`experiment_id, arm_id, account_id, campaign_ref`, not E1 `run_id` or
`checkpoint_id`. `ResearchContext`, `ResearchCandidate`,
`AttemptRecord`, `CostReceipt` and `ModelReplayRecord` are immutable
research facts, but an arbitrary identical account string is not the
producer-issued association to the full E1 manifest. The current
`ValidationResult` is a transient validation result, not automatically a
retained `validation_id` receipt. Krish must provide a trusted public
identity/validation proof, including for failed attempts without a candidate.

**Matthew RESULT [#508](https://github.com/KanujVerma/drift/issues/508).**
Merged `EvaluationRunIdentityV1/V2`, `ExperimentRun`,
`EvaluationRunArtifactsV1/V2`, `EvaluationResultV1` and
`PortfolioStateV1/V2` validate evaluator admission, bundle, trace, marked
book and numerical result. None alone binds the original E1
`RunAccountBindingV1` to a trusted account-provisioning event and exact
`(campaign,run,arm,checkpoint)`. A deterministic result hash can legitimately
occur under distinct **operational** runs; it cannot be used as a sole account
join or a counter of independent experiments. Distinct verified operational
associations are retained even when a replay returns the same result hash.
Neither new run IDs nor repeat content hashes alone prove new independent
scientific samples. The accepted trial/replication protocol determines sample
identity.

For each producer, the future accepted evidence must identify its **actual
trusted issuer/retention authority, version/profile, original source reference
and digest, earliest eligible availability, scope, idempotent replay rule and
public verifier**. Do not replace origin verification with the hash of
caller-supplied text.

## 4. Predeclared outcome vocabulary

These are **scientific consumer expectations**, not new persisted producer
enums. Final code must map them only through accepted, versioned contracts.

| Concept | Consumer treatment |
| --- | --- |
| Missing declared checkpoint snapshot | `MISSING_SNAPSHOT`, no synthesized provenance or qualified trial |
| Submitted zero-event snapshot | `UNOBSERVED`, not missing, not a completed RESULT |
| Submitted recorded event | `EVENTS_RECORDED`, structurally present but unqualified until producer evidence |
| Missing required eligible producer evidence | Unavailable/awaiting evidence with explicit reason |
| Attempted use of evidence after its decision cutoff | Invalid causal lookahead; no backdated eligibility |
| Trusted research `hold`, `abstain`, `unavailable` | Retain actual attempt and reason; no manufactured executable target |
| Failed or rejected producer attempt | Retain terminal failure and costs; nullable candidate, never a fabricated accepted proposal |
| M2 evaluator `COMPLETE` | Evaluator-lane completeness only, not automatic scientific result completeness |
| Staged zero orders, partial fills, UNKNOWN | Separate authentic state and cardinality, not fictional fills or finality |
| Complete original account NAV but unknown operating cost | Trading return may remain known; economic gain unavailable |
| Later correction or invoice | New immutable as-of version, no retroactive decision admission |

For research, `decision_cutoff` bounds **information admitted into context**,
not the wall-clock completion of the subsequent model request. A frozen
time-eligible context may be built and reviewed after cutoff, and an eligible
candidate may complete later within its separately accepted timing/expiry
rules. Only actual post-cutoff evidence read into that decision or a later
response improperly reused as an earlier input constitutes lookahead.

## 5. Synthetic acceptance matrix for both producer teams

Each row below is a **test specification**; it is **not an executed test**.
A case marked `READY_LOCAL` already has independent structural/metric
coverage in #500. Cases marked `BLOCKED_ON_507`, `BLOCKED_ON_508`, or
`BLOCKED_ON_BOTH` need genuine accepted producer source/fixture types first.

| ID | Controlled input or mutation | Required expectation | Dependency |
| --- | --- | --- | --- |
| L01 | Exact fixed B/R manifest, distinct accounts, B recorded + R submitted empty | `BOTH_SUBMITTED`; B `EVENTS_RECORDED`, R `UNOBSERVED` | READY_LOCAL |
| L02 | Delete B snapshot after proving L01 positive | B `MISSING_SNAPSHOT`, R `UNOBSERVED`, pair `TEST_MISSING`; no phantom B | READY_LOCAL |
| L03 | Reuse B portfolio account in R binding | E1/E6A refuse cross-arm duplicate account | READY_LOCAL |
| R01 | Trusted research context, accepted candidate and terminal attempt, matched E1 full manifest and checkpoint | Admitted **research association only**, not fill or RESULT | BLOCKED_ON_507 |
| R02 | Same arm/account, wrong `run_id` or `checkpoint_id` | Refuse E1 association even if raw `Scope` strings match | BLOCKED_ON_507 |
| R03 | Wrong research account, modified complete manifest, wrong issuer or original hash | Refuse, preserve unmodified source records | BLOCKED_ON_507 |
| R04 | A market/context input or matured feedback first available at `2026-01-30T21:00:01Z` is consumed despite decision cutoff `21:00:00Z` | Invalid causal lookahead from **input evidence**; refuse the decision | BLOCKED_ON_507 |
| R05a | Verified `hold` with a resolved matching incumbent | Assert `hold` and incumbent match; no target order; retain attempt/reason | BLOCKED_ON_507 |
| R05b | Verified `abstain` without strategy, targets or cash | Assert `abstain`, separate reason/status and no order | BLOCKED_ON_507 |
| R05c | Verified `unavailable` from missing eligible input | Assert `unavailable` and missing-input reason, not hold/abstain | BLOCKED_ON_507 |
| R06 | Failed or rejected attempt, missing accepted candidate, retained raw failure evidence | Retain failure, genuine nullable candidate and cost basis; no fake `VALID` | BLOCKED_ON_507 |
| R07 | Same attempt/replay id with conflicting retained content, or duplicate exact replay | Conflicting content refused; genuine exact replay remains idempotent and not another independent sample | BLOCKED_ON_507 |
| R08 | Raw cost `unknown` vs evidenced `verified_zero`, shared work and superseding correction | Preserve distinctions and correction lineage; no silent zero or double count | BLOCKED_ON_507 |
| P01 | Proven E1 account provisioning, M0 run, M2 result/book/trace and matched cutoff | Admit **platform association** with retained original artifact hashes | BLOCKED_ON_508 |
| P02 | Result assigned to another B/R account or run/checkpoint despite matching result hash | Refuse original account/run join | BLOCKED_ON_508 |
| P03a | Two trusted operational account/run associations share one M2 result hash | Retain both original associations, no join on result hash alone; scored units follow accepted replication policy | BLOCKED_ON_508 |
| P03b | Exact M2 evidence replayed under a new operational ID, no new scientific unit | Retain original and replay lineage; do not increment independent scored samples | BLOCKED_ON_508 |
| P04a | Trusted no-order `hold` and valid current account state | Preserve incumbent, retain zero actual staged/fill orders; do not interpret as mandate refusal | BLOCKED_ON_508 |
| P04b | Explicit mandate/admission `REFUSED` with no orders | Retain refusal/trace/reason and zero verified fills; no completed trade or silent `hold` | BLOCKED_ON_508 |
| P04c | Order status `UNKNOWN` or evidence unavailable with no confirmed fills | Preserve unresolved/unknown status and non-complete scientific result; do not infer no-order completion from absent fills | BLOCKED_ON_508 |
| P05 | N staged orders, some partial fills and one unresolved order | Count only verified actual fills; remain unresolved for dependent completion | BLOCKED_ON_508 |
| P06 | Evaluation `COMPLETE` but missing valuation, reconciliation or required disposal basis | Preserve raw evaluator classification, refuse stronger scientific completeness | BLOCKED_ON_508 |
| P07 | Result, trace, bundle or admission hash contradicts the original retained pair | Refuse association; no new result by rehashing disputed bytes | BLOCKED_ON_508 |
| P08 | Real result made available after decision cutoff, or later correction/invoice | No retroactive eligibility, append versioned later view only | BLOCKED_ON_508 |
| J01 | Full verified research + platform association match the same original E1 trial and as-of cutoff | Derived trial can link both separately; only then consider producer-qualified outcome | BLOCKED_ON_BOTH |
| J02 | Both originals individually valid but contradict each other on account, run or checkpoint | Refuse join, preserve each original record and reason | BLOCKED_ON_BOTH |
| J03 | B evidence complete, R evidence unavailable or partial | Keep both attempted/opportunity identities; do not report a complete paired B/R result | BLOCKED_ON_BOTH |
| J04 | Tamper retained original event/snapshot or replace it with a forged newer hash | Refuse original fingerprint mismatch, no retrospective repair | BLOCKED_ON_BOTH |

The later accepted fixtures must include **one success and meaningful failure in
each producer's own trust path**. A consumer-only constructor proving that two
identical strings compare equal does not satisfy R01 or P01.

## 6. Independent numeric oracles, not invented account evidence

The following is already tested as **supplied Decimal arithmetic** in #500,
not a real result supplied by M0/M2:

| Item | AI B | Conventional R |
| --- | ---: | ---: |
| Starting NAV, USD | 10000 | 10000 |
| Mock ending **net-of-trading-cost** NAV, USD | 10120 | 10060 |
| Net trading return as a fraction | 0.012 | 0.006 |
| Separately supplied research operating cost, USD | 25 | 5 |
| Economic gain after operating cost, USD | 95 | 55 |

The derived paired return difference is **0.006**, or **0.6 percentage
points**. Economic gain difference is **USD 40**. Do not subtract already
posted trading transaction costs a second time. If required research cost is
unknown, economic gain is **unavailable** while a legitimately known trading
return remains known. A valid losing B test (NAV 9980, operating cost 25)
gives B economic gain **-45** and B-minus-R advantage **-100**, not an
excluded case.

These values are **not** fill/account receipts. For future J01 they may be
used only after each producer supplies an independently verifiable synthetic
platform book and its separate attributable research-cost evidence.

## 7. Required order of checks for a future trial projection

1. Independently revalidate original E1 campaign/arms/full run-account binding,
   immutable trial provenance and E6A checkpoint declaration/snapshot audit,
   including the #511 single-view provenance-account correction before
   asserting accepted structural binding.
2. Resolve producer **accepted contract revisions** and verifiers, not names
   or hashes copied from a caller's envelope. Reject missing/unrecognized
   issuer or version before interpreting its claims.
3. Independently verify research association to *all* original E1 identifiers,
   original context/attempt/candidate or failure evidence and true cutoff.
4. Independently verify platform account provisioning, M0 operational binding,
   original M2 admission/result/book/trace, session valuation, execution
   cardinality and cutoff. M2 result hash alone cannot establish account ID.
5. Cross-check both producers against the **same** complete E1 manifest and
   checkpoint. Keep all failure/unknown/correction states in a non-complete
   scientific view. Do not convert `RESULT_BOUND` event labels into proof.
6. Append a separate immutable derived trial revision referencing original
   fingerprints. No mutation of prior E1, event, provenance or E6A objects.
7. Only if verified eligible numeric facts are complete, call the existing
   Decimal metric API. Keep operating costs separate from the portfolio book;
   maintain attempted/qualified/complete denominators separately.

This order is a **consumer test plan**, not a declared implementation
signature. Code-level accepted public verifier names and attachment schemas
remain pending #507/#508 and final B2 design.

## 8. Exact producer handoff and activation gates

**Krish #507 must supply:** source file path and accepted revision for the
research association/validation retention, actual trusted issuer/proof,
immutable original `Scope`/context/attempt/candidate/replay/cost hashes,
availability and wrong-run/wrong-account/late/failed-attempt fixtures. A
transient `ValidationResult` is not itself the required retained receipt.

**Matthew #508 must supply:** source file path and accepted revision for
the original account provisioning and E1-to-M0-to-M2 association, trusted
issuer/proof, original run/admission/bundle/result/trace/book evidence,
zero/N/UNKNOWN cardinality, finality and wrong-account/duplicate-result/cutoff
fixtures. `EvaluationRunIdentity`, `ExperimentRun` and
`PortfolioStateV1/V2` do not natively contain the full E1 account/checkpoint
link.

**B2:** Only once both accepted producer contracts exist, open a distinct
Kanuj-owned design issue to specify *actual public producer types* and the
versioned immutable attachment/trial projection under a separately claimed
file, provisionally `stage1-e6b-trial-record-design.md`. This file is not
that B2 design.

**B3:** Implement the subsequently accepted typed projection and strict tests
under a new issue/branch/write-set. Do not make an absent producer silently
succeed. **B4/G2:** Real synthetic end-to-end producer evidence may follow
with separate acceptance. **G1/G3:** historical source rights, frozen
financial/study policy, statistical claims and any trading remain additional,
independent gates.

## 9. Non-goals and validity of this plan

No new `TrialRecordV1` Python type, producer issuer, accepted source
qualification, portfolio optimizer, execution engine, broker/paper order,
historical backtest, scored AI advantage, research spending authorization or
recomputed immutable E1/event hashes is created here. The plan is complete
only when future reviewers can map every R/P/J fixture to an actually
**accepted** authoritative public producer verifier without guessing fields.
