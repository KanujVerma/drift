# Drift M1 Point-in-Time Data Design

**Status:** Historical umbrella research. M1a is implemented and verified. The
original mixed M1b scope below was superseded by the separately approved M1b/M1c
design; current milestone state belongs in `docs/architecture/roadmap.md`.

The implementation rulings and completed M1a execution record are in
`../plans/2026-09-01-m1a-temporal-provenance.md`. This document remains the
historical research source. Current historical-equity architecture is in
`2026-09-02-m1b-m1c-historical-equity-semantics-design.md`; M1b implementation is
recorded in `../plans/2026-09-03-m1b-historical-security-identity-universes.md`.
The two-part milestone sequence below is retained as history, not current scope.

## Decision summary

Point-in-time provenance remains the correct next capability, but the roadmap's
single milestone should be split into two required submilestones:

- **M1a, provenance and temporal evidence:** immutable manifests, exact byte and
  schema identity, source and license provenance, channel-scoped availability
  evidence, revisions, storage-neutral partitions, validation decisions, and
  leakage fixtures for revised or late data.
- **M1b, historical market semantics:** stable security and listing identity,
  dated identifier mappings, point-in-time universe membership, corporate-action
  and delisting events, calendar references, and the adversarial fixtures those
  concepts require.

M1 is complete only when both submilestones are complete. M1a alone must not be
presented as sufficient for an equity backtest. No evaluator, ingestion platform,
broker, agent, feature system, or live connection belongs in either submilestone.

The recommended architecture is a content-addressed manifest plus explicit
source-specific record and event contracts. It rejects both a coarse
manifest-only claim and a generic temporal observation database.

## Problem and claim boundary

The future system needs to answer a narrow question for every value used by a
historical decision:

> Was this exact version available through the information channel declared by
> the experiment no later than its decision cutoff?

A dataset manifest is useful evidence about immutable bytes, declared semantics,
and lineage. It is not, by itself, proof that every record was historically
available. M1 must make false point-in-time claims difficult, preserve unknowns,
and produce machine-checkable reasons for eligibility or rejection.

M1 cannot prove that a vendor timestamp is truthful, reconstruct history that a
source did not retain, establish legal rights from a URL, prevent leakage in a
future label or train/test splitter, or make a backtest realistic. Those are
important limits, not reasons to omit the minimum temporal contract.

## Evidence classification

### Repository facts

- M0 is complete at `301dc9d`; the maintenance pass is complete at `4587745`.
- `DatasetReference` already pins a dataset ID and version, schema version,
  content hash, temporal coverage, three policy summaries, and an
  `ArtifactReference` for a manifest.
- `ExperimentSpecification` embeds one immutable `DatasetReference`, and
  `ExperimentRun` separately records the dataset hash.
- M0 canonical JSON, SHA-256 hashing, immutable audit-event envelopes, SQLite
  append-only storage, and replay are compatibility-sensitive persisted
  contracts.
- M0 and M1a use Python 3.14 and Pydantic 2. M1a adds no dependency and preserves
  M0 persisted model, serialization, event, and ledger contracts.

### Primary-source and academic evidence

- ALFRED exposes values as they existed in historical real-time periods rather
  than only today's revised series. The Philadelphia Fed's real-time-data work
  shows that latest-available data can make forecast evaluation look better than
  evaluation against data actually available at the time.
- Qlib's point-in-time format exists specifically because amended financial
  values can leak into earlier backtests when only the latest value is retained.
- SEC documentation distinguishes filing acceptance and dissemination behavior,
  and warns that it has no timestamp for the instant content first became
  available on sec.gov. Acceptance time is therefore evidence, not universal
  proof of public availability.
- CRSP distinguishes permanent company and security identifiers, retains
  delisting reasons and outcomes, and does not treat a ticker as permanent
  identity. Survivorship literature shows that truncating failed funds or
  omitting delisting outcomes biases results.
- Exchange and index documentation distinguishes announcement, effective, and
  implementation dates. Current constituents cannot safely reconstruct a
  historical investable universe.
- LEAN and Zipline demonstrate useful action, normalization, mapping, and session
  concepts, but their abstractions do not prove that an arbitrary input dataset
  is point-in-time safe.

### Engineering inference

- Two temporal axes are necessary: what a fact describes and when a particular
  version became usable. More named timestamps are justified only when they
  answer a distinct question.
- Immutable version chains and bounded availability evidence are sufficient for
  M1. A universal bitemporal database is not.
- Dataset-level policy is safe only for demonstrably uniform sources. Mixed
  releases, filings, revisions, event feeds, and vendor delays require record,
  field, or event evidence.
- Eligibility must be a versioned validation result, not a mutable quality label
  stored inside the manifest.

### Unresolved assumptions

- The first supported asset and universe scope has not been selected.
- No canonical vendor or license for identity, constituents, corporate actions,
  or delisting outcomes has been selected.
- The first supported data resolution is undecided. M0's microsecond datetime
  representation is adequate for daily and minute-level contracts, but not a
  general nanosecond market-data type.

No practitioner anecdote is needed to justify this design. Practitioner reports
may later help prioritize fixtures, but they cannot establish correctness.

## Researched failure modes

M1 is designed against these silent failures:

1. A March-quarter fundamental appears in an April decision even though it was
   released in May.
2. A restated value overwrites the value known before the restatement.
3. Today's index members are projected backward.
4. A delisted security disappears, or its unknown final outcome becomes zero or
   a fabricated total loss.
5. A reused ticker joins two unrelated securities.
6. A future split or dividend changes past model inputs through a fully adjusted
   series.
7. A public release is treated as vendor-visible before the vendor delivered it.
8. A date-only release is invented as midnight or market-open availability.
9. A missing bar becomes a zero return or a forward-filled future observation.
10. A current macro database replaces the vintage visible at decision time.
11. A session label is mistaken for an exchange timestamp across daylight
    saving, holidays, or early closes.
12. Bytes, schema, units, parser, calendar, mapping, or transform logic change
    while a familiar dataset name remains constant.

## Temporal terminology

M1 retains the minimum concepts below. Names such as `event_time`,
`observation_time`, `publication_time`, and `revision_time` are not universal
top-level fields because different sources use them inconsistently.

| Concept | Required? | Question answered | Location |
|---|---:|---|---|
| `valid_period` | Yes for facts | What real-world period or instant does this fact describe? | Record or field |
| `effective_at` | Only for state-changing events | When did this action or membership change take economic or legal effect? | Event |
| `availability` | Yes for historical eligibility | When could this exact version be used through a named information channel? | Record, field, or event |
| `acquired_at` | Yes for source import provenance | When did Drift or its import process receive the source snapshot? | Manifest/source acquisition |
| `ingested_at` | Yes when system visibility matters | When did a named Drift pipeline make the record usable? | Availability evidence for a `system` channel |
| `decision_at` | Later evaluator input | Which versions may a historical decision select? | Future decision/run record, not the fact |
| `execution_at` | Later execution input | When did an order or fill occur? | Future execution record, not M1 |

Source publication, vendor delivery, and local ingestion are alternative evidence
bases, not interchangeable timestamps. If a strategy declares a vendor channel,
public publication does not prove vendor availability. If it declares a system
channel, a delayed local ingest can make information unavailable even after it
was public.

## Availability evidence

Each availability claim is scoped to an information channel:

```text
AvailabilityChannelV1
  kind: public | vendor | system
  identifier: stable source, product, or pipeline identifier
  version: optional contract or pipeline version

AvailabilityEvidenceV1
  channel
  status: exact | bounded | rule_derived | unknown
  available_lower: optional UTC instant
  available_upper: optional UTC instant
  precision: source precision such as second, minute, date, or unknown
  source_timezone: optional IANA timezone required for local dates
  basis: source_dissemination | vendor_delivery | local_ingest | declared_rule
  evidence_reference: optional ArtifactReference
  rule_reference: optional immutable rule hash
```

Semantics:

- `exact` has equal lower and upper instants backed by source evidence.
- `bounded` has an evidence-backed interval. A date-only release is a window in
  the source timezone, never an invented midnight timestamp.
- `rule_derived` is produced by a versioned conservative rule from retained
  inputs. The rule and inputs must be hash-addressed. It is not silently upgraded
  to exact.
- `unknown` has no safe availability claim. Its bounds are absent.

For decision cutoff `D`, a version is definitely usable only if its matching
channel has `available_upper <= D`. It is definitely unavailable if
`available_lower > D`. If `D` falls inside a bounded window, or the evidence is
unknown, the answer is unknown and strict historical evaluation must fail
closed. A conservative rule such as next verified session open may convert a
date window into a later upper bound, but the raw evidence and rule identity
remain visible.

Dataset or partition defaults are allowed only when the source contract is
uniform, states the covered records, channel, timezone, cutoff, precision, and
correction handling, and a validator proves every record is covered. Intraday
data, mixed-release tables, fundamentals, event feeds, and heterogeneous joins
require record or event evidence. If fields in one row have different release
times, normalize them into separate facts when practical; use field-level
availability only when splitting would destroy source meaning.

## Revisions and vintages

M1 models an immutable fact version, not a mutable row:

```text
FactVersionV1
  fact_version_id: UUIDv7
  logical_fact_key: source + entity + concept + valid_period + unit + dimensions
  revision_kind: initial | revision | restatement | correction | withdrawal
  supersedes_fact_version_id: optional UUIDv7
  value: source-typed value or null with a reason
  availability: one or more channel-scoped evidence records
  source_artifact: ArtifactReference
  payload_hash: SHA-256
```

`available_from`, `valid_from`, and `valid_to` are not added as ambiguous generic
columns. The valid period belongs to the fact; channel availability belongs to
the version. A later version that revises Q1 retains Q1 as its valid period and
links to the prior version. A point-in-time query chooses the latest nonwithdrawn
version whose availability upper bound is no later than the decision cutoff for
the declared channel.

Version invariants:

- Versions are immutable and never overwritten.
- A successor has the same logical fact key and names its immediate predecessor.
- A predecessor has at most one successor within one source sequence unless an
  explicit competing-variant contract applies.
- Chains are acyclic, and source sequence or availability does not move backward
  without retained exception evidence.
- A reconstruction discovered later is not backdated to the date printed on the
  document.
- Withdrawal preserves the prior value and the withdrawal event; it does not
  erase either.

## Recommended architecture

### Layer 1: exact immutable bytes

Hash exact stored bytes with SHA-256. Parquet metadata, row counts, provider
checksums, and object-store version IDs are useful assertions but not substitutes
for the byte hash.

```text
raw bytes
  -> file SHA-256
  -> PartitionDescriptorV1
  -> canonical DatasetManifestV1 body
  -> manifest SHA-256
  -> existing DatasetReference
```

Physical cache paths and mutable object URLs do not define dataset identity. A
new M1 artifact reference should use a stable logical content URI such as
`drift+sha256://<digest>`. A separately configured resolver may map a digest to
zero, one, or many physical locations. M1 defines the resolver boundary and
tests a local fixture resolver; it does not build object storage.

### Layer 2: immutable manifest

```text
DatasetManifestV1
  manifest_schema_version: "1"
  hash_profile: "drift-canonical-json-sha256-v1"
  dataset_id: UUIDv7
  dataset_version: nonblank source or Drift version
  dataset_kind: typed dataset kind
  created_at: UTC instant
  source: SourceDescriptorV1
  acquisition: AcquisitionDescriptorV1
  license: LicenseDescriptorV1
  schema: SchemaDescriptorV1
  partitions: canonically ordered tuple[PartitionDescriptorV1, ...]
  temporal_contract: TemporalContractV1
  semantic_contracts: tuple[typed contract, ...]
  lineage: optional LineageDescriptorV1
```

The manifest hash is computed from canonical JSON of the body and is not stored
inside its own hash preimage. Overall temporal coverage is derived from partition
coverage and cross-checked against the existing `DatasetReference`; it is not a
second independent manifest field. Validation outcomes and mutable lifecycle
state are also excluded.

### Manifest field justification

| Field | Failure prevented and level rationale | Derivable or unknown? |
|---|---|---|
| schema and hash profile versions | Old readers silently changing meaning or hashes; manifest-wide | Never inferred |
| dataset ID and version | Same name referring to changed semantics; manifest-wide | Required, version may be source or Drift assigned |
| dataset kind | Applying the wrong semantic validators; manifest-wide | Required from a closed M1 enum |
| created time | Unordered manifest creation and audit ambiguity; manifest-wide | Required, not availability evidence |
| source descriptor | Unattributed or mutable-source data; manifest-wide | Required, credentials prohibited, source version may be unknown |
| acquisition descriptor | Inability to reconstruct which snapshot Drift received; manifest-wide | Required acquisition time and evidence reference |
| license descriptor | Accidental export, retention, or derived-use violation; manifest-wide | Unknown rights allowed but block operations that require them |
| schema descriptor | Type, unit, null, or semantic-role drift; manifest-wide with field entries | Required and hash-bound; actual bytes must match |
| partitions | File substitution, stale references, and ambiguous coverage; partition-level | Required, physical locations derived by a resolver |
| temporal contract | Treating period labels as availability or mixing channels; manifest-wide policy plus record bindings | Required; actual evidence remains record or event level |
| semantic contracts | Dataset-kind-specific identity, universe, action, price, and session interpretation; manifest-wide bindings | Required only when the dataset kind needs them |
| lineage | Unreproducible derived bytes; manifest-wide | Required for derived data, absent for raw source data |

### Schema and partition descriptors

`SchemaDescriptorV1` defines stable field IDs, names, logical types, nullability,
units or currency where relevant, and semantic roles such as valid-period start,
availability upper bound, listing ID, or raw close. Drift should define a small
storage-neutral logical-type vocabulary, not expose Pydantic or Arrow as the
scientific contract. An optional external-schema fingerprint can bind a Parquet
or Arrow schema.

`PartitionDescriptorV1` contains a partition ID, canonical logical partition
key, existing `ArtifactReference`, byte size, media type, format version, row
count, schema hash, logical coverage, and optional key range. Partitions are
sorted by logical key and content hash. Duplicate IDs, duplicate logical keys,
overlapping incompatible coverage, hash mismatches, or a parsed schema mismatch
fail validation. Row count and coverage are asserted values verified from bytes,
not identities on their own.

### Dataset-kind semantic contracts

The manifest does not contain one large list of mostly irrelevant policies. A
closed `dataset_kind` selects a discriminated union of typed contracts. Each
contract uses enum roles and field IDs from the manifest schema, not free-form
contract names:

- revised facts: logical-fact key, valid-period, availability, revision, value,
  unit, and null-reason bindings;
- market observations: listing ID, venue, UTC timestamp, session date, interval,
  bar timestamp convention, availability, price basis, values, and null or
  missingness reason bindings;
- universe events: universe ID/version, stable security or listing ID,
  action/interval, effective time, availability, and source-event bindings;
- identity mappings: internal ID, external ID type/value/scope, valid interval,
  availability, and source revision;
- corporate actions and listing terminations: action type, involved stable IDs,
  terms, effective dates, availability, source event, and revision bindings;
- session observations: venue, IANA timezone, local session date, verified UTC
  open/close, special status, source, availability, and calendar version.

`MarketObservationContractV1` also pins the manifest hashes for the identity,
universe or strategy-scope, corporate-action/termination, and calendar datasets
against which observations were validated. It requires a price basis, positive
typed interval, timestamp convention, source-record ID, raw OHLCV value roles,
missingness role, and availability roles. Other contract variants similarly
name their complete required bindings. Pydantic's
discriminator is the closed contract-kind enum; an arbitrary JSON policy map or
string such as `raw_price_basis` cannot satisfy the validator.

This lets source adapters preserve native fields while presenting the minimum
Drift semantics. M1 defines the contracts and validates synthetic fixtures; it
does not implement real adapters.

## Security identity and universe

Ticker, CUSIP, FIGI, and provider symbols are mappings, not canonical identity.
M1b defines opaque UUIDv7 IDs at the minimum levels needed to prevent false
joins:

```text
IssuerV1: issuer_id
SecurityV1: security_id, issuer_id, instrument type, share class, currency
ListingV1: listing_id, security_id, venue, trading currency, tradable interval
IdentifierMappingV1:
  mapping_id, scope, internal_id, identifier type/value, venue when applicable,
  valid_period, availability, source revision
```

One issuer may have multiple securities and listings. A ticker mapping is dated
and venue-scoped. Equal tickers do not imply continuity; a renamed listing may
retain its listing ID, while later ticker reuse points to a different security.
FIGI or a provider permanent ID may be retained as optional external evidence,
but Drift does not require or claim equivalence with a proprietary system.

Universe membership is an event/interval dataset:

```text
UniverseDefinitionV1
  universe_id, rule_version, provider, methodology reference, eligibility basis

UniverseMembershipV1
  membership_id
  universe_id, security_id or listing_id
  effective_period [from, to)
  availability
  action: add | remove | correction
  opaque provider source-event ID, source sequence, supersedes membership ID,
  and source revision
```

A candidate is eligible at `T` only if the membership effective period contains
`T`, the event is definitely available through the declared channel by `T`, the
listing is tradable, and any strategy-specific investability rule also passes.
Absence from a later snapshot is not evidence of an earlier removal. Current
constituents cannot be relabeled as historical membership.

Membership resolution requires the target `universe_id`, listing ID, listing
records, information channel, and cutoff. It first validates one acyclic,
single-successor source sequence per universe/listing pair and rejects unresolved
ties or conflicting active events. It then considers only the named universe and
a listing whose tradable interval contains the cutoff. Input order never breaks
a tie.

## Corporate actions, delistings, and prices

M1b preserves atomic source-provenanced facts and uncertainty:

```text
CorporateActionEventV1
  event_id, logical action key, security/listing IDs, action type
  announced evidence when present, effective/ex/record/payable instants as relevant
  ratio or cash terms when relevant, child/successor IDs when relevant
  source-native terms artifact, availability, source sequence, revision kind,
  supersedes event ID

ListingTerminationEventV1
  event_id, logical termination key, listing_id, last trade/effective instants,
  availability
  status and reason family, source reason, successor IDs
  consideration, final-value evidence, delisting return evidence, source sequence,
  revision kind, supersedes event ID
```

Action and termination versions use the same immutable-chain invariants as fact
versions. A point-in-time action lookup validates the chain, filters by the named
channel and cutoff, and selects the sole active version. A vendor correction
cannot coexist ambiguously with the original or retroactively change action
terms before its own availability.

Missing terminal value remains unknown. It is never automatically zero or minus
100 percent. Mergers, exchange moves, acquisitions, liquidations, suspensions,
and exchange delistings are not collapsed into one outcome.

Raw OHLCV is the canonical observation basis. Every price dataset declares
`price_basis` as `raw`, `split_adjusted`, `dividend_adjusted`,
`total_return_adjusted`, or `unknown`. Provider-adjusted data is retained only as
a derived dataset with its action cutoff, source revision, lineage, and explicit
basis. Unknown or fully back-adjusted input cannot support promotion-quality
features.

`MarketObservationV1` binds each parsed record to a listing, venue, valid
interval, channel-scoped availability, local session date, immutable calendar
schedule hash, a positive typed bar interval and timestamp convention, price
basis, source record ID, numeric raw OHLCV values, and an explicit missingness
state. Historical eligibility requires a
versioned market-record validator to inspect every observation and all referenced
identity, membership, action, termination, and session records for the requested
channel and validated coverage. Manifest declarations alone cannot promote a
market dataset.

A future backtester, not M1, computes quantity changes, dividend cash flows,
reinvestment, successor conversions, cash in lieu, taxes, settlement, total
returns, and unresolved-delisting policy.

## Calendars and time zones

M1 does not calculate exchange calendars. It records enough meaning for a later
calendar adapter:

- venue or MIC;
- IANA timezone;
- session kind;
- local session date;
- verified UTC open and close, including early closes or overnight boundaries;
- source, version, content hash, known coverage, and availability;
- bar interval and whether the timestamp means interval start or end.

A calendar reference must resolve to an immutable artifact or pinned adapter
version and generated schedule hash. Unknown sessions stay unknown. Nominal
weekly hours may not fabricate holidays, early closes, unscheduled closures, or
daylight-saving behavior. `exchange_calendars` is a viable later adapter, but its
own documentation disclaims universal accuracy outside some maintained bounds,
so Drift must pin and validate the actual schedule used.

Every `SessionObservationV1` repeats the calendar ID, calendar version, and
schedule hash it belongs to, plus its own availability evidence. Every market
observation repeats the schedule hash and timestamp convention it used. The
validator rejects a session or bar that cannot be joined exactly to the pinned
calendar reference.

## Provenance and lineage

For raw data, source provenance records provider/publisher, product, source
identifier/version, acquired time, evidence artifact, and the exact raw byte
hashes. Credentials, signed URLs, personal data, and mutable `latest` endpoints
must not enter a manifest or audit payload.

For a derived dataset, `LineageDescriptorV1` records:

- input manifest hashes;
- transformation specification version and canonical configuration;
- implementation/code artifact hash;
- execution-environment hash;
- input-selection rule;
- output schema hash;
- execution time;
- determinism claim: `deterministic`, `unknown`, or `not_deterministic`.

This proves which immutable inputs and transformation identity produced which
immutable outputs. M1 does not build a transformation runner, feature DAG,
learned preprocessing system, or cache. Later outputs, including features and
model inputs, can reuse the same manifest and lineage contract.

## Licensing contract

M1 records operational facts, not legal conclusions:

```text
LicenseDescriptorV1
  provider legal name
  agreement or license identifier and optional version
  canonical terms reference
  acquired_at
  allowed_purpose: research | commercial | other | unknown
  redistribution: allowed | restricted | unknown
  derived_artifact_use: allowed | restricted | unknown
  retention restriction and optional access expiration
  attribution requirement
  optional rights-evidence ArtifactReference
```

Unknown rights do not block retaining a lawful internal provenance record, but
they fail closed for export, redistribution, or promotion flows that require
confirmed rights. M1 does not parse license prose or decide what the law allows.

## Validation and eligibility

Validation is separate immutable evidence:

```text
DatasetValidationDecisionV1
  decision_id
  manifest_hash
  validator_version and implementation hash
  checked_at
  validation_scope: manifest_only | records_and_events
  result: pass | fail
  usage_eligibility: exploratory_only | historical_evaluation_eligible
  declared_use
  validated_coverage
  checked_channels and dataset kinds
  findings: typed codes with artifact references
```

There is no numeric confidence score and no mutable `validated` flag in a
manifest. A later strategy may contribute promotion evidence only when every
input manifest has a passing, non-superseded decision that grants
`historical_evaluation_eligible` for the declared information channel and use.
Exploratory-only inputs may support diagnostics but their outputs must remain
ineligible for promotion. Final strategy promotion remains outside M1.

A manifest-only decision can verify structure, hashes, lineage references, and
declared contracts, but is always `exploratory_only`. Historical-evaluation
eligibility requires `records_and_events` scope from a versioned validator that
actually inspected the relevant bytes, parsed schema, required record or event
fields, temporal evidence, identity mappings, and dataset-kind invariants. M1
implements this scope only for its small synthetic formats and fixtures. A real
Parquet, vendor, or source adapter must later earn the same scope rather than
inheriting it from a fixture validator.

The eligibility artifact exposed to a future evaluator is not a bare M0
`DatasetReference`. `DatasetEligibilityBindingV1` contains that unchanged
reference plus the validation-decision ID and hash, declared use, channel, and
validated coverage. A construction function emits the binding only for a
passing, `records_and_events`, `historical_evaluation_eligible` decision whose
manifest, use, channel, and coverage match exactly. M0 experiment records remain
valid provenance, but cannot contribute future promotion evidence without this
separate binding and its audit event.

Market dependencies cross the same boundary. Each of the four pinned identity,
universe, action/termination, and calendar inputs is supplied as a
`BoundDatasetInputV1`: manifest, exact verified bytes, scoped validation
decision, and matching `DatasetEligibilityBindingV1`. The market validator
verifies all hashes, uses, channels, and coverage, then reparses the dependency
records from those exact bytes. It never accepts in-memory dependency records
beside an asserted manifest hash. Arbitrary favorable mappings or action data
therefore cannot borrow another dataset's eligibility decision.

An overall dataset is not called `verified PIT` merely because some records are
exact. Eligibility is conditional on dataset kind, channel, temporal coverage,
validator version, and declared use. A bounded observation can pass only when
its upper bound is before the decision cutoff. `rule_derived` evidence may pass
only under an explicitly allowed conservative rule. Unknown evidence never
passes strict historical evaluation.

### High-value fail-closed validators

1. Reject unsupported manifest, schema, hash-profile, or semantic-contract
   versions and all unknown fields.
2. Reject missing, malformed, duplicate, noncanonical, or mismatched manifest,
   partition, schema, code, environment, input, and artifact hashes.
3. Verify exact file bytes before trusting parsed metadata, row counts, schema,
   coverage, or statistics. The M1 synthetic reader returns the verified bytes
   and all parsing consumes that immutable byte value, never the pathname after
   hashing. A future large-file adapter must hash and parse the same open file
   descriptor with identity checks or use an immutable content-addressed object.
4. Reject duplicate partition IDs or logical keys, incompatible overlap, stale or
   unavailable artifact references, and broken lineage.
5. Reject missing required semantic bindings, type/unit mismatches, invented
   precision, invalid UTC or IANA timezone data, and impossible temporal bounds.
6. Reject `unknown` availability presented with bounds, `exact` availability
   without one instant, and bounded evidence with a reversed window.
7. Reject a strict historical selection when availability is unknown, the upper
   bound exceeds the cutoff, or the evidence channel differs from the run.
8. Reject revision cycles, branching without an explicit variant contract,
   predecessor key mismatch, backward source sequence, and overlapping active
   versions for the same key and channel.
9. Reject ticker-only joins, overlapping unacknowledged identifier mappings,
   membership outside a listing period, and current-snapshot backfills.
10. Reject action identity mismatches, impossible action terms, future-known
    adjustments, unknown price basis, and raw/adjusted mixing.
11. Reject missing-bar coercion, forward fills across unavailable intervals, and
    absence interpreted as zero, market closure, or delisting.
12. Reject an unresolved or unversioned calendar reference and bar timestamps
    inconsistent with the declared session convention.
13. Reject derived datasets without complete input manifest hashes, transform
    identity, output schema, and determinism claim.
14. Reject new use when required source, rights, calendar, transform, or input
    evidence is unavailable. Historical replay may report unavailable artifacts
    without rewriting history.

Dataset creation and cross-object construction services enforce new M1 rules.
They do not mutate M0 models or retroactively reinterpret old events.

## Adversarial fixture suite

The implementation must use small, readable, synthetic fixtures with exact
expected selections and typed failures:

1. Initial EPS 1.20 and later restatement 0.90; the earlier cutoff selects 1.20.
2. Q1 results released May 5; an April cutoff sees no Q1 fact.
3. Date-only filing with a bounded local-day window; an intraday cutoff remains
   unknown until a conservative rule's upper bound.
4. SEC-public fact delivered later by a vendor; a vendor-channel run waits for
   delivery while a public-channel run follows its own evidence.
5. Late local ingestion; a system-channel run waits, while public evidence is
   unchanged.
6. Initial GDP and later macro revision; each cutoff selects the correct ALFRED-
   style vintage.
7. Vendor correction and withdrawal; both the superseded value and event remain.
8. Index addition effective June 1; January membership is false even when the
   current snapshot includes the stock.
9. Delisted security with explicit cash acquisition outcome; historical universe
   retains it and does not create a loss.
10. Delisted security with unknown terminal value; no zero or minus-100-percent
    coercion is allowed.
11. Ticker reuse across unrelated securities, plus a rename for one continuing
    listing; only the rename preserves identity.
12. One issuer with two share classes where only one is a constituent.
13. Split announced and effective after feature time; raw features do not change,
    and future action knowledge cannot enter a point-in-time transform.
14. Cash dividend fixture separating raw price change from economic return.
15. Spinoff with a child that begins trading later; no historical child price is
    invented.
16. Missing bar, halt, zero volume, holiday, and delisting as distinct states;
    none may be inferred from another.
17. Early close, daylight-saving transition, and overnight session labels with
    explicit UTC boundaries.
18. Malicious filename/path traversal, duplicate logical partition, changed byte,
    schema drift, huge declared metadata, and unavailable lineage artifact.
19. A fully adjusted vendor history whose action cutoff is after the decision;
    it remains exploratory-only.
20. Replay fixture persisting selected fact-version IDs and hashes; the same
    decision reconstructs identical inputs.

## Hostile data boundary

M1 validation treats manifests, filenames, source text, Parquet metadata, and
future agent-consumed text as untrusted:

- strict versioned schemas reject unknown fields and bound string, collection,
  nesting, column, metadata, and declared-size limits;
- resolvers allowlist schemes and roots, reject credentials, absolute or parent
  traversal where disallowed, symlink escape, device files, and FIFOs;
- validators verify byte hashes before parsing and impose compressed and
  decompressed size, ratio, row-group, and nesting limits;
- synthetic readers parse the returned verified byte value, so a same-path or
  same-size replacement after hashing cannot alter the inspected data;
- no Pickle, object deserialization, embedded code, or metadata instruction is
  executed;
- source text is data, never an instruction to an agent;
- malformed columnar data and archive bombs belong in a later sandboxed ingestion
  adapter, but M1 defines the resource-limit and fail-closed interface now.

M1 implements only safe local synthetic-fixture validation. It does not build a
general parser sandbox.

## Relationship to M0 and backward compatibility

M0 persisted models remain unchanged.

- `DatasetReference` stays the compact experiment-facing bridge. For new M1
  objects, its `content_hash` equals the manifest hash, its
  `manifest_reference.kind` is `dataset`, and the two hashes match.
- `DatasetEligibilityBindingV1` is a new, separately hashed permission artifact
  that binds a `DatasetReference` to one validation decision, declared use,
  channel, and coverage. A raw `DatasetReference` remains provenance, not proof
  of historical-evaluation eligibility.
- `ArtifactReference` points to manifest, partition, source, license, calendar,
  transform, and validation evidence. New M1 content should use stable logical
  content URIs; physical resolver state remains outside semantic identity.
- `ExperimentSpecification` stays unchanged and pins an exact manifest through
  its nested dataset reference. A future evaluator must also receive and audit a
  matching `DatasetEligibilityBindingV1`; direct construction of an M0
  specification never grants eligibility.
- `ExperimentRun` stays unchanged. A future construction rule requires its
  dataset hash to match the specification's manifest hash.
- Canonical JSON and SHA-256 are reused under a named M1 hash profile.
- Existing audit-event envelopes and ledger storage are reused with new event
  types such as `dataset.manifest.recorded`, `dataset.validation.completed`, and
  `dataset.superseded`. Event payloads use new explicit schema versions.

Adding even optional fields to an M0 frozen model can change serialization and
hashes. M1 therefore introduces parallel versioned types and construction rules,
not fields on existing types. Old events replay with their original schemas and
hashes. If a historical M0 dataset hash does not already equal a new manifest
hash, create a new dataset version for future experiments rather than rewriting
history. A future `DatasetReferenceV2` would require a separate ADR, adapter, and
event schema.

## Reuse versus build

Drift owns the scientific claim. It may later reuse commodity mechanics behind
the contracts in ADR 0005.

| Candidate | Potential reuse | Why it does not replace M1 | Current fit |
|---|---|---|---|
| Apache Arrow and Parquet | Columnar schema, metadata, and storage | Writer-controlled metadata does not prove origin, exact bytes, or PIT semantics | Strong later storage-format candidate; Apache-2.0 ecosystem; no M1 dependency |
| DuckDB | Parquet inspection and validation queries | Not a provenance, availability, or eligibility system | Strong later local query adapter; MIT; no M1 dependency |
| `exchange_calendars` | Session schedules, holidays, early closes, timezone handling | Calendar identity, version, schedule hash, coverage, and source still belong to Drift | Viable later adapter; Apache-2.0; current metadata advertises Python 3.14, but accuracy bounds require validation |
| Qlib | PIT concepts and later data/research evaluation | Its handler and storage assumptions cannot be Drift's scientific guarantee | Conceptual reference or isolated later adapter; no core-runtime commitment |
| Zipline Reloaded | Bundle, mapping, factor, and calendar concepts | Bundle ingestion and backtest conventions are framework-specific | Reference or later evaluator comparison, not an M1 substrate |
| LEAN | Mapping, factor files, action models, normalization, simulation models | Large C# engine and adjusted modes do not prove source availability | Later simulation comparison, not M1 |
| NautilusTrader | Catalog and typed market/instrument models | Opinionated event/runtime system and LGPL boundary do not replace Drift evidence | Later isolated adapter candidate |
| DVC or lakeFS | Physical content caching, remote/object versioning | Storage versioning does not define PIT, identity, license, or eligibility semantics | Optional future storage plumbing |
| OpenTrade | Approval and monitoring UX reference | It can place real orders, uses an incompatible trust boundary, and its license/runtime do not solve provenance | Observe only, never part of M1 |

Any adoption requires a fresh release, license, Python, security, reproducibility,
and boundary review. M1 adds none of these dependencies.

## Architecture alternatives

| Alternative | Leakage protection | Complexity | Storage coupling | False-confidence risk | Migration/testability | Decision |
|---|---|---|---|---|---|---|
| A. Coarse manifest with dataset-level `next_day` policy | Low for mixed or revised data | Low | Low | Very high | Easy, but tests only metadata | Reject |
| B. Manifest plus explicit source-specific record/event contracts and validation decisions | High for claims it supports | Moderate and bounded | Low | Low if unknowns fail closed | High testability, additive to M0 | Recommend |
| C. Generic bitemporal fact store for every observation | Potentially high | High before real source needs exist | High | Medium because generic fields invite false mappings | Large migration and semantic burden | Reject for M1 |
| D. Adopt Qlib, Zipline, LEAN, or a data-versioning platform as the core | Varies and is not independently proven | High integration and lock-in | High | High if framework behavior is mistaken for evidence | Runtime/license migration risk | Reject |

Alternative B is intentionally a contract layer. It is strong enough to detect
the target leakage classes, storage-neutral, compatible with M0, and small enough
to falsify with synthetic fixtures before acquiring real market data.

## Final adversarial review

| Attempted cheat | Required defense | Residual limitation |
|---|---|---|
| Put May earnings in an April partition | Record availability, not partition date, controls selection | A lying source timestamp cannot be proven false without external evidence |
| Overwrite original EPS with restatement | Immutable version chain and cutoff selection | Missing source vintages remain missing |
| Use current index constituents | Point-in-time membership events and listing intervals | A vendor may not license or retain historical membership |
| Drop failed securities | Historical membership and explicit termination outcomes | Unknown terminal value remains unresolved and blocks strict claims |
| Join on ticker | Validators require stable security/listing IDs and dated mappings | Cross-provider entity resolution remains source-specific |
| Back-adjust with a later split | Raw price basis and action availability cutoff | A future backtester must still implement correct accounting |
| Use post-event news with an old article date | Channel-scoped availability evidence, not document date | First-public time may be unknowable |
| Forward-fill through a missing period | Explicit missingness and availability checks | Strategy-specific permissible imputation belongs later |
| Call a manifest `verified PIT` | Separate scoped validation decision and usage gate | Validator defects remain possible, hence version/hash retention |
| Swap a physical file at the same path | Exact byte hash and content-addressed logical reference | Resolver security and object durability remain operational concerns |

The review changed the design in four ways: eligibility moved out of the
manifest; information channels became explicit; date-only evidence became a
bounded interval; and M1 was split so a provenance-only implementation cannot
be mistaken for equity-backtest readiness.

## Non-goals

M1 does not include real vendor integration, market-data downloads, broker or
Robinhood connectivity, Alpaca, orders, credentials, agents, OpenAI SDK,
LangGraph, Qlib integration, RD-Agent, a backtester, portfolio construction,
risk, execution, model training, feature engineering, vector storage,
dashboards, cloud deployment, streaming, a calendar library, entity-resolution
automation, total-return calculation, tax or settlement logic, a temporal
database, or an executable transformation pipeline.

## Implementation acceptance boundary

An approved M1 implementation must:

- add only versioned contracts, local validators, immutable validation evidence,
  and synthetic fixtures;
- keep M0 persisted models and hashes unchanged;
- remain offline and broker-neutral;
- introduce no dependency or Python-runtime change without a separate decision;
- pass the complete M0 gate plus M1 adversarial tests and compatibility fixtures;
- leave M1a outputs ineligible for equity historical evaluation until M1b is
  complete for the relevant dataset kinds.

## Open questions before implementation

1. Is the first supported scope US exchange-listed common equities only, or must
   M1b also cover ETFs, ADRs, OTC securities, options, or global listings?
2. Which first source or synthetic source contract will anchor identity,
   constituents, actions, and delisting semantics?
3. Is minute-level UTC precision sufficient for the first real dataset, allowing
   the M0 microsecond type, or must raw record timestamps support nanoseconds?
4. Which information channel should the first evaluator simulate: public source,
   a named vendor product, or a retained Drift system feed?
5. Which conservative rules, if any, may convert bounded date-only evidence into
   historical-evaluation eligibility?
6. Must provider-adjusted histories be prohibited from all model features, or
   permitted for exploratory display only?
7. Which universe families come first: named index membership, a provider screen,
   or a strategy-defined investability rule?
8. How should a future evaluator handle unknown delisting value: reject the run,
   retain missing valuation, or use a separately approved sensitivity policy?
9. What internal use, retention, export, and derived-artifact actions should each
   licensing enum gate?
10. What maximum file, metadata, column, row-group, and decompression limits are
    appropriate for the first real format adapter?

## Requested outcome traceability

| Final report item | Canonical design evidence | Planned verification |
|---:|---|---|
| 1. M1 recommendation | Decision summary | M1a and M1b review gates |
| 2. Supporting evidence | Evidence classification and references | Documentation source audit |
| 3. Strongest objections | Problem and claim boundary | Final adversarial review |
| 4. Leakage classes | Researched failure modes | M1a and M1b fixture suites |
| 5. Temporal terms | Temporal terminology | Temporal unit tests |
| 6. Manifest model | Recommended architecture | Manifest model and hash tests |
| 7. Record availability | Availability evidence | Cutoff and channel tests |
| 8. Revisions/vintages | Revisions and vintages | Fact and action chain tests |
| 9. Identity/universe | Security identity and universe | Ticker, listing, and membership tests |
| 10. Corporate actions | Corporate actions, delistings, and prices | Action, termination, and raw-price tests |
| 11. Unknown handling | Availability evidence | Unknown and bounded fixtures |
| 12. Validators | Validation and eligibility | Unit and integration validation tests |
| 13. Adversarial fixtures | Adversarial fixture suite | Parameterized fixture matrices |
| 14. M0 relationship | Relationship to M0 | Pinned serialization and replay tests |
| 15. Backward compatibility | Relationship to M0 | No-diff and historical-hash gates |
| 16. Alternatives | Architecture alternatives | Design review |
| 17. Recommendation rationale | Recommended architecture | M1a and M1b acceptance gates |
| 18. Drift-owned parts | Reuse versus build | Dependency and boundary scan |
| 19. Later reuse | Reuse versus build | Fresh adoption review required |
| 20. Non-goals | Non-goals | Forbidden-capability scan |
| 21. Design path | This document | Repository path check |
| 22. Plan path | Linked implementation plan | Repository path check |
| 23. Verification | Implementation acceptance boundary | Complete repository gate |
| 24. Commit | Design-task Checkpoint | Git verification |
| 25. Git status | Design-task Checkpoint | Clean-status verification |
| 26. Open questions | Open questions before implementation | Implementation approval review |

## References

- [Croushore and Stark, A Real-Time Data Set for Macroeconomists](https://www.philadelphiafed.org/the-economy/macroeconomics/forecasting-with-a-real-time-data-set-for-macroeconomists)
- [FRED real-time periods](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html)
- [ALFRED download semantics](https://alfred.stlouisfed.org/help/downloaddata)
- [Qlib point-in-time database](https://qlib.readthedocs.io/en/stable/advanced/PIT.html)
- [SEC EDGAR timestamp FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions)
- [SEC EDGAR API update behavior](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [WRDS Compustat restatement and snapshot concepts](https://wrds-www.wharton.upenn.edu/documents/2180/WRDS_SP_Webinar_Feb_002.pdf)
- [Brown, Goetzmann, Ibbotson, and Ross, Survivorship Bias in Performance Studies](https://doi.org/10.1093/rfs/5.4.553)
- [Shumway, The Delisting Bias in CRSP Data](https://doi.org/10.1111/j.1540-6261.1997.tb03818.x)
- [CRSP permanent identifier concepts](https://www.crsp.org/wp-content/uploads/guides/CRSPSift_User_Guide.pdf)
- [OpenFIGI overview and identifier levels](https://www.openfigi.com/about/overview)
- [MSCI index review archive](https://app2.msci.com/eqb/gimi/stdindex/index_review.html)
- [NYSE trading hours and calendars](https://www.nyse.com/trade/hours-calendars)
- [Zipline session and calendar semantics](https://zipline.ml4trading.io/trading-calendars.html)
- [LEAN equity data and corporate actions](https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/us-equity/requesting-data)
- [Apache Parquet metadata specification](https://parquet.apache.org/docs/file-format/metadata/)
- [Apache Arrow columnar format and custom metadata](https://arrow.apache.org/docs/format/Columnar.html)
- [DuckDB Parquet metadata functions](https://duckdb.org/docs/stable/data/parquet/metadata)
- [`exchange_calendars` package metadata](https://github.com/gerrymanoim/exchange_calendars/blob/master/pyproject.toml)
- [ADR 0005: External Tools Stay Behind Drift Contracts](../../adr/0005-external-tools-behind-drift-contracts.md)
