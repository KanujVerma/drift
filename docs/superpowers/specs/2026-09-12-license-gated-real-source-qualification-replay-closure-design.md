# Drift M1e: License-Gated Real-Source Qualification and Replay Closure Pilot

Date: 2026-09-12. Status: independently reviewed architecture design. Implementation is not
authorized by this document.

Canonical baseline: `af75cce0f763de025f8ae3516577a9d0a1acead9`.
M0 through M1d are complete. This specification defines the smallest empirical
milestone before evaluator or backtester implementation.

## 1. Decision

The next milestone is:

> **M1e: License-Gated Real-Source Qualification and Replay Closure Pilot**

M1e will test whether one precisely declared real-source collection can satisfy
selected M1b, M1c, and M1d contracts, whether Drift may legally retain the
required evidence, and whether the accepted interpretation can be replayed
offline from exact source and environment artifacts.

M1e is a qualification pilot, not provider-wide acceptance and not a market-data
platform. It may complete with a documented `FAIL` or `UNKNOWN` result. A
negative result that preserves the evidence and identifies the blocking layer is
scientifically useful.

M1e does not implement an evaluator, backtester, portfolio, returns, strategy,
broker, order flow, production credentials, or live trading. It does not acquire
bulk data. It does not normalize provider ambiguity into convenient defaults.

## 2. Sequencing decision

Four sequences were considered.

| Sequence | Strongest case | Decisive weakness | Decision |
|---|---|---|---|
| A. Evaluator first, qualify later | Synthetic accounting and role separation can be developed independently | Evaluator policies would be chosen before real omission, revision, licensing, and session semantics are observed | Reject as the next step |
| B. Qualify one real source, then evaluator | Exposes real coverage and rights limits before accounting code exists | “One source” is too coarse and can turn into vendor-centric architecture or documentation-only acceptance | Modify |
| C. Thin evaluator and qualification together | Provides an immediate consumer and exposes interface gaps | Changes two uncertain systems together; a return can conceal source fallback or leakage | Reject |
| D. Capability-scoped qualification plus offline replay; evaluator contract review only | Falsifies source, rights, snapshot, and replay assumptions through existing M1a-M1d contracts | Requires disciplined sample and packaging limits | **Accept** |

> **Sequencing Update (2026-09-19, [ADR 0012](../../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md))**:
> The original sequencing decision (Sequence D above) was architecturally correct
> under the uncertainty available at design time. Subsequent empirical provider
> screening across algoseek, Databento free tier, and Alpaca Basic successfully exposed
> the real-world omission, revision, licensing, and session failure modes the sequence
> was intended to discover. However, because no zero-cost provider satisfies all
> promotion-grade M1e hard gates, paid promotion-grade qualification (Task 8) is
> deferred until exploratory research produces candidates that economically justify
> paying for commercial reference validation. Under ADR 0012, an exploratory M2
> evaluator implementation is authorized before positive M1e completion, using free
> development data (Alpaca Basic) with explicit limitations. Positive M1e qualification
> remains strictly required for promotion-grade evaluation.

The current hypothesis B was directionally correct but insufficiently bounded.
The unit of qualification is not a vendor. It is:

```text
provider legal entity
+ product/dataset and publisher
+ licensed entity/users/purpose
+ declared date/universe/field scope
+ exact delivered snapshot
+ provider methodology/version
+ Drift qualification profile/version
+ accepted consumer purpose
```

No result may be generalized beyond that tuple.

## 3. Why qualification and replay closure stay together

Provider semantics, retention rights, snapshot identity, and environment replay
are one falsification boundary. Data that cannot be retained or replayed cannot
support durable promotion-quality research. Conversely, an environment archive
without legally retained source bytes reproduces no scientific input.

This does not justify generalized acquisition infrastructure. The pilot needs:

1. one rights decision for one declared use;
2. one bounded real-source corpus;
3. one qualification report with independent per-layer outcomes;
4. one immutable snapshot inventory;
5. one platform-specific offline environment closure;
6. one clean replay of pre-evaluator M1b-M1d hashes.

Fleet-scale ingestion, multi-provider orchestration, automated entitlement
enforcement, a general archival service, and production deployment remain later
work.

## 4. Repository reuse and ownership

M1e extends existing provenance instead of creating a parallel system.

- `DatasetManifestV2` remains the dataset manifest.
- `AcquisitionDescriptorV1.evidence_reference` points to an exact acquisition
  receipt artifact.
- `LicenseDescriptorV1.terms_evidence_reference` points to exact contract and
  rights-assessment evidence. The descriptor continues to record provenance and
  does not itself declare legal permission.
- `ArtifactReference` remains the content-addressed reference.
- Existing validation decisions, bundles, M1a availability evidence, M1b
  resolutions, M1c outcomes, and M1d views remain authoritative.
- Existing experiment metadata may later refer to an environment closure, but
  M1e does not execute strategy experiments.

Physical paths, credential-bearing URLs, API keys, cookies, signed query
parameters, and secret headers never enter canonical identities.

## 5. M1e outcome model

Qualification is multidimensional. There is no weighted score and no single
vendor grade.

### 5.1 Status values

| Status | Meaning |
|---|---|
| `PASS` | All declared requirements for this exact dimension, scope, and consumer purpose are evidenced |
| `PARTIAL` | Some claims pass, but at least one declared subcapability remains unsupported; downstream use is limited accordingly |
| `FAIL` | Evidence contradicts a required property or the rights gate denies the intended use |
| `UNKNOWN` | Available evidence cannot decide the requirement; no convenient default is permitted |

`PARTIAL` and `UNKNOWN` are not weaker forms of `PASS`. Any critical
dimension required by a consumer must be `PASS`.

### 5.2 Independent dimensions

Every qualification report contains separate results for:

1. security and listing identity;
2. universe and lifecycle;
3. corporate-action terms;
4. occurred effects;
5. settlements and terminal outcomes;
6. source observations and field methodologies;
7. scheduled and realized sessions;
8. corrections and point-in-time revisions;
9. coverage and omission semantics;
10. licensing and retention;
11. acquisition completeness and snapshot consistency;
12. offline replay closure.

Each dimension binds its exact evidence references, tested cases, limitations,
admitted purposes, and adjudication policy version.

### 5.3 Layer gates

| Layer | A `PASS` requires, within the frozen scope | Fail-closed boundary |
|---|---|---|
| M1b identity and universes | Permanent security and listing identity; historical ticker/name/exchange and primary-listing mappings; delisted-security retention; required classifications; universe definition and point-in-time membership; explicit revision/availability semantics | Current symbols, survivor-only lists, inferred venue history, or current-only snapshots cannot satisfy historical identity or membership |
| M1c actions and outcomes | Source terms plus distinct announcement, effective/occurrence, entitlement, settlement/payment, correction, and availability evidence for every supported split, distribution, merger, conversion, spinoff, liquidation, and terminal/continuing claim path | Terms are not occurrence; pay dates are not settlement proof; missing or unsupported consideration stays partial/unknown and cannot become zero |
| M1d observations and sessions | Proven source basis; exact OHLC/volume population, interval, auction, sale-condition, session, correction, omission, zero/null, and adjustment semantics; independently pinned scheduled and realized sessions | A field named daily or unadjusted is insufficient; omitted rows, zero volume, final corrected history, or current calendars cannot silently establish historical facts |
| Cross-layer revision and coverage | Finite-cutoff availability, exact source vintages, expected populations, omissions, and correction lineage compose without current-universe or latest-revision fallback | Any unresolved join, incomplete expected population, conflicting correction, or unavailable vintage limits the affected purpose to `PARTIAL`, `FAIL`, or `UNKNOWN` |
| Rights, acquisition, and replay | Exact applicable rights, closed-world acquisition reconciliation, retained native/grading bytes, complete replay inputs, and a demonstrated offline reproduction | Technical access, a local hash without origin, a license hash without current authorization, or expected output hashes without input payloads never passes |

## 6. Provisional provider qualification matrix

These are documentation-screen signals, not qualification results or legal
adjudications. The status words identify visible support and gaps only. Every
candidate remains `UNKNOWN` for actual use until the qualification profile,
executed product-specific terms, and measured sample are frozen.

| Candidate | M1b | M1c | M1d | Revisions/coverage | Retention/replay | Provisional disposition |
|---|---|---|---|---|---|---|
| CRSP 1925 US Stock | `PARTIAL`, strong PERMNO/PERMCO, names, exchange and delisting history | `PARTIAL`, strong distributions and delisting/outcome fields | `PARTIAL`, daily trade fields but public documents do not close exact auction, population, omission, or publication semantics | `PARTIAL`, named releases and correction notes, but current releases can rewrite deep history | Public product documents do not establish the required post-subscription raw and derived survival rights | Research benchmark; require executed terms before a rights result |
| Databento Security Master, Corporate Actions, and U.S. equities products | `PARTIAL`, PIT listing/security/issuer records since 2005-01-01 | `PARTIAL`, broad PIT event taxonomy only from 2018-05-01 | `PARTIAL`, excellent granular schemas; daily OHLCV can be UTC-day or NLS+ summary rather than Drift regular session | `PARTIAL`, PIT records and batch hashes are strong; old corrected vintages are not guaranteed retrievable | `UNKNOWN`, exact product agreement controls archival, cloud, derived, fixture, and post-account rights | First contract inquiry and likely pilot frontrunner, not accepted |
| Massive, formerly Polygon.io | `PARTIAL`, dated ticker lookup and delisted flag; ticker-event API is experimental | `PARTIAL/UNKNOWN`, splits and dividends are documented but full merger, spinoff, bankruptcy, settlement, and residual-outcome authority are not | `PARTIAL`, unadjusted flat files and sale-condition mappings; day files span premarket through after-hours and correction vintage is unclear | `UNKNOWN`, historical files can be regenerated after methodology changes | Public standard terms appear incompatible with durable replay; an exact order form and declared use are not yet adjudicated | Do not proceed under the public screen; reopen only after exact terms are reviewed |
| NYSE/ICE first-party historical and reference products | `PARTIAL`, Security Master and listing notices | `PARTIAL`, 60+ NYSE Group action types; full historical start/revision policy not public | `PARTIAL`, Daily TAQ from 1993 and other venue products provide strong raw/session evidence | `UNKNOWN`, delivery and correction/vintage guarantees require contract evidence | `UNKNOWN`, one-time back-history purchase is promising but continuing rights are not public | High-quality institutional challenger; ask archival-rights question |
| Nasdaq direct products | `PARTIAL`, symbol directories and reference feeds | `PARTIAL`, Daily List covers listings, delistings, names, symbols, dividends and splits from 1998 onward | `PARTIAL`, NLS+/Basic and tick-history products expose market data but product-specific field/session rules apply | `UNKNOWN`, versioned specifications do not prove immutable customer vintages | `UNKNOWN`, current GDA and service order control; CUSIP may require separate rights | Contract-only candidate |
| Nasdaq Data Link / Sharadar | `PARTIAL`, active/delisted reference coverage | `PARTIAL`, common actions but public event-vintage semantics are incomplete | `PARTIAL/UNKNOWN`, adjusted/unadjusted EOD exists but session, auction, omission and original-publication semantics are unclear | `UNKNOWN`, fundamentals PIT claims cannot be generalized to prices/actions | `UNKNOWN`, publisher-specific terms control | Useful challenger, not first-party Nasdaq truth |
| Norgate Data | `PARTIAL`, delisted and PIT membership support | `PARTIAL/UNKNOWN`, public product material does not close full M1c support | `PARTIAL` | `UNKNOWN`, no customer-addressable old versions are established by the reviewed public material | Public subscription terms require deletion of exports and related artifacts after expiry | Public screen is incompatible with durable replay; exact-profile result remains unadjudicated |

CRSP documents a daily U.S. stock product from 1925, permanent identifiers,
daily trade/volume fields, distributions, delistings, and explicit release
corrections.^1 Databento documents PIT security master history, PIT corporate
actions from 2018-05-01, and provider-specific OHLCV limitations.^2 Massive
documents unadjusted U.S. stock flat files from 2003-09-10 and condition-level
aggregate update rules, but its standard market-data terms restrict copying,
derived use, and post-termination retention.^3 Norgate's public FAQ requires
deletion of exports, normalized rows, snapshots, events, backups, and metadata
after subscription expiry.^16 Nasdaq and NYSE expose useful
first-party reference, corporate-action, and historical trade products, but
product rights and revision history remain contract questions.^4

## 7. Qualification harness architecture

The future executable harness operates on already acquired, legally permitted
files. Network acquisition and credentials are a separate controlled step.

```text
exact provider-native bytes
+ exact provider methodology and schema bytes
+ acquisition receipt
+ rights assessment
+ qualification profile
        |
        v
provider-specific qualification adapter
        |
        +--> M1b candidate assertions
        +--> M1c candidate facts
        +--> M1d candidate observations/sessions
        |
        v
existing Drift validators and resolvers
        |
        v
dimension results: PASS / PARTIAL / FAIL / UNKNOWN
        |
        v
immutable qualification report and replay closure
```

The adapter may decode and map. It may not invent:

- permanent identity from the current ticker;
- historical availability from current acquisition time;
- event occurrence from announcement or terms;
- settlement from a pay date;
- regular-session semantics from a field called “daily”;
- no-trade from an omitted row or zero volume;
- completeness from a successful response;
- rights from technical download ability.

Unknown native values and unsupported semantics remain retained and produce
`UNKNOWN` or `FAIL`.

### 7.1 Qualification profile

The profile declares:

- exact provider/product/publisher IDs;
- product schema and methodology versions;
- legal entity, user class, purpose, and infrastructure;
- security/listing/universe scope;
- date range and revision cutoff;
- requested M1b/M1c/M1d roles;
- required golden-case definition and pre-acquisition instance-manifest hashes;
- critical versus optional dimensions;
- accepted downstream purpose, such as “historical decision input”,
  “retrospective audit only”, or “coverage diagnostic only”.

Changing any field creates a different qualification.

The profile freezes before acquisition and therefore does not contain delivered
snapshot identity. `QualificationTargetV1` records `NOT_ACQUIRED`,
`ACQUIRED_UNSNAPSHOTTED` with exact receipts/failure evidence, or
`SNAPSHOT_BOUND` with the exact `RealSourceSnapshotV1` hash. A negative result
never mints a snapshot that was not built.

Historical-decision input and retrospective audit are separate qualification
identities. The initial pilot uses a `PilotProfileSetV1` with exactly two
purpose-specific profiles whose provider, subscriber, infrastructure, source
scope, policy, and golden-case requirements otherwise match. They may share
legally authorized acquisition evidence, but each retains independent dimension
results and acceptance.

### 7.2 Result acceptance

A provider may pass observation preservation while failing split normalization,
or pass current retrospective analysis while failing historical decision use.
The report preserves those distinctions. No overall score may hide a critical
`FAIL` or `UNKNOWN`.

The pre-replay report contains the eleven non-replay dimensions. Replay binds
that immutable report, then the typed replay result supplies the twelfth
dimension and produces the final purpose report. The final report is never an
input to its own replay.

## 8. Golden real-source cases

The pilot uses a continuous bounded sample plus event windows. Independent
truth sources grade provider claims; the provider does not grade itself.

Before candidate acquisition, freeze an exact instance manifest for all 18
cases, including any evidence-backed substitutions. Each executable predicate
retains a pre-acquisition subject/logical-key selector specification, independent
truth claim or constant, comparison operation, evidence requirements, and every
status branch. After mapping, a separate binding records zero or more exact
candidate record/mapping hashes without changing that selector. Human-
adjudicated extraction decisions bind exact primary-source bytes and extracted
typed values; later truth claims reference those decisions. Bare URLs or prose
invariants are not executable grading evidence.

| ID | Historical case | What it tests | Independent primary evidence |
|---|---|---|---|
| G01 | Meta Platforms `FB` to `META`, effective 2022-06-09 | Same security/listing, changed ticker/name, unchanged CUSIP | Meta SEC-filed release and Nasdaq Daily List^5 |
| G02 | Roundhill Metaverse ETF `META` to `METV` on 2022-01-31, followed by Meta using `META` | Negative control only: ticker reuse must not join unrelated securities or make an excluded ETF eligible | Roundhill issuer page, Meta filing, exchange records^5 |
| G03 | Linde plc transfer from NYSE to Nasdaq, effective 2023-11-07, retaining `LIN` | Same security and ticker, new primary-listing history | Linde filing and issuer release^15 |
| G04 | A delisted security with continued OTC claim | Listing termination is not security extinction | SEC Form 25, FINRA Daily List, issuer/bankruptcy filings |
| G05 | NVIDIA 10-for-1 split, trading adjusted 2024-06-10 | Announcement, legal effect, trading-basis date, exact ratio | NVIDIA 8-K and exchange action record^6 |
| G06 | GE 1-for-8 reverse split, 2021 | Reverse ratio, fractional treatment, first post-basis session | GE 8-K, issuer notice, exchange record |
| G07 | One ordinary quarterly cash dividend | Declaration, ex, record and payable dates remain distinct | Issuer IR release and exchange ex-date record |
| G08 | One large special distribution with due bills | Due-bill redemption and delayed ex-date | FINRA UPC notice, Nasdaq Ex-Date/Daily List, issuer filing |
| G09 | Twitter/X fixed-cash acquisition, 2022 | Terms, occurrence, delisting, fixed consideration and settlement evidence | Merger agreement, closing 8-K, NYSE notice |
| G10 | One fixed-share or mixed-consideration merger | Multiple components and successor identity | S-4/14A, closing filing, successor listing |
| G11 | GE Vernova spinoff, 2024 | New security/listing, excluded-property receipt, parent continuity | GE information statement/8-K and exchange notice |
| G12 | Bed Bath & Beyond 2023 bankruptcy/delisting/cancellation sequence | Delisting, OTC continuation, claim cancellation and unknown recovery | Bankruptcy filings, Form 25, FINRA notices |
| G13 | One provider action correction with retained old/new versions | Revision selection and unchanged earlier cutoff | Provider correction notice plus issuer/exchange evidence; CRSP release-note edits are candidate sentinels |
| G14 | One corrected daily aggregate | Final corrected bar must not become originally known | Provider original/corrected receipts plus independently re-aggregated eligible trades |
| G15 | Standard early close | Schedule, realized bounds and field aggregation interval | NYSE/Nasdaq official calendar and first-party trade/status data |
| G16 | 2018-12-05 national day of mourning closure | Scheduled versus realized closure | Exchange notice and SEC/exchange records |
| G17 | One security halt or suspension with no qualifying regular-session trade | Venue interruption, lifecycle, source omission and no-trade remain distinct | Nasdaq halt/status data, SEC/issuer notice and raw trades |
| G18 | Multi-class symbol suffix, such as Berkshire Hathaway Class A/B | Class identity and lossy symbol-normalization defense | Issuer filing, exchange security master, stable external IDs |

If a named case is unavailable under the candidate product or license, the
qualification result records the gap. Substitution requires an equally explicit
case and independent evidence. A tiny sample need not contain every event, but
no absent case may be reported as passing coverage.

Every decisive grading artifact follows the same exact-byte receipt, temporal
availability, contractual classification, retention, and snapshot-binding rules
as candidate-provider evidence. A URL-only or unretained page may guide review
but cannot support `PASS`.

## 9. Acquisition receipt

`AcquisitionReceiptV1` is an immutable evidence payload referenced by the
existing manifest acquisition descriptor. It contains:

- provider legal identity;
- product, dataset, publisher and entitlement identifiers;
- credential-free request method, route template and canonical parameters;
- authenticated provider endpoint identity, available request IDs, and safe
  origin evidence;
- requested universe, fields, date range and revision cutoff;
- frozen expected-object manifest for files/endpoints, as-of universe rule,
  fields, dates, partitions, and expected keys;
- collector source hash/version and invocation identity;
- request start/end timestamps;
- status and a bounded allowlist of response metadata;
- provider object, batch, release or snapshot IDs;
- exact transport-body, stored-object, archive-member, and decompressed-payload
  references, sizes, media types and SHA-256 hashes when those byte layers
  differ;
- provider-published manifests, checksums, or signatures when available;
- ordered page/file receipts, cursors and provider sequence;
- expected and observed counts when supplied;
- retry, duplicate and failed-page evidence;
- completion marker and documented completeness claim;
- methodology/schema and licensing evidence references.

It never stores secrets, authorization headers, cookies, signed URLs, or
credential-bearing error text.

Before the first request, `AcquisitionPlanV1` binds the authorization, exact
credential-free request scope, expected-object inventory hash, native-layer
rule, limits, and freeze time. An inventory-discovery request is separately
authorized and receipted. Expected inventory cannot be derived after observing
the response it is supposed to test.

Provider-native bytes mean the exact post-transfer-decoding response entity or
published file before collector decompression, parsing, normalization, or
re-serialization. Transport bodies, stored archives, and decompressed members
are separately identified when they differ. A local hash proves local content,
not provider origin; absent authenticated origin evidence leaves origin
`UNKNOWN`.

### 9.1 Pagination and atomicity

A final page is not proof of completeness by itself. A paginated acquisition
passes only when:

1. every page in the declared chain is retained;
2. page identities, cursors and byte hashes are unique and ordered;
3. the expected-object manifest reconciles received, missing, duplicate, and
   extra files, partitions, dates, and keys;
4. provider counts or completion markers reconcile;
5. duplicate/retry handling is explicit;
6. all pages share an immutable snapshot/release token, or cross-page
   consistency is reported `UNKNOWN`.

The same closed-world reconciliation applies to unpaged endpoints and bulk
bundles. If neither the provider nor an independently justified expected-object
manifest can enumerate the requested scope, acquisition completeness cannot be
`PASS`.

Changing result order changes the acquisition receipt. A separate semantic-set
equivalence decision may show that the decoded facts are unchanged; it must not
rewrite the native receipt.

## 10. Dataset snapshot identity

`RealSourceSnapshotV1` binds:

- qualification profile hash;
- rights-assessment hash;
- acquisition receipt hashes;
- exact native artifact hashes;
- per-component provider release/vintage IDs and source-state timestamps;
- explicit cross-component consistency decision and coordinated-cutoff rule;
- revision cutoff and coverage assertions;
- provider methodology/schema hashes;
- qualification-adapter semantic and source hashes;
- Drift manifests and validation-decision hashes;
- validated bundle hashes;
- M1a availability-policy hash;
- content-addressed replay-input inventory containing exact M1b-M1d query
  payloads, selection and composition policies, normalization queries,
  resolution contexts, supporting artifacts, original validation-run and bundle
  identities, and independent grading evidence;
- expected M1b/M1c/M1d output hashes.

The snapshot ID is the hash of that canonical descriptor. Locations and
credentials are excluded. Reacquiring identical source bytes creates a new
acquisition receipt but may reuse the same content-addressed objects. Snapshot
identity changes when acquisition, rights, schema, policy, adapter, validation,
or accepted coverage changes.

Current corrected history is not automatically historically knowable. A
snapshot may be admitted for retrospective audit while failing historical
decision use. Hashing components acquired at different times does not make them
mutually contemporaneous; absent a provider-coordinated vintage or justified
cutoff rule, snapshot consistency is `UNKNOWN`.

## 11. Licensing and retention gate

Licensing is an acceptance dimension, not a note.

`RightsAssessmentV1` binds a contract-topology manifest, exact executed
terms/order forms, and answers for:

- every controlling or incorporated agreement, publisher term, schedule,
  policy, click-through assent, amendment, and service order, including exact
  bytes/hash, title, version, effective date, precedence, and assent evidence;
- assessment time, validity interval, entitlement and termination state, notice
  source, and mandatory reassessment triggers;
- subscriber legal entity and professional status;
- named users, contractors and service providers;
- internal automated/non-display research;
- model development and future trading support;
- local, private-Git, CI, cloud and backup storage;
- raw-byte retention duration;
- post-subscription and post-product use;
- required deletion and certification;
- normalized/derived row retention;
- model parameters, experiment metrics and reports;
- small private or public test fixtures;
- redistribution and publication;
- upstream publisher restrictions;
- effective dates, amendment/version and controlling-document precedence.

Each retained content hash also binds a contractual data classification,
controlling provision, permitted purpose and storage locations, retention/use
horizon, and deletion or certification duty. Drift's technical `DatasetKind`
never decides whether an artifact is raw, derived, confidential, or retainable
under a provider agreement.

Each answer is `ALLOWED`, `DENIED`, or `UNKNOWN` with evidence. Generic
sales email is insufficient unless incorporated into the executed agreement or
a countersigned addendum. A missing applicable node in the contract topology
forces the affected answer to `UNKNOWN`.

Hard failure for promotion-quality replay occurs when:

- exact raw bytes cannot be retained through the required replay horizon;
- post-termination use or backups must be deleted;
- internal automated analysis is display-only or otherwise prohibited;
- derived outputs needed by Drift cannot survive;
- the upstream publisher/product cannot be identified;
- correction vintages cannot be retained locally and old versions are not
  retrievable;
- cloud/CI/service-provider access needed by the declared environment is denied.

Public Git fixtures remain synthetic unless a signed right names the exact
extract. Private Git is still copying, cloud storage, backup, and potentially
multi-user access. Executed agreements and full rights assessments default to
encrypted, access-controlled, non-Git evidence; only non-sensitive decisions
and references may be committed.

No reviewed public CRSP product document establishes the required post-term
retention right; that result remains `UNKNOWN` until exact terms are reviewed.
Databento says historical exchange licensing and redistribution rights vary by
dataset; that does not establish indefinite vendor-license retention.^7 Massive standard terms require restricted
personal/display or order-form use and deletion/cessation on termination.^3
NYSE and Nasdaq direct use is governed by product agreements and service
orders.^4

An acquisition-time assessment is immutable evidence of what was decided then,
not perpetual permission. Every replay requires a separate immutable
authorization decision against the current entitlement, termination state,
notices, retained contract topology, purpose, users, and environment. Existing
bytes cannot be used merely because their old rights-assessment hash verifies.

## 12. Replay and environment closure

M1e uses a hybrid, runner-neutral environment descriptor plus one demonstrated
platform-specific offline replay bundle.

### 12.1 EnvironmentClosureV1

The descriptor binds:

- Drift Git commit and clean-tree archive hash;
- built wheel/sdist hashes;
- `pyproject.toml`, `uv.lock`, and exported `pylock.toml` hashes;
- exact downloaded wheel/sdist artifacts and index identities;
- uv version and installer artifact;
- Python implementation, exact version/build, executable artifact and standard
  library identity;
- OS, architecture, kernel/runtime compatibility claim and relevant system
  libraries;
- optional OCI manifest, config/layer digests and selected platform;
- exact TZif, schedules and other deterministic external inputs;
- environment build recipe hash;
- no-network restore command;
- security classification and known vulnerabilities at capture time.

`uv.lock` fixes a universal resolution but does not identify one installed
binary environment across all platforms.^8 PEP 751 provides a standardized
installation lock format, not the interpreter or operating system.^9 An OCI
digest content-addresses a userspace image graph, but only if the exact
platform manifest and blobs are retained; host kernel/runtime assumptions
remain.^10

### 12.2 Initial recommendation

Do not mandate Docker in M1e. Drift currently has a small Python runtime with a
native `pydantic-core` dependency and
a roughly 107 MB local environment. First attempt a platform-specific offline
bundle containing:

1. source and built artifacts;
2. exact Python distribution/build evidence;
3. `uv.lock` and `pylock.toml`;
4. a complete local wheel/sdist cache inventory, plus retained build toolchain
   artifacts when an sdist must be built;
5. TZif and source snapshots;
6. a deterministic restore recipe;
7. a fresh offline rebuild and replay on the declared macOS/arm64 platform.

If that cannot be restored on an explicitly characterized supported host
without undeclared or unavailable dependencies, the acceptance
path escalates to a retained OCI layout or equivalent sandbox image, pinned by
platform-specific digest. A copied `.venv` alone does not pass because Python
documents virtual environments as non-portable.^11 A mutable container tag never
passes; Docker documents that digest pinning freezes content but also opts out
of automatic security updates.^10

### 12.3 Security lanes

| Lane | Purpose | Rule |
|---|---|---|
| Historical exact replay | Reproduce old hashes | No network, secrets or broker access; non-root; read-only inputs; bounded resources; never update in place |
| Current safe development | Patched ongoing work | Synthetic data by default; real licensed data stays outside Git in approved encrypted storage |
| Future promotion | Assess current reviewed artifacts | Consume attestations and hashes; never execute arbitrary historical environments with production credentials |
| Future production | Operational execution | Current patched builds only; research/replay grants no execution authority |

An old vulnerable environment is preserved as an untrusted replay artifact, not
promoted. A patched environment is a new environment identity.

## 13. Replay acceptance

Given a retained qualification snapshot and environment closure from six months
earlier, a fresh offline host must:

1. obtain a current replay-time authorization decision, freeze pre-run isolation
   and clean-target plans, then verify source, license, environment and package
   artifact hashes;
2. reconstruct the declared environment without provider access or populated
   package caches;
3. load exact native source bytes;
4. rerun qualification and existing Drift validation;
5. reproduce exact selected source-record hashes;
6. reproduce M1b resolution hashes;
7. reproduce M1c outcome/reference hashes;
8. reproduce M1d schedule, mapping, derivation, view and reference hashes;
9. reproduce qualification-dimension outcomes and limitations from the exact
   retained queries, policies, contexts, validation identities, and grading
   evidence;
10. record execution and dispose of the target under the frozen plan; and
11. verify post-run system-offline and fresh-target attestations bound to that
    exact request, attempt, target, process tree, and control interval before
    finalizing `MATCH`.

Historical reconstruction preserves original canonical IDs, timestamps, query
payloads, policies, contexts, and dependency hashes. The new replay attempt has
a separate envelope with its own attempt ID, wall-clock timestamps, temporary
paths, cache layout, process IDs, and diagnostics. Only fields in that separate
envelope may be excluded by the comparison policy; existing canonical artifacts
are compared exactly.

Replay results distinguish:

- `MATCH`;
- `SOURCE_BYTES_UNAVAILABLE`;
- `USE_DENIED_BY_RIGHTS`;
- `ENVIRONMENT_ARTIFACT_UNAVAILABLE`;
- `PLATFORM_INCOMPATIBLE`;
- `SEMANTIC_IDENTITY_MISMATCH`;
- `OUTPUT_HASH_MISMATCH`.

A retained hash without bytes may explain what is missing but cannot produce
`MATCH`.

Package-manager flags such as `uv --offline` or `--no-index` are not proof that
the process lacked network capability. Replay returns `MATCH` only when an
enforced OS, host, or VM isolation mechanism and fresh restore target are bound
by exact evidence. Until that mechanism is selected and evidenced for the
macOS/arm64 target, environment machinery may be tested but accepted replay
must pause.

The immutable replay request binds pre-run isolation and clean-target plans.
System-offline and fresh-target attestations are created only after execution
and disposal, and bind the exact request, attempt, VM/boot, target, process tree,
and control interval. A post-run attestation cannot be fabricated as a pre-run
request input.

## 14. Historical depth

There is no universal number of years that makes a strategy evaluation valid.
Required history depends on hypothesis, holding period, effective independent
observations, parameter search, multiple testing, and the claim being made.
Backtest selection over many configurations can produce impressive false
results even with long samples.^12

| Window | Assessment |
|---|---|
| 5 years | Omits 2008 and most rate/market-structure variation; report that limitation rather than inferring cross-regime coverage |
| 10 years | Includes COVID and the 2022 rate transition but still omits 2008; report the resulting contemporary-window limitation |
| Post-Reg NMS, approximately 2007 through last complete year | Strong initial provider-coverage target for a future broad cross-regime daily-equity claim; not an evaluator acceptance rule |
| Post-decimalization, approximately 2001 onward | Preferred provider-coverage extension; adds crisis and structural-transition evidence, but pre/post-Reg NMS remain different regimes |
| 1990 or 1925 onward | Stress extension, not a default minimum; older methodology and market-structure comparability need separate qualification |

The SEC records completed decimalization in April 2001 and phased Regulation NMS
compliance through 2007.^13 Those dates identify market-structure changes, not
statistical sufficiency. A 2007 start captures the 2008 crisis, COVID, and
multiple rate regimes. A 2001 extension is preferable if every layer remains
qualified. M1e reports whether a provider can support those windows; it does not
freeze a future evaluator's minimum history or inference claim.

M1e itself does not download that full history. Its pilot uses:

- a continuous engineering slice capped at 100 securities and two years; and
- at most 20 golden event windows, normally 20 sessions before through 20
  sessions after the event.

The pilot proves semantics and replay only. It does not prove dataset-scale
coverage or strategy validity.

## 15. Source composition

Do not assume one provider can satisfy every layer.

Single-source use remains the default pilot because it minimizes joins and
rights intersections. Independent SEC, issuer, exchange and FINRA evidence may
grade the source without becoming a second operational data provider.

If the primary candidate fails a critical layer:

1. retain the independent failure;
2. identify the smallest missing authority;
3. qualify a second source independently;
4. create an explicit composition profile only after both sources pass their
   own rights and replay gates;
5. reject uncertain identity joins, duplicate occurrences and conflicting
   corrections.

The composed result inherits the intersection of license restrictions. Equal
dates, tickers, amounts, or ratios never establish occurrence or identity
equivalence.

A plausible future composition is CRSP for long-history identity/outcome
research plus exchange/Databento observations and sessions, but public licensing
and vintage evidence do not currently authorize that architecture.

## 16. Storage

Initial storage remains file-based and content-addressed. No database or object
store dependency is justified before measured acquisition.

- Real raw bytes live outside Git under an approved private root.
- Canonical descriptors, hashes and non-sensitive qualification decisions may
  be committed.
- Content objects are stored once by hash; snapshots reference them.
- Each object has a contractual classification independent of Drift's source or
  derived technical label; retention follows the rights assessment.
- Backup copies exist only when permitted and are part of the declared rights
  scope.

Measured local context: the current Drift environment is about 107 MB and the
three synthetic M1d fixture versions are under 3 MB combined. CRSP publishes
current full-product package sizes near 3.7-4.1 GB.^1 Massive's compressed daily
aggregate files are tens of MB per year and begin in 2003, while its raw trade
files are vastly larger.^3

Planning allowances:

| Scope | Allowance |
|---|---|
| M1e bounded pilot including environment and backup | 2-5 GB |
| Full daily-row source plus canonical/derived views for roughly 2007 onward | 10-40 GB before repeated vintages |
| Full closure with retained source vintages and redundant backups | 25-100 GB |
| Tick-level archives | Outside M1e; potentially multi-terabyte |

Actual bytes and compression ratios must replace these allowances before a
storage dependency is proposed.

## 17. Future adapter boundary

A provider adapter consumes:

```text
verified provider-native bytes
+ verified provider methodology/schema
+ acquisition receipt
+ rights assessment
```

and produces candidate M1b/M1c/M1d records plus a complete mapping report.

The adapter:

- is deterministic and versioned;
- has no credential or network authority while transforming;
- preserves unmapped native fields and codes;
- binds every mapping rule and native object hash;
- may return `UNKNOWN` or `FAIL` per field/record/dimension;
- never emits evaluator objects, returns, holdings or strategy signals;
- is tested against golden cases and mutation attacks.

Provider-specific logic ends at this boundary. Existing Drift validators decide
whether the candidate records are admissible.

## 18. Future evaluator handoff

M1e hands a future evaluator only:

- an accepted historical universe and M1b resolutions;
- accepted source observations;
- accepted source-basis and split-normalized M1d views;
- M1c economic outcomes and explicit limitations;
- session artifacts;
- missingness/usability results;
- qualification profile/report;
- snapshot and rights identities;
- replay environment identity.

The evaluator receives no API client, provider cursor, vendor ticker fallback,
raw adjusted dataframe, or implicit “latest” data. It must not reinterpret a
`PARTIAL`, `FAIL`, or `UNKNOWN` qualification.

Evaluator policy, returns, holdings, cash, costs, slippage, walk-forward
evaluation, purging/embargo, multiple-testing corrections, and promotion remain
outside M1e.

## 19. Adversarial acceptance

The design fails if any attack can silently produce `PASS` or replay
`MATCH`.

| Attack | Required result |
|---|---|
| Adjusted data labeled raw | Observation dimension `FAIL` |
| Current symbol used for historical identity | Identity `FAIL` |
| Delisted securities omitted | Coverage `FAIL` or `UNKNOWN`, never complete |
| Revised action treated as originally known | Historical-decision dimension `FAIL` |
| Final corrected bar backdated | Decision use denied; retrospective lane may remain explicit |
| Missing pagination page or cursor cycle | Acquisition completeness `FAIL` |
| Successful response with partial product coverage | Coverage remains `PARTIAL` or `UNKNOWN` |
| Current-only reference snapshot called PIT | Revision dimension `FAIL` |
| Mutable URL overwritten | New content/acquisition identity; old replay remains bound to old bytes |
| Result order changes | Native receipt changes; semantic equivalence requires separate proof |
| Methodology changes under same endpoint | Qualification identity changes or fails |
| License blocks raw replay | Rights `FAIL`; no durable replay claim |
| Package or interpreter artifact disappears | Environment replay fails explicitly |
| Mutable container tag changes | Environment identity mismatch |
| Historical image patched in place | Prohibited; new closure identity |
| Two sources report one action | No double count without proven occurrence equivalence |
| Cross-source identity disagrees | Composition `FAIL` or `UNKNOWN` |
| Exact data but changed code/environment | Replay mismatch |
| Exact environment but absent source bytes | `SOURCE_BYTES_UNAVAILABLE` |
| Secret appears in receipt/log | Validation `FAIL`; artifact rejected |
| Expired rights but retained bytes exist | `USE_DENIED_BY_RIGHTS` |

## 20. M1e completion criteria

### 20.1 Positive completion

M1e completes positively when:

1. one pilot profile set with separate historical-decision and retrospective-
   audit profiles is frozen;
2. exact applicable legal evidence is retained and adjudicated;
3. one bounded real-source corpus is acquired under explicit authorization;
4. every critical dimension is `PASS`, and every optional dimension has an
   evidenced status with no hidden score;
5. golden cases are executed against independent truth evidence;
6. an immutable snapshot identity is produced;
7. an offline platform-specific environment is rebuilt from retained artifacts;
8. all required pre-evaluator M1b-M1d hashes replay exactly;
9. mutation, pagination, methodology, rights, and environment attacks fail
   closed;
10. the evaluator handoff contains no provider-specific logic.

### 20.2 Evidenced-negative completion

M1e completes negatively when a frozen profile is falsified before or during
acquisition, qualification, or replay, provided that it:

1. retains all lawfully retainable contract, source, grading, and failure
   evidence with exact references;
2. preserves every dimension's actual `PASS`, `PARTIAL`, `FAIL`, or `UNKNOWN`
   result, records execution reachability separately, and identifies the
   critical failing or unresolved gate without inventing unavailable output
   artifacts;
3. records `NOT_ACQUIRED`, exact deletion/certification evidence, or the
   applicable non-`MATCH` replay state;
4. demonstrates that the failure cannot silently pass any downstream gate; and
5. authorizes neither real-data evaluation nor a general provider rejection
   beyond the frozen profile.

A negative result does not require successful acquisition, a snapshot of bytes
that rights forbid retaining, or exact output replay for unsupported layers. It
closes the pilot's falsification question, not replay closure.

## 21. Explicit non-goals

M1e does not include:

- bulk or recurring production acquisition;
- live market data;
- an always-on provider connector;
- secret management beyond describing the future boundary;
- a generalized adapter framework;
- a calendar engine;
- an evaluator or backtester;
- returns, holdings, portfolio cash, costs or slippage;
- strategy, feature, indicator, ML or recursive research;
- broker, Robinhood, order, trading or production execution;
- automatic promotion;
- a new database or object-store dependency.

## 22. Material open questions

These must be answered before an executable M1e plan:

1. What legal entity will subscribe, and is the intended use personal,
   professional, business, non-display, model development, or future
   trading-support use?
2. Which users, contractors, CI systems, cloud providers and backup locations
   need access?
3. Is indefinite post-subscription raw replay mandatory? This design assumes
   yes for promotion-quality research.
4. Are real bytes allowed only in private storage, or is a tiny private/public
   fixture required?
5. Is the initial replay platform the current macOS/arm64 host, or should M1e
   standardize a Linux/OCI platform?
6. Which exact consumer claim should the first provider scope support:
   historical decision input, retrospective audit, or both?
7. Does the user already have institutional CRSP, WRDS, exchange, Databento,
   Nasdaq, NYSE, or other entitlements?

These questions affect the executable plan and vendor contract inquiries. They
do not change the architecture decision that rights, exact bytes, qualification,
and offline replay form one milestone boundary.

## 23. Disagreements and corrections

### “Qualify one source first”

Evidence for: one source reduces joins, licensing intersections and rework.

Evidence against: a provider may pass observations while failing identity,
outcomes, revisions or retention. Provider-wide acceptance hides the failing
layer.

Correction: qualify one exact product/scope per dimension, with negative results
accepted.

### “Environment closure could follow provider qualification”

Evidence for: environment work can look operational and independent.

Evidence against: a qualification result that cannot be rebuilt offline does
not test durable reproducibility.

Correction: include one minimal offline replay closure, but defer generalized
packaging and deployment.

### “Twenty years is the minimum”

Evidence for: approximately post-Reg NMS history includes 2008, COVID and
multiple rate regimes.

Evidence against: no duration cures multiple testing, structural change or weak
source semantics.

Correction: treat post-Reg NMS as a nonbinding provider-coverage target for a
future broad claim, not a statistical guarantee or evaluator rule; M1e itself
uses only bounded pilot data.

### “One provider should supply every layer”

Evidence for: simpler joins and rights.

Evidence against: current documentation shows different strengths and
historical depths by layer.

Correction: start with one operational source and independent truth evidence;
compose only after each source independently passes.

## 24. Sources

1. CRSP. [Research products and PERMNO](https://www.crsp.org/research/);
   [CIZ flat-file data guide](https://www.crsp.org/wp-content/uploads/guides/CRSP_US_Stock_%26_Indexes_Database_Guide_Flat_File_Format_2.0.pdf);
   [June 2025 release notes and historical edits](https://www.crsp.org/wp-content/uploads/mdaz_202506_quarterly.pdf).
2. Databento. [Security Master](https://databento.com/docs/schemas-and-data-formats/security-master);
   [Corporate Actions dataset](https://databento.com/docs/venues-and-datasets/corporate-actions);
   [schema and OHLCV conventions](https://databento.com/docs/knowledge-base).
3. Massive. [Stocks flat-file overview](https://massive.com/docs/flat-files/stocks/overview);
   [day aggregates](https://massive.com/docs/flat-files/stocks/day-aggregates);
   [condition codes](https://massive.com/docs/rest/stocks/market-operations/condition-codes);
   [market-data terms](https://massive.com/legal/market-data-terms-of-service).
4. Nasdaq and NYSE. [Nasdaq Corporate Action Solutions](https://www.nasdaq.com/products/data/equities/corporate-action-solutions);
   [Nasdaq 2026 Global Data Agreement update notice](https://nasdaqtrader.com/TraderNews.aspx?id=DN2026-4);
   [NYSE reference data](https://www.nyse.com/market-data/reference);
   [NYSE historical data](https://www.nyse.com/market-data/historical);
   [NYSE market-data contracts](https://www.nyse.com/market-data/pricing-policies-contracts-guidelines).
5. Meta Platforms and Roundhill. [Meta SEC-filed ticker-change release](https://www.sec.gov/Archives/edgar/data/1326801/000132680122000070/may312022-exhibit991.htm);
   [Roundhill METV history](https://roundhillinvestments.com/etf/metv/).
6. NVIDIA. [June 2024 Form 8-K](https://www.sec.gov/Archives/edgar/data/1045810/000104581024000144/nvda-20240607.htm).
7. Databento. [Pricing and dataset-specific licensing](https://databento.com/pricing);
   [market-data licensing FAQ](https://databento.com/blog/introduction-market-data-licensing).
8. Astral. [uv project lockfile](https://docs.astral.sh/uv/concepts/projects/layout/);
   [resolution and reproducibility](https://docs.astral.sh/uv/concepts/resolution/).
9. Python Packaging Authority. [PEP 751](https://peps.python.org/pep-0751/).
10. Open Container Initiative. [Content descriptor specification](https://specs.opencontainers.org/image-spec/descriptor/);
    Docker. [Pulling by immutable digest](https://docs.docker.com/reference/cli/docker/image/pull/).
11. Python Software Foundation. [Virtual environments](https://docs.python.org/3/library/venv.html);
    [zoneinfo](https://docs.python.org/3/library/zoneinfo.html).
12. Bailey, Borwein, López de Prado, and Zhu.
    [The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf);
    Novy-Marx. [Backtesting Strategies Based on Multiple Signals](https://www.nber.org/papers/w21329).
13. U.S. Securities and Exchange Commission.
    [Decimalization completion](https://www.sec.gov/news/speech/spch509.htm);
    [Regulation NMS](https://www.sec.gov/rules-regulations/2005/06/regulation-nms);
    [2007 compliance phase](https://www.sec.gov/news/press/2007/2007-29.htm).
14. U.S. Securities and Exchange Commission. [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces);
    [Form 25](https://www.sec.gov/files/form25.pdf).
15. Linde plc. [October 2023 Form 8-K](https://www.sec.gov/Archives/edgar/data/1707925/000165495423013397/lin_8k.htm).
16. Norgate Data. [Subscription and Licensing FAQ](https://norgatedata.com/faq.php).
