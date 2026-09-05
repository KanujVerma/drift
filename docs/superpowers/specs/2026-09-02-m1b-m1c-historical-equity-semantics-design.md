# Drift M1b and M1c Historical Equity Semantics Design

**Status:** Approved architecture with M1b implemented, independently reviewed,
and verified. Its historical execution record is:
`docs/superpowers/plans/2026-09-03-m1b-historical-security-identity-universes.md`.
The original combined M1c scope below is historical design context, superseded
by the [2026-09-05 economic events and observations design](2026-09-05-historical-economic-events-and-observations-design.md)
and [ADR 0009](../../adr/0009-separate-economic-events-and-observation-semantics.md).
The successor M1c and M1d milestones are designed only, with no executable plans
or implementation. The new design governs all future-market sketches below,
including outcome anchoring, role/query families, normalization, sessions,
missingness, research eligibility, and completion criteria. It does not change
completed M1b behavior.

Implementation refinements are recorded in
[ADR 0006](../../adr/0006-independent-historical-identity-and-lifecycle-facts.md)
(independent mapping/lifecycle facts and versioned interpretation) and
[ADR 0007](../../adr/0007-authenticated-point-in-time-universe-composition.md)
(source-definition replay, retained membership identity, and authenticated
structural composition). [ADR 0008](../../adr/0008-verify-selected-content-and-dependent-equivalence.md)
records selected-value integrity and dependent-equivalence replay. These rulings and the execution record govern M1b
where they refine the original sketches below. M0/M1a contracts are unchanged.

## Decision summary

Historical equity semantics remain the correct next problem after M1a, but they
do not form one implementation milestone.

- **M1b, Historical Security Identity and Universes**, establishes what issuer,
  economic security, and venue listing a record refers to; how external
  identifiers and primary-listing classifications changed; what listings existed
  or terminated; and which security or listing was an effective, historically
  knowable member of a named universe.
- **M1c, Market Events and Observation Semantics**, consumes M1b identities to
  represent corporate actions, terminal economic outcomes, source-observed daily
  market data, cutoff-aware normalized views, sessions, missingness, and
  historical-tradability results.

The split is causal. M1c action, bar, calendar, and outcome records cannot be
interpreted safely without stable security and listing identities. M1b can be
implemented and adversarially tested without prices, action accounting, or a
calendar engine. Neither milestone is an evaluator or backtester.

The first supported research scope is domestic operating-company common shares
with one explicitly evidenced primary listing on NYSE, Nasdaq, or NYSE American,
long-only, regular-session daily research. Classification must be proven by a
versioned source adapter. Unknown classification is indeterminate; a strict
admission gate rejects the candidate without relabeling the evidence as confirmed
ineligible.

## Problem

M1a can prove what bytes and fact versions were available through a channel by a
cutoff. It intentionally does not know whether `ABC` is a ticker, whether two
records describe the same share class, whether a listing existed, whether a
universe silently dropped a failed company, or whether a historical price was
retroactively adjusted using a future split.

Before an equity evaluator can exist, Drift must answer two different groups of
questions:

1. **Historical identity and candidacy:** What economic security and venue
   listing existed, what was it called, how was that interpretation corrected,
   and could it have belonged to the declared candidate universe?
2. **Market meaning and realized history:** What source observation or market
   event occurred, which session did it describe, what information was usable at
   decision time, and what later economic outcome belongs only to ex-post
   accounting?

A provider's current symbol table, current constituents, adjusted-close column,
or missing final row cannot answer these questions. M1b and M1c define the
minimum scientific contracts against which future adapters can be tested.

## Evidence classification

### Repository facts at design time

This subsection records the pre-M1b baseline. Current implemented capabilities
are described in the architecture overview and execution record linked above.

- M0 provides immutable research references, canonical JSON, SHA-256 content
  hashing, append-only audit-event drafts, SQLite ledger storage, verified replay,
  and tamper detection.
- M1a at commit `0385493` provides exact-byte dataset manifests, public/vendor/
  system channels, exact/bounded/unknown availability evidence, immutable fact
  revisions, causal predecessor availability, exact-object validation decisions,
  and query-bound eligible/ineligible/indeterminate results.
- `DatasetManifestV1` is asset-neutral and distinguishes source facts from
  derived facts. `RecordTemporalContractV1` binds record roles without providing
  market semantics.
- M1a's synthetic validator is deliberately format-specific. Each M1b or M1c
  record format needs its own versioned validator and cannot inherit a passing
  M1a validation decision.
- No real data source, provider adapter, security master, calendar library,
  evaluator, backtester, broker, or trading capability exists.

### Primary-source facts

- CRSP separates permanent company and security identifiers. Its documentation
  describes PERMCO as company-level across name changes and PERMNO as
  security-level across trading history, demonstrating that company and security
  are different research identities.
- OpenFIGI distinguishes share-class, composite, and venue-level identifiers.
  Multiple listings can share a share-class FIGI while retaining distinct
  venue-level FIGIs.
- SEC CIK identifies a filer, not a security or listing. SEC ticker/CIK/exchange
  association files are periodically updated and carry no guarantee of accuracy
  or scope.
- CRSP separately records listing/delisting information, post-delisting value,
  distributions, delisting returns, and reasons why a return is missing.
- LEAN distinguishes permanent symbols from changing tickers and exposes raw,
  split-adjusted, adjusted, scaled-raw, and total-return behavior. Its adjusted
  modes may use the entire split and dividend history.
- Exchange schedules include holidays and early closes. The
  `exchange_calendars` project supplies reusable schedules but explicitly does
  not guarantee every calendar's historical accuracy.

### Academic evidence

- Shumway documents material bias when negative delisting outcomes are missing
  from stock-return data and observes that many actual negative-delisting returns
  were unavailable.
- Brown, Goetzmann, Ibbotson, and Ross show that sample truncation by survival
  can create apparent return predictability.
- Look-ahead benchmark research shows that using later index composition can
  materially bias portfolio evaluation.

### Third-party framework behavior

- LEAN's symbol, mapping, factor-file, normalization, and corporate-action models
  are useful failure-case references, not Drift's architecture.
- NautilusTrader's venue-qualified instrument IDs demonstrate why a raw symbol
  alone is ambiguous, but a symbol-plus-venue string is still not a historical
  economic-identity system.
- `exchange_calendars` is a possible future schedule producer, not authoritative
  provenance by itself.

### Engineering inference

- Drift needs issuer, security, and listing levels because facts, economic
  claims, and venue/session histories attach to different subjects.
- Immutable identity assertions must be correctable through later assertions and
  dataset versions. Mutating or merging stored IDs would break replay.
- A universe version must target either security or listing identity, never an
  untyped mixture.
- Decision information and ex-post outcomes require separate types and consumer
  interfaces. A role enum on one permissive bag is too easy to misuse.
- Raw observations are the provenance primitive, but a cutoff-valid normalized
  view can be a legitimate derived research input.

### Unresolved assumptions

- No provider has been selected or shown to supply complete historical identity,
  action, outcome, bar, universe, or calendar evidence.
- No named index methodology is selected.
- The first evaluator's rebalance moment and fill convention remain undecided.
- Corporate-action event variants beyond the initial scope may require later
  schema versions.

## Initial supported scope

### Included

| Dimension | Initial contract |
|---|---|
| Economic instrument | Domestic operating-company common share |
| Listing | One time-scoped, provenance-backed primary listing |
| Venues | NYSE, Nasdaq, NYSE American |
| Research direction | Long-only |
| Frequency | Daily |
| Session | Regular session only |
| Identity evidence | Explicit, versioned classification and mapping records |
| Test data | Synthetic adversarial histories only |

The phrase `domestic operating-company common share` is a Drift eligibility
classification, not a ticker/exchange heuristic and not an alias for CRSP share
codes. A future adapter must provide source fields, mapping rules, provenance,
M1a availability, and validation evidence for:

- equity versus fund, receipt, unit, derivative, or preferred claim;
- common-share subtype and share class;
- operating corporation versus REIT, fund, trust, or acquisition vehicle;
- domestic versus foreign issuer classification;
- venue and listing role over an effective period.

If any required classification is unknown or conflicting, structural eligibility
is indeterminate and cannot become eligible under the initial contract.

### Explicitly excluded

- ETFs, exchange-traded products, closed-end funds, and unit investment trusts;
- ADRs, depositary shares, and foreign ordinary shares;
- REITs and other shares of beneficial interest;
- preferred shares and convertibles;
- SPACs, acquisition-company common shares, units, warrants, and rights;
- OTC securities;
- secondary and foreign listings;
- options, futures, cryptoassets, debt, shorting, and leverage;
- premarket, after-hours, auction-only, overnight, and intraday observations.

These are extension boundaries, not claims that excluded assets are unsuitable
forever. CRSP's separate classifications show that a generic `US Equity` bucket
hides materially different issuer and security forms. SEC descriptions show
that ETFs add NAV, creation/redemption, fund holdings, and distribution
semantics, while ADRs add an underlying foreign security, depositary ratio,
currency conversion, and depositary fees.

## Terminology

| Term | Meaning in Drift |
|---|---|
| Issuer | Legal/reporting economic entity that issues securities |
| Security | One economic/legal claim or share class issued by an issuer |
| Listing | One venue-specific admission and trading history for a security |
| Identity assertion | Immutable, sourced claim about an identity or relationship |
| Identity dataset version | Manifest-bound interpretation of a set of assertions |
| External identifier mapping | Dated, sourced mapping from an external namespace/value to a Drift identity |
| Primary listing assertion | Time-scoped sourced classification of a listing under a named methodology |
| Universe definition | Versioned, content-addressed membership meaning and methodology |
| Membership target level | Exactly `security` or `listing` for one universe version |
| Effective time | When a lifecycle, membership, or action state becomes true |
| Availability | M1a evidence for when a channel could know a record version |
| Source observation | Market value exactly as delivered under a documented source basis |
| Normalized view | Derived artifact produced from raw observations, actions, and a versioned policy |
| Decision information | Data legally usable by the historical decision cutoff and channel |
| Ex-post outcome | Later realized facts used only to measure economic results |
| Structural eligibility | Whether identity, classification, listing, and universe requirements are met |
| Historical tradability | Later M1c query result combining classification, lifecycle, universe, and session state; data evaluability is separate |

### Effective-time and revision compatibility

M1a's `AvailabilityEvidenceV1` answers when information was knowable through a
channel. M1b/M1c also need to represent when a lifecycle or economic state took
effect, including open-ended, date-only, bounded, corrected, or unknown
boundaries. The current `ValidPeriodV1` requires two exact UTC boundaries, and
M1a includes that period in a fact's logical revision key. It therefore cannot
represent a correction that changes an effective boundary while retaining the
same logical assertion.

The smallest consistent additive design has three parts:

```text
TemporalBoundaryClaimV1
  shape: exact | bounded | unknown
  lower_bound, upper_bound
  source_precision, source_time_label, source_timezone
  evidence_reference

TemporalIntervalClaimV1
  start: TemporalBoundaryClaimV1
  end: TemporalBoundaryClaimV1 | null

RevisionEnvelopeV1
  logical_record_id
  record_version_id
  revision_kind, supersedes_record_version_id, source_sequence
  availability
  payload_hash, source_artifact
```

`end=null` means explicitly open-ended/ongoing; an `unknown` end means evidence
says the interval ended but its boundary cannot be established. Boundary claims
reuse M1a's shapes, precision vocabulary, source-window validation, UTC
normalization, and safe-reference rules. They have no channel or availability
basis because they answer `when did the state take effect?`, not `when could a
channel know it?`.

The revision envelope's stable key excludes correctable effective claims. The
effective interval is versioned payload, so a later correction can supersede it
without creating a different logical event. A generic causal-chain validator
consumes these envelopes and preserves M1a's revision-kind, predecessor,
source-sequence, channel-availability, and backward-availability invariants.
Existing `FactVersionV1` behavior does not change.

M1b/M1c record manifests require an additive `DatasetManifestV2` with a
discriminated temporal contract:

```text
DatasetManifestV2
  same storage-neutral provenance and partition fields as V1
  manifest_schema_version: "2"
  temporal_contract:
    RecordTemporalContractV1 | AssertionTemporalContractV1

AssertionTemporalContractV1
  logical_record_id field
  effective interval/boundary fields
  availability field
  version/predecessor/source-sequence fields
  payload and null/unknown-state fields
```

This is explicit schema evolution, not reinterpretation. `DatasetManifestV1`,
`RecordTemporalContractV1`, `FactVersionV1`, existing hashes, validators, and
ledger replay remain unchanged. `DatasetReference` can continue pointing to the
exact new manifest hash because it does not interpret manifest internals. The
exact V2 schema and migration tests must be approved in M1b planning.

## Milestone boundary and dependency flow

```text
M1a temporal provenance
    |
    v
M1b identity assertions and corrections
    -> issuer / security / listing datasets
    -> external identifier histories
    -> listing lifecycle and termination state
    -> universe definitions and membership histories
    -> structural eligibility results
    |
    v
M1c action, outcome, observation, and session datasets
    -> source/raw daily observations
    -> corporate actions and final terms
    -> terminal economic outcomes
    -> pinned session schedules
    -> normalized-view artifacts
    -> missingness and historical-tradability results
    |
    v
Future evaluator, separately designed
```

M1b does not produce an equity return. M1c does not select or score a strategy.
The future evaluator must receive distinct decision-information and outcome
inputs rather than a general market-data collection.

## M1b: identity architecture

### Identity hierarchy

All internal IDs are Drift UUIDv7 values minted once and never reused.

| Level | Represents | Remains stable through | Requires a different identity when | Why the level is necessary |
|---|---|---|---|---|
| `IssuerV1` | Legal/reporting economic entity | Ticker changes, listing changes, multiple share classes, ordinary name change | New legal/economic issuer after a merger, spinout, or reorganization when evidence establishes discontinuity | Filings and issuer classifications are not share-class or venue facts |
| `SecurityV1` | One economic/legal claim or share class | Ticker change, exchange transfer, split/reverse split, ordinary recapitalization that preserves the claim | Rights materially change, a class converts, a merger cancels the claim, or evidence establishes a successor claim | Prices, actions, and ownership terms apply to a security, not the whole issuer |
| `ListingV1` | One venue-specific admission and trading history | Ticker change on the same venue and continuous admission | New venue admission, exchange transfer, termination followed by a distinct relisting, or a second simultaneous venue | Sessions, symbols, tradability, and bars are venue-specific |

Continuity is an assertion supported by evidence, not a universal rule. A
share-class conversion or reorganization may be `resolved`, `distinct`,
`successor`, or `indeterminate`. Drift must not infer continuity from similar
names or split identities merely because terms changed.

### Identity assignment

```text
IdentityAssignmentV1
  revision: RevisionEnvelopeV1
  identity_kind: issuer | security | listing
  internal_id: UUIDv7
  source_namespace: string
  source_key: string
  assertion: create | affirm | retract | replace
  effective_interval: TemporalIntervalClaimV1
```

UUIDv7 supplies unique internal naming only. It does not discover sameness,
resolve provider disagreements, or make independently minted IDs reproducible.
An ID is stable because the immutable assignment dataset is retained and reused,
not because its random value can be regenerated.

Every rebuild consumes a specific identity-dataset manifest. A future operational
registry or cache may index the latest validated dataset, but it is disposable
and never authoritative. Experiments pin the identity manifest they used.

### Correcting identity without rewriting history

Identity corrections are immutable assertions in a new dataset version:

```text
IdentityRelationshipVersionV1
  revision: RevisionEnvelopeV1
  left: IdentityReferenceV1(kind, internal_id)
  right: IdentityReferenceV1(kind, internal_id)
  relationship_kind:
    issuer_has_security | security_has_listing |
    equivalent_to | distinct_from | successor_of | reorganized_from
  resolution_status: resolved | disputed | indeterminate
  effective_interval: TemporalIntervalClaimV1
```

Rules:

- An original ID, assignment, or relationship is never deleted, reassigned, or
  mutated.
- `equivalent_to` does not physically merge IDs. A resolution query may choose a
  canonical representative for one identity-dataset version while preserving
  aliases and provenance.
- `distinct_from` corrects an erroneous collapse and blocks transitive aliasing.
- A one-to-many split of an earlier interpretation creates new IDs plus explicit
  `distinct_from` or `successor_of` relationships. It does not retroactively edit
  the old dataset.
- Current resolution is a query over one manifest and cutoff, returning
  `resolved`, `conflict`, or `indeterminate` with exact supporting assertion
  hashes.
- An experiment using version A replays version A even when version B later
  corrects it.

Resolution also declares its mode:

- `as_known` applies only assertion versions eligible through the requested M1a
  channel/policy by the historical cutoff. This is the only mode accepted by a
  decision-information bundle.
- `current_interpretation` applies the active assertions in the pinned identity
  dataset version for present-day inspection or repair. It is labeled ex-post
  interpretation and cannot silently replace an old experiment's identity input
  or enter historical decision features.

`IdentityResolutionResultV1` binds the identity-manifest hash, mode,
`knowledge_cutoff`, `evaluation_time`, channel/policy hashes, all considered
assertion hashes, selected assertion hashes, and a
`resolved | conflict | indeterminate` classification.

Equivalence and distinction graphs reject self-relations, contradictory active
`equivalent_to`/`distinct_from` paths, and unresolved cycles. Ambiguity produces
an indeterminate result, not an arbitrary canonical ID.

Relationship endpoints are kind-checked:

| Relationship | Left kind | Right kind |
|---|---|---|
| `issuer_has_security` | issuer | security |
| `security_has_listing` | security | listing |
| `equivalent_to` / `distinct_from` | issuer, security, or listing | same kind as left |
| `successor_of` / `reorganized_from` | issuer or security | same kind as left |

Listing succession caused by a venue transfer belongs to listing lifecycle,
not a generic cross-kind relationship.

This is correction-capable identity evidence, not a general automated
entity-resolution engine.

### External identifier mappings

```text
ExternalIdentifierMappingVersionV1
  revision: RevisionEnvelopeV1
  target_level: issuer | security | listing
  target_id
  namespace: ticker | cik | cusip | figi | provider | exchange_symbol | other
  identifier_value
  provider_or_authority
  effective_interval: TemporalIntervalClaimV1
  mapping_status: asserted | ambiguous | withdrawn
```

Namespace and target level are mandatory. CIK normally maps to issuer, FIGI and
CUSIP variants may map to security or listing depending on the source contract,
and ticker/exchange symbol maps to listing. Drift does not hardcode those
assumptions globally; each adapter declares and validates its namespace meaning.

Mapping validation rejects:

- overlapping active mappings of one authority/namespace/value to different
  targets unless the record is explicitly `ambiguous`;
- ticker resolution without venue/listing scope;
- a mapping outside its target's valid lifecycle;
- current-snapshot mappings backfilled into earlier periods;
- corrections that overwrite or detach historical mapping versions.

A ticker change creates a new mapping interval for the same listing. Ticker reuse
creates a later mapping interval to a different listing. Equal strings never
establish identity.

### Security classification assertions

Initial-scope classification is a sourced record, not a policy hash or adapter
boolean:

```text
SecurityClassificationVersionV1
  revision: RevisionEnvelopeV1
  issuer_id, security_id
  issuer_form: operating_company | fund | reit | trust | acquisition_company | other | unknown
  issuer_domicile and incorporation_country: sourced value | unknown
  instrument_form: common_share | preferred | receipt | unit | warrant | right | other | unknown
  share_class_label: sourced value | unknown
  domestic_status: domestic | foreign | indeterminate
  effective_interval: TemporalIntervalClaimV1
  source_taxonomy_id/version and source fields
```

Conflicting active classification assertions produce `indeterminate`. The
structural admission policy may reject that candidate, but the evidence result
is never relabeled as confirmed ineligible. A provider adapter must retain its
native taxonomy and a versioned mapping into this small Drift vocabulary.

### Primary listing

Primary status is needed only because the initial scope selects one primary US
listing. It is therefore a time-scoped assertion, not an intrinsic field:

```text
ListingRoleVersionV1
  revision: RevisionEnvelopeV1
  security_id, listing_id
  role: primary | secondary | indeterminate
  methodology_id, methodology_version
  effective_interval: TemporalIntervalClaimV1
```

The methodology and evidence decide what `primary` means. A provider disagreement
can remain ambiguous. An exchange transfer normally terminates one listing,
creates another for the same security, and changes the primary-role assertion.

Within one security, methodology, and evaluation instant, exactly one listing
may resolve as primary. Two overlapping primary assertions from the same
methodology are invalid. Conflicting methodologies remain separate and a query
that does not select one is indeterminate. Every role assertion must reference a
listing connected to the named security by a validated
`security_has_listing` relationship.

## M1b: listing lifecycle

```text
ListingLifecycleVersionV1
  revision: RevisionEnvelopeV1
  listing_id
  event_kind:
    admitted | first_regular_trade | suspended | resumed | venue_transfer
  effective_time: TemporalBoundaryClaimV1
```

The listing's venue is fixed for that admission. An exchange transfer terminates
the old listing and creates a new listing linked to the same security. A ticker
change does neither.

Lifecycle invariants:

- no listing is effective before its admission or first supported trading
  boundary;
- suspension and resumption intervals cannot overlap inconsistently;
- termination does not follow from missing bars;
- a terminated listing remains in historical datasets;
- every lifecycle version uses M1a availability and causal revision semantics;
- unknown first/last trading precision remains bounded or unknown.

### Termination boundary

```text
ListingTerminationVersionV1
  revision: RevisionEnvelopeV1
  listing_id
  reason:
    acquisition | merger | bankruptcy | exchange_delisting |
    voluntary_withdrawal | venue_transfer | reorganization | unknown
  last_regular_trade_time: TemporalBoundaryClaimV1
  effective_time: TemporalBoundaryClaimV1
  successor_relationship_ids
  outcome_evidence_status: known | partial | unknown
```

`ListingTerminationVersionV1` is the sole lifecycle termination authority. It is
not duplicated as a generic lifecycle event. Its revision envelope's
`logical_record_id` is the logical termination ID.

M1b records identity and lifecycle facts only. It does not store cash
consideration, share conversion, terminal value, payout, or return. Those are
M1c outcome records. `outcome_evidence_status=unknown` remains unknown and blocks
any future policy that requires a resolved terminal result.

No current listing means only that the current lifecycle is inactive. It never
means the security did not exist historically.

## M1b: universe architecture

### Universe definitions

```text
ResearchUniverseDefinitionV1
  universe_id
  universe_version
  universe_kind: structural
  target_level: security | listing
  methodology_reference and methodology_hash
  identity_manifest_hash
  classification_contract_hash
  created_at

SourceUniverseDefinitionVersionV1
  revision: RevisionEnvelopeV1
  universe_id, universe_version
  universe_kind: index | provider_coverage
  target_level: security | listing
  methodology_reference and methodology_hash
  identity_manifest_hash
  effective_interval: TemporalIntervalClaimV1
```

One universe version has exactly one target level. Issuer membership is omitted
until a concrete use requires it. A security-target universe means an economic
share class belongs regardless of which supported listing later supplies
tradability. A listing-target universe means that particular venue admission is
the member. The initial structural universe targets `listing` because its primary
venue and later session/tradability semantics are part of candidacy.

Research-authored structural definitions are preregistered experiment policies;
they are not claims about what an index provider historically published.
Source-derived index/provider definitions carry M1a availability and revision
evidence through their revision envelope. Both forms are immutable,
manifest-bound, and content-addressed. A researcher cannot silently change the
candidate set without changing experiment provenance.

### Membership versions

```text
UniverseMembershipVersionV1
  revision: RevisionEnvelopeV1
  universe_id, universe_version
  target_level, target_id
  membership_effect: included | excluded
  effective_time: TemporalBoundaryClaimV1
  source_event_id
```

`membership_effect` describes business state. `revision_kind` in the envelope
describes whether this record is an initial assertion, correction, restatement,
or withdrawal. Withdrawing a bad assertion is not an effective universe removal;
an exclusion record is. Every membership target level must exactly match its
universe definition.

Membership resolution binds two separate inputs and asks two separate questions:

1. Was the membership event knowable through channel C by knowledge cutoff K?
2. Was membership economically effective at evaluation time E?

An addition announced May 20 and effective June 1 is known upcoming membership
on May 25, but is not current effective membership. A future evaluator may
inspect upcoming events as decision information only if its declared strategy
allows it; current-membership selection remains false before June 1.

Current constituent snapshots cannot establish historical membership. Absence
from a later snapshot is not an earlier removal event. Corrections append new
membership versions and never rewrite the source event seen by old experiments.

### Universe kinds and screening boundary

- **Structural universe:** explicit supported security classification and
  listing-role/lifecycle requirements. M1b implements its synthetic contract.
- **Index universe:** named methodology plus sourced membership events. M1b
  defines the generic contract and adversarial fixtures but selects no index
  family or real adapter.
- **Provider coverage:** what a dataset/provider actually covered, distinct from
  economic eligibility or investability.
- **Strategy-derived screen:** explicitly outside M1b. Price, ADV, market cap,
  earnings, and other filters are future evaluator calculations from PIT inputs.

A later derived screen must produce its own content-addressed universe artifact
that names its base universe, exact inputs, code/policy hash, and cutoff.

### Structural eligibility result

M1b may return a query-bound `StructuralEligibilityResultV1` with classification
`eligible`, `ineligible`, or `indeterminate`, reasons, `knowledge_cutoff`,
`evaluation_time`, channel/policy, identity-manifest hash, universe-manifest
hash, and supporting selection-proof hashes.
It answers only classification, listing lifecycle, primary-role, and effective
membership. It does not claim a session was open, a bar exists, or the security
could have been executed. Full historical tradability is M1c.

## M1c: market-event architecture

### Corporate-action envelope

```text
CorporateActionVersionV1
  revision: RevisionEnvelopeV1
  security_id and optional listing_id
  action_kind
  announcement/evidence fields when source supplies them
  effective/ex/record/payable TemporalBoundaryClaimV1 fields only where relevant
  typed terms
```

`action_kind` initially distinguishes:

- forward and reverse split;
- regular and special cash distribution;
- stock distribution;
- merger/acquisition;
- spinoff;
- share-class conversion;
- rights distribution only as an explicitly deferred variant unless the initial
  implementation proves it necessary.

Terms are a discriminated union, not one object with dozens of fake optional
fields:

- split terms require a positive numerator/denominator ratio;
- cash-distribution terms require amount, currency, and applicable ex/payable
  dates;
- stock-distribution/spinoff terms require child security and distribution ratio;
- merger terms retain one or more typed consideration components and successor
  relationships;
- conversion terms retain predecessor/security-successor ratios and conditions.

Availability says when terms were knowable. Effective, ex, record, and payable
dates say when different economic or entitlement states apply. One never stands
in for another. Missing or irrelevant dates remain absent; date-only evidence
uses M1a bounded precision.

Action corrections use the same revision projection and causal predecessor rule
as M1a. Earlier announced terms remain replayable for decision information,
while final realized terms can be selected for ex-post accounting at their later
availability.

### M1a revision projection

Each versioned M1b or M1c record exposes a deterministic projection containing:

- stable logical record ID that excludes correctable effective claims;
- version ID and source sequence;
- revision kind and predecessor;
- availability evidence;
- typed payload hash and source artifact, with effective claims inside the
  versioned payload.

Validators apply M1a's causal chain invariants to that projection. Drift does not
copy or weaken the temporal algorithm inside each market type.

## M1c: terminal economic outcomes

M1c links economic results to M1b terminations:

```text
TerminalOutcomeVersionV1
  revision: RevisionEnvelopeV1
  logical_termination_id
  selected_termination_version_hash
  termination_selection_reference_hash
  security_id, listing_id
  outcome_status: resolved | partial | unknown
  consideration_components:
    cash | successor_security | distributed_security | rights | other
  settlement/effective dates where known
  currency and ratios where applicable
  information_role: ex_post_outcome
```

Unknown outcome carries no zero value and no fabricated return. An explicitly
evidenced worthless security may record zero terminal value; that is different
from missing evidence. Any imputed delisting return belongs to a future evaluator
assumption and must never be stored as source truth.

Shumway's findings justify retaining failures and treating missing terminal
returns as a scientific problem. They do not justify hardcoding a universal
negative imputation.

## M1c: observation architecture

### Source/raw daily observation

Source-observed market data is the provenance primitive. `raw` means values are
retained as delivered under an explicit source definition and have not been
back-adjusted by Drift. It does not imply that the source is correct or that
provider-side transformations are absent; the source contract must disclose its
basis.

```text
DailyMarketObservationVersionV1
  revision: RevisionEnvelopeV1
  logical key: source + listing + session + interval + source basis
  listing_id, security_id
  session_id and session_schedule_hash
  source_record_id
  currency
  open, high, low, close, volume
  source_price_basis: source_raw | provider_adjusted | unknown
  completeness and source flags
```

The initial validated decision-data primitive requires `source_raw`. A
provider-adjusted or unknown basis may be retained for forensic comparison but
cannot masquerade as raw.

An actual minimal daily-bar version type is justified in M1c because actions, sessions,
currency, volume, normalization, and missingness must attach to a concrete
record. M1c does not build columnar storage or market-data ingestion.

Corrections append observation versions under the same logical key. Historical
selection uses the revision envelope and M1a causal availability, so a current
corrected bar cannot overwrite bytes or values used by an earlier experiment.

### Bar meaning

The initial bar contract is `regular_session_aggregate`. It binds:

- one listing and one verified regular session;
- explicit UTC session open and close plus local session date;
- the source's inclusion boundary and timestamp convention;
- OHLC aggregation basis and trade eligibility rules supplied by the adapter;
- volume unit as source shares/contracts under the source basis;
- M1a availability after the completed observation was delivered.

A date label alone is never a session timestamp. The design leaves interval and
session-kind fields extensible for later intraday support without implementing
intraday auctions, halts, or extended hours.

### Currency

Listing quote currency, price currency, cash-distribution currency, and terminal
cash consideration are explicit. Initial supported observations require a
three-letter source currency code and expected USD under the structural scope.
Unexpected or unknown currency is indeterminate. FX conversion is outside M1c.

## M1c: normalized views

The design does not require every decision feature to use numerically raw prices.
It requires raw/source observations to remain the provenance base and every
normalization to be an explicit derived artifact:

```text
source/raw observation manifests
  + corporate-action manifest
  + normalization policy/version/hash
  + knowledge cutoff and channel/policy
  + effective-action cutoff
  + information role
  -> derived normalized-view manifest and exact output hashes
```

```text
NormalizationPolicyV1
  policy_id, version, implementation_hash
  price_basis:
    split_normalized | distribution_normalized | total_return
  price_factor_rule
  volume_factor_rule
  fractional-share/rounding declarations where relevant
  action_selection_rule
  role: decision_information | ex_post_outcome
```

| Basis | Meaning | Initial permitted role |
|---|---|---|
| `split_normalized` | Earlier price and share-volume values are rescaled only for eligible, already-effective share-ratio actions | Decision information or ex-post outcome |
| `distribution_normalized` | Price continuity also reflects eligible cash or property distributions under an explicit factor rule | Ex-post outcome only initially |
| `total_return` | Derived value includes an explicit distribution/reinvestment convention | Ex-post outcome only initially |

None of these names implies a universal formula. The policy implementation hash,
rounding, entitlement, reinvestment, and action-selection rules define the
actual transformation.

Initial decision-data support should permit source raw and cutoff-aware
split-normalized views. Distribution-normalized and total-return artifacts remain
defined concepts but should not become decision inputs until their treatment is
separately tested.

For a decision view with knowledge cutoff K and evaluation time E, an action may
affect normalization only when:

1. its action version is eligible through the declared channel/policy by K; and
2. its economic effective/ex boundary is no later than E.

A split announced but not yet effective may be known information but cannot
rescale past decision features as if the economic change had occurred. A split
effective after E cannot change the E-normalized history, even when known by K.
For split normalization,
the volume factor is the reciprocal economic share factor corresponding to the
price factor. Cash distributions never adjust volume.

LEAN's fully adjusted modes demonstrate the risk: they may use the entire split
and dividend history so the same old date is adjusted consistently regardless of
backtest end date. That is convenient presentation, not proof that the adjusted
value was a historical source observation.

## Hard information-role boundary

Base manifests are lineage and replay inputs, not decision authorization. They
may contain later corrections, future removals, final action terms, emergency
closures, and outcomes. Decision-facing code never receives an unrestricted
base-manifest resolver.

Every decision input first produces a purpose-typed normalized query and an
exact audit-side selection proof:

```text
NormalizedSelectionQueryV1
  purpose:
    identity_resolution | structural_eligibility | universe_membership |
    listing_lifecycle | listing_termination | corporate_action |
    terminal_outcome | market_observation | session
  information_role: decision_information | ex_post_outcome
  resolution_mode
  record_contract_hash and schema_hash
  knowledge_cutoff
  evaluation_time or target_session
  channel and policy hashes

CutoffSelectionProofV1
  source_manifest_hash
  DatasetValidationDecisionV2 hash
  selection_algorithm/version/hash
  normalized_query and query_hash
  considered_record_hashes
  selected_record_hashes
  classification and reasons
```

The considered set is retained so omission of a future-bearing or conflicting
record is detectable, but the full proof stays behind the audit/validation
boundary. Selection proof validators recompute M1a availability, revision
causality, business-effective time, schema/record contracts, and target-level
rules. A manifest hash alone cannot substitute for a proof.

Decision code receives only:

```text
DecisionSelectionReferenceV1
  selection_proof_hash
  normalized_query_hash
  purpose and decision_information role
  selected_record_hashes
```

Outcome accounting separately receives through the outcome capability:

```text
OutcomeSelectionReferenceV1
  selection_proof_hash
  normalized_query_hash
  purpose and ex_post_outcome role
  selected_record_hashes
```

Neither reference exposes considered hashes or audit-side proofs. Decision code
does not receive outcome references, source manifests, or an unrestricted
resolver. The decision resolver authorizes exactly the union of selected record
hashes in `DecisionSelectionReferenceV1` values and output hashes in a validated
materialized view.

The purpose/role matrix is closed. Decision identity, structural eligibility,
membership, lifecycle, action, observation, and session references require
`decision_information`. Final termination and terminal-outcome selection for
accounting require `ex_post_outcome` and an `OutcomeSelectionReferenceV1`.
`TerminalOutcomeVersionV1` binds the exact selected termination version plus
that outcome-side reference. Neither reference exposes considered hashes.

Raw or normalized decision data is exposed only through a cutoff-materialized
view:

```text
DecisionMaterializedViewReferenceV1
  role: decision_information
  derived_manifest_hash
  DecisionSelectionReferenceV1 hashes
  knowledge_cutoff, evaluation_time
  channel and policy hashes
  normalization_policy_hash or explicit source_raw basis
  output_record_hashes
  validator/validation-decision hashes
```

For normalized views, validation additionally proves that every action factor
comes from a selected action version that was eligible by `knowledge_cutoff` and
effective by `evaluation_time`. Outcome records and unselected base records are
not addressable through this reference.

M1c uses distinct capabilities and evaluator inputs, not one permissive bag with
a role flag:

```text
DecisionInformationBundleV1
  purpose-typed DecisionSelectionReferenceV1 values for identity resolution,
    structural eligibility, universe membership, actions, and session
  DecisionMaterializedViewReferenceV1
  knowledge_cutoff, evaluation_time
  channel/policy and complete bundle hash

OutcomeEvidenceBundleV1
  base identity and termination manifest hashes
  purpose-typed OutcomeSelectionReferenceV1 values
  final action/outcome manifests
  realized session/observation evidence
  valuation cutoff
  exact validation-decision hashes
```

The future evaluator receives the two bundles through separate parameters and
separate resolver capabilities. The decision capability resolves only record
hashes in `selected_record_hashes` and materialized `output_record_hashes`; it
cannot resolve considered hashes, base manifests, or unselected records. The outcome
capability is unavailable from decision code. A
`TerminalOutcomeVersionV1`, final merger consideration, later dividend, future
split, future index removal, or later halt cannot validate inside a
`DecisionInformationBundleV1`. Ex-post accounting may consume what actually
happened after the decision, because measuring a later outcome is not the same
as leaking it into the decision.

Bundle validation requires every nested purpose, role, normalized-query hash,
knowledge cutoff, evaluation time/target session, channel, and policy to match
the outer bundle. An outcome proof cannot satisfy an action, observation,
membership, or session slot.

No evaluator, position ledger, cash accounting, reinvestment, tax, settlement,
or return calculation is implemented by M1c.

## M1c: calendar and session contract

M1c consumes an immutable schedule artifact rather than calculating exchange
holidays itself:

```text
CalendarArtifactV1
  calendar_id, calendar_version
  venue
  IANA timezone
  coverage
  schedule_artifact and content hash
  source/methodology references
  producer implementation/environment hashes

SessionVersionV1
  revision: RevisionEnvelopeV1
  session_id
  calendar_id/version and schedule hash
  venue, local session date
  regular open/close UTC
  status: regular | early_close | closed | emergency_closed | unknown
```

Initial observations may bind only to `regular` or `early_close` sessions. A
closed or unknown session cannot receive a normal bar. DST is resolved in the
schedule artifact and verified through UTC boundaries. Calendar versions and
generated schedule bytes are experiment provenance.

`exchange_calendars` may later produce schedule artifacts because it supports
many exchange calendars and current Python 3.14. Adoption still requires a
current dependency/license review, official-exchange comparison, coverage-bound
tests, and an ADR. The library itself states that accuracy is not guaranteed for
all calendars and ranges.

## Missing-observation and data-evaluability semantics

One null bar and one mutually exclusive status cannot represent every cause.
M1c keeps orthogonal states:

```text
SessionResolutionV1
  regular | early_close | closed | emergency_closed | unknown

ListingLifecycleResolutionV1
  active | not_yet_listed | suspended | halted | terminated | unknown

ProviderCoverageResolutionV1
  expected | not_expected | unknown

ObservationAvailabilityResolutionV1
  present | no_trade | provider_missing | corrupt_artifact | unknown

DataEvaluabilityResultV1
  evaluable | not_evaluable | indeterminate
  all four resolution hashes
  selected observation hash if present
  knowledge_cutoff, evaluation_time, channel/policy
```

Multiple states may coexist, such as a terminated listing on a closed session.
Provider missingness is permitted only when a validated provider-coverage record
says data was expected for that listing/session; otherwise it remains unknown.
An intraday halt is distinct from a longer suspension, although initial daily
support may return indeterminate when it cannot establish how the halt affected
the session aggregate.

Not every listing/session pair needs a stored negative row. Resolution combines
validated bar, lifecycle, session, provider-coverage, and artifact evidence. A
zero return is a calculated economic result, never a missingness substitute. A
zero-volume or no-trade state is not automatically a halt, closure, or delisting.

## Historical tradability semantics

Historical tradability is a query-bound M1c result, not a timeless listing flag:

```text
HistoricalTradabilityResultV1
  classification: tradable | not_tradable | indeterminate
  reasons
  listing and security IDs
  structural eligibility result hash
  effective universe membership hash
  lifecycle/termination hashes
  session-resolution hash
  knowledge_cutoff, evaluation_time, channel/policy and complete input hashes
```

For the initial daily scope, `tradable` requires supported classification,
active primary listing, effective universe membership, regular/early-close
session, and no effective suspension/halt/termination. It does not require a
provider bar to exist. Data availability is reported separately by
`DataEvaluabilityResultV1`, so a provider gap cannot change market tradability or
silently remove a candidate. M1c does not model broker restrictions, locates,
buying-power rules, or real-time execution checks.

## M1a integration and compatibility

M0 and M1a persisted contracts remain unchanged.

M1a's `DatasetValidationDecisionV1` requires `dataset-manifest-v1` and, for
record scope, `record-temporal-v1`. It cannot truthfully validate manifest V2 or
an assertion temporal contract. M1b therefore requires an additive decision:

```text
DatasetValidationDecisionV2
  decision_schema_version: "2"
  manifest_hash and manifest_schema_version
  temporal_contract_kind and version
  validator/profile IDs, versions, and hashes
  checked_at and validation scope
  exact validated artifact and record hashes
  checked contract discriminators
  result and deterministic findings
```

V2 enforces actual manifest/contract discriminators instead of inserting V1
contract names. `DatasetValidationDecisionV1` remains unchanged for M1a. New
audit-event payload schemas identify which decision version they reference.
Cutoff selection proofs for M1b/M1c manifest V2 records must reference a passing
V2 decision with matching manifest, schema, and temporal-contract hashes.

M1b and M1c reuse:

- the storage-neutral provenance and exact content-addressed partition rules of
  `DatasetManifestV1`, carried forward explicitly by additive
  `DatasetManifestV2`;
- `ValidPeriodV1` only where a fact truly has exact closed boundaries;
- `AvailabilityEvidenceV1` and public/vendor/system channels;
- `RevisionKind` and causal predecessor semantics through deterministic
  projections;
- existing canonical JSON, SHA-256, validation contexts/decisions, event drafts,
  append-only ledger, and replay.

Public, vendor, and system channels are sufficient. Provider/product identity
lives in channel identifier/version and source metadata. New channel kinds would
add vocabulary without answering a new temporal question.

The concrete additive gap is assertion/event temporality.
`ValidPeriodV1` requires exact UTC boundaries and `DatasetManifestV1` requires a
fact-period contract, while a listing termination, membership change, ex-date,
or last-trade boundary may be date-only, bounded, open-ended, corrected, or
unknown. `TemporalBoundaryClaimV1`, `TemporalIntervalClaimV1`,
`RevisionEnvelopeV1`, `AssertionTemporalContractV1`, `DatasetManifestV2`, and
`DatasetValidationDecisionV2` above are the proposed minimal additions. They
reuse M1a validation mechanics without changing existing M1a objects or hashes.

### Replacement records without a captured predecessor

A source or vendor may deliver a current corrected record without the consumer
having observed the original. This does not justify weakening M1a causality.

- The record is the initial observed version for that declared channel and
  retained source snapshot.
- Its source-native correction label is preserved separately.
- Historical completeness is `partial` or `unknown`; the dataset cannot claim a
  complete revision history before its first observed version.
- If a predecessor is referenced but absent, chain validation remains failed or
  indeterminate rather than exposing the correction as though its history were
  complete.

No existing M1a schema or behavior must change. The proposed additive boundary,
interval, revision-envelope, assertion-contract, manifest-V2, and
validation-decision-V2 types receive their own schema versions and do not alter
prior hashes or replay.

## Provider and adapter acceptance contract

No single provider is assumed to be universal truth. A future bake-off evaluates
each claimed information category independently.

| Capability | Evidence required |
|---|---|
| Identity history | Stable source keys, issuer/security/listing level meaning, dated mappings, corrections, ticker reuse/change examples |
| Classification | Explicit security/issuer/listing taxonomy, versioned mapping to Drift scope, unknown handling |
| Lifecycle | Admission, first/last trade, suspension, transfer, termination, successor evidence |
| Survivorship | Delisted/failed securities retained and coverage methodology documented |
| Universe | Historical membership events or snapshots, announcement/effective semantics, correction history |
| Corporate actions | Raw action terms, relevant dates, availability evidence, revisions, successor relationships |
| Terminal outcomes | Actual consideration/value evidence and explicit missing-reason semantics |
| Market observations | Source raw/unadjusted basis, OHLCV definitions, currency, corrections, no silent fill-forward |
| Normalization | Complete adjustment methodology, action cutoff behavior, price/volume factor relationship |
| Sessions | Venue calendar definition, holidays, early closes, timezone, versioned coverage |
| PIT availability | Source publication/vendor delivery precision and limitations compatible with M1a |
| Reproducibility | Snapshot/version identifiers, deterministic download/export, exact bytes and hashes |
| Licensing | Governing terms reference, retention/export/derived-use constraints for the intended operation |
| Operations | Coverage, update cadence, correction delivery, format stability, rate/cost limits |

An adapter earns validation only for the categories and coverage it proves. Drift
may compose identity, actions, outcomes, bars, universes, and calendars from
different sources. Provider disagreement remains explicit evidence, not a hidden
priority rule.

## Reuse versus build

### Drift-specific contracts

Drift must own:

- internal identity assignments and correction semantics;
- issuer/security/listing distinctions;
- historical mapping and universe target-level rules;
- structural eligibility, role separation, and leakage gates;
- termination-versus-outcome boundary;
- raw/source and normalized-view provenance;
- exact manifest, validation, and experiment bindings;
- adversarial fixtures and compatibility guarantees.

### Commodity components potentially reusable later

- `exchange_calendars` or another calendar producer behind an immutable schedule
  artifact contract;
- Arrow/Parquet for physical typed storage;
- DuckDB for local inspection/validation queries;
- external identifier services such as OpenFIGI as optional mappings;
- LEAN/Zipline action and normalization behavior as comparison or later
  simulation adapters;
- NautilusTrader instrument definitions as a later execution-facing adapter.

None is selected or added. Framework symbols, factor files, calendars, and
normalization modes do not replace Drift's scientific contracts.

## Architecture alternatives

| Alternative | Correctness/PIT | Corrections | Provider independence | Complexity | Decision |
|---|---|---|---|---|---|
| Flat security-master row containing issuer, share, listing, ticker, and lifecycle | Weak; encourages false joins and timeless fields | Overwrite-prone | Low | Superficially low | Reject |
| Layered identities backed by a mutable operational registry | Clear levels, but current registry can rewrite history | Operational mutation | Medium | Medium | Reject as authority; permit only as cache |
| One fully event-sourced market database for identity, actions, bars, sessions, and outcomes | Potentially strong | Strong | High | Excessive before a source or evaluator exists | Reject for current milestones |
| Framework-native LEAN, Zipline, or Nautilus identity and normalization | Depends on platform conventions | Varies | Low | High integration/lock-in | Reject as core |
| Immutable manifest-bound typed datasets with query-derived current resolution | Strong and explicit | Append-only versions | High | Moderate and staged | Recommend |

The recommended architecture is not a commercial security master. It is a
small set of immutable record contracts plus resolution functions and validation
evidence.

## Scientific invariants

1. Ticker, CIK, FIGI, CUSIP, name, and provider ID are mappings, never Drift
   identity.
2. Issuer, security, and listing IDs are distinct and never reused.
3. Identity corrections append assertions and dataset versions; old experiments
   replay the old interpretation.
4. UUID generation never establishes sameness or reproducibility by itself.
5. Primary-listing status is effective-period and availability scoped.
6. A universe version targets one identity level only.
7. Known future membership and effective current membership are different
   queries.
8. Current constituent or symbol snapshots cannot backfill history.
9. Delisted and failed securities remain in historical identity and membership
   datasets.
10. Missing terminal outcome is not zero, a total loss, or an ignored row.
11. M1b lifecycle termination and M1c economic outcome are separate records.
12. Corporate-action knowledge and economic effect are separate times.
13. Source/raw observations remain retained beneath every derived view.
14. A decision normalization uses only actions eligible by knowledge cutoff K
    and effective by evaluation time E.
15. Future outcomes never validate inside decision-information bundles.
16. Volume and price split factors remain economically reciprocal under the
    declared policy.
17. A missing observation has a typed cause or remains unknown.
18. Historical tradability is a hash-bound query result, not a static flag.
19. All versioned records reuse M1a availability and causal revision semantics.
20. No M1b/M1c validation result inherits trust from the M1a synthetic validator.
21. Every historical query binds both knowledge cutoff and evaluation time or
    target session.
22. Decision code receives purpose-typed selection references containing only
    selected/materialized record hashes, not full proofs or unrestricted base
    manifests.
23. Provider observation availability affects data evaluability, never the
    underlying market-tradability result.

## Adversarial synthetic histories

### M1b fixtures

- ticker change on one continuing listing;
- ticker reuse years later by an unrelated listing;
- two share classes under one issuer;
- two simultaneous listings for one security;
- exchange transfer creating a new listing for the same security;
- IPO/new admission unavailable before first supported trade;
- primary-listing change and conflicting provider methodologies;
- erroneous identity merge later corrected to `distinct_from`;
- two IDs later asserted `equivalent_to` without deleting either;
- issuer/security relationship correction;
- current symbol snapshot attempting historical backfill;
- structural universe with an unsupported or unknown classification;
- index addition known before effective date;
- index removal correction and current-constituent backfill attempt;
- acquisition, bankruptcy, voluntary withdrawal, and venue-transfer termination;
- termination with unknown outcome evidence;
- missing bars with no termination event.

### M1c fixtures

- forward and reverse split with coherent raw price/share/volume semantics;
- regular and special cash distributions with distinct terms;
- merger with cash, stock, and mixed consideration;
- spinoff whose child listing begins later;
- action correction retaining earlier known terms;
- March decision confronted with a June split;
- June purchase later receiving an actual dividend or terminal loss;
- present-day fully adjusted history presented as raw;
- cutoff-aware split-normalized view with exact input/action hashes;
- future action factor injected into a decision view;
- future outcome object injected into a decision bundle;
- early-close and DST schedule boundaries;
- provider missing bar versus market closed, not listed, suspended, halted,
  terminated, and no trade;
- unknown currency and an action amount in a different currency;
- calendar-version change altering a historical session.

## Final adversarial review

| Attempted cheat | Design defense | Remaining external uncertainty |
|---|---|---|
| Join history by today's ticker | Dated listing mapping plus internal ID | Source history may be incomplete |
| Treat ticker change as new security | Mapping changes while listing/security stays stable | Continuity evidence can be disputed |
| Collapse reused ticker | Nonoverlapping mappings to distinct listing IDs | Provider may omit old mapping |
| Merge issuer and share class | Typed issuer-to-security endpoint matrix rejects cross-kind relations | Complex reorganizations may remain indeterminate |
| Merge share classes | Separate security IDs and class evidence | Provider classification can conflict |
| Treat primary listing as timeless | Versioned role assertion, one primary per selected methodology/evaluation time | Methodologies may disagree |
| Use current universe historically | Decision capability resolves only selected hashes in a purpose-typed reference, never the full membership manifest or audit proof | Historical membership may be unavailable |
| Add member at announcement | Purpose-typed selection reference binds a query whose knowledge cutoff is separate from evaluation time | Announcement precision can be bounded |
| Drop bankrupt/delisted names | Terminated identities and memberships remain retained | Terminal economic value may remain unknown |
| Convert unknown outcome to zero | Separate unknown outcome status and no default return | Evaluator later needs reject/sensitivity policy |
| Use successor before it exists | Successor and admission selection proofs bind knowledge cutoff and evaluation time | Source may not establish exact boundary |
| Rewrite identity after correction | New assertion/dataset version plus explicit `as_known` versus `current_interpretation` mode; old manifest replayable | Current resolution may remain disputed |
| Rewrite action with final terms | Versioned observation/action chain plus exact considered/selected record proof | Incomplete vendor history blocks full PIT claim |
| Back-adjust March using June split | Materialized view proves action knowledge and effect by March cutoff | Vendor raw basis must be proven |
| Leak future dividend/merger/delisting | Outcome resolver capability is unavailable to decision code | Capability wiring must preserve the boundary |
| Call adjusted history raw | Source basis enum and derived-view lineage | Provider documentation can be inaccurate |
| Treat absent bar as zero | Orthogonal observation/data-evaluability states never synthesize return | Cause may remain unknown |
| Treat provider gap as delisting | Provider coverage/data evaluability are separate from lifecycle and tradability | Provider coverage evidence may be incomplete |
| Change universe until results improve | Universe definition/version becomes experiment input | Multiple-testing control belongs to evaluator |

The review changed the design in eleven material ways:

1. the original single milestone became causal M1b/M1c stages;
2. immutable identity assignments gained explicit correction assertions and
   manifest-version replay;
3. primary-listing status became a sourced temporal classification;
4. universe target level became mandatory and uniform per version;
5. raw data remained the provenance primitive while legitimate cutoff-normalized
   decision views were allowed;
6. decision and outcome evidence became separate bundle types rather than one
   role-tagged collection;
7. decision bundles now accept purpose-typed selection references and
   materialized views rather than full proofs or unrestricted base manifests;
8. uncertain/open effective time, correctable effective boundaries, and
   assertion revision keys gained explicit additive V2 contracts;
9. security classification became a versioned source assertion;
10. identity relationships gained a kind-safe endpoint matrix and primary-role
    uniqueness rules; and
11. tradability and data evaluability became separate results with orthogonal
    session, lifecycle, provider-coverage, and observation states.

## Backward compatibility

- M0 and M1a models, canonical serialization, hashes, event envelopes, ledger,
  and compatibility fixtures remain unchanged.
- M1b and M1c use new explicit V1 record schemas, additive
  `DatasetManifestV2`, and new validators. Existing `DatasetManifestV1` remains
  unchanged and replayable.
- Manifest V2 carries forward V1's storage-neutral provenance and partition
  identity while adding a discriminated assertion/event temporal contract.
  New validators bind M1b/M1c roles to concrete record formats.
- `DatasetValidationDecisionV2` truthfully binds manifest V2 and its actual
  temporal-contract discriminator. Decision V1 remains unchanged.
- Historical experiment references continue to pin exact dataset manifests.
- New identity/action/membership corrections create new dataset versions and
  audit drafts; they never rewrite ledger history.
- A future need to change M1a causal revision semantics or channel kinds requires
  a separate design, version, migration, and replay analysis. The proposed
  manifest V2 is additive and never deserializes or rehashes V1 history.

## Milestone completion boundaries

### M1b is complete only when

- identity assignments and corrections are immutable and replayable;
- issuer/security/listing distinctions and relationships are validated;
- source classification assertions and identity endpoint kinds are validated;
- external identifiers and primary-listing roles are temporal;
- listing lifecycle/termination and structural eligibility are explicit;
- universe definitions target one level and membership is PIT/effective-time safe;
- manifest/decision V2 and purpose-typed cutoff selection proofs are validated;
- adversarial identity, survivorship, and membership fixtures pass;
- no price, action accounting, session, or evaluator behavior has entered M1b.

### M1c is complete only when

- actions, revisions, outcomes, raw daily observations, currency, and session
  semantics reference validated M1b identities;
- normalized views bind exact raw/action inputs, policies, cutoffs, and roles;
- decision bundles resolve only validated cutoff-selection/materialized-view
  hashes, and outcome capabilities are separate;
- missingness and historical-tradability results are typed and hash-bound;
- calendar schedules are pinned artifacts rather than unversioned imports;
- adversarial future-action, adjustment, outcome, session, and missingness cases
  pass;
- no evaluator, portfolio accounting, broker, or trading capability exists.

## Original design authorization boundary

This section records what this design document alone did not authorize. M1b was
subsequently approved and implemented through its separate execution plan;
M1c and the other deferred capabilities still have no implementation authority.

This design does not authorize or include:

- an M1b or M1c implementation plan;
- production M1b/M1c code or schema migration;
- any real provider selection, ranking, adapter, API, download, or credential;
- CRSP, OpenFIGI, SEC, exchange, or index-provider integration;
- Arrow, Parquet, DuckDB, `exchange_calendars`, LEAN, Zipline, NautilusTrader,
  Qlib, RD-Agent, or another new dependency;
- a general automated entity-resolution engine or mutable master registry;
- a calendar engine or market-data store;
- an evaluator, backtester, feature engine, strategy, model, portfolio, cash
  ledger, tax, settlement, risk, execution, broker, order, or trading system;
- Robinhood, Alpaca, MCP, OAuth, agents, LLM calls, OpenAI SDK, LangGraph, cloud
  infrastructure, or real-time streaming;
- ETFs, ETPs, ADRs, foreign shares, REITs, preferreds, CEFs, SPACs, OTC,
  options, futures, crypto, shorting, or leverage.

## Open questions before implementation planning

1. What exact source-neutral classification vocabulary proves domestic
   operating-company common share without importing one provider's ontology?
2. Should the initial structural universe always target listing, or should M1b
   also implement a security-target fixture before M1c?
3. Which relationship types are essential in the first identity-correction
   implementation, and which should remain unrecognized/indeterminate?
4. Does `equivalent_to` need a canonical representative selection rule in M1b,
   or can current resolution return an equivalence set?
5. What exact temporal boundary defines listing admission for daily research:
   first regular-way trade, first official close, or another source event?
6. Should named index membership remain contract-only in M1b implementation, or
   should a synthetic index fixture be required even without a real provider?
7. Which termination reasons are closed enums versus preserved source-native
   values with a broader family?
8. Which M1c action variants are required before the first evaluator: only
   splits, cash distributions, mergers, and terminations, or also spinoffs and
   conversions?
9. Should decision split-normalization occur only after an action becomes
   effective, or at the first completed session after effectiveness for daily
   bars?
10. What precise OHLC trade-inclusion and official-close conventions must a
    future bar adapter prove?
11. What provider-coverage evidence is sufficient to classify an absent row as
    `provider_missing` rather than `unknown` in data evaluability?
12. What schedule producer and official-exchange comparison are sufficient for
    the initial NYSE/Nasdaq/NYSE American calendar artifact?
13. What future evaluator policy handles unknown terminal outcomes: rejection,
    sensitivity scenarios, or separately approved imputation?
14. What exact `DatasetManifestV2` and `AssertionTemporalContractV1` wire schema
    adds event temporality without duplicating V1 provenance fields?
15. Should cutoff materialized views contain copied selected records, a
    content-addressed index over base partitions, or both for small and large
    datasets?
16. What module/process boundary will enforce that decision code receives only
    the selected-record resolver capability and cannot resolve audit-side
    considered hashes or outcome manifests?

## References

- [CRSP permanent security and company identifier definitions](https://www.crsp.org/wp-content/uploads/2023/09/Sift_guide.pdf)
- [CRSP share/security classification codes](https://www.crsp.org/wp-content/uploads/ShareCode.html)
- [CRSP delisting return and missing-return definitions](https://www.crsp.org/crsp_pdf/crsp-us-stock-indexes-databases-data-descriptions-guide-crspaccess/)
- [Shumway, The Delisting Bias in CRSP Data](https://doi.org/10.1111/j.1540-6261.1997.tb03818.x)
- [Brown, Goetzmann, Ibbotson, and Ross, Survivorship Bias in Performance Studies](https://doi.org/10.1093/rfs/5.4.553)
- [Look-Ahead Benchmark Bias in Portfolio Performance Evaluation](https://arxiv.org/abs/0810.1922)
- [OpenFIGI allocation and share-class/listing rules](https://www.openfigi.com/docs/figi-allocation-rules.pdf)
- [SEC EDGAR CIK and ticker-association documentation](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
- [SEC ETF investor bulletin](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-24)
- [SEC ADR investor bulletin](https://www.sec.gov/files/adr-bulletin.pdf)
- [LEAN permanent security identifiers and historical ticker mapping](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/security-identifiers)
- [LEAN US-equity normalization semantics](https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/us-equity/requesting-data)
- [LEAN corporate-action behavior](https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/us-equity/corporate-actions)
- [S&P DJI equity index corporate-action policies](https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-equity-indices-policies-practices.pdf)
- [NYSE 2026 trading calendar](https://www.nyse.com/publicdocs/nyse/ICE_NYSE_2026_Yearly_Trading_Calendar.pdf)
- [`exchange_calendars` accuracy bounds](https://github.com/gerrymanoim/exchange_calendars/blob/master/exchange_calendars/exchange_calendar.py)
- [NautilusTrader instrument identity](https://nautilustrader.io/docs/latest/concepts/instruments/)
- [ADR 0005: External Tools Stay Behind Drift Contracts](../../adr/0005-external-tools-behind-drift-contracts.md)
