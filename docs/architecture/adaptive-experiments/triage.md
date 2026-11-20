# Synthetic Offline Triage Runtime Candidate (Issue #381)

## Status and provenance

**DRAFT / BLOCKED ON THE EXACT ACCEPTED MATTHEW SRC CONTRACT.**
This is the Kanuj-owned, independently testable minimal deterministic news-event
screening candidate. Actual GitHub publisher Krish-Verma / executing agent
ChatGPT under the user's explicit request; not an authenticated action by
KanujVerma or Matthew. Only the four paths in #381 are edited.

At implementation start, main was
`0ec5e4bbb89488a49dfc438b2ad1420bc87e56ef`, including the
independently verified K0-K5 offline intelligence code from merged PR #457.

The **accepted behavior** is
[triage-design.md](triage-design.md), issue #393, merged PR #398.
The **sole normative minimal source envelope is still a proposal**:
Matthew's [issue #394](https://github.com/KanujVerma/drift/issues/394)
and [draft PR #415](https://github.com/KanujVerma/drift/pull/415), source
revision `3b68d22691c5d157d12eed71e3f1a863f466020a`.
Its earlier independent CI passed, and Kanuj accepted limited design-semantic
compatibility, but the exact SRC runtime wire, validator, original-evidence
and processing receipt formats have not been accepted. Issue #381's native
#394 dependency is not silently removed by this draft, and no Matthew
type/source is impersonated.

This implementation defines **consumer-local synthetic projection dataclasses**
and two pure functions. They are not installed SRC types, M1d news facts,
qualified provider coverage or independently authenticated provenance.
The actor supplying these projections remains responsible for actual source
identity, retained original bytes, rights and timestamps. A supplied hash or
`quality_state="usable"` cannot establish source truth. Until Matthew and
Kanuj accept an exact wire adapter/revision, this module is for synthetic
testing and review, not production ingestion.

## Boundaries and public surface

- `src/drift/news_triage/screen.py` exports
  `screen_event(*, evidence, policy, context_id, decision_cutoff, prior=())`
  and
  `screen_feed_coverage(*, coverage, decision_cutoff)`.
- `src/drift/news_triage/__init__.py` exports these pure functions plus
  `EventKey`, `EvidenceRef`, `EventEvidence`, `ScreeningPolicy`,
  `PriorScreening`, `ScreeningResult`, `FeedCoverage`,
  `FeedScreeningResult` and `policy_digest`.
- `tests/unit/test_news_triage.py` exercises the 14 accepted behavior cases,
  with multiple additional negative, replay, timestamp, type and capability
  controls. No external model, network, filesystem I/O, account/ledger
  mutation, broker call, persistence, sentiment inference, fuzzy clustering
  or hidden market relevance heuristic.
- All emitted categories are **caller-supplied** and exactly allowlisted or
  excluded by a supplied canonical local policy; they are not inferred from
  article text or securities. This module does not infer price direction
  or create orders.

### Local synthetic projection, not an SRC schema

| Projection / field | Evidence meaning and local checks |
|---|---|
| `EventKey.source_id,event_id,version,content_sha256` | Exact source/version/digest assertion; nonblank scoped tokens and lowercase 64-char SHA, not origin authentication |
| `EventEvidence.received_at,normalized_at,available_at` | Independently supplied, timezone-aware, monotonic prospective eligibility; publication may be unknown without falsely becoming receipt |
| `availability_ref,content_ref,quality_ref` | Caller-retained digest references; content digest must match `EventKey`; require actual producer verification before operational use |
| `quality_state` | Local `usable`, `missing`, `conflicting`; label states are untrusted until an accepted SRC verifier authenticates them |
| `coverage_state` | `covered`, `partial`, `failed`, `unknown`; an independently usable retained event is not retroactively invalidated merely because broader feed coverage failed |
| `ScreeningPolicy` | Exact immutable allowed/excluded categories, id/version and canonical hash of the entire supplied policy; overlap and changed-policy forgery refuse |
| `PriorScreening` | Caller-provided prior status, source key, policy hash/version, logical context, quality proof, receipt reference and verified availability clock |
| `ScreeningResult` | Typed decision, reason, retained source/policy/context/revision/duplicate references, cutoff and canonical decision hash |
| `FeedCoverage` | Separate feed evidence, exact interval, count, status and observed/available clock, never fabricated as a news story |

The output state is one of
`CANDIDATE_ALERT`, `NO_ALERT`, `ABSTAIN`, `UNAVAILABLE`.
`CANDIDATE_ALERT` means **request deeper analysis only**, never trade.
`NO_ALERT` means explicit exclusion or proven same-context duplicate.
`ABSTAIN` means policy/category/source relation cannot be resolved.
`UNAVAILABLE` means required usable source/time/quality evidence is absent.

An event with known usable evidence and partial coverage can be screened
without claiming the entire feed was complete. Confirmed complete empty
coverage yields a separate `EMPTY` result and **zero fabricated events**.
Broken or unknown feed coverage yields `UNAVAILABLE`, not ordinary NO_ALERT.
Event content is inert even when it contains prompt-injection or BUY/SELL text.

### Exact-context duplicate and causal boundary

Duplicate NO_ALERT is permitted only if all of these are established from a
prior **available** and **conclusive** record:

1. Exact `source_id,event_id,version,content_sha256` equality;
2. Same policy ID, version and full policy hash;
3. Same logical screening context, with no global sharing across arms;
4. Prior outcome CANDIDATE_ALERT or NO_ALERT, not ABSTAIN/UNAVAILABLE;
5. Compatible quality reference SHA for the current retained source evidence;
6. Valid prior receipt reference and availability at or before the current
   decision cutoff.

A changed policy, earlier inconclusive status or other arm cannot suppress
the new event. A future prior result cannot rewrite an earlier screening.
The same proven source/event/version with conflicting content SHA produces
ABSTAIN, not arbitrary first-copy-wins. A genuine new version with
a valid `revision_of` reference is evaluated separately. The module never
turns text similarity into exact duplicate proof.

Deterministic identity commits to the effective source/policy/context,
quality/coverage/availability, revision, cutoff, disposition and
conclusive duplicate reference. Future prior records that are not yet
available are excluded from decisions and replay identity. Exact replay of
the same input produces the same record hash; no global mutable history is
stored in this package.

## Accepted behavior cases and additional adversarial evidence

| Case | Core expected result |
|---|---|
| 1 new allowed event | Candidate alert with event, policy and provenance refs |
| 2 explicit excluded category | No alert and explicit exclusion reason |
| 3 exact policy/context/quality-scoped conclusive duplicate | No alert with prior receipt reference |
| 4 distinct evidenced revised edition | New candidate, original version not erased |
| 5 required receipt or available-clock evidence missing | Unavailable |
| 6 unknown or policy-unspecified category | Abstain |
| 7 same native version, different retained digest | Abstain and preserve contradiction |
| 8 malformed source identity/digest | Unavailable, no automatic repair |
| 9 hostile instructions in inert text | Same metadata classification, zero execution |
| 10 truly covered empty versus failed/unknown feed | Separate EMPTY versus UNAVAILABLE, never a fabricated item |
| 11 future revision evidence | Unavailable until actual cutoff, no past rewriting |
| 12 changed screening policy | Fresh evaluation, no global duplicate |
| 13 earlier abstain/unavailable | Fresh evaluation once adequate evidence arrives |
| 14 separate arms or future prior screening | No cross-arm suppression or temporal leak |

Added guards verify malformed policy hashes/overlapping categories, duplicate
order invariance, source-quality change, partial-feed versus event availability,
naive/impossible clocks, contradictory revision relation, canonical record
identity, independent events and AST absence of source network/dynamic execution
capabilities. Tests are synthetic witnesses, not provider-data validation.

### Runnable engineering checks (only on an exact SHA)

```bash
uv sync --locked
uv run python --version
uv run pytest -q tests/unit/test_news_triage.py
uv run ruff check src/drift/news_triage tests/unit/test_news_triage.py
uv run ruff format --check src/drift/news_triage tests/unit/test_news_triage.py
uv run mypy src/drift/news_triage tests/unit/test_news_triage.py
uv build
git diff --check origin/main...HEAD
uv run pytest
```

A Green focused suite is not the same as full canonical CI or acceptance of
the Matthew producer interface. A separate independent AntiGravity report
should validate correct offline behavior, negative controls, caller
forgeability and exact source/SRC compatibility. All currently unrun
checks must be identified as NOT_RUN until actual exact-head evidence exists.

## Reciprocal acceptance and next integration gates

1. Matthew must **publish and accept** #394/PR #415's exact minimal SRC
   profile/schema, strict immutable field types, retained-ref/digest rules,
   source-receipt version, availability policy, quality and feed coverage
   states, and prior-screening receipt interface. See the concrete
   compatibility request in #394. Kanuj must accept the source consumer's
   exact mapping to #393.
2. When producer interfaces are accepted, add an exact producer-owned
   adaptation/check issue that maps validated Matthew SRC bytes to these
   consumer-local projections. Until then this draft cannot be advertised
   as an authenticated news intake or an implementation of Matthew's wire.
3. Preserve Kanuj #392 arm mapping and independent per-arm preprocessing
   under a future accepted experiment contract. Do not let one arm's prior
   processing globally suppress another's valid event.
4. AntiGravity independently tests this exact PR head and reports failures
   to the issue owner. Do not merge/close #381 as production-ready while
   #394 has unresolved review/wire gates, even if synthetic unit tests pass.

`#381` owns only its four existing exact paths. Matthew's source
contracts, M1 data, `src/drift/intelligence/`, broker, ledger, risk,
fixtures, interpreter/lockfile and external providers remain untouched.
No automatic paper/shadow/live trades or real capital are authorized.
