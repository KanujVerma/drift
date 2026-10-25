# Synthetic research-to-execution candidate

Owner issue: [#564](https://github.com/KanujVerma/drift/issues/564).
Platform predecessor: [#563](https://github.com/KanujVerma/drift/pull/563),
source `e22104511f2b2b7b5466dc00785e76eeb2aad523`.

## Scope and authority

This slice connects actual existing K1 scripted/conventional producer calls to
installed strategy execution and the original account-to-M0-to-RESULT evidence
chain. It is a **local synthetic integration candidate**, not accepted G2,
an original scheduler grant, a numerical mandate, the scientific R formula,
a scientific `TrialRecordV1`, or provider/broker permission.

The public module is `drift.loop.stage1_synthetic_research_execution`.
It imports the existing K1 contracts, validators, receipt store and producers,
and the existing platform ledger, prepared account, evaluator and original
RESULT reader. It introduces no second account ledger or evaluator.

The installed host, its configured SQLite root and approved strategy code are
trusted. Raw research choices are inert typed data. Arbitrary hostile Python
in the trusted process, a malicious replacement host, forged out-of-band trust
configuration and general external issuer authentication are outside this
candidate's boundary. Existing original-issuer properties remain false.

A real source-retained proposal is not automatically an approved order. The
candidate's `g2_accepted`, `scientifically_qualified` and `authorizes_trading`
properties are always false, including after a locally complete execution.
These are explicit limitations, not runtime switches an integrator can turn on.

## Public inputs and deterministic producer binding

`OfflineResearchRequestV1` accepts one of two mutually exclusive modes:

- `scripted_fixture`: typed `RawChoice`, an optional simulated timeout or
  malformed output, and explicitly synthetic transport cost evidence.
- `conventional_fixture`: a typed candidate pool and explicit finite Decimal
  fixture scores. The scores are not the accepted scientific R algorithm.

No real model API is called. The ADAPTIVE_AI synthetic arm uses the labelled
scripted mode, never a claim that an AI made the choice. The conventional arm
uses the actual installed conventional selector with the declared fixture
scores. Their original producer labels and receipts are preserved.

The coordinator resolves only installed, default B3/B4/B5 constructors. It binds
actual code hashes, strategy versions and default parameter fingerprints.
There is no caller-supplied strategy object, dynamic import, arbitrary objective
callback, model-generated code or parameter tuning. E1 campaign and arm family
membership further restrict this installed set.

`installed_registry_reference`, `synthetic_universe_reference` and
`original_portfolio_reference` expose the exact references required in the K1
context. The universe reference enumerates the supplied synthetic bundle's
security identities; it does not confer per-session market eligibility. The
installed evaluator remains responsible for its actual admitted universe.

The full E1 campaign/arms/account manifest and provenance snapshot are verified
through their existing public verifier. Context account, arm, campaign,
portfolio, universe, registry, source grade and current source inventory are
cross-checked. Only `SYNTHETIC_TEST` campaigns and `synthetic_fixture` contexts
are accepted. A fresh funded account is not a verified invested incumbent, so
no hold is authenticated merely from the arm's initial-strategy label.

## One opportunity and its retained state machine

This profile supports **one research opportunity per prepared account**, not a
sequence of monthly switches. All records are appended through the existing
SQLite ledger. Each phase has one account-scoped deduplication key:

1. `stage1.synthetic_research.opportunity`: the original E1/account references,
   immutable context and request, complete evaluator input/policy identities,
   allowed families and installed-code inventory. Appended before K1 runs.
2. `stage1.synthetic_research.original_output`: the actual producer output and
   complete exported K1 receipt journal, linked to the opportunity hash. Actual
   start/terminal attempt records, cost basis, failure/refusal and candidate
   absence are retained, not synthesized from an eventual financial result.
3. `stage1.synthetic_research.m0_reservation`: for a valid proposal only, bind
   its original candidate hash, installed strategy/parameters and fresh M0 run
   and audit-event identifiers before dispatch.
4. `stage1.synthetic_research.outcome`: retain no-dispatch reason, original
   failed M0 invocation, or the actual original RESULT locator plus first
   decision proof. A result lookup by financial content hash alone is forbidden.

Every body is canonical JSON with an independent content digest and explicit
candidate profile/issuer identity. Duplicate phases, conflicting references,
noncanonical/duplicate JSON keys and reversed phase ordering refuse.
Original event chains and original financial artifact hashes are unchanged.

No automatic retry follows an uncertain write. An interrupted opportunity or
reservation remains `UNRESOLVED`; replay must not allocate new cash or run the
strategy again. A successfully committed outcome whose acknowledgement was
lost can be recovered by the cold reader, but still cannot be reexecuted.

## Research must actually control the first executed decision

A selected strategy family is not enough: ignoring proposed target weights
would claim to execute a proposal while doing something else. The coordinator
wraps the selected installed strategy without changing its actual intents.
At its first decision, it requires the research cutoff to equal the evaluator
cutoff and compares the producer target's exact whole-share quantities against
the installed strategy's actual targets. Target arithmetic uses exact rational
ratios over Decimal values and requires the exact weights plus cash to sum to
one. Missing prices, empty targets or conflicting quantities refuse before
staging, not a manufactured sell-all or a successful no-op.

The exact first decision context and actual intent are retained with the local
outcome. A cold reader reparses them, reruns the fixed installed strategy and
checks the original trace's context and intent hashes. A genuine original M0
result cannot validate a forged or unrelated first-decision proof.

Later decisions remain that same installed strategy's frozen internal behavior.
This is not an adaptive monthly switch implementation and does not rewrite the
historical B3/B4/B5 algorithms. B3 has a full 379-session two-arm integration
fixture. B4 and B5 additionally execute with twelve fictional securities,
253 completed lookback sessions and the next fill session; both retain their
complete first-decision history and original results for cold verification.
Those constant-price fixtures establish the execution/retention path, not real
market eligibility, optimized selection or the full scored/reset campaign.
Insufficient B4 history remains a separate failure control. Qualified reference
histories and adaptive monthly campaign continuity remain separate gates.

## Actual post-execution M0 completion clock

The existing M0 context historically required callers to supply `completed_at`
before the evaluator ran. A newly prepared account's actual claim/consumption
occurs during that run; supplying the start instant made the original RESULT
clock join fail. Guessing a future completion or backdating account clocks is
not an acceptable repair.

`ExperimentRunnerContext.completion_clock` is an additive optional callback.
M0 captures it together with the engine, ledger, strategy and observer before
execution. If present, it samples once after the actual outcome, on both success
and genuine strategy failure. It requires an exact timezone-aware datetime,
canonicalizes it and refuses rollback before original invocation start. That
single value is used for the M0 run and original audit event timestamp.

No callback preserves the historical supplied-clock contract and event schema.
A bad or unavailable post-execution clock propagates without a false completed
M0 record. A previously claimed invocation remains unresolved; this does not
authorize another execution. Matthew's review is required for this additive
producer interface.

## Cold verification and honest outcomes

`read_synthetic_research_execution` requires independently supplied configured
origin, opportunity locator and full E1 context. It opens existing evidence
read-only, verifies the original account and all phase links, deterministically
replays the offline K1 producer, compares the complete original output/journal,
then independently verifies the original platform association and first decision.
It needs neither the original account lifecycle nor the live writer/engine.

For failed executions, equal invocation dictionaries are not sufficient proof.
The reader parses the original three-UUID binding, verifies the claim's exact
producer profile, schema, entity, issuer, account-scoped deduplication key,
witness reference and identity digest, and requires its event ID to equal the
original invocation ID. The reservation, claim and failed M0 clocks and event
positions must be causally ordered in the same verified ledger snapshot.

A failure may legitimately occur before book consumption. The reader does not
invent or require a consumption receipt in that case. When a receipt exists,
it must be unique and must match the original claim, allocated book bytes,
execution identity and invocation, with valid producer metadata and an event
position and timestamp between claim and failed M0. A semantically contradictory
receipt is refused even when the enclosing ledger's hash chain is valid.
These checks establish local failure attribution, not account-wide zero fills,
general issuer authentication or scientific completion.

Readers do not create missing ledgers or repair their schema/triggers. Current
installed source identity must match the retained inventory. Reading older
source versions requires that exact retained code environment rather than
silently reinterpreting historical behavior under newly installed code.

States are deliberately distinct:

| State | Meaning |
| --- | --- |
| `NO_DISPATCH` | Actual research failed/refused, supplied a non-proposal, or was retained too late. No M0 invocation by this coordinator. |
| `UNRESOLVED` | A retained phase lacks its subsequent original evidence. No completed result or automatic retry is inferred. |
| `EXECUTION_FAILED` | Original bound M0 failed and has no successful financial artifact. This does not assert account-wide zero fills. |
| `LOCAL_EXECUTION_NOT_COMPLETE` | Original evaluator returned a non-complete classification, retained without promotion. |
| `LOCAL_EXECUTION_COMPLETE` | The bounded original execution and decision join verifies locally, not G2 or scientific acceptance. |

The reported research-cost value is zero only when all original attributable
fixture receipts explicitly have `verified_zero` USD basis. Estimates and
unknowns remain unavailable in this field; no independent invoice truth, full
cost-supersession adjudication, shared-cost attribution or economic-gain report
is introduced. Cold replay makes no external inference call but is not a claim
that infrastructure or storage is universally free.

## Lossless large-context retention and compatibility

Each local canonical record payload is capped at 1 MiB, including its escaped
body and envelope. Original RESULT retention keeps its existing 4 MiB cap.
Neither cap is raised to accommodate full B4/B5 history.

Outcome event schema `1` retains the existing inline `first_context_utf8` and
its exact field set. Small first-decision contexts continue to use that wire
format, with no added null artifact field. Historical schema-1 originals are
not upgraded or rewritten.

A large first context uses additive outcome event schema `2`, with
`first_context_artifact` profile `drift-synthetic-decision-context/1` and
encoding `zlib-base64`. The artifact retains its original uncompressed byte
length, SHA-256 digest and complete compressed data. `first_context_utf8` must
be null. Only an actual returned M0 outcome with an original context kind and
intent may carry this representation. Both-context, failed-outcome, missing
proof and unknown/downgraded schema combinations refuse.

Compression is only transport: the cold reader verifies the complete original
uncompressed bytes and the original evaluator context/intent hashes. It uses
strict canonical base64 and bounded streaming decompression with a separate
32 MiB decoded-context ceiling. Truncation, trailing data, concatenated streams,
noncanonical base64, dishonest lengths, digest mismatches, duplicate JSON keys,
nonfinite JSON and noncanonical original bytes refuse. No unbounded flush or
partial-context success is permitted.

The first-decision guard checks both the decoded ceiling and the encoded
payload capacity before returning an intent for staging. A proof that exceeds
either bound fails without staging that first order. This does not promise
future I/O will succeed: an interrupted final append still leaves existing
M0 facts present and the opportunity unresolved, without automatic retry.
The limits are bounded retention-resource choices for this synthetic profile,
not financial thresholds or permission to discard history.

## Remaining G2 requirements

This candidate does not close [#507](https://github.com/KanujVerma/drift/issues/507),
[#508](https://github.com/KanujVerma/drift/issues/508),
[#485](https://github.com/KanujVerma/drift/issues/485) or G2 itself.
Accepted original scheduler issuance/availability and K1 validation authority,
Matthew's declared issuer/witness and mandatory mandate/switch boundary,
accepted typed scientific trial projection, complete G2 negative matrix and
independent producer/consumer acceptance are still required. The existing
[#513](https://github.com/KanujVerma/drift/pull/513) proposal is not silently
implemented or accepted by calling these local opportunity records grants.

The exact release/test/review status belongs in #564 and its PR checkpoint,
not in this durable interface description. User merge approval is recorded;
independent producer acceptance and ordinary branch protections still apply.

### Failed computation identity

Claim/consumption equality alone cannot authenticate a failed computation. The
reader validates the claimed run hash through `EvaluationRunIdentityV2` against
the retained opportunity's input, admission, policy, source and evaluator
evidence hashes and the selected installed strategy/parameters. This coordinator
uses the canonical factory's unchanged zero environment-closure default. The
failed M0 experiment UUID must also follow the existing canonical baseline
strategy-and-bundle derivation. Matching foreign identities and a different
experiment ID refuse even when the original ledger hash chain verifies.

A failure before the original account claim commits does not append a terminal
account-attributed failure. Its original M0 failure remains retained, and the
research reservation remains `UNRESOLVED` and cold-readable. A committed claim
whose acknowledgement was lost may support `EXECUTION_FAILED` only after all
original failed-run checks pass. Neither state permits another invocation or
asserts that no fills occurred. No claim or consumption is synthesized.
