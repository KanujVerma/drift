# Stage 1 original invocation proof: bounded synthetic decision packet

## Purpose and authority

[Integration issue #562](https://github.com/KanujVerma/drift/issues/562) joins
the engine opening-book lifecycle from
[A / #547](https://github.com/KanujVerma/drift/pull/547), the original local
account receipts from [B / #549](https://github.com/KanujVerma/drift/pull/549),
and M0 result retention from
[C / #551](https://github.com/KanujVerma/drift/pull/551). It addresses the
[reported invocation-binding defect](https://github.com/KanujVerma/drift/pull/551#discussion_r4344264326)
under the account-origin architecture in
[#508](https://github.com/KanujVerma/drift/issues/508). The byte-aware source
scanner correction in [#561](https://github.com/KanujVerma/drift/pull/561)
remains a separate source-admission safeguard.

This packet records the candidate's design, evidence, limits, and release
decision. GitHub owns current heads, writer reservations, check results, and
acceptance. Full repository verification, hosted exact-head CI, and their
revision-specific results are recorded on that issue and its integration PR.
This packet does not establish Matthew or Krish D1/D2 acceptance, producer
authority, or scientific eligibility.

## Decision and trust boundary

**Recommendation implemented for this bounded candidate:** run installed,
trusted platform strategy code on an owner-configured local host, retaining
original synthetic evidence in that host's configured ledger. This follows
the bounded strategy direction in [product decision D01](../decisions.md).
The evaluator, lifecycle, observer, executable strategy implementation, clock,
and configured ledger root belong inside this trust boundary. Model or
research data does not supply arbitrary Python for execution in that process.

The invocation identifier establishes a causal relationship among local
events. It is public operational data, not a secret capability, issuer
signature, or protection against a privileged host replacing its trust root.
The original allocation observation is a local observed-available-by witness;
M0's caller-supplied completion time is not a new availability witness.

**Trust-boundary recommendation for architecture review:** retain this
trusted-host boundary for the bounded synthetic candidate. Supporting hostile
executable code requires a separately scoped process-isolation boundary.
The recommendation and its
implementation do not mean that the user answered an optional boundary
question or that the independent D1/D2 owner gates were accepted.

## Why invocation identity is necessary

The predecessor could match an account's consumption to a later M0 event by
deterministic run identity, result/trace hashes, final-book hash, and chronology.
Those checks cannot distinguish two executions of the same deterministic
evaluation. A previously consumed account could therefore be associated with
a fresh engine's result.

A phase check before M0 also fails. Account A can start ready, be consumed
during engine B's strategy callback, and appear consumed when B's M0 finishes.
That transition does not prove that B used A's original book. Both scenarios
are represented by adversarial regression tests.

M0 now mints one fresh UUIDv7 `invocation_id` inside each observed attempt,
after validating caller inputs and before invoking the selected engine. It
captures three canonical identifiers:

| Binding field | Meaning |
| --- | --- |
| `invocation_id` | Fresh operational identity of this attempted invocation |
| `m0_run_id` | Canonical M0 experiment-run identifier |
| `m0_audit_event_id` | Canonical identifier selected for that M0 audit event |

`OriginalInvocationBindingV1` and its copy/parse helpers require exact UUIDv7
values and canonical text. Every boundary receives a detached value, including
new UUID objects. A frozen dataclass alone would leave reflectively mutable
UUID leaves shared with callbacks.

The engine's optional `original_invocation_binding` argument requires an
actual prepared book and both bound lifecycle callbacks. It cannot fall back
to constructing fresh legacy cash. Claim and consumption receive separate
copies of the same captured binding. M0 retains its own copy and captures its
engine, ledger, strategy, and observer before execution.

## Immutable evidence chain and versions

Each successful account association has seven original events in the same
configured ledger, with the schema sequence **1 / 1 / 2 / 2 / 3 / 2 / 2**.

| Order | Event type | Schema | Required relationship |
| --- | --- | --- | --- |
| 1 | `stage1.synthetic_account.allocation` | `1` | Original engine-book bytes and verified E1 account scope |
| 2 | `stage1.synthetic_account.allocation_observed` | `1` | Committed allocation reference and local readback witness |
| 3 | `stage1.synthetic_account.invocation_claim` | `2` | Allocation, witness, deterministic identity, and invocation binding |
| 4 | `stage1.synthetic_account.book_consumed` | `2` | Original claim ID/hash, book digest, and identical binding |
| 5 | `m2.evaluation.run.recorded` | `3` | Same binding, actual canonical artifacts, and completed final-book hash |
| 6 | `stage1.synthetic_result.original_m0_claim` | `2` | Unique reservation of this original M0 for this allocation |
| 7 | `stage1.synthetic_result.original_retained` | `2` | Complete original artifact bytes and verified predecessor references |

Allocation and witness retain
`drift-stage1-synthetic-account-local/1-candidate`. Bound claim and consumption
use `drift-stage1-synthetic-account-local/2-candidate`. C's reservation and
RESULT use `stage1-m0-original-association/2-candidate`. Readers dispatch on
explicit event type, schema, and profile combinations.

The bound claim's event ID equals `invocation_id`. The existing ledger's unique
event ID and unchanged per-allocation invocation deduplication key enforce
one claim per invocation and one claim per allocation. Consumption verifies
the immutable original claim rather than trusting only lifecycle memory. C
also retains the unique original-M0 reservation and per-allocation RESULT
deduplication key.

C verifies exact binding equality across claim, consumption, M0, reservation,
and RESULT. The binding's M0 run ID must equal the original M0 entity ID, and
its audit ID must equal the original M0 event ID. Existing E1 manifest, account,
identity, artifact, final-book, hash-chain, ordering, and timestamp checks
remain required.

Historical schema-1 account events and schema-1/schema-2 M0 events remain
immutable history. They cannot be upgraded into invocation proof by adding a
binding afterward. Mixed bound and unbound claim/consumption pairs refuse.
The ordinary M0 path without an observer retains its schema-1 payload and
original call surface.

Operational identifiers stay outside deterministic evaluator identity,
RESULT, trace, portfolio, and cost construction. Two independent B/R
invocations may have identical deterministic artifact bytes while retaining
different allocations, invocation IDs, M0 IDs, and association references.

## Cold readback without a writer

[`read_original_result`](../../../../src/drift/loop/stage1_original_result_association.py)
accepts the configured origin, original account readback, association
reference, full E1 provenance/configuration, expected run IDs, and observation
clock. It needs no live engine, account lifecycle, or result observer.

The public
[`LocalSyntheticAccountReceiptStoreV1.open_existing`](../../../../src/drift/ledger/stage1_synthetic_account_receipts.py)
uses `SQLiteLedger.open_existing`. Reopening does not create a missing ledger
or repair missing append protections before verification. The reader reopens
the original allocation and witness, verifies all seven events and complete
artifact bytes, and checks the complete E1 manifest again. Supplied references
locate evidence; they do not authorize an origin.

Cold readback does not prepare an account, invoke a strategy, restore spent
cash, append a new RESULT, or acquire another execution opportunity. A valid
readback still reports `original_issuer_authenticated_for_e6b=False` and
`scientifically_qualified=False`.

## Failure and one-shot behavior

| Condition | Required outcome |
| --- | --- |
| Malformed binding or unprepared bound engine | Refuse before a fresh cash book or original claim; no successful association |
| Prepared engine lacks bound callbacks | Refuse without legacy callback fallback; consumed escrow is terminal |
| Claim commits but acknowledgment or verification fails | Preserve original evidence and terminal uncertainty; no recredit |
| Consumption succeeds but evaluation fails | Record a failed M0 attempt with its binding; no successful artifacts or C RESULT |
| Original M0 audit append fails | Propagate failure before the result observer; account remains spent or uncertain |
| Result observer fails after completed M0 | Preserve the completed original M0 and propagate the association error |
| M0 reservation commits but RESULT append fails | Preserve the reservation; no phantom result or reuse by another account |
| Later independent readback fails | Refuse verification without rewriting an already committed original |

Changing the invocation ID, checkpoint, or M0 ID cannot fund another execution
from the same original allocation. A failed binding validation before a claim
does not itself consume a prepared book. Existing explicit promotion and
strategy-parameter admission refusals remain refusals, not manufactured
completed results.

## Full-window synthetic evidence

The
[`test_full_window_b3_accounts_have_distinct_original_invocations_and_cold_readback`](../../../../tests/integration/test_stage1_original_invocation_end_to_end.py)
test executes the installed `B3MonthlyEqualWeightRebalanceStrategy` through
the actual session evaluator with `EvaluationRunIdentityV2` parameter binding.
Both arms independently execute B3 to verify platform lineage and account
separation. This is not a comparison between different strategies.

Observed fixture dimensions and outputs:

| Quantity | Evidence |
| --- | --- |
| Complete session window | 379 weekday sessions, 2024-01-02 through 2025-06-13 |
| Warmup and observation | 253 warmup plus 126 observation sessions |
| Universe | 12 distinct synthetic security IDs and 12 distinct listing IDs |
| Complete serialized input bundle | 18,989,140 bytes, retained separately and reopened for validation |
| Strategy and prices | Installed B3, constant USD 100 per synthetic security |
| Initial book, each arm | USD 10,000 cash, no holdings |
| Actual fills, each arm | 12 buys of 8 shares, USD 9,600 gross traded notional |
| Final book, each arm | USD 400 cash, USD 9,600 holdings, USD 10,000 NAV |
| Trading costs and net P&L | Zero under the explicit synthetic zero-fee fixture |
| Complete retained artifacts, each arm | 572,534 bytes, including 897 trace events |
| Ledger proof | Two distinct seven-event chains and successful cold readback |

The trace count includes 758 session-boundary events, 127 strategy decisions,
and 12 actual fills. Retained artifact bytes remain below the unchanged
4,194,304-byte cap. The larger input bundle is a separate retained input, not
truncated RESULT content. No artifact cap was increased, and no source window,
artifact, or trace was truncated to obtain this result. These sizes describe
the verified fixture; they are not new wire-format limits or golden hashes.

The provisional ETF labels are VOO, IJH, IJR, VEA, VWO, QQQ, SHY, IEF, TLT,
TIP, LQD, and GLD. They label fictional constant-price securities. The fixture
uses synthetic XNYS-shaped weekdays at 14:30-21:00 UTC, without real exchange
holidays, daylight-saving transitions, or actual listing-MIC qualification.
Corporate-action coverage is a quiet synthetic fixture. The evaluator result
is exploratory; its M1d-shaped realized-view inputs are restated synthetic
fixtures, not source qualification or authenticated market-data replay proof.

This proof includes B3 current-close decision inputs. It does not exercise
B4/B5 lookback inputs, AI selection, R optimization, or the future
`SC-001` through `SC-021` scored window and reset. The 379-session history is
unscored. Identical B/R returns here show deterministic accounting and distinct
operational lineage, not investment advantage or scientific replication.

## Verification map

| Contract | Source and focused evidence |
| --- | --- |
| Detached binding and original engine custody | [Binding API](../../../../src/drift/evaluator/opening_book_lifecycle.py), [engine](../../../../src/drift/evaluator/engine.py), [unit tests](../../../../tests/unit/test_evaluator_opening_book_lifecycle.py) |
| Immutable account originals and dual uniqueness | [Receipt store](../../../../src/drift/ledger/stage1_synthetic_account_receipts.py), [lifecycle](../../../../src/drift/loop/stage1_synthetic_account_lifecycle.py), [unit tests](../../../../tests/unit/test_stage1_synthetic_account_lifecycle.py), [adversarial tests](../../../../tests/adversarial/test_stage1_synthetic_account_origin.py) |
| Actual M0 invocation, audit, and legacy compatibility | [M0 runner](../../../../src/drift/evaluator/experiment_runner.py), [M0 integration tests](../../../../tests/integration/test_evaluator_experiment_run.py) |
| Original RESULT association and cold verification | [Association and reader](../../../../src/drift/loop/stage1_original_result_association.py), [integration tests](../../../../tests/integration/test_stage1_original_result_association.py), [forgery and cold-read tests](../../../../tests/adversarial/test_stage1_original_result_forgery.py) |
| Complete synthetic window and retained artifacts | [End-to-end test](../../../../tests/integration/test_stage1_original_invocation_end_to_end.py) |

The adversarial cases include stale consumption followed by a fresh M0,
consumption during another engine's M0, each crossed binding identifier in an
otherwise valid hash chain, legacy evidence relabeling, missing ledgers,
removed append protections, and interrupted RESULT retention after the M0
reservation. Positive tests verify complete bytes and distinct original
invocations, not only matching summary metrics.

Use the pinned interpreter and verification process in
[Agent workflow](../../agent-workflow.md). A focused reproduction is:

```bash
uv run --locked python -m pytest -q \
  tests/integration/test_stage1_original_invocation_end_to_end.py \
  tests/adversarial/test_stage1_original_result_forgery.py
```

Focused evidence does not replace the full exact-head pytest, Ruff, mypy,
build, whitespace, and hosted CI gates required by that workflow. Their actual
results and independent review belong in #562's issue/PR evidence.

## Alternatives and remaining authority

| Alternative | Assessment |
| --- | --- |
| Identity/hash/chronology checks alone | Cannot distinguish repeated deterministic executions |
| Account phase checks around M0 | Cannot distinguish consumption by a different engine during the same interval |
| Fresh operational binding plus immutable originals | Chosen bounded fix; preserves deterministic hashes and uses existing ledger uniqueness |
| Process isolation with validated messages | Required if hostile executable strategy/plugin/model code must run; separate architecture and implementation scope |

The candidate does not solve hostile same-process reflection, class/module
replacement, or arbitrary thread interference with trusted platform code.
Process isolation would require a separately reviewed execution boundary and
data-only communication; an invocation UUID does not provide it.

Authenticated producer/issuer authority, Matthew/Krish D1/D2 acceptance,
scheduler grants and first-available visibility, original K1 evidence, costs
outside the synthetic fixture, E6B eligibility, scientific scoring, source
qualification, and operational trading permission remain separate gates.
The result established here is retained synthetic engineering evidence with
verified local invocation lineage. None of those other gates is granted by
this packet, the source scanner, or a passing synthetic run.
