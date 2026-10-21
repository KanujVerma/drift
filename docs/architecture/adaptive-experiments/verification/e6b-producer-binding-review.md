# E6B original K1 research binding and platform issuer reconciliation

**Issue:** [Krish implementation assist #540](https://github.com/KanujVerma/drift/issues/540), consuming original [P0 research producer #507](https://github.com/KanujVerma/drift/issues/507).
**Related owner decision:** [Matthew P0 #508](https://github.com/KanujVerma/drift/issues/508), latest proposed original book lifecycle, **not yet accepted**.
**State:** Candidate source and tests published for AntiGravity review. No original producer grant/issuer certified, no full E6B result admitted, no broker or live operation.

## 1. Actual repository and authority

The accepted foundation on main is E1 campaign and full run-account bindings, Stage1 original-trial provenance, M0/M2 book/result/trace, and merged research K0-K5. Do not weaken them, replace their hash preimages or install a second evaluator/ledger. [#507's authenticated Krish NARROW producer decision](https://github.com/KanujVerma/drift/issues/507#issuecomment-6302653579) identified four independent proof gaps: original Matthew account provisioner, original Kanuj scientific scheduler invocation grant, original Krish retained validation/attempt evidence, and verified connection of each immutable record to the exact E1 scope. The original `TrustedInvocationBinding` in merged K1 is a *caller wrapper*, not an issuer-signed trial membership certificate.

On #508, Matthew has produced a detailed source-backed **proposal** for a future engine-owned prepare/consume lifecycle and original retention in the one existing M0 SQLite audit ledger. It remains active producer design. This code must not assume his proposed class names are imports or assign an unaccepted issuer. The complete review and remaining owner decisions are recorded in this document and on #508, rather than a duplicate fake implementation of account provisioning.

Current additional related gates: Kanuj's [scheduler grant proposal #512 / draft PR #513](https://github.com/KanujVerma/drift/pull/513) at head `80b54a55950bda44166661e5f3312a85f09e4d48` (its original grant issuer is not implemented); the [E6B B1.5 28-case fixture plan](https://github.com/KanujVerma/drift/issues/507#issuecomment-6302535419); still-open independent provenance/rebuild correction #511/#504; the separate platform #508 M0/M2 association and source/rights/mandate contracts. An E1 binding hash is not a proof that M2 created the associated account.

Accountable code producer for this child is Krish, authenticated actor `Krish-Verma` through GPT-6 at the user's request to resolve idle gaps; Matthew remains accountable for the original platform and Kanuj for E1 scientific scheduling. No unaffiliated reviewer has accepted these candidate fields. Root [AGENTS.md](../../../../AGENTS.md), [workstreams](../../workstreams.md), [agent workflow](../../agent-workflow.md) and [scientific experiment contract](../contracts/experiment.md) still govern.

## 2. Exact source ownership and scope

This draft PR adds only:
- `src/drift/intelligence/e1_trial_association.py` (real E1/K1 source-bound structural joining code)
- `tests/unit/test_intelligence_e1_trial_association.py` (source-backed positive and adversarial fixtures, **not run**)
- `docs/architecture/adaptive-experiments/verification/e6b-producer-binding-review.md` (this contract, cross-owner response and AntiGravity packet)

All accepted K1/E1/E6A records, schema versions, original hashes, source grade, private retained bytes, ledger, actual validation runner, M2 engine, original `PortfolioStateV2`, external scheduling and account issuer, domain core and all active PR paths remain read-only. This is neither a new registry with side effects nor a competing orchestrator.

## 3. Source-bound code contract, with exact limitations

`build_retained_validation_candidate(...)` receives an **actual freshly revalidated K1 `ValidationResult`**, the exact attempted research ID, an original raw-output `StoredArtifactRef` when VALID, a claimed retained canonical validation-artifact `StoredArtifactRef`, and a named external validator-issuer reference and availability time. It verifies:

- Known `VALID` requires `is_valid=True`, an actual `ResearchCandidate` linked to the same attempt, and a raw output reference.
- `REJECTED` / `INVALID` / `REFUSED` require `is_valid=False` and no candidate; a failure without a candidate remains a first-class research observation.
- The declared retained canonical ValidationResult digest matches `content_hash(validation.model_dump(mode="python"))` at the caller's specified original bytes profile. The proposed candidate `RetainedValidationCandidateV1` binds the validation ID, status/reason, original raw/output storage claims, original candidate reference if applicable, externally claimed issuer, timestamp, and its own versioned canonical record hash.
- No `ValidationResult` existing on main has an original permanent `validation_id` or issuer. This builder alone does not persist anything. The separate local ledger adapter described below now retains its canonical decision and caller-supplied raw bytes under a bounded append-only audit event and verifies readback. That verifies integrity against the **supplied ledger instance**, not original issuer authority; it is not an accepted K1 end-to-end production wire.

`review_research_e1_binding(...)` consumes accepted full `CampaignSpecV1`, `ArmSpecV1` collection, `RunAccountBindingV1` collection, expected runs, genuine `Stage1TrialProvenanceSnapshotV1` and original K1 `ResearchContext`, started/terminal `AttemptRecord`, optional original validation receipt, candidate, optional `ModelReplayRecord`, K1 `CostReceipt` records, exact logical request, deadline and review availability. Optional exact grant/allocation `ArtifactReference` values are hashed into **a candidate** for later comparison, but are never treated as issuer verification.

The verifier snapshots the E1 collections once, invokes the accepted public `verify_stage1_trial_provenance_snapshot` against the complete manifest, and revalidates exact K1 model types through their current Pydantic model rules (including original self-excluding hashes). The existing `ResearchReceiptStore` checks the start/terminal chain and cost receipt correction lineage. It refuses cross-arm/account/campaign, forged original E1 run/checkpoint/manifest, changed attempt methods/budget, wrong context/record hash, missing K1 validation, orphan candidate, inconsistent outcome, impossible evidence chronology, late ready-at-deadline, conflicting cost IDs and invalid source versions. The code never guesses a run from `Scope.experiment_id` or lets `portfolio_account_id` strings substitute for Matthew's issuer.

The accepted `ResearchContext.decision_cutoff` bounds *consumed inputs* (the original context validator already checks `ContextInput.available_at` and `memory_cutoff`). However, it is legitimate for source-complete K1 analysis to finish after that cutoff but before the **separately declared decision deadline**. The original `AttemptRecord.completed_at` must therefore precede or equal the deadline. The original `ResearchContext.review_started_at` must precede or equal the actual attempt start. Where model replay is present, request/response/parse and retained-validation observation have a separately checked causal order. A supplier may not change a terminal record to make it earlier: original hashes, version and existing validators must still match.

The outcome is `ResearchE1BindingReview`: structural consistency, a **candidate-only** additive association content hash over the original immutable E1/K1 references, candidate disposition or failed absence, known as-of raw research cost receipt hashes, late cost receipt IDs, source refusal reasons, and a permanent list of missing trusted producers. It deliberately returns `original_issuer_verified=False` and `admitted_for_e6b_or_trading=False` on **every possible call**, even when all original K1/E1 hash and source checks pass. No subsequent consumer is permitted to promote that hash into original allocation authority, authentic validation, a trade, a completed RESULT or a scientific sample.

### Dispositions and costs

- `propose`: original validated strategy/candidate can be referenced structurally; the mandatory risk, source, grant and result proof are still missing.
- `hold`: requires a recorded incumbent reference, but actual matching compliant incumbent state is separately verified under Matthew. It never silently sells or claims a safe hold from unverified state.
- `abstain` / `unavailable`: remain different non-order outcomes with original reasons and no strategy/target trade authority.
- `failed` / `rejected`: actual started and terminal attempts with original failure evidence and no candidate stay present in the denominator; missing billing remains UNKNOWN, not free.
- K1 `CostReceipt` is raw inference/research spending. It does **not** change the authoritative trading NAV or paid trading fees. A correction is appended under current `ResearchReceiptStore` semantics, never silently overwritten. A cost receipt recorded later than an earlier as-of association is reported as late; a repeated deterministic candidate is not another independent scored trial.

## 3A. Actual local validation original-byte append/readback implemented

The source now includes `append_local_validation_original(...)` and
`readback_local_validation_original(...)`, using the already merged
`Ledger`/`AuditEventDraft` abstraction and no new SQLite schema. The
append procedure:

1. Revalidates the accepted real `ValidationResult`, exact original
   `ArtifactReference`, UUID7 audit event and subject IDs, and one explicit
   UTC timestamp. It accepts raw model/output bytes or explicit absence.
   Original raw output is bounded to 1 MiB. All content is inert.
2. Serializes the validation result through Drift's existing
   `canonical_json`, hashes the exact canonical bytes and stores the
   **actual bytes as a UTF-8 string** within an immutable audit event.
   If supplied, raw output bytes are stored as exact base64 with a separate
   SHA-256 and typed `StoredArtifactRef`. No raw output, including
   failed/no-call absence, is invented.
3. Emits a uniquely keyed
   `k1.validation.original_candidate_recorded` event with the validation
   ID, attempt, original canonical decision bytes, raw bytes and claimed
   issuer. Existing ledger uniqueness refuses double issuance of the same
   validation ID.
4. After the real append, calls `ledger.verified_events()`, locates the
   exact event and verifies its event hash/type, full closed payload,
   original canonical JSON, absence of duplicate keys, reconstructed real
   K1 `ValidationResult`, raw base64 and both byte digests, and the
   declared candidate hash. An alternate blank/copy ledger or mismatched
   expected event digest refuses.
5. Returns `LocalValidationReadback` with the actual audit event ID/hash,
   original validation digest, original raw byte digest if any, and the
   typed retention candidate. The assessment accepts an optional
   `local_validation_readback` and binds its actual event hash into the
   proposed E1 association preimage.

**Important trust boundary:** The `Ledger` supplied to these routines is
not independently authenticated by these functions. The issuer claim and
the `timestamp` inside today's `AuditEventDraft` remain caller-supplied.
Thus `trusted_research_issuer_authenticated=False`, `can_admit_e6b=False`,
`original_issuer_verified=False` and `admitted_for_e6b_or_trading=False`
remain unconditional. Attaching an auditor-selected trusted read-only
retention context, real collector/scheduler invocation hook, independently
measured availability witness, and source isolation/capability enforcement
requires an explicit accepted producer and independent review. The local
append itself is a genuine side effect **when a caller invokes it on a
real supplied ledger**; the author did not invoke it in this session and
the test uses only a temporary, offline synthetic ledger. No application
has yet been wired to record its validator's original decision at issuance
time, so a later copied `ValidationResult` cannot be described as an
authentic original production result.

### Added regression oracles (written, intentionally unrun)

- Append a genuine synthetic `REJECTED` or `VALID` K1 decision and literal
  raw output to temporary `SQLiteLedger`, reopen read-only, verify exact
  event, original decision and raw-byte hashes.
- Reissue the same validation ID with a new event ID; the already merged
  unique audit dedup key must refuse instead of producing a second original.
- Re-read the original under a wrong event hash or another ledger; refuse.
- Oversized raw output never creates an audit event; REFUSED with no raw output
  retains the reason and exact missingness.
- Join a re-read canonical validation candidate to actual E1/K1 original
  records. Its candidate association hash binds the durable event hash,
  but still does not authenticate the original issuer, scheduler or book.
- Fraudulent retained-validation status/candidate mismatch and forged
  self-consistent issuer ref never grant original E1/scientific admission.

These checks exercise genuine local persistence **only when AntiGravity runs
the synthetic tests later**. They are not a claim of currently passing
pytest, full CI or independent review.

## 4. Research consumer NARROW of Matthew's #508 opening-book proposal

Krish may accept a research **consumption ordering** without choosing Matthew's platform implementation or declaring issuer authority. The reviewed proposed direction is technically compatible **conditional on four independently testable facts**:

1. An actual evaluator-owned original `PortfolioStateV2` is prepared from its accepted engine configuration only once, with the original opening cash, first session/admission and currency evidence. Equal bytes built by an external wrapper are **not** enough.
2. That actual book and allocation key `(campaign_id, run_id, arm_id)` are durably retained, with the entire E1 manifest and an independently pinned issuer/ledger readback **before** the scheduler grant. Checkpoints refer to that allocation rather than allocate new cash. No external caller may choose its own trusted database or claim issuer approval by self-hashing.
3. M2 must consume the exact prepared book after a durable invocation claim and **must not call the opening initializer again**. A crash after claim with no retained output is unresolved; it cannot silently rerun from new cash. Existing core evaluator import-direction guards, old result/trace/hash bytes and original success/failed classifications remain unchanged.
4. Only after actual M0 runner output is canonically retained may the platform association link its original operational UUID, M2 result/trace/book original bytes, version/admission/cost policy and distinct complete/unknown/finality states to the original allocation. Trading net NAV already includes posted fees; independent research operating receipts are not debited again. Matching hash strings do not make the account issuer authentic or make repeated evaluation a new scientific sample.

**Cross-producer timing issue needing explicit ruling:** Matthew's proposal distinguishes a ledger write's caller-supplied event timestamp from the independently witnessed *available-by* time. Kanuj's proposed scheduler `allocation_first_available_at` must not silently be populated by a weaker inferred availability time. The accepted issuer and scheduler interface must freeze the basis and causal comparison. Likewise, trusted original result availability cannot come from a caller's predeclared `ExperimentRunnerContext.completed_at` that predates the actual run.

Thus Krish's research consumer disposition for #508 is **NARROW / CONDITIONALLY COMPATIBLE**, *not* Matthew's required owner ACCEPT or an approved source code write-set. Next Matthew actions are D1 accept or amend the optional engine-owned prepare/consume boundary, D2 choose the actual trusted ledger/issuer/availability verifier, D3 obtain Kanuj scheduling and Krish consumer acceptance of exact fields, then D4 issue a single bounded implementation path reservation. The #508 current source-backed 40k-byte proposal is detailed and valuable but still not the accepted original record.

## 5. Future accepted producer integration sequence

The smallest legitimate next dependency closure is:

1. Matthew issues the original allocator and retained opening-book receipt and an independent **trusted original** verifier, owned by #508.
2. Kanuj freezes the original logical E1 scheduler grant and issuer verification (not a platform-account creation), owned by #512/#513. The grant binds the exact `logical_request_id`, full manifest, account/arm/run/checkpoint/trial, method, input cutoff, deadline and original start-based expiry/revocation.
3. Krish wires this module's source and validation candidate to a **real retained validator output written by the accepted K1 producer**. This requires an additional exact source/retention write-set and approved issuer, not importing a publicly self-made receipt as trusted.
4. Both accepted issuers verify against their original retained bytes and stable trust roots. A new typed `VerifiedResearchE1Association` could then be issued by the accepted producer. This module deliberately defines none and returns no usable permit.
5. Matthew supplies authoritative M0/M2 RESULT, including actual original cash/holdings/claim state, fills/refusals/UNKNOWN, net posted fees, precise outcome availability and result/book/trace identity. Kanuj independently verifies the two original producer associations before deriving a later scientific trial revision. The research output is **not** the authority for the platform book.

No stage above lets an AI model, trial projector or test harness self-approve a research/system/source permission.

## 6. AntiGravity handoff: tests written, intentionally NOT RUN

At the exact published PR head, inspect the three new files and source-bound contracts and run these commands, without altering the historical fixtures or existing E1/K1 hashes:

```bash
uv run pytest tests/unit/test_intelligence_e1_trial_association.py -q
uv run ruff check src/drift/intelligence/e1_trial_association.py tests/unit/test_intelligence_e1_trial_association.py
uv run ruff format --check src/drift/intelligence/e1_trial_association.py tests/unit/test_intelligence_e1_trial_association.py
uv run mypy src tests
uv run pytest
uv build
git diff --check
```

Then run the canonical [Drift verification gate](../../agent-workflow.md), confirm exact path ownership, review each R01-R08/J01-J04 from [#507](https://github.com/KanujVerma/drift/issues/507), and verify no E1/K1 earlier bytes, old deterministic replay or promotion permissions change.

The authored, **unexecuted** cases include actual accepted E1 `CampaignSpecV1/ArmSpecV1/RunAccountBindingV1` and provenance builder, accepted K1 original context/attempt/candidate and real `ResearchReceiptStore`, then wrong account, run, checkpoint and entire manifest; loss of original validation receipt; wrong validation/candidate hash; a late candidate deadline; hold, abstain, unavailable and failed no-candidate; unknown billing; forged source clock, changed logical request; stable replay hash without extra sample. AntiGravity should independently add: valid post-cutoff but pre-deadline model completion, model response or parse after deadline, cost correction after as-of, overlapping model/ref identity, duplicate and conflicting retained validator originals, issuer-forged grants, trust-root reassignment, replay after revocation and actual Matthew book readback once their accepted producer endpoints exist. Non-vacuous trusted positive controls require #508 and #512 sources; inventing a fake signature to make these pass would be invalid.

**No tests, build, dependency changes, private-source reads, real ledger writes during this authoring session, issuer registration, broker operations, schema migration, GitHub merge or independent acceptance are claimed by this publication.** Any automatically started CI must be assessed at the exact new HEAD and remains distinct from AntiGravity review.

## 7. Release disposition and accurate issue status

The child #540 can reach *candidate code delivered* while #507 remains open pending accepted original validation retention and issuer integration. #508 is still actively under Matthew's producer decision process; its exact accepted account issuer, durable allocation/consume path and separate RESULT association are **not finished** by this work. E6B #485 stays blocked on three producer origins and their contract acceptance. Report any completed code and its tests honestly as source-only, not as a claim that the missing authoritative records already exist.
