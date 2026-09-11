# M1d Source Observations, Sessions, and Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve source daily claims and materialize only query-authorized, session-bound source-basis or split-normalized research observations.

**Architecture:** Add typed M1d source, query, proof, and derived-view families. Reuse M1a exact-byte validation and finite availability, M1b identity/lifecycle/universe folds, and M1c economic facts without changing their persisted contracts. Require the complete cross-layer join, not merely independent component tests.

**Tech Stack:** Existing Python 3.14+, Pydantic, pytest, Ruff, mypy, uv; standard-library `fractions`, `decimal`, `zoneinfo`, `io`, `hashlib`. No new dependency.

**Execution status:** Tasks 1 through 4 are accepted. Task 5 has earned independent Sol and controller acceptance and is the next planned commit with subject `feat: map economic actions to session share basis`. Tasks 6 through 8 remain unstarted. The planning-only acceptance record below is historical.

**Current orchestration authority, 2026-09-08:** The user's current instruction supersedes the historical Task 2-only stop boundary and authorizes the Sol root to complete reviewed Tasks 2 through 8 autonomously. Task 2 must first close its independent-review repair loop, acceptance gate, commit, and Checkpoint. Execution then continues directly through Task 8 unless a material stop condition in the current authorization is reached.

**Spec:** [Historical economic events and observations](../specs/2026-09-05-historical-economic-events-and-observations-design.md), especially sections 7 through 10 and the M1d acceptance rows; ADRs [0006](../../adr/0006-independent-historical-identity-and-lifecycle-facts.md), [0007](../../adr/0007-authenticated-point-in-time-universe-composition.md), [0008](../../adr/0008-verify-selected-content-and-dependent-equivalence.md), [0009](../../adr/0009-separate-economic-events-and-observation-semantics.md).

## Global Constraints

- Work in `/Users/kanuj/Documents/projects/drift`, not the ChatGPT mirror.
- Planning baseline: `aecee94207dbd64aa5154fe03295f35566ec7268` on `main`.
- The planning commit itself did not authorize implementation. Separate execution authority is recorded above; task checkboxes are updated only after verified acceptance.
- M0, M1a, M1b, and M1c are complete. Their persisted source models, canonical bytes, proof algorithms, fixtures, and code-bound replay decisions remain protected.
- Source observations never mutate in place. Missing facts are unknown, not zero. There is no implicit latest evidence vintage.
- Research-session eligibility is not broker tradability, fill availability, or execution authority.
- No provider selection, acquisition, networking, credentials, broker, agent runtime, database, prices feed, live stream, ML, strategy, feature/indicator, evaluator, backtester, return calculation, holdings/cash accounting, transaction cost, slippage, portfolio/risk, optimizer, or trading.
- Synthetic daily regular-session US common-share research only. No options, futures, crypto, intraday strategy, or extended-hours support.
- No `exchange_calendars`, `tzdata`, or other dependency adoption; no holiday/recurrence engine, package alias equivalence, or container/environment closure.
- Do not touch any `.DS_Store` or `docs/handoffs/2026-09-03-m1b-implementation.md`. Never stage a directory wholesale.
- Use strict RED/GREEN, independent spec/adversarial review, and controller verification. The separate user execution request authorizes reviewed task commits and continued execution without routine approval pauses.
- No U+2014 in artifacts. Use Checkpoint at accepted boundaries; use Session Handoff only for unfinished noncanonical context. No continuity database.

---

## 1. Architecture rulings and evidence

M1d remains **one milestone with eight independently reviewable tasks**. Splitting preservation from normalization would isolate valid storage earlier, but would permit a misleading completion claim before the first real consumer proves source/session/action compatibility. Tasks 1 through 4 provide the preservation review boundary without a second milestone. Tasks 5 through 7 must falsify the join before completion. No provider, calendar engine, accounting layer, older-contract change, or new dependency is necessary.

The following are bounded refinements of the spec, not permission to redesign older layers. Evidence was checked on 2026-09-07.

| Disputed simplification | Strongest case for it | Contrary evidence and consequence | Smallest ruling |
| --- | --- | --- | --- |
| One OHLCV population by field name | Easy conventional bar interface | [CTA CTS specification](https://www.ctaplan.com/publicdocs/ctaplan/CTS_Pillar_Output_Specification.pdf) and [UTP output specification](https://www.utpplan.com/DOC/UtpBinaryOutputSpec.pdf) define different eligibility and official-value messages. A field name cannot establish its population. | Generic per-field methods; narrow common-price profile; row identifies the selected fallback branch. |
| Official close equals last eligible trade | They often coincide numerically | The same feed specifications distinguish official/corrected values from ordinary last-sale updates. Equal numbers are not semantic equivalence. | Admit only a method proving the required current-session selector/population; keep mixed claims audit-side. |
| Scheduled open equals a security's first trade | Useful nominal clock | [NYSE auctions](https://www.nyse.com/trade/auctions) states a security can open after 09:30. Schedule, venue outcome, and security activity have different subjects. | Separate facts; never require first trade to equal nominal open. |
| Zone name or calendar version suffices | Compact familiar identifier | [Python zoneinfo](https://docs.python.org/3.14/library/zoneinfo.html) searches system/package data; key-based serialization need not retain rules. | Retain exact TZif bytes and output bytes, use `ZoneInfo.from_file`; no ambient lookup. |
| Generated rows can simply copy source availability | Reuses source revision machinery | M1a's closed derived rule is single-input; a schedule also depends on timezone and methodology. Copying one timestamp hides dependencies. | M1d derivation verifies every semantic input at the query cutoff; generated output is not a fabricated source revision. |
| Missing row/zero volume proves no trade | Some products omit inactive days | Conditional emission is not proof of complete capture or of the converse implication. `test_universes.py` already requires positive coverage for absence. | Separate presence, price activity, any activity, and provider-gap proof. |
| Every individually usable bar needs complete dataset coverage | Strong conservative default | A verified present assertion does not require a complete universe inventory to prove its own value. | Coverage completeness required for absence and action-path completeness, not for a complete present fact alone. |
| M1b outcome composition needs a new fold | `CURRENT_INTERPRETATION` is not finite-V | Existing `AS_KNOWN` accepts finite K independent of evaluation time. A read-only `structural_inputs` probe at fixed E yielded indeterminate for 2018-12-31 and eligible for 2020-01-01. | Internally query unchanged M1b at K=outer V; retain its proof audit-side inside a typed M1d outcome. |
| M1c safe projection already has dates | It already verifies selected economic content | `EconomicSafeFactProjectionV1` has no dates; exact selected terms contain `TermsPayloadV1.dates`. | Narrow M1d date projection from replayed exact source record, never a fabricated field on M1c. |
| All-history adjustment is causally safe | Stable historical scale, some features scale invariant | [QuantConnect documentation](https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/us-equity/requesting-data) explicitly describes full-history adjusted modes. This is a valid product convention, not Drift historical-decision authorization. | Action occurrence, availability, effective cutoff, and anchor all gate each factor, regardless of numerical invariance. |
| Any same-session dividend must block split arithmetic | Unknown dividend unit basis can affect economic interpretation | Pure same-security split ratios commute; cash-only facts are not a share-unit transform. M1c retains cash separately. | Block only affected transformations; never calculate cash or total return. Unknown share-basis impact still blocks. |
| Existing M1c fixtures replay under every future package | Desirable simple test command | `economic_implementation_hash()` hashes every installed Drift `.py`; adding M1d changes it even with unchanged M1c behavior. | Explicit pinned legacy-code replay lane, no fingerprint narrowing, fixture rebinding, or hidden skips. |

Exact ratio reasoning: for q resulting shares per predecessor share, one predecessor economic claim maps to q units; the reciprocal price-unit conversion is 1/q. This is a unit transform, not a promise of realized price continuity or conserved market value. [Python Fractions](https://docs.python.org/3.14/library/fractions.html) supports exact rational arithmetic from decimal strings. Never introduce binary float inputs.

## 2. Ownership and public surface

All files below are future execution targets, not changes made by this planning task. New models extend existing `FrozenModel`, `extra='forbid'`, `schema_version: Literal['1']='1'`, canonical serialization through the existing serializer. Unknown enum values fail schema validation; known `unknown` variants preserve uncertainty. Unqualified IDs use existing UUID7; source IDs, names, labels and reasons use `NonBlankStr`; hashes use `SHA256Hash`; instants use `UTCDateTime`; dates use `datetime.date`. Optional fields are explicit nullable values, not missing proof. SHA-256 identities use the existing canonical hashing function; ordered sets are unique sorted tuples. Raw source ordering is retained separately where meaningful.

| Task | Create production modules | Create tests/support |
| --- | --- | --- |
| 1 | `src/drift/domain/observations.py`, `src/drift/domain/observation_query.py`, `src/drift/markets/observation_validation.py` | `tests/unit/test_observation_contracts.py`, `tests/unit/observation_test_support.py`; test-only legacy lane from section 10 |
| 2 | `src/drift/domain/sessions.py`, `src/drift/markets/session_generation.py`, `src/drift/markets/session_validation.py` | `tests/unit/test_session_artifacts.py`, `tests/unit/session_test_support.py` |
| 3 | `src/drift/markets/observation_selection.py`, `src/drift/markets/session_binding.py` | `tests/unit/test_observation_selection.py`, `tests/unit/test_session_binding.py` |
| 4 | `src/drift/domain/observation_usability.py`, `src/drift/markets/observation_usability.py` | `tests/unit/test_observation_usability.py` |
| 5 | `src/drift/domain/action_sessions.py`, `src/drift/markets/action_sessions.py` | `tests/unit/test_action_sessions.py` |
| 6 | `src/drift/domain/normalization.py`, `src/drift/markets/normalization.py` | `tests/unit/test_normalization.py` |
| 7 | none | `tests/integration/test_m1d_observation_history.py`, `tests/integration/test_m1d_action_normalization.py`, `tests/integration/test_m1d_adversarial_matrix.py`; `tests/fixtures/m1d/v1/` |
| 8 | none | `tests/integration/test_m1d_compatibility.py`; lifecycle documentation |

Do not extend old M1b/M1c enums, role dispatchers, reference families, or validator implementations. M1d uses its own role dispatcher and verifier. Use existing `DatasetManifestV2`, `RevisionEnvelopeV1`, `AssertionVersionProjectionV1`, availability policies, resolver, canonical serializer, and validation decision envelopes without wire changes. No broad top-level exports are required.

### 2.1 Shared query and proof contracts

`ObservationDecisionQueryV1` contains `kind: Literal['decision']`, `decision_time` (T), `knowledge_cutoff` (K), `effective_cutoff` (E), `listing_id`, `security_id`, `venue` (existing MIC enum), `session_date`, `source_id`, `contract_hash`, `source_selection_policy_hash`, `profile_hash`, `requested_channel: AvailabilityChannelV1`, `availability_policy_id`, `availability_policy_hash`, and `input_context_hash`. `ObservationOutcomeQueryV1` has identical subject/policy/context fields, `kind: Literal['outcome']`, `economic_horizon` (H), and `evidence_vintage_cutoff` (V), with no T/K/E fields. Their `kind`-discriminated union is `ObservationQueryV1`. These are additive M1d types, not M1c queries carrying meaningless action kinds for a source-only bar. M1c queries are built separately only by the action adapter. Exact source, not a provider-preference search, is selected.

`ObservationSourceSelectionPolicyV1` has policy ID/version and a tuple of `ObservationSourceBindingV1`: dataset role, source ID, contract hash if applicable, exact MIC/listing scope, inclusive date bounds, manifest hashes and methodology hashes. Bindings must be non-overlapping for the same role/key unless they are partitions of the same explicitly enumerated inventory. Unresolved overlapping reporting authority is indeterminate. No UUID/record-order priority. The policy contains no context/query hash, avoiding a cycle.

Use C=K and B=E for decision queries, C=V and B=H for outcome queries. Existing decision invariants, including K<=T and E<=T, remain enforced. Historical values require both availability by C and relevant economic/completion times <=B; observation completion must also be <=C. Outcome is finite-V, not latest. A source schedule for a future date can be selected as a forecast if known by C, but cannot authorize a future completed observation or anchor.

`M1dSelectionProofV1` binds exact query hash, purpose (`observation`, `observation_coverage`, `scheduled_session`, `realized_session`, `session_coverage`, `contract`), context hash, subject, all considered version hashes, selected hashes, immutable M1a selections/availability decisions, semantic algorithm hash, implementation hash, and result classification (`selected`, `absent`, `indeterminate`). Absent means no selected claim in the verified inventory, not economic absence.

`M1dDatasetInput` is an in-memory audited input: manifest, validation-run context, retained raw artifacts, parsed records, claimed decision, claimed bundle. It is built only after the raw-input validator below returns genuine PASS plus parsed records, then `build_validated_dataset_bundle` succeeds. Every public consumer reconstructs PASS from exact bytes and verifies equality with claimed records/decision/bundle. A constructed/serialized PASS is not a capability. `ObservationInputRecordV1` is the union of daily observation and observation coverage; `SessionInputRecordV1` is scheduled/realized session and session coverage. Contracts are exact supporting methodology artifacts with independently evaluated availability, not fake revision-envelope rows.

`M1dResolutionContext` contains tuples of these inputs, retained availability evidence/policies, M1b exact dataset inputs and universe definition, optional M1c `EconomicResolutionContext`, and retained schedule generation inputs. It also retains the actual canonical artifact bytes for `ObservationSourceSelectionPolicyV1`, `ObservationContractV1`, `ScheduleGenerationPolicyV1`, `ActionSessionPolicyV1`, `NormalizationPolicyV1`, and M1c `EconomicSourceSelectionPolicyV1`, not hashes alone. Store these in one immutable snapshotted mapping `supporting_artifacts: Mapping[str, VerifiedArtifactBytes]` keyed by exact byte hash, with schema/version and canonical content hash verified after parsing the appropriate closed type. Typed policy lookup rebuilds actual values from those bytes, rejects duplicate/conflicting keys, and compares the query's semantic content hash. This avoids forward imports of Task6 models into Task1 while retaining fully replayable policy values. No arbitrary policy plugin dispatch. Context hashes exclude local resolver paths and include every semantic input/record/artifact/policy hash; policies have no reverse reference to the enclosing context/query. Snapshot inputs before verify/use, following M1c materializers.

`M1dSelectedRecordsV1` is the query/purpose/role-bound tuple of exact selected source records plus its proof. It is audit material, not a decision-data reference. Task6 introduces `ObservationDecisionReferenceV1` and `ObservationOutcomeReferenceV1` in `domain/normalization.py` alongside their actual consumer, separately binding the exact derived view hash, full normalization-query hash, derivation hash, and context hash. They are not needed by Task1 or source selection. References cannot be relabeled or used without complete dependent replay.

Proposed exact function signatures (new types are defined in this plan; old types retain their existing imports):

```python
def validate_observation_dataset(
    manifest: DatasetManifestV2,
    artifacts: Mapping[str, VerifiedArtifactBytes],
    run: ValidationRunContextV1,
    supporting_artifacts: Mapping[str, VerifiedArtifactBytes],
) -> tuple[DatasetValidationDecisionV2, tuple[ObservationInputRecordV1, ...]]: ...
def validate_session_dataset(
    manifest: DatasetManifestV2,
    artifacts: Mapping[str, VerifiedArtifactBytes],
    run: ValidationRunContextV1,
    supporting_artifacts: Mapping[str, VerifiedArtifactBytes],
) -> tuple[DatasetValidationDecisionV2, tuple[SessionInputRecordV1, ...]]: ...
def m1d_implementation_hash() -> str: ...
def select_observation_records(
    query: ObservationQueryV1, purpose: str, context: M1dResolutionContext
) -> M1dSelectedRecordsV1: ...
def verify_observation_selection(
    selected: M1dSelectedRecordsV1, context: M1dResolutionContext
) -> None: ...
```

The signatures' ellipses specify interfaces, not implementation stubs to commit. `purpose` must validate against the closed six-value purpose literal above. `M1dSelectedRecordsV1` exposes its tuple as `records`; role/purpose determines its closed union of source models. All verifiers replay and compare the complete canonical result; mismatch raises `ValueError`. Resolver corruption raises existing `ArtifactIntegrityError`; unavailable artifacts use a new M1d-local `ObservationArtifactUnavailableError` in `observation_validation.py`. Invalid syntax/schema fails validation. Valid but insufficient/conflicting source evidence returns an explicit indeterminate/unusable result, not an exception and not a fabricated value.

`m1d_implementation_hash` identifies installed Drift `.py` path/byte pairs in deterministic order; implement it by delegating to unchanged `economic_implementation_hash`, whose existing algorithm identifies the whole installed package rather than just economic code. It does not stand in for the semantic policy hash or historical information authority. No modification to the old economic fingerprint. Persist exact Python implementation/version and `uv.lock` hash in derivations; this is identification, not complete environment closure. The execution preflight ruling below explains why a narrower import inventory does not close the actual M1c-dependent path.

Its exact scope is regular Python source files. The unchanged helper rejects symlinks and unreadable selected source, and checks regularity after opening a selected file. It skips a preexisting nonregular entry such as a newly added FIFO named `.py`; do not claim that it rejects every filesystem anomaly. Replacing an inventoried source file still changes/removes its inventory entry and invalidates exact old identity. Test regular-source mutations/additions, non-Python exclusion, relocation, symlinks and selected-file read/race failure without asserting unsupported FIFO behavior. No M1c modification or extra filesystem-hardening layer is required for this ruling.

## 3. Source claim contracts

### 3.1 Immutable observation methodology

`ObservationContractV1` has `contract_id`, `version: NonBlankStr`, `source_id`, `methodology_artifact_hash`, `availability: tuple[AvailabilityEvidenceV1,...]`, and the following closed semantic fields. Contract identity is immutable content-addressed methodology, not an evolving assertion chain; a source row binds its exact version. Unknown values are allowed for retention, never converted into proof of the narrow profile.

| Field | Type and meaning |
| --- | --- |
| `market_population` | `consolidated`, `primary_exchange`, `named_venue`, `provider_composite`, `unknown`; explicit tuple of MICs if known |
| `populations` | tuple of `TradePopulationV1`: population ID, feed identity/version, venue scope, sale-condition policy artifact hash, odd-lot rule, opening/closing auction rules, correction/cancellation treatment, evidence hash |
| `field_methods` | tuple of `ObservationFieldMethodV1`, uniquely keyed by method ID: field name, meaning, population ID, ordering policy hash, precision/scale, null and zero semantics, fallback branch ID, equivalence evidence hash or null, field adjustment basis and basis-methodology hash |
| `field meaning` | `first_trade_price`, `maximum_trade_price`, `minimum_trade_price`, `last_trade_price`, `official_open`, `official_close`, `share_volume`, `dollar_volume`, `trade_count`, `lot_count`, `other`, `unknown` |
| `ordering` | `execution_time_then_source_sequence`, `source_sequence`, `feed_state_policy`, `not_applicable`, `unknown`; tie/correction policy bound by artifact |
| `volume_relationships` | tuple of `PopulationRelationshipV1`: exact `price_population_id`, `volume_population_id`, relation `price_subset_of_volume`, `equal`, `different`, `unknown`, evidence hash; unique ordered endpoints, not a contract-global assertion |
| `currency` | explicit ISO currency label or `unknown`; no FX conversion |
| `timestamp_meaning` | `exchange_local_session_date`, `utc_interval`, `publication_date`, `other`, `unknown`; source label syntax and timezone ID retained |
| `interval_policy` | inclusion at open/close plus auction-event inclusion rule; explicit event-policy hash, not just datetime <= |
| `revision_policy` | `retained_revision_history`, `current_snapshot_only`, `unknown`; correction horizon (`finite` with duration, `unbounded`, `unknown`) |
| `row_emission` | `every_relevant_session`, `conditional_on_qualifying_activity`, `explicit_markers`, `unknown`; exact omission/marker policy hash |
| `adjustment_basis` | contract summary `unadjusted`, `split_adjusted`, `dividend_adjusted`, `total_return_like`, `mixed`, `unknown`; each selected field method independently declares one of the first four or `unknown`, with basis methodology hash |

Rules like odd-lot/auction handling are explicit `included`, `excluded`, `conditional`, `unknown`; `conditional` must bind the source decision table. The source contract can retain conditional/unknown methods without an interpreter for a real feed. Synthetic admitted methods use explicit known policies. Source-native extra field names are bounded nonempty strings, not executable expressions or extension plugins.

Task1 defines `ObservationMethodologyV1` as canonical synthetic JSON, containing policy/version, the contract's population/method/encoding/omission rules, and literal method algorithm `synthetic_declared_trade_population_v1`. The closed interpreter admits only exact supported canonical rule bytes; arbitrary hashes, prose claims of equivalence or unknown feed policies are retained but not admission authority. Per-field null meanings are `no_value`, `no_eligible_price_trade`, `not_applicable`, `source_missing`, `unknown`; zero meanings are `numeric_zero`, `no_eligible_price_trade_sentinel`, `source_missing_sentinel`, `invalid`, `unknown`. Volume meaning also declares unit `shares`, `currency_notional`, `trades`, `lots`, `other`, `unknown`. Population binds session scope (`regular`, `extended`, `full_day`, `unknown`) and event time basis (`execution`, `report`, `processing`, `unknown`). Profile requires regular/execution or a supported policy proving exact equivalence. All referenced methodology bytes and availability evidence must be in audited context closure, not merely named by hash. No general policy interpreter or real feed adapter is added.

The generalized per-field unit vocabulary additionally includes `currency_per_share`. Initial USD price methods must declare this unit, while qualifying share-volume declares `shares`. A volume-only unit enum would force every price method to claim `unknown`, contradicting positive profile/equivalence requirements. Generic unknown or incompatible units remain source evidence; Task4 admission checks dimensional meaning and Task6 applies factors only to supported units. This is a pre-persistence M1d contract clarification, not a new instrument or currency-conversion capability.

`MethodEquivalenceV1` is a closed synthetic relation with `contract_id`, `source_id`, `field_name`, `from_method_id`, `to_method_id`, `kind: Literal['identical_trade_selector_population_v1']`, and exact methodology artifact hash. Both methods must exist in the same bound contract and field. Each method stores `effective_selector` (`first`, `maximum`, `minimum`, `last`, `sum`, `official`, `other`, `unknown`) independently of its native source label/declared meaning. The interpreter compares effective selector, population ID, event-time basis, ordering/tie/correction policy, sale-condition policy, odd-lot/auction treatment, interval endpoints, currency, unit, precision, and adjustment basis. All dimensions must be known and equal; no caller-provided covered-dimensions subset is accepted. An official-labeled method can qualify only when its supported source rule establishes the identical effective selector, never by overriding `official`/`unknown` with a claimed equivalence hash. V1 admits no general theorem/prose proof.

`MethodBranchV1`: branch ID, method ID, trigger kind (`always`, `source_marker_equals`), marker name/value or null; unique method/branch identity. Each source row's selected method must have an active branch: `always` has no marker, while `source_marker_equals` requires that exact retained source flag key/value under the supported method rule. Simultaneously active competing branches, missing marker, unknown trigger, foreign-contract relation, or nonidentical selector/population makes admission indeterminate or incompatible, not guessed from numbers. Native flags are therefore unique key/value pairs, not unparsed strings. Require tests that change each equivalence dimension and each branch marker while keeping output numbers equal. Population containment must reference the selected common-price population and selected share-volume method population; unrelated containment evidence cannot authorize them.

### 3.2 Observation rows

`DailySourceObservationVersionV1` contains the existing revision envelope; stable native chain key `(source_id, native_record_id)`; source-record locator and hash; `contract_hash`; exact independently evidenced `security_id`, `listing_id`, MIC and attributed `session_date`; source-local label/timezone; claimed UTC interval (`TemporalBoundaryClaimV1` start/end or unknown); `completion_time` claim; tuple of `SourceFieldValueV1`; `source_flags`; optional first/last eligible trade times; `activity_claim` (`qualifying_price_trade`, `explicit_no_qualifying_price_trade`, `unknown`); and `any_trade_claim` (`reported`, `explicit_none`, `unknown`). Attribution is version payload, not the immutable chain key, so a coherent listing/date correction remains representable. Validate and select all chains in the exact inventory before subject/date filtering; an A-to-B correction must not resurrect the superseded A row.

`SourceFieldValueV1`: `field_name`, `method_id`, `native_text: str|None`, `value: Decimal|None`, `state` (`value`, `null`, `omitted`, `sentinel`, `unknown`), `native_flag: str|None`. Accept Decimal only from exact JSON strings, reject binary floats/nonfinite values, retain signed/zero sentinels and precision for generic claims. Every row method ID resolves to exactly one contract method for that field, including the selected fallback branch. Never infer branch from matching numbers. Cross-source and conflicting same-version records fail validation; conflicting independently valid sources remain evidence and fail qualified composition.

Do not enforce common-bar inequalities in the generic source model. Valid mixed official values may lie outside ordinary H/L. Null/omitted states cannot have a fabricated numeric value. Negative price claims can be retained but cannot satisfy the positive-price research profile.

Intrinsic chronology is independent of the query clock: when a source asserts a completed observation, its claimed completion cannot definitely predate the interval end, and independently trusted own-channel availability cannot definitely predate actual completion. A contradictory early-published complete bar remains retained but cannot gain completed authority merely because a July query is later. Require a correcting version/evidence to cure the claim, following M1c's actual-claim chronology rule. Overlapping uncertain bounds are not globally rejected; they withhold dependent authority until the required ordering is proven. Apply the same rule to realized-session reports claiming an actual outcome before it could occur; schedules legitimately known in advance are exempt.

### 3.3 Initial admitted profile

`RegularSessionTradeBar` is a versioned, hashed admission policy, not the generic source schema. It requires:

1. Known unadjusted USD source; exact single listing/security/session binding.
2. Four positive finite `currency_per_share` prices from one proven nonempty eligible trade population, with current-session first/max/min/last semantics and explicit total ordering/tie/correction rules. `low <= min(open,close) <= max(open,close) <= high`.
3. Share volume >0, exact fractional shares allowed; its declared population equals or contains the price population over the same session/event boundary. This deliberately narrows the generic separately declared volume population to avoid an unexplained empty-volume/nonempty-price contradiction.
4. Declared auction treatment. Official values or fallback values qualify only if the selected method's evidence proves precisely the same required selector and population. Numerical coincidence is insufficient. Prior-session/quote/auction-only substitution is not first/last of the common population.
5. Exact realized regular-session coverage and completion. First/last eligible security trades may occur inside the bounds; nominal open is not the first trade. A partial interruption is admissible when retained actual intervals and contract explicitly establish complete aggregation of eligible trades across the interruption. Unknown interruption treatment makes usability indeterminate, not automatically full-day suspension.

No imputation, forward-fill, resampling, zero-price synthesis, or clipping outliers. Nonadmitted claims remain readable as audit evidence but cannot become the initial decision-data view.

Admission checks adjustment basis on every selected required field method, not just the contract summary. A price-split-adjusted/share-volume-unadjusted claim is valid generic `mixed` evidence and is refused by both initial consumer modes. Per-row method selection can represent a changing field basis without erasing native claims. The profile requires one proven share basis across its price and share-volume populations; a method with unknown intraday basis homogeneity cannot qualify simply by being called unadjusted.

### 3.4 Coverage

`ObservationCoverageVersionV1` contains revision/source identity; exact source/contract hash; MIC; explicit listing/security scope; inclusive local-date interval; snapshot identifier/as-of evidence; covered dataset/partition hashes; exact record inventory `(assertion_id, version_id, record_hash)`; methodology/omission rule hash; status (`expected_complete`, `not_expected`, `partial`, `unknown`); explicit exception keys and missing-artifact hashes; revision-history completeness (`complete`, `current_only`, `unknown`). Coverage cannot include itself in its inventory or claim unverified artifacts. The retained enclosing manifest binds it; no hash cycle.

Historical absence requires complete relevant revision capture, not just a modern complete snapshot. A `current_only` snapshot is retained and may prove what was observed at its documented snapshot availability, not backdated historical values. A complete present source version with authentic historical availability remains independently usable even if unrelated coverage is partial.

## 4. Sessions and exact timezone provenance

`SessionKeyV1`: MIC, literal `regular`, local ISO date. Exact venue identity only; no alias substitution.

`ScheduledSessionVersionV1`: revision/source identity, session key, state (`regular`, `early_close`, `closed`, `unknown`), local open/close labels or null, timezone ID, per-boundary fold (`0`, `1`, null), source temporal evidence, methodology hash. Open rows require both local boundaries; closed/unknown rows do not manufacture them. Only explicit dense date rows are supported in the initial generator. A compact source list must be expanded with independently proven completeness and explicit closed-date rules before admission; M1d does not infer omitted weekends/holidays.

`SessionCoverageVersionV1`: revision, source/MIC/scope, inclusive date bounds, exact source-row inventory and source artifact hashes, expected daily cardinality, exceptions, methodology hash, snapshot and revision-history completeness, status as in observation coverage. Missing exact date outside or inside unproven coverage is unknown, not closed. Completeness validates every date, including explicit closed and unknown rows.

`TimezoneInputV1`: timezone identifier, raw TZif SHA-256, tzdb distribution/release identifier or explicit `synthetic`/`unknown`, exact artifact hash, `reconstruction_observed_at: UTCDateTime`, `canonical_encoding_contract_hash`. It identifies reconstruction inputs, not historical information authority; neither capture time nor tzdb release time is passed to M1a cutoff eligibility. Version strings alone are insufficient. Synthetic acceptance uses an explicitly authored finite transition table encoded as valid TZif, documented as synthetic, not a copy of real historical truth. No future transition recurrence generation.

`HistoricalBoundaryOffsetV1`: boundary (`open`, `close`), `utc_offset_seconds: int|None`, `methodology_encoding_hash: SHA256Hash|None`, `authority_artifact_hash: SHA256Hash|None`, `authority_availability_evidence_hash: SHA256Hash|None`. Store exactly one entry for each boundary of an open source row; entries with null authority remain valid source evidence and do not generate eligible UTC bounds. Closed/unknown source rows have no offset entries. Claimed offset is a source value, not taken from the reconstruction TZif. An offset outside Python's supported strict (-86400,86400) second range is retained but its reconstruction is indeterminate. There is no inference from zone name alone.

`ScheduledSessionVersionV1.historical_boundary_offsets` owns these exact row-bound assertions. Original authority artifact bytes must be retained; their selected `AvailabilityEvidenceV1` is looked up by recomputed hash, must reference those exact bytes, and is evaluated at C. The enclosing revision binds that source's assertion that the stated offset/method applies to this exact MIC/date/boundary. A later correction creates a new revision, never a timeless offset override.

`HistoricalTimezoneMethodologyV1` is a canonical supporting-artifact model: schema1, source ID, methodology ID/version, source timezone label, timezone identifier, literal interpretation `explicit_boundary_offsets_v1`, original `source_methodology_artifact_hash`, `source_methodology_availability_evidence_hash`, and current `canonical_encoding_contract_hash`. The boundary's encoding hash selects exact canonical bytes from supporting artifacts; parse this closed type, match source/zone/label/interpretation to the selected row, then separately retain/verify the original source-methodology bytes and referenced availability evidence at C. The modern encoding is not itself backdated. A metadata digest or current parser alone cannot supply source authority. Exact selected source-row binding establishes initial applicability; do not extrapolate a source methodology to other dates or infer a recurrence rule. The same distinction applies to observation methodology: its source meaning and exact row applicability are historical authority, while today's canonical encoding and implementation are reconstruction identity.

Here `canonical_encoding_contract_hash` means the immutable M1d v1 encoding-schema specification identity, not a mutable producer implementation or its capture time. Enforce the recognized v1 schema hash. Modern encoder code/package/capture identities belong only in generation-policy/reconstruction lineage; changing them without changing the represented source facts must not create a new source revision. Canonical methodology bytes and source-row identity therefore remain stable under a semantics-preserving encoder implementation change. If a future encoding schema actually changes, that is a new explicit encoding contract, not silent rewriting of v1.

For synthetic admission, verify original methodology bytes against the exact supported canonical source-method payload: schema1, kind `historical_timezone_methodology`, source ID, methodology ID/version, source timezone label, timezone identifier, interpretation `explicit_boundary_offsets_v1`. Verify offset authority bytes against kind `historical_boundary_offset` with schema1, source ID, MIC, local date, boundary name, exact local label, timezone identifier and asserted offset seconds. Every compared value comes from the selected row/encoding and must match the retained original payload; an artifact hash or availability timestamp alone cannot authorize a different offset/date. Unknown/unrecognized source formats remain retained but unsupported for generation. These are closed synthetic source payloads, not real-provider adapters.

Authority methodology encoding references original source bytes/evidence and its canonical encoding contract, never a schedule/query/output hash. The source revision references that encoding; generated outputs reference selected source and reconstruction inputs. This graph has no hash cycle. An artifact used both as historical authority and as reconstruction input must satisfy both roles independently.

`ScheduleGenerationPolicyV1`: literal algorithm `explicit_local_rows_to_utc_v1`, semantic algorithm hash, producer/name/version, exact producer source/package hash, implementation hash, Python identity, lockfile hash, timezone-input hash, `canonical_encoding_contract_hash`, and sorted unique `historical_timezone_methodology_encoding_hashes`. The schema hash must equal the recognized v1 schema hash in both timezone and methodology encodings. The methodology-encoding tuple must exactly equal the hashes referenced by the selected open/close authority claims, not an unscoped substitute mapping hash. Input-only identity, no output hash.

`SessionOutputV1`: session key/state, exact UTC open/close or null, original local labels/folds, `interpretation_status` (`authorized`, `indeterminate`, `conflict`). `GeneratedSessionRowV1` binds that output value with source-version hash and generation-policy hash. `ScheduleArtifactV1`: query hash, selected source/coverage proof hashes, generation-policy hash, timezone bytes hash, generated-at UTC, exact canonical output bytes hash, output row inventory hash, `historical_authority_availability_proof_hashes`, `reconstruction_input_hashes`, `classification` (`generated`, `indeterminate`, `conflict`) and reasons. Exact output bytes serialize the ordered `SessionOutputV1` values, while row inventory hashes serialize full provenance-bearing generated rows. This explicit two-object boundary lets unchanged UTC output retain byte identity while changed producer/source provenance changes row and derivation identity. Unknown/conflicting interpretation carries no eligible UTC boundaries; source state/labels remain retained. The artifact is an M1d derivation, not a new source assertion whose publication date copies one input. Output rows never point back to their enclosing artifact hash.

```python
def generate_schedule(
    query: ObservationQueryV1,
    context: M1dResolutionContext,
    policy: ScheduleGenerationPolicyV1,
) -> ScheduleArtifactV1: ...
def verify_schedule(
    artifact: ScheduleArtifactV1, context: M1dResolutionContext
) -> None: ...
```

Generation reads the same verified TZif bytes it hashes, constructs `ZoneInfo.from_file(BytesIO(data), key=identifier)`, and converts each explicit local boundary. Round-trip local->UTC->local must reproduce the label and specified fold. Reject nonexistent time; require explicit fold for ambiguous time. Retain UTC exact or INTERVAL boundary claims instead of invoking older DATE/MINUTE validators with ambient host timezone data. Check historical schedule/coverage/source-methodology/offset authority availability independently at C, not literal modern TZif/code/runtime/encoding capture time. Compute authoritative UTC independently as local label minus its sourced offset, and require the verified TZif conversion and offset to match. Missing/unknown/unavailable authority is indeterminate; a disagreement is conflict, with no eligible generated UTC boundary. A unique modern answer alone supplies no authority. Generation time, reconstruction capture and code creation are lineage, not market publication. Previously generated bytes replay without consulting today's zone database; a later corrected historical offset requires a freshly selected source revision and agreeing reconstruction bytes.

Before constructing nested temporal models or invoking old M1b/M1c validators in any M1d replay path, precheck their raw temporal payloads. The initial M1d authority profile permits SECOND, explicit UTC INTERVAL/SESSION bounds and UNKNOWN, but does not admit DATE/MINUTE temporal encodings that make existing M1a validation consult ambient `ZoneInfo`. Preserve such verified raw inputs audit-side; return dependent M1d indeterminate with `unsupported_authority_precision`, not a fabricated replacement time. Apply the guard to owned source revisions, supporting availability/derivation evidence, and older contexts actually consumed by the query. Do not inspect unused M1c context in source-basis mode. Synthetic date-only facts retain their native label with explicitly evidenced UTC INTERVAL bounds. Do not edit older models, rewrite old bytes, or patch global timezone behavior. Test with ambient lookup made unavailable that accepted M1d replay never consults it, and that unsupported raw precision is classified before nested parsing.

`RealizedSessionVersionV1`: revision/source identity, session key, `outcome` (`opened`, `did_not_open`, `unknown`), optional exact actual open/close bounds, orthogonal source assertions `reported_as_scheduled`, `late_open`, `early_close` each `asserted`, `denied`, or `unknown`; tuple of interruption intervals; interruption coverage (`complete`, `partial`, `unknown`); source evidence/methodology hashes; optional compared schedule hash. Silence is unknown, not denied. Late opening, early close and interruption may coexist. Closed/unknown cannot carry contradictory proven-open bounds. Opened with unknown bounds is retained, but cannot supply exact binding. Derived comparison to a selected schedule is separately computed, never overwrites these source assertions.

An independently sourced realized report is valid with no earlier schedule. `reported_as_scheduled` is retained source language, not permission to fill missing actual times. When no compared schedule exists the derived schedule comparison is unknown. Later emergency closure never rewrites an earlier selected scheduled-open assertion. A venue opening does not establish security-level trade activity.

`ObservationSessionBindingResultV1`: exact query/observation/contract hashes, session key, selected schedule/realized proof hashes, source label mapping, claimed and actual intervals, classification (`bound`, `conflict`, `indeterminate`), ordered reason codes, dependency/context/policy/code hashes. Bind only identical venue/date/listing, proven label meaning, exact compatible actual regular interval and endpoint/auction policy. Scheduled/realized changes may legitimately differ; compare against realized actual interval without rewriting schedule. A source bar on proven did-not-open is conflict; unknown actual interval is indeterminate. Require source completion at/after its entire claimed interval and <=min(B,C). No schedule-only completed-bar admission.

```python
def bind_observation_session(
    query: ObservationQueryV1, context: M1dResolutionContext
) -> ObservationSessionBindingResultV1: ...
def verify_session_binding(
    result: ObservationSessionBindingResultV1, context: M1dResolutionContext
) -> None: ...
```

## 5. Missingness, eligibility, and usability

`ObservationAssessmentV1` preserves these independent axes and the exact contributing proof hashes. Never replace them with a single dominant reason.

| Axis | Closed values |
| --- | --- |
| scheduled day | regular, early_close, closed, unknown |
| realized outcome | opened, did_not_open, unknown; independent early/late/interruption details |
| M1b lifecycle | active, not_yet_listed, suspended, terminated, indeterminate; partial-period evidence retained |
| coverage | expected_complete, not_expected, partial, unknown |
| record presence | present, absent, unknown |
| required fields | complete, partial, unknown |
| qualifying price activity | reported, explicit_none, unknown |
| any reported activity | reported, explicit_none, unknown |
| artifact integrity | verified, corrupt, unavailable |
| cutoff availability | eligible, ineligible, indeterminate |
| provider gap | proven, not_proven |
| usability | usable, unusable, indeterminate |

Low-level integrity failure raises the typed read-boundary error; no source rows or absence assertion are emitted from those bytes. `assess_observation` catches only `ArtifactIntegrityError` and `ObservationArtifactUnavailableError`, returning `ObservationReadFailureV1` with query hash, requested artifact hash, integrity (`corrupt`, `unavailable`), typed error code, all source-derived axes `unknown`, provider gap `not_proven`, and usability `unusable` for corrupt or `indeterminate` for unavailable. It carries no parsed rows, selected proof, numeric view or absence fact. A normal `ObservationAssessmentV1` has `kind='assessment'` and integrity literal `verified`; failure has `kind='read_failure'`. `ObservationAssessmentResultV1` is their discriminated union. Malformed schemas/forged proof errors are not swallowed as missingness. Constructors cannot turn caller-supplied integrity into authority: verification reruns the exact read/assessment and compares the complete result. A verified dataset with no selected row is assessed normally.

`ListingSessionEligibilityResultV1` contains query, M1b identity/structural/lifecycle replay hashes, selected schedule hash, classification (`eligible`, `ineligible`, `indeterminate`), reasons and context/policy/code identities. It answers only selected research-universe and scheduled-session requirements. Use unchanged M1b `AS_KNOWN` with inner K=C and evaluation time equal to the relevant source-session point. For an outer outcome, inner finite K=V proofs stay audit-side; they are not exportable as a decision view. Never use `CURRENT_INTERPRETATION`. Rebuild exact old dataset validation before invoking M1b public folds. Eligibility can be known for a scheduled-open day without claiming it occurred or that a bar is usable.

For a completed bar, independently replay lifecycle/structural evidence over the relevant interval, not merely at query T or today's listing. A fully pre-listing, post-termination, or fully suspended interval is unusable for this profile. A partial halt/interruption need not fail: require positive interval evidence and contract aggregation semantics. If existing M1b facts cannot settle interval coverage, return indeterminate, not a new lifecycle inference. Delisted historical bars remain usable when the source interval was eligible.

The interval adapter is a finite boundary sweep, not a new lifecycle fold. From complete causally selected M1b lifecycle/classification/membership/relationship coverage, collect all exact state-change boundaries intersecting the observation interval plus its endpoints. At each nonempty constant-state segment call the unchanged public structural and lifecycle resolvers with K=C, evaluation=segment start; preserve the exact endpoint event convention. Any unknown/bounded change overlapping the interval makes the relevant segment indeterminate. A disjoint pre/post-interval unknown fact does not. For partial suspension, require a source methodology that explicitly aggregates only permitted eligible-trade segments and complete evidence for those segments; never erase the suspended segment or assume zero trades there. Retain the segment results and selected event/coverage hashes in assessment dependencies. This adds interval composition, not source-event semantics or M1b reinterpretation.

Provider gap requires all of: proven relevant realized opening; historical listing allowed observation; source product expected this exact row independent of unknowable activity; complete relevant coverage/revision capture; verified exact artifact inventory; and absent row under selected omission methodology. Missing any premise means `not_proven`, not a competing invented reason. A conditional-on-activity source cannot prove expected row without positive activity evidence. A no-trade marker can establish no qualifying price trade while broader volume/other trades exist. Missing row, zero volume and null close alone never prove no qualifying trade or no trading.

Usability is `unusable` when a verified necessary condition is false (e.g. wrong profile, future completion, known conflicting venue/session, partial required prices); otherwise `indeterminate` when a necessary fact is unknown/conflicting; otherwise `usable`. Preserve all reasons/axes even when one false condition decides unusable. No numeric consumer view for either nonusable state. A complete present bar does not require dataset-wide completeness; split normalization separately requires complete relevant economic-action history.

```python
def resolve_listing_session_eligibility(
    query: ObservationQueryV1, context: M1dResolutionContext
) -> ListingSessionEligibilityResultV1: ...
def assess_observation(
    query: ObservationQueryV1, context: M1dResolutionContext
) -> ObservationAssessmentResultV1: ...
def verify_observation_assessment(
    result: ObservationAssessmentResultV1, context: M1dResolutionContext
) -> None: ...
```

## 6. M1c action/session mapping

`ActionSessionPolicyV1`: policy/version, semantic hash, mapping mode (`explicit_first_basis_date`, `exact_trading_basis_transition`), referenced source date-role methodology hash, endpoint policy (`require_explicit_designation`), implementation identity. The method must prove that the chosen source date/instant means a trading share-basis change for the exact venue/security. Generic legal-effect, announcement, record or payable dates are not silently interpreted as trading-basis dates.

`ActionSessionQueryV1`: outer observation query, exact selected M1c action/occurrence identity, source term/effect hashes, listing/security/MIC, requested candidate date range, policy hash. `ActionDateProjectionV1` contains only selected action/occurrence identity, exact source record hashes, date-role/boundary facts, applicable same-security share component and basis-methodology hash. Build it from `resolve_economic_facts`/verified M1c selection and exact selected `TermsPayloadV1.dates`/effect time, not from nonexistent safe-projection dates. Recheck full M1c context and source equality; strip locators/irrelevant source fields from consumer projection.

If the mapping uses a terms date, require the replayed `EconomicAssociationResolutionV1` for this exact effect and its terms association to be `resolved`, with `selected_target_hash` equal to the exact chosen terms hash. Bind that association result hash in `ActionDateProjectionV1` and the mapping result. Same security/source is not enough to join two different actions. Missing/conflicting/foreign target yields indeterminate. An effect-time-only mapping may omit terms only when the selected mapping methodology proves that exact effect-time field itself means trading-basis transition; generic legal occurrence time is insufficient.

The adapter builds an unchanged `MarketDecisionQueryV1` or `MarketOutcomeQueryV1` for the same security/channel/K or V, and retrieves the exact `EconomicSourceSelectionPolicyV1` value from context. Call `resolve_economic_facts(m1c_query, economic_context, economic_source_policy)` and matching selection/projection verifiers with that policy; bind its full hash. Its `history_start` and `through` must exactly equal the inner query window. For normalization the window is source session opening through proven anchor basis instant, bounded by outer B/C; inner E/H is the latter instant, never later than the outer horizon. T/K or V stay unchanged. A source-only view never constructs this economic query.

The required closed economic action-kind scope for split completeness is all fourteen current M1c classes: `forward_split`, `reverse_split`, `regular_cash_dividend`, `special_cash_distribution`, `stock_dividend`, `cash_acquisition`, `stock_acquisition`, `mixed_acquisition`, `spinoff`, `conversion`, `liquidation`, `bankruptcy_reorganization`, `rights_warrants_cvr`, `other_unsupported`. The M1d policy pins this literal set; it is not dynamically widened when an old enum changes. M1c query, source policy and relevant terms/effect coverage must agree on the entire set, exact source/security/window/inventory and supported occurrence identity methodology. A split-only complete dataset is insufficient. Settlement completeness is not needed for a split unit conversion. Only forward/reverse split effects produce q. Known cash-only distributions are basis-neutral; any other relevant class requires proof it does not change this security's share basis, otherwise normalization is indeterminate. Unknown/unsupported does not mean basis-neutral.

The old M1c API still requires all three family owners and exact context bindings. Synthetic helpers supply a genuine validated empty settlement dataset, its owner/binding, and explicit complete empty-record coverage; they do not omit that owner or fabricate PASS. M1d gates split units on the exact terms/effect coverage and occurred share-component results, not aggregate `EconomicOutcomeResolutionV1.evidence_completeness` or `support_status` when those are partial solely because settlement evidence is incomplete. In a supplied context with incomplete settlement coverage, preserve that audit lineage without contaminating a proven share-unit transform. Do not require dividends delivered, claims closed, or cash calculated.

`FirstPostActionSessionResultV1`: query hash, classification (`mapped`, `not_applicable`, `indeterminate`), first-post session key and transition claim or null, exact M1c occurrence/term/effect hashes, selected session/coverage proofs, date projection hash, reason tuple, policy/context/code hashes. A mapped result is not by itself a factor authorization; normalization still checks action occurrence, basis applicability, horizon and anchor.

Mapping rules:

1. Positive **occurred** same-security split effect, not announcement/promise/settlement alone. Known cancellation/no applicable split is not applicable; uncertain occurrence is indeterminate.
2. Explicit source first-ex-basis date maps only if that exact date is proven actually open for the exact venue and source methodology gives the date that meaning. A closed/emergency/unknown day is indeterminate; no silent roll.
3. An exact source trading-basis transition strictly before proven actual opening maps to that session. An exact after-close transition maps to the next positively proven open session only when the method explicitly declares this basis rule and every intervening date has complete selected closed/open coverage. This is a documented transition rule, not rolling an ambiguous date.
4. Intraday transition, ambiguous bounded/date-only time, unproved endpoint equality, venue mismatch, gap, or competing dates yields indeterminate. A transition exactly at open/close needs explicit method designation; otherwise do not guess event order.
5. Source-selected corrections replace earlier versions only through immutable revision selection at C. Do not choose whichever schedule/action version happens to make the mapping succeed. All relevant conflicts remain hashed.
6. Deduplication scope is the selected M1c effect-family owner, exact security and positively identified source-native economic occurrence. Require complete effect coverage with `occurrence_key_semantics='economic_occurrence_ids'`. M1c admits one owner per fact family; M1d adds no cross-source equivalence seam. Equal date/ratio from two sources is not occurrence equivalence and overlapping authority remains indeterminate. Compare all selected reports for the same evidenced occurrence before window filtering. Conflicting ratios/dates block affected mapping even if one proposed date lies outside the window.

```python
def map_action_to_session(
    query: ActionSessionQueryV1, context: M1dResolutionContext
) -> FirstPostActionSessionResultV1: ...
def verify_action_session_mapping(
    result: FirstPostActionSessionResultV1, context: M1dResolutionContext
) -> None: ...
```

## 7. Derived views and exact split arithmetic

`NormalizationPolicyV1`: mode (`source_basis`, `split_normalized`), version, semantic algorithm hash, profile hash, mapping policy hash (null for source_basis), price/volume output decimal scales, literal `half_even` rounding, implementation identity. Scales are nonnegative bounded integers, no floats. Source-basis retains native exact decimal values/precision with factor1 and no quantization; scale fields must be null in that variant. Split mode defines canonical price/share-volume output scales. Reject positive price rounded to zero; retain exact rational nonzero share-volume even if display quantizes to zero, marked explicitly as rounding rather than absence.

`NormalizationQueryV1`: observation query, policy hash, `anchor_session: SessionKeyV1|None`; source_basis requires null anchor and no action inputs. Split mode requires same listing/security/venue, A>=source session S, exact proven anchor basis instant <=B and <=C. Do not require anchor's completed daily close merely to express earlier observations in its already-effective basis. Do not return that anchor's incomplete close. Future known schedule/announced split never establishes a future anchor.

`ExactRatioV1`: reduced signed numerator as canonical integer string, positive denominator as canonical integer string, zero represented 0/1; action q and factors strictly positive. `FieldTransformV1`: field/method/meaning, exact source value, exact rational factor, exact rational transformed value, optional quantized decimal value/scale. Only prices and **share-volume** receive split factors. Dollar volume/trade count/lot count have no admitted split mapping in V1; requesting them as transformed fields is unsupported, never multiplied by q.

`NormalizationDerivationV1`: query and role, source selection/assessment/binding hashes, normalization and mapping policy hashes, semantic algorithm hash, exact implementation/Python/lock identities, source/action/coverage/session/TZif/artifact hashes, ordered unique occurrence mappings, target basis, exact per-field factor product, output hash. `DerivedObservationViewV1`: role-discriminated query, source session/listing/security, basis mode/anchor, exact transformed fields, usability hash, derivation hash. Output value hash is over payload excluding the derivation back-reference; derivation hashes that payload, and view binds derivation. No hash cycles.

`NormalizationResultV1` has classification (`materialized`, `unusable`, `indeterminate`), all diagnostic dependency/reason hashes, and optional view/reference. Only materialized includes a view and the corresponding decision/outcome reference. Public materializers snapshot and verify all dependencies; supplied values/hashes alone never authorize outputs.

```python
def normalize_observation(
    query: NormalizationQueryV1, context: M1dResolutionContext
) -> NormalizationResultV1: ...
def verify_normalization(
    result: NormalizationResultV1, context: M1dResolutionContext
) -> None: ...
def materialize_observation_decision(
    reference: ObservationDecisionReferenceV1,
    query: NormalizationQueryV1,
    context: M1dResolutionContext,
) -> DerivedObservationViewV1: ...
def materialize_observation_outcome(
    reference: ObservationOutcomeReferenceV1,
    query: NormalizationQueryV1,
    context: M1dResolutionContext,
) -> DerivedObservationViewV1: ...
def compose_split_factors(
    ratios: tuple[ExactRatioV1, ...],
) -> tuple[ExactRatioV1, ExactRatioV1]: ...
```

Algorithm, applied after source usability is proven:

Materialization requires the caller's full original `NormalizationQueryV1`, not merely its digest. Match `content_hash(query)` to the reference, enforce the nested decision/outcome role and exact input context, then recompute normalization and compare the complete reference/derivation/output before returning. Do not put future query/derived-output artifacts into the input-context hash or invent a registry to recover a query from its hash. Existing M1c `resolve_decision_records` and projection resolvers already use explicit query arguments. A changed query with matching visible numbers must fail the reference check.

1. Source-basis returns the unadjusted source values only. Generic provider-adjusted/unknown-basis rows stay audit-side, not a mislabeled source view. This path does not require or consult action completeness.
2. Split mode reconstructs complete relevant M1c action/effect coverage for the security from S through A, including potentially basis-changing unsupported event classes and exceptions. Unknown relevant timing/basis or incomplete history blocks transformation. A definitely irrelevant event does not contaminate an independent bar; an unavailable future event cannot enter selected-action/factor lineage or consumer diagnostics of an earlier query. Full audited inventory/context hashes may bind opaque retained future bytes, as in M1c, without exposing their dates, values, locators or authority in the consumer projection.
3. Select revisions at C; resolve occurred applicable effects and map first-post sessions. Only S < first_post <= A and basis transition <=B,<=C contribute. Announced but uneffected action contributes no factor; don't mistake omitted future effects for unknown past history when complete as-known coverage proves the relevant interval.
4. Deduplicate evidenced occurrence equivalence before filtering. Each actual same-security split contributes q=resulting/predecessor from M1c's proven share component, not provider factor fields. Unknown unit basis/conditions or unsupported cross-security conversion blocks the affected transform.
5. Compose Q=product(q) as exact rational. Price factor=1/Q; qualifying share-volume factor=Q. Source session already first-post has factor1 for that occurrence. Forward2 gives price100->50 and shares10->20; reverse1/10 gives100->1000 and10->1.
6. Pure same-security unit splits commute. Canonical occurrence sorting is serialization order only. Any meaningful noncommutative/unknown share-basis precedence blocks. Cash-only facts stay separate, with no dividend arithmetic; unknown unit basis of an affected cash/economic computation remains unresolved and cannot be advertised as total return.
7. Multiply exact input decimals converted from strings by exact ratios. Quantize once at final output with integer half-even, preserving unrounded numerator/denominator. Hash every input/policy/code identity even when output numbers happen to match.

The primitive implementation shape and exact oracle are:

```python
from fractions import Fraction

q = Fraction("3") / Fraction("2") * Fraction("2") / Fraction("3")
price_factor, share_factor = 1 / q, q
assert (price_factor, share_factor) == (Fraction(1), Fraction(1))
assert Fraction("100") * Fraction(1, 2) == Fraction("50")
assert Fraction("10") * Fraction(2) == Fraction("20")


def quantized_integer(value: Fraction, scale: int) -> int:
    scaled = value * (10**scale)
    sign = -1 if scaled < 0 else 1
    units, remainder = divmod(abs(scaled.numerator), scaled.denominator)
    twice = 2 * remainder
    increment = twice > scaled.denominator or (
        twice == scaled.denominator and units % 2 == 1
    )
    return sign * (units + int(increment))


assert quantized_integer(Fraction("1.005"), 2) == 100
assert quantized_integer(Fraction("1.015"), 2) == 102
```

## 8. Synthetic support and acceptance matrix

`tests/unit/observation_test_support.py` will define `ObservationHarness` with methods `decision(T, K, E, session_date)`, `outcome(H, V, session_date)`, `assess(query)`, `normalize(query, mode, anchor_date=None)`, `replace_source_revision(close, available_at)`, and `context`. `tests/unit/session_test_support.py` defines `session_rows()` and `timezone_bytes()` for the fixed corpus below. Helpers build genuine manifests, exact bytes, PASS decisions/bundles and retained evidence through public validators, not `model_construct` or forged proofs. Negative tests may forge copies only to prove rejection. Task 5 adds M1c fixture construction through the existing `EconomicHarness`, with documented action/coverage configuration, and `map_action(basis: str, mode: Literal['explicit_first_basis_date','exact_trading_basis_transition']) -> FirstPostActionSessionResultV1`. That helper builds an occurred2-for-1 same-security effect, the supplied sourced date/instant with its exact supported method, complete literal action-class coverage and November session corpus, then calls public `map_action_to_session` with outcome horizon H=2026-12-01T00:00:00Z and finite evidence vintage V=2026-12-02T00:00:00Z. Accepted M1c complete coverage requires its interval end after H, snapshot at or after that end, and availability by V; literal H=V at the same instant is impossible without weakening M1c. The helper does not implement a second mapper. Helpers may not assert test expectations internally.

Base synthetic listing is an existing M1b-supported USD domestic common share on XNYS, stable UUIDs reused consistently across exact identity manifests. Base session 2026-01-05 local09:30-16:00 yields14:30-21:00Z, actual opened same bounds, source O100/H110/L90/C105, share-volume10, publication21:01Z, decision T=K=E=22:00Z. Explicit first trade14:35Z and last20:59Z show boundaries need not be trade times. Synthetic summer2026-07-06 yields13:30-20:00Z; early-close2026-11-27 yields14:30-18:00Z. Explicit Nov26/28/29 closed rows and Nov30 open support after-close mapping. These are test assertions with retained synthetic evidence, not a historical market calendar product.

Each matrix ID becomes a named parametrized case with an independent semantic oracle. Pair a denied query with an authorized one where possible. Full success means these contracts survive, not reaching a test-count target.

| ID | Case and required oracle | Task |
| --- | --- | --- |
| O01 | Valid base bar -> usable exact source values; no action inputs in source basis | 1,4,7 |
| O02 | Mixed/unknown OHLC populations -> retained, not common-profile usable | 1,4 |
| O03 | Official close outside common H/L -> retained; no last-trade alias; proven equivalent selected branch passes | 1,4 |
| O04 | First eligible trade14:35 despite scheduled14:30 -> valid, not rewritten | 3 |
| O05 | Per-row fallback changed with unchanged contract -> old branch proof cannot authorize new value | 1,3 |
| O10 | Equivalence with changed selector/condition/basis or wrong contract, inactive/ambiguous branch marker -> no admission despite equal numbers | 1,4 |
| O11 | Containment relates unrelated price/volume populations -> selected volume population not proven, no admission | 1,4 |
| O06 | Zero/sentinel volume or volume-only report -> no synthesized close/no-trade claim | 1,4 |
| O07 | Current provider split/dividend-adjusted or unknown basis -> audit retained, source/split consumer refused | 4,6 |
| O09 | Split-adjusted prices with unadjusted share volume -> generic mixed claim retained; required field basis checks refuse consumer view | 1,4,6 |
| O08 | Partial fields/negative price/range failure -> no numeric consumer view, evidence retained | 4 |
| S01 | Early close and winter/summer UTC offsets -> exact outputs from retained TZif | 2 |
| S02 | Missing date at coverage edge/unproven sparse list -> unknown, not closed | 2,3 |
| S03 | Later emergency did-not-open -> prior scheduled-open query unchanged; later binding conflict | 3,7 |
| S04 | Realized early close/late open/interruption coexist and differ from schedule -> actual bounds retained | 2,3 |
| S12 | Report silent on lateness vs explicitly denied lateness -> distinct retained assertions and hashes | 2,3 |
| S05 | Unknown realization or open report without bounds -> no completed-bar authority | 3,4 |
| S06 | Realized closure/open report without prior schedule -> valid source; comparison unknown | 2,3 |
| S07 | Schedule correction after K -> earlier exact artifact/proof replays unchanged | 3,7 |
| S08 | Changed tzdb/producer same UTC output -> output-byte hash same, derivation different; changed UTC differs both | 2,7 |
| S09 | Ambiguous fold/nonexistent local time/ambient-zone substitution -> reject unproved conversion | 2 |
| S10 | Closed/unknown schedule with present bar -> preserve source, no silent discard or package override | 3,4 |
| S11 | Exact close auction boundary requires declared event policy, not implicit inclusive interval | 3 |
| T01 | Close requested at same-day open -> ineligible/incomplete despite forged early publication | 3,4 |
| T02 | Source close100 Jan2, correction99.5 Jan5 -> Jan3 selects100; later finite V selects99.5 | 3,7 |
| T03 | Future-only source/historical methodology/offset authority/coverage -> unavailable at K; modern reconstruction capture alone is not a cutoff gate | 2,3 |
| S13 | Modern TZif/encoding captured after K agrees with historical offset authority -> eligible; only derivation identity changes | 2,7 |
| S14 | Unique modern conversion without historical offset authority -> indeterminate; source open row retained | 2,7 |
| S15 | Newer TZif changes past offset contrary to selected authority -> conflict, no rewritten UTC boundary | 2,7 |
| S16 | Same authoritative UTC under different reconstruction bytes -> same output values, different reconstruction lineage | 2,7 |
| S17 | Offset authority corrected after K -> old snapshot replays; later V may use new authority with agreeing TZif | 2,3,7 |
| S18 | Historical source-method availability crosses K -> authority changes; modern encoding capture crossing K does not | 1,2,7 |
| S19 | Foreign/hash-mismatched authority evidence or wrong fold -> fail closed despite plausible modern UTC output | 2,7 |
| S20 | Raw DATE/MINUTE authority stopped before ambient nested parsing; explicit UTC INTERVAL/SECOND paired case works without ambient lookup | 1,2,7 |
| S21 | Wrong policy encoding-schema or selected-methodology hash set -> replay failure even with identical UTC output | 2,7 |
| T04 | Outer outcome uses M1b K=V internal AS_KNOWN; moving V earlier removes later facts | 4,8 |
| T05 | Intrinsically early-published complete bar/realized outcome remains invalid at later K; corrected evidence can cure | 3,4 |
| T06 | Listing/date attribution A-to-B correction selects chain before subject filtering; no resurrected old A row | 1,3 |
| M01 | Absent row + all expected-row premises -> provider gap proven; never zero price | 4 |
| M02 | Absent with partial/current-only/unknown coverage -> provider gap not proven | 4 |
| M03 | Explicit no qualifying-price-trade marker -> price activity none; any activity independent | 4 |
| M04 | Conditional emission + absent row/zero volume/nullclose -> no inferred no-trade without positive evidence | 4 |
| M05 | Corrupt/missing artifact -> integrity error, no parsed absence or lifecycle conclusion | 1,4 |
| M06 | Not-yet-listed/full suspension/terminated interval -> unusable; old active pre-delisting bar still usable | 4 |
| M07 | Partial interruption with complete compatible aggregation passes; unknown treatment indeterminate | 4 |
| M08 | Multiple unknown axes all retained, no dominant missing reason | 4 |
| M09 | Present complete row with unrelated partial coverage -> source view allowed; normalization still checks actions | 4,6 |
| A01 | Exact first-ex-basis date proven actually open -> mapped | 5 |
| A02 | After early close -> next proven open only under explicit rule and complete intervening coverage | 5 |
| A03 | Before actual open -> current session; intraday/equal endpoint without designation -> indeterminate | 5 |
| A04 | Ambiguous date-only/legal date without basis meaning -> indeterminate | 5 |
| A05 | Closed/unknown/emergency source date -> no roll, indeterminate | 5 |
| A06 | Venue/listing/security mismatch -> no mapping | 5 |
| A07 | Corrected date or ratio after historical K -> old query unchanged; later query revised | 5,7 |
| A08 | Duplicate same occurrence -> factor once; conflicting reports crossing window edge -> block | 5,6 |
| A09 | Two sources report equal date/ratio -> not automatic equivalence; overlapping ownership blocked | 5,6 |
| A10 | Effect resolves to terms A but caller substitutes same-security terms B's date -> replay rejects; unresolved terms cannot supply a date | 5,7 |
| N01 | Jan100 plus June2-for-1, January decision ->100, no June selected-action/factor lineage; July authorized June anchor ->50 | 6,7 |
| N02 | Announced future split, K after announcement E before occurrence -> no factor | 6,7 |
| N03 | Future anchor, or July T/K with May E and June action/anchor -> denied | 6,7 |
| N04 | Forward2 and reverse1/10 -> exact reciprocal price/share factors | 6,7 |
| N05 | Sequential3/2 then2/3 -> exact Q1 before quantization; order permutation invariant | 6 |
| N06 | Dollar volume/trade count/lot count presented as share volume -> typed rejection | 6 |
| N07 | Same-session pure splits commute; unknown meaningful share-basis precedence -> indeterminate | 6 |
| N08 | Split plus cash-only dividend -> split units supported, no economic-return claim; affected unknown unit basis blocked | 6 |
| N09 | Incomplete/unsupported relevant action history -> no claimed complete factor; definitely irrelevant event harmless | 6 |
| N12 | Complete forward/reverse-split-only coverage omits stock-dividend/other classes -> incomplete required scope, normalization refused | 5,6 |
| N13 | Proven split with incomplete settlement evidence -> unit factors permitted; no claim of complete economic outcome | 5,6 |
| N10 | First-post source session -> factor1 for that occurrence; no double adjustment | 6 |
| N11 | Final half-even tie and positive-price-to-zero -> exact rounding/rejection; no intermediate float | 6 |
| P01 | Genuine proof with substituted selected row/date/q/schedule or omitted dependency -> replay rejects | 3,5,7 |
| P02 | Forged normalization/view/output/factors/reference -> complete dependent replay rejects after dump/load | 6,7 |
| P03 | Outcome reference/nested outcome input injected into decision -> type+query+role replay rejection | 3,6,7 |
| P04 | Same output under changed policy/code -> derivation/reference identities differ | 6,7 |
| P05 | Physical local path move with same bytes -> content identity unchanged; wrong bytes fail same-descriptor read | 1,7 |
| P06 | Input mutation between verify/use -> snapshot binds same content, substitution rejected | 3,6 |
| C01 | Old canonical/ledger/temporal/identity/economic contracts byte-identical and tested | 8 |
| C02 | M1c v1/v2 pinned replay actually executes; unavailable pin or tampered old bytes -> failing gate | 1,8 |
| C03 | No runtime provider/return/execution/network/dependency addition | 8 |
| P07 | Temporary semantic/shared/unrelated .py mutation changes package identity; non-.py edit/path relocation does not | 1,8 |
| P08 | Unimported .py addition changes nested M1c and joined M1d lineage/replay, not source facts or exact numeric values | 6,7,8 |

N01 also demonstrates that 100/50 and 200/100 can have the same ratio while a fixed dollar threshold differs. Neither observation authorizes future inputs; these arithmetic examples are test oracles, not implemented features/strategies.

## 9. Execution tasks and commit boundaries

Every task begins by reading its contract sections and named existing sources. Write the listed failing tests before implementation; an import failure is only initial RED, followed by semantic failures against a minimal implementation. Record exact command, relevant failure and later PASS in this plan's execution record. Fresh reviewer checks spec then adversarial behavior; controller replays material findings. Never have simultaneous writers on overlapping files. A task is accepted only after its focused tests and checks pass. Run the full gate after Tasks 1, 4, 6, 7 and 8; also after any shared-validator/proof change. At other bounded tasks run all newly affected tests and Ruff/mypy; no test is silently skipped.

The following snippets establish concrete test APIs. Task 1 builds the harness and exact input contracts; later methods are added only by their owning task. Parametrized matrix cases supplement these examples with exact oracles above.

Property-shaped requirements supplement the examples without adding Hypothesis or another dependency. Use deterministic pytest parameter products over positive coprime ratio numerators/denominators1..12, decimal scales0..6, and both forward/reverse factors: factor reciprocity, permutation invariance of pure split products, identity q1, exact source/output rational round-trip and final quantization ties. Construct valid inputs directly, no broad filtering. Serialize/deserialize each public proof/result/reference, then change one selected value, role, cutoff, or dependency and require replay failure. These bounded domain tests do not claim exhaustive testing of all rationals; they test algebraic laws rather than mirroring an implementation formula. Keep example-based tests for source-semantic and temporal scenarios where algebra alone says nothing.

### Task 1: Exact source contracts and honest legacy replay

**Files:** Task 1 row in section2; legacy test-only files in section10. **Reads:** `datasets/assertions.py`, `datasets/resolver.py`, `domain/temporal.py`, `markets/economic_validation.py`, `tests/unit/economic_test_support.py` under existing `src/drift/` or `tests/` roots.

**Produces:** contracts in section3; `validate_observation_dataset`, `m1d_implementation_hash`; validated dataset inputs; base harness exact bytes and query builders. Does not implement sessions/usability/action logic.

- [x] RED: exact decimal/string round-trip, unknown/mixed retention, selected-method foreign key, immutable revisions, strict manifests/record inventories, corrupt bytes, self-reference rejection, legacy lane success/failure oracles.
- [x] Run `uv run pytest tests/unit/test_observation_contracts.py tests/integration/test_m1c_pinned_replay.py -q`; observe the missing contracts, then behavioral validation failures.
- [x] GREEN: implement only frozen models and independent role-dispatch validator. Hash and parse the same verified bytes; rerun authentic structural/PASS/bundle validation, reject wrong rows/roles/version links/coverage inventory. Add explicit legacy lane before first new source file so the full gate remains meaningful.
- [x] Use concrete Decimal oracle, not float equivalence:

```python
from decimal import Decimal
from drift.domain.observations import SourceFieldValueV1


def test_source_decimal_round_trip():
    value = SourceFieldValueV1(
        field_name="close",
        method_id="last-v1",
        native_text="99.500",
        value=Decimal("99.500"),
        state="value",
        native_flag=None,
    )
    loaded = SourceFieldValueV1.model_validate_json(value.model_dump_json())
    assert loaded.value == Decimal("99.500")
    assert loaded.native_text == "99.500"
```

- [x] Fresh Terra ordinary schema review plus Sol observation semantics review; fix substantive findings with failing regressions first. Run full gate section11. Commit exact owned files only, subject `feat: add exact source observation contracts` after authorized commit gate.

### Task 2: Explicit schedules, realized outcomes, pinned conversion

**Files:** Task2 row. **Consumes:** Task1 audited inputs/query/proof types; existing availability/resolver. **Produces:** section4 models, `generate_schedule`, `verify_schedule`, `validate_session_dataset` and fixed session fixture helpers.

Task 2 may add session datasets and closed role dispatch to the shared M1d context, and session-specific subjects to the shared proof family. Select the calendar publisher through its role-specific policy binding, not the bar's `query.source_id`. A narrow session selector is required here for generation before Task 3's generic observation selection exists; Task 3 must reuse it. Preserve observation role/type/subject guards. A small typed selected-session container beside session models is permitted to avoid circular imports while reusing the same proof family. These are dependency-preserving M1d additions, not changes to older contracts or a second query engine.

- [x] RED: S01/S02/S04/S06/S08/S09 and S13-S19, distinguishing unknown historical offset authority from modern reconstruction capture. Build a finite synthetic TZif with explicit transitions and documented bytes; do not load a system timezone as the oracle.
- [x] Run `uv run pytest tests/unit/test_session_artifacts.py -q`; verify failures specifically concern conversion, availability, realized/source independence and identity.
- [x] GREEN: implement explicit-row conversion and full input/output replay; retain source rows separately from query-bound generated artifact. Implement independent realized axes with no required schedule dependency.
- [x] Test core standard-library conversion against the exact fixture:

```python
from datetime import datetime, timezone
from io import BytesIO
from zoneinfo import ZoneInfo
from session_test_support import timezone_bytes


def test_retained_synthetic_winter_and_summer():
    zone = ZoneInfo.from_file(BytesIO(timezone_bytes()), key="Synthetic/Eastern")
    winter = datetime(2026, 1, 5, 9, 30, tzinfo=zone).astimezone(timezone.utc)
    summer = datetime(2026, 7, 6, 9, 30, tzinfo=zone).astimezone(timezone.utc)
    assert winter.isoformat() == "2026-01-05T14:30:00+00:00"
    assert summer.isoformat() == "2026-07-06T13:30:00+00:00"
```

- [x] Independently review causal provenance and fold/endpoint attacks with fresh Sol. Focused tests, Ruff and mypy. Commit `feat: add immutable scheduled and realized sessions` with exact owned paths after authority gate.

### Task 3: Causal selection and observation/session binding

**Files:** Task3 row; extend owned harness methods for selection/binding. **Consumes:** audited Task1/2 contexts. **Produces:** `select_observation_records`, verifier, binding functions and proof family section2/4. Every consumer verifies selected-value equality, not just hash agreement.

- [x] RED: T01/T02/T03, S03/S05/S07/S10/S11, O04/O05 and P01/P03/P06. Include empty verified inventory distinct from unknown coverage.
- [x] Run `uv run pytest tests/unit/test_observation_selection.py tests/unit/test_session_binding.py -q` and observe historical revision/session substitution failures.
- [x] GREEN: use M1a finite revision/availability selection on each family, never latest; source/contract/coverage cutoffs independently checked. Bind against actual bounds and explicit label/endpoint semantics; retain schedule comparison separately.
- [x] Concrete regression uses two immutable source revisions:

```python
from observation_test_support import ObservationHarness
from drift.markets.observation_selection import select_observation_records


def test_correction_does_not_rewrite_prior_selection():
    h = ObservationHarness()
    old = h.decision(
        "2026-01-05T22:00:00Z",
        "2026-01-05T22:00:00Z",
        "2026-01-05T22:00:00Z",
        "2026-01-05",
    )
    original_context = h.context
    before = select_observation_records(old, "observation", original_context)
    h.replace_source_revision(close="99.5", available_at="2026-01-08T00:00:00Z")
    expanded = h.decision(
        "2026-01-05T22:00:00Z",
        "2026-01-05T22:00:00Z",
        "2026-01-05T22:00:00Z",
        "2026-01-05",
    )
    after = select_observation_records(expanded, "observation", h.context)
    assert before.records == after.records
    assert old.input_context_hash != expanded.input_context_hash
    assert select_observation_records(old, "observation", original_context) == before
```

The harness replaces its frozen context rather than mutating `original_context`. Old proofs replay only against their original retained snapshot. Pair this test with an assertion that the old query plus expanded context is rejected. Context/query/proof hashes change when retained future evidence is added; historical selected values do not. Apply the same rule to schedule-correction S07: replay the old artifact against old inputs; a new inventory requires a freshly bound query even if UTC output matches. Future-only facts must not be projected into decision payload/diagnostic facts; inventory provenance is not authorization to expose them.

- [x] Fresh Sol temporal/session review; replay every Important finding. Focused tests plus old temporal tests and Ruff/mypy. Commit `feat: bind causal observations to historical sessions` after authority gate.

### Task 4: Orthogonal missingness and narrow research usability

**Files:** Task4 row; add harness `assess`. **Consumes:** selection/binding and unchanged M1b public folds with exact context rebuild. **Produces:** section5 functions/results. Do not produce factors or action mapping here.

- [x] RED: M01 through M09, O01/O02/O03/O06/O07/O08 and T04. Pair missing/zero/explicit marker to prove they do not collapse to one reason. Pair historically active delisted listing with post-termination interval.
- [x] Run `uv run pytest tests/unit/test_observation_usability.py -q`; observe false provider-gap/no-trade and interval/lifecycle leakage failures.
- [x] GREEN: implement independent axis derivation and necessary-condition composition; reuse M1b AS_KNOWN finite-C queries, not copied folds. Do not turn partial interruption into full suspension or require unrelated dataset completeness.

```python
from observation_test_support import ObservationHarness


def test_same_day_close_is_not_available_at_open():
    h = ObservationHarness()
    q = h.decision(
        "2026-01-05T14:30:00Z",
        "2026-01-05T14:30:00Z",
        "2026-01-05T14:30:00Z",
        "2026-01-05",
    )
    result = h.assess(q)
    assert result.usability != "usable"
    assert result.provider_gap == "not_proven"
```

- [x] Independent Sol missingness/adversarial review plus Terra unchanged-M1b compatibility review. Full gate. Commit `feat: compose historical observation usability` after authority gate. This is the preservation review boundary, not milestone completion.

### Task 5: Verified M1c action-to-session application boundaries

**Files:** Task5 row; extend harness with exact M1c occurred effects/coverage. **Consumes:** unchanged M1c selection/facts/context, Task2/3 sessions. **Produces:** section6 models/functions and only mapping results, no normalized prices.

- [x] RED: A01 through A08, relevant S03/S07, P01/P03; make the fixture prove selected terms dates cannot be substituted and announcement alone cannot become occurrence.
- [x] Run `uv run pytest tests/unit/test_action_sessions.py -q`; observe date-role/closed-date/occurrence/dependency failures.
- [x] GREEN: implement narrow verified date projection, exact venue matching, explicit mapping modes, complete intervening date coverage, exact same-occurrence conflict comparison. Do not extend M1c safe projection or infer legal-date semantics.
- [x] Required table-driven oracle uses existing fixed corpus: ex-basis Nov26 closed -> indeterminate; exact basis Nov27 18:05Z under after-close rule -> Nov30; Nov27 14:00Z before-open -> Nov27; Nov27 16:00Z intraday -> indeterminate. Execute all four cases through `map_action_to_session`, not a test-only mapping shortcut.

```python
import pytest
from observation_test_support import ObservationHarness


@pytest.mark.parametrize(
    ("basis", "mode", "expected", "date"),
    [
        ("2026-11-26", "explicit_first_basis_date", "indeterminate", None),
        (
            "2026-11-27T18:05:00Z",
            "exact_trading_basis_transition",
            "mapped",
            "2026-11-30",
        ),
        (
            "2026-11-27T14:00:00Z",
            "exact_trading_basis_transition",
            "mapped",
            "2026-11-27",
        ),
        (
            "2026-11-27T16:00:00Z",
            "exact_trading_basis_transition",
            "indeterminate",
            None,
        ),
    ],
)
def test_mapping_has_no_implicit_date_roll(basis, mode, expected, date):
    result = ObservationHarness().map_action(basis, mode)
    assert result.classification == expected
    assert (
        result.first_post_session.local_date.isoformat()
        if result.first_post_session is not None
        else None
    ) == date
```

`SessionKeyV1` stores its local date as `local_date`; `FirstPostActionSessionResultV1` names its optional key `first_post_session`. The table's helper arguments gain concrete Literal/string annotations in the future test module, without changing the oracle.
- [x] Fresh Sol M1c/session adversarial reviewer verifies exact selected source dates and source authority. Focused new and M1c action tests plus Ruff/mypy. Commit `feat: map economic actions to session share basis` after authority gate.

### Task 6: Causal source-basis and split-normalized views

**Files:** Task6 row; harness normalization methods. **Consumes:** proven usability and mapped occurred effects with complete relevant action coverage. **Produces:** section7 result/view/reference/materializer families, exact factors and final quantization.

- [ ] RED: N01 through N11 and P02/P03/P04/P06. Numeric happy path alone is insufficient: a forged factor with correct output must fail replay. Source-basis path must pass with no economic context.
- [ ] Run `uv run pytest tests/unit/test_normalization.py -q`; record future-anchor/effective-cutoff/role and exact-rational failures before fixes.
- [ ] GREEN: implement source-basis and exact split algorithm section7 with no cash/returns. Use exact Fraction accumulation and integer half-even code shown there; serialize canonical rational components. Rebuild all dependencies from snapshot on every materialization.

```python
from drift.domain.normalization import ExactRatioV1
from drift.markets.normalization import compose_split_factors


def test_reciprocal_composition_without_intermediate_rounding():
    factors = compose_split_factors(
        (
            ExactRatioV1(numerator="3", denominator="2"),
            ExactRatioV1(numerator="2", denominator="3"),
        )
    )
    assert tuple((f.numerator, f.denominator) for f in factors) == (
        ("1", "1"),
        ("1", "1"),
    )
```

- [ ] Fresh Sol causal/normalization review, separate from mapping implementer. Full gate including current-code M1c composition and pinned legacy fixture lane. Commit `feat: derive cutoff-safe split observation views` after authority gate.

### Task 7: Immutable joined fixture and adversarial acceptance

**Files:** Task7 row only, except concrete regressions may fix owned M1d source through RED/GREEN. **Consumes:** public interfaces Tasks1-6. **Produces:** exact synthetic manifest/source/session/TZif/policy/action/expected-decision/outcome/derivation bytes with an independently pinned hash index at `tests/fixtures/m1d/v1/`.

- [ ] RED: every matrix ID has a named joined test or explicit focused-test pointer; at minimum O01,T02,S03,S07,A01-A08,N01-N04,O07 and P01-P06 execute the full source->session->M1b->M1c->normalization->reference->materializer path.
- [ ] Run `uv run pytest tests/integration/test_m1d_observation_history.py tests/integration/test_m1d_action_normalization.py tests/integration/test_m1d_adversarial_matrix.py -q`; demonstrate failures under selected-value, future-role and factor substitutions.
- [ ] GREEN: write exact synthetic fixture once accepted; generator is test support, never a provider adapter. Fixture generation must not overwrite accepted v1; subsequent code-bound changes require explicit new fixture version or pinned-code replay, never rebinding old bytes.
- [ ] Test replay semantics explicitly:

```python
from drift.domain.normalization import NormalizationResultV1
from drift.markets.normalization import verify_normalization


def assert_roundtrip_replays(result, context):
    loaded = NormalizationResultV1.model_validate_json(result.model_dump_json())
    verify_normalization(loaded, context)
    assert loaded == result
```

The integration tests supply public normalized results and exact retained contexts; this helper is not a substitute for constructing them or for forged-copy negative cases. Give test helper arguments concrete `NormalizationResultV1` and `M1dResolutionContext` annotations when implemented.

- [ ] Fresh Sol independently attacks joined causality and Terra checks fixture inventory/role compatibility. Controller checks matrix completeness and actual failures. Full gate. Commit `test: prove joined historical observation normalization` after authority gate.

### Task 8: Compatibility, forbidden scope, canonical completion

**Files:** Task8 row; `AGENTS.md`, `README.md`, `docs/architecture/roadmap.md`, `docs/architecture/overview.md`, ADR0009/spec lifecycle and this plan, only to record actually accepted implementation. **Consumes:** all exact acceptance evidence. **Produces:** completed canonical M1d status, not provider/evaluator readiness.

- [ ] RED if any old contract bytes/source/fixture silently changed, pinned replay lane skipped, matrix case missing, new dependency or forbidden runtime capability exists. Compare protected paths against planning baseline; classify every difference, fail on unauthorized old contract modification.
- [ ] Run complete compatibility/full gate section11, explicitly inspect archived v1/v2 subprocess results and current-code cross-layer tests.
- [ ] GREEN: fix only demonstrated M1d regressions; if older persisted contract must change, STOP for user decision instead of adapting it. Record task commits, RED/GREEN, reviewer outcomes and deliberate limitations in execution record.
- [ ] Fresh independent final review across six lenses; controller validates every Important/Critical finding. Stop polishing once no material defect remains.
- [ ] Commit exact canonical completion docs/tests only, `docs: complete M1d synthetic observation milestone`, if future commit authority allows. Run Checkpoint and STOP. No provider bake-off, evaluator plan, implementation of later capability, or clean-completion handoff.

## 10. Protected M1c replay lane

This test-only migration is necessary in Task1 because whole-package fingerprints change as soon as new source files exist. The older persisted contracts and fixture bytes are not modified. Pin v2 interpreter source to `aecee94207dbd64aa5154fe03295f35566ec7268`; pin v1 interpreter source to `4d54d7e553beba8cdd5413ea1181e7efac7a236b`.

Create `tests/_pinned_m1c.py`, `tests/integration/test_m1c_pinned_replay.py`, and a narrowly scoped `tests/conftest.py` hook. Do not add test package `__init__.py` files. The invariant is no skip, fake PASS, narrowed fingerprint, modified old test module, or re-signed old fixture. The six unchanged cases in `tests/integration/test_m1c_economic_history.py` execute under the exact v2 baseline source. Actual archived v1 replay executes the four original cases under the v1 source, not merely a content-hash check.

Use `pytest_pyfunc_call(pyfuncitem)` for exactly the resolved legacy module path plus these literal names: `test_m1c_fixture_preserves_installment_lineage`, `test_m1c_fixture_selects_corrected_installment_revision`, `test_m1c_fixture_rejects_pinned_partition_tampering`, `test_m1c_fixture_rejects_expected_hash_index_tampering`, `test_m1c_v1_bytes_remain_valid_but_replay_requires_pinned_code`, `test_m1c_v2_preserves_v1_economic_source_facts`. Return `None` for every other node. For each intercepted node run that identical node under the baseline child; return `True` only after child exit0, otherwise fail that same item with captured output. Verify the complete module's defined six-node inventory, not equality with the user's intentionally selected subset: an ordinary focused `module.py::test_name` invocation must still execute that one archived node. New/missing/renamed definitions or unexpected selected module nodes fail visibly. A standalone parametrized extra test is insufficient because it leaves the original current-code tests failing. The new `test_m1c_pinned_replay.py` runs actual archived v1 four cases and negative routing/isolation/pin/tamper tests.

The runner must verify current protected baseline source files, the unchanged legacy test module and current v1/v2 fixture bytes against literal path/SHA-256 pins recorded in the test-only helper before routing; new M1d files are additive and not in the old pin. Pin every baseline `src/drift/*.py`, old module/helper and v1/v2 fixture file, plus lock/project bytes; expected digests are not regenerated from mutable inputs. Extract via local `git archive` the pinned `src/drift`, legacy history module, `tests/unit/economic_test_support.py`, relevant v1/v2 fixture directories, `pyproject.toml`, and `uv.lock` into a bounded `TemporaryDirectory`, with no install/network. A read-only planning probe executed both exact archives successfully: baseline six cases and archived v1 four cases.

Use `sys.executable` from the locked environment; child cwd is archive root, `PYTHONPATH` is replaced with exactly archive/src and archive/tests/unit, `PYTHONNOUSERSITE=1`, `PYTHONDONTWRITEBYTECODE=1`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`; remove inherited `PYTEST_ADDOPTS`, disable cache provider. Verify child imported `drift.__file__` is inside the archive. No current imported Drift objects cross the subprocess. Archive must lack the new conftest; a `DRIFT_PINNED_REPLAY_CHILD` marker additionally refuses recursion. One session cache keyed by literal commit is cleaned with context-manager/finalizer cleanup, never stored in the repository. Archive identity, exact test node set and child failure propagate in pytest output. Missing commit, extraction error, missing test, changed lock/Python floor, altered protected file, or any child failure fails the parent gate. All other M0-M1c tests run against current installed source, including new M1d/M1c integration. This is code-bound compatibility verification, not full retained-environment reproducibility.

## 11. Verification and independent execution routing

Run from the real project root:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv build
git diff --check
```

Explicit compatibility command, in addition to the full suite:

```bash
uv run pytest tests/integration/test_replay.py tests/integration/test_m1_m0_compatibility.py tests/integration/test_m1b_m1a_compatibility.py tests/unit/test_assertions.py tests/unit/test_dataset_validation_v2.py tests/unit/test_listing_semantics.py tests/unit/test_security_identity.py tests/unit/test_universes.py tests/integration/test_m1c_action_matrix.py tests/integration/test_m1c_economic_history.py tests/unit/test_m1c_final_hardening.py -q
```

After Task1, also explicitly run `tests/integration/test_m1c_pinned_replay.py`; after Task8 include `tests/integration/test_m1d_compatibility.py`. Old canonical/ledger tests remain in full suite. Verify old source/fixture hashes, canonical serialization, temporal finite cutoffs, identities/lifecycle/universes, economic terms/effects/settlements/outcomes, and actual pinned v1/v2 replay. No monkeypatching implementation hashes or quietly dropping failing legacy tests.

Inspect every new import and behavior for prohibited capabilities, not mere word matching. Search `src/drift` for `requests|httpx|socket|urllib|broker|robinhood|alpaca|backtest|portfolio|strategy|return|credential|agent`; existing descriptive references and Python return statements are not capabilities. Inspect all matches in changed files and verify dependency/lock/Python requirements unchanged. Price values in the authorized synthetic observation layer are not network feeds. Verify new source contains no dynamic code execution, credentials, external acquisition, fill/trading machinery or feature/return computations.

Future routing: Astra orchestrates and accepts; Luna performs bounded inventories/matrix checks; Terra implements ordinary schema/test/context work; Sol implements/reviews load-bearing selection/session/normalization semantics. Use fresh minimal context: task objective, exact owned files, sections/interfaces, baseline and current task commits, tests, exclusions. Parallelize only read-only reviews or disjoint owned files after interfaces are fixed. Reviewers do not self-approve their implementation. Model name is not evidence. Escalate repeatedly inadequate bounded work Luna->Terra->Sol->Astra rather than retrying indefinitely.

## 12. Planning acceptance and future execution record

Planning-only state: one M1d executable plan, no runtime/test/fixture/dependency changes. Baseline full gate observed 1093 tests passing, Ruff/format, mypy (86 files), build and diff check passing. Final planning review/verification is recorded below before commit. Planning commit identity is obtained from Git history for this file; do not attempt a self-referential commit hash in its own content.

At the planning checkpoint, execution tasks 1 through 8 were not started and required separate authorization. That authorization has now been supplied; current execution state is recorded above and in the acceptance entries below. Deferred provider acceptance must establish actual field/population rules, licensing/retention, exact historical schedule corpus, revision capture and coverage. Runnable environment closure belongs before promotion-quality experiments. These deferred gates do not authorize provider selection or evaluator design here.

### Execution preflight rulings, 2026-09-07

Two independent Sol challenges were required by the new implementation authorization. The controller checked their live-code evidence and primary references. A fresh independent Sol preflight review is now PASS: its raw-precision guard, explicit policy-to-methodology hash edges, and truthful regular-file fingerprint scope findings were resolved before Task1/2 scientific contract acceptance. The existing five implementation-hash tests also passed during that review. Current Task1 implementation remains subject to its separate code/spec/adversarial review and full gate.

Ruling A: Separate historical information/methodology/offset authority from modern reconstruction provenance. The all-input cutoff rule was conservatively useful against modern corrections but falsely made historical eligibility depend on when a literal replay tool was captured. Removing that gate alone would let newer timezone data rewrite past UTC boundaries. The smallest correction is exact row-bound historical offsets/methodology with M1a availability, plus equality between independently authoritative UTC and pinned TZif conversion. Unknown authority is retained but yields no eligible boundary. [IANA](https://data.iana.org/time-zones/theory.html) documents corrected/uncertain timezone history; [Python](https://docs.python.org/3.14/library/zoneinfo.html) distinguishes supplied TZif bytes from ambient lookup. Cost if wrong: added provenance fields and conservative indeterminacy for inadequately sourced offsets, rather than silent historical rewriting. No older contract or calendar engine changes.

Ruling B: Retain one whole-package M1d v1 fingerprint and reuse the unchanged accepted package-inventory function. A read-only import probe found a30-of48-file M1c import closure, but this omits a real behavior dependency: `economic_implementation_hash` reads all installed Drift Python files and binds replay-checked M1c results consumed by M1d. Following that file-read dependency makes the full scientific closure whole-package. Narrower source-only identities could reduce churn, but would require a separate capability-scoped contract and would not stop joined M1c-dependent churn. Cost if wrong: visible unnecessary source-only invalidation and future replay maintenance; an incomplete narrow closure risks silent false equivalence. Mutation tests P07/P08 make the conservative cost explicit. Semantic rules, implementation identity and historical authority remain distinct.

Ruling C: Task6 materializers take the full normalization query explicitly, following the existing M1c reference-resolution pattern. The initial reference-plus-context signature supplied only hashes, so no consumer could recover arbitrary T/K/E or H/V, policy and anchor without an unplanned registry or cyclic input context. Keep references compact and hash-bound, but define/test them with their Task6 consumer rather than as unused Task1 types. Cost if wrong: one explicit argument and deferred type placement; no older contract changes or new continuity/artifact registry. Query substitution remains a required replay attack.

### Reviewed planning acceptance, 2026-09-07 (historical)

Three fresh independent Sol reviewers covered all six requested lenses: source semantics and missingness/usability; temporal leakage and M1c integration; sessions/timezone provenance and compatibility/scope. All accepted the repaired plan with no open Important or Critical finding. The controller checked the reported API/coverage/association counterexamples against live source and independently reran the finite-cutoff and archived-code probes.

Twelve material review findings were resolved before planning acceptance: exact fallback equivalence/branch triggers; selected population-containment endpoints; diagnostic versus verified assessment types; raw validator bootstrap; tri-state realized assertions; retained policy values; per-field adjustment basis; required action-class coverage; same-owner occurrence scope; exact effect-to-terms association; original versus expanded context replay; and settlement API structure without an accounting-completeness gate. Additional controller checks pinned intrinsic chronology, chain-before-attribution selection, interval lifecycle composition and opaque inventory versus consumer authority. These are planning repairs, not claims that M1d runtime tests exist or pass.

The final plan has eight execution tasks and 70 named acceptance-matrix rows. No material stop condition was reached. M1d remains one milestone. Full pre-commit repository gate passed: 1,093 tests (33.64s), Ruff lint, format (117 files including this plan), mypy (86 files), source/wheel build, and whitespace check. The explicit M0-M1c compatibility selection passed 443 tests. Independent controller temporary-archive probes passed all six baseline M1c history cases and all four archived v1 cases. Local documentation links, current lifecycle/stale-plan search, U+2014 and protected-path checks passed. All five unrelated `.DS_Store` hashes and the historical M1b handoff hash match preflight and remain excluded.

Publication scope is exactly this plan plus minimal lifecycle edits to AGENTS, README, roadmap, overview, ADR0009 status/consequences and the design's lifecycle paragraphs. Completed M1c execution history remains untouched. No runtime source, tests, fixtures, dependency/lock/Python requirement, provider, evaluator or trading change was made. The planning publication subject is `docs: plan M1d observations sessions and normalization`; its actual commit and post-commit Checkpoint must be verified from Git and reported after publication. STOP after that Checkpoint; no clean-completion Session Handoff is needed.

### Task 1 acceptance, 2026-09-08

Task 1 adds immutable source observation/methodology/coverage models, role-specific queries and proof shapes, exact source dataset validation, immutable audited contexts, and the test-only pinned M1c replay lane. Terra implemented the legacy lane; Sol implemented the scientific contracts. Fresh Terra and Sol reviewers independently checked schema/quality and adversarial integrity. Both reviews are clean after bounded repairs, with no open Important or Critical finding.

The controller reproduced the substantive defects before accepting fixes: editable pin inventory, focused-node collection failure, cross-role and future-purpose record relabeling, foreign fallback ownership, unrelated support metadata mistaken for temporal evidence, malformed bundle metadata, and query-to-record subject mismatch. The raw chronology finding was corrected through evidence-based review: raw contradictory source claims remain retained; Tasks 3/4 must deny completed authority. A different valid bundle is a new valid identity, while malformed constructor-bypassed metadata fails replay. No original-bundle registry was added.

The legacy lane's first RED was only an absent helper. Its subsequent guard-removal remediation and later genuine inventory/focused-node REDs are recorded honestly, not substituted for an invented original sequence. Scientific implementation used behavioral REDs for scalar, contract, row, query, validator and context guards. Fix round 1 addressed eight review/type groups; fix round 2 observed 12 subject mismatch failures before the corresponding guards, with the valid inclusive coverage boundary preserved.

An initial controller gate passed 1,135 tests but failed full mypy with 110 errors in the new test file omitted by the narrower worker check. The repaired final controller gate passed `uv run pytest` with 1,159 tests in 42.96s; Ruff lint and format (126 files), `uv run mypy src tests` (94 files), `uv build`, and working/index whitespace checks all passed. The source-plus-legacy focused run passed 66 tests, including actual archived M1c replay. The literal six-node lane also preserves single-node invocations and checks exact old module definitions and immutable inventory bytes.

All changes are additive M1d source/tests plus this execution record. Protected M0-M1c source/tests/fixtures, dependency/lock/Python settings, all five unrelated `.DS_Store` files and the old M1b handoff remain unchanged. No provider, networking, broker, credentials, runtime agent, database, session implementation, normalization, evaluator or trading capability was added by Task 1. Task 2 begins only after the planned `feat: add exact source observation contracts` publication and Checkpoint. Its session interfaces will extend the new context additively and select calendar sources by role-specific policy bindings, not by the observation provider ID.

### Task 2 worker-output checkpoint, 2026-09-08: NOT ACCEPTED

Baseline and current HEAD: `0f2aa6d89b49401f77af225655d61ca2f522553d`. Task 2 commit: **none**. The Sol worker completed its bounded assignment with `DONE_WITH_CONCERNS`, froze all files, and made no staging or commit changes. Per the user's latest stop instruction, the controller did not start a fresh acceptance review or fix loop. Task 2 execution checkboxes remain unchecked because worker completion and passing checks are not acceptance.

Preserved output: new `domain/sessions.py`, `markets/session_generation.py`, `markets/session_validation.py`, `tests/unit/test_session_artifacts.py` and `tests/unit/session_test_support.py`; bounded shared changes in `domain/observation_query.py` and `markets/observation_validation.py`. Production paths are under `src/drift/`. These implement source schedule/coverage/realized models, exact session validation, finite role-bound selection, retained TZif conversion against independent historical offset authority, and query-bound generation/replay. No Task 3 observation selector, usability, action mapping, normalization, provider or evaluator work was started.

Continuation interfaces: `ScheduleArtifactV1` retains its full query and generation policy beside their hashes; `verify_schedule(artifact, context)` therefore has the data needed to replay. `SessionSubjectV1` contains source/MIC/local-date/regular-scope fields. `SelectedSessionRecordsV1` reuses the shared `M1dSelectionProofV1`, while `M1dSelectedRecordsV1` stays observation-only. Task 3 should reuse or extract the Task 2 finite `_select_record` semantics rather than introduce a second proof family. Session publishers are selected from role-specific policy bindings, not from the bar query's source ID.

Worker report and detailed RED/GREEN history: `.superpowers/sdd/2026-09-07-m1d-source-observations-sessions-normalization/task-2-report.md`. Review these three explicitly reported concerns before accepting Task 2:

1. The shared proof still accepts an observation-subject shape for a session purpose to preserve an earlier Task 1 construction test. The selected-session container requires `SessionSubjectV1`; independently review whether this compatibility seam is justified.
2. Ambiguous-fold and nonexistent-local-time branches have round-trip guards, but direct synthetic transition-hour cases were not added. Required Task 2 coverage for those branches remains an acceptance question, not a waived requirement.
3. Session coverage replay uses a permissively typed internal helper to avoid a shared-container import cycle. Review that boundary and exact replay behavior.

Fresh controller Checkpoint evidence on the frozen runtime state: `uv run pytest tests/unit/test_session_artifacts.py tests/unit/test_observation_contracts.py -q` passed **89 tests in 1.66s**; full `uv run pytest` passed **1,192 tests in 44.83s**; `uv run ruff check .`, `uv run ruff format --check .` (131 files), `uv run mypy src tests` (99 files), `uv build` and `git diff --check` all passed. The full suite includes the pinned M1c replay lane. This verifies the reported snapshot, not the unperformed independent acceptance review.

Index is empty. Task 2's shared-file edits and this plan are tracked modifications; the five new Task 2 files are untracked. The existing minimal M1d handoff remains untracked. All five unrelated `.DS_Store` hashes and the historical M1b handoff hash match the saved baseline; dependencies/lockfile are unchanged. No Task 2 commit is claimed or created for unreviewed work. Resume from Git plus this record, review/finish Task 2 acceptance, then proceed to the still-unstarted Task 3 only in the fresh authorized continuation.

### Task 2 acceptance, 2026-09-08

A fresh Sol continuation reproduced the frozen 89-test baseline and independently reviewed the exact uncommitted Task 2 snapshot. The review rejected the first candidate with five Important findings and one Minor runtime-topology finding. The controller independently reproduced each issue before repair: false unretained reconstruction identities still generated and replayed; nested source-temporal evidence could be missing while validation returned PASS; an observation-shaped subject could claim a session-purpose proof; realized-session payload substitution survived direct model validation; named S02/S08/S09/S17-S19 public-path oracles were incomplete; and typed context slots were not enforced at runtime.

The original Task 2 implementer remained the only source writer for three bounded behavioral repair rounds. Fix round 1 closed exact reconstruction-lineage retention and running implementation identity, recursive nested evidence closure, strict session subjects, realized payload self-hashes, context-slot allowlists, and acyclic coverage-helper typing. Fix round 2 added direct constructor and serialized payload attacks plus genuine public schedule cases for sparse coverage, producer-only provenance changes, authorized UTC changes, ambient lookup resistance, and corrected historical offset authority across separate old/new contexts. A scoped reviewer found the ambient sentinel patched the wrong imported symbol; fix round 3 corrected it with a live proxy on the generator-owned `ZoneInfo` binding that permits retained-byte `from_file` and rejects direct ambient construction. Fresh Sol scoped re-reviews closed every finding with no new Important or Critical issue.

The three inherited worker concerns were substantiated as follows. The proof-subject compatibility seam was a genuine Important contract defect and was removed. Missing direct DST fold/gap coverage was a genuine Important acceptance gap; the underlying retained-byte conversion behavior was correct and now has public-path fold, gap, wrong-fold, and ambient-lookup tests. The permissive helper type was only partly a defect by itself, but it exposed a genuine Minor unchecked context-slot topology; both the runtime invariant and structural typing were repaired.

Final controller acceptance gate on the reviewed snapshot: source/session focused tests passed 118 in 3.07s; full `uv run pytest -q` passed 1,221 in 44.95s; Ruff lint and format (131 files), mypy (99 source files), source/wheel build, and `git diff --check` passed. The full suite includes actual pinned M1c replay. Task 2 remains additive and preserves source schedule, realized outcome, reconstruction provenance, and historical authority as separate facts. No M0-M1c persisted contract, dependency, provider, network, broker, evaluator, return, portfolio, or trading capability changed. The accepted publication subject is `feat: add immutable scheduled and realized sessions`; its exact hash is obtained from Git history after publication rather than embedded self-referentially here.

### Task 3 acceptance, 2026-09-08

One fresh Sol implementer added finite observation/session selection, complete selection replay, and exact observation-to-realized-session binding. A bounded extraction removed the duplicate Task 2 selector while preserving its semantic algorithm identity. Public selection now covers all six purposes through honest observation, session, and contract facades. Old proofs replay only against their original context; retained future revisions can change context identity without rewriting an earlier selected value. Exact present observations bind only through independently selected realized intervals and explicit field-used endpoint/auction semantics. Schedule and coverage facts remain separate diagnostics rather than substitute authority.

Fresh Sol review rejected the first candidate with one Critical and four Important findings. The controller reproduced future realized-outcome exposure, a private policy-bypassing contract path, arbitrary-population endpoint checks, rejection of schema-permitted equivalent overlaps, and dataset-wide coverage incorrectly blocking an exact present row. The repaired design adds a closed completion-evidence companion referenced by the existing realized record. Exact-bounds opened reports use actual close; did-not-open and opened-without-bounds reports require exact source completion plus a matching availability witness that does not predate completion. This preserves accepted Task 2 record bytes, keeps availability distinct from event completion, and prevents later cutoffs from curing intrinsically early publication. Contract selection uses an additive audit facade with exact policy, manifest, methodology, cutoff, and replay binding. Equivalent overlaps collapse only on identical authority; relevant endpoint rules come only from field-used populations.

Two scoped Sol re-reviews found and closed residual backdating and extra-methodology inventory defects. A final test-only round converted both live probes into durable regression tests. Fresh controller acceptance passed 44 Task 3 tests in 8.44s, 231 affected Task 1/2/temporal tests in 11.49s, and all 1,265 tests in 54.65s. Ruff lint, format (135 files), mypy (103 source files), source/wheel build, and `git diff --check` passed. No Task 4 missingness, M1b/M1c action use, normalization, dependency, provider, network, broker, evaluator, return, portfolio, or trading capability was added. The accepted publication subject is `feat: bind causal observations to historical sessions`; its exact hash is obtained from Git history after publication.

### Task 4 acceptance, 2026-09-09

Task 4 adds orthogonal assessment/read-failure contracts, narrow source-profile admission, conjunctive provider-gap proof, scheduled research eligibility, and finite M1b interval composition through unchanged public AS_KNOWN folds at outer C=K/V. Missing, null, zero, sentinel, source adjustment, integrity, coverage, schedule, realization, listing state, and activity remain separate axes. Nonusable or indeterminate results expose no numeric view. A complete present fact does not require dataset-wide completeness; absence and provider gap do.

Parallel Sol and Terra reviews rejected the first candidate. The controller verified incomplete structural boundary coverage, ignored unknown boundaries, incomplete venue-transfer dependencies, unproved partial-suspension aggregation, noncausal coverage snapshots, inferred M1b channel fallback, future-correction poisoning, corrupt reads masking forged context/policy, realized-outcome coupling in scheduled eligibility, and binding-first erasure of intrinsic profile failures. The repaired implementation sweeps every relevant selected M1b structural fact family, treats exact boundaries as half-open, preserves relevant bounded/unknown uncertainty, and supplies full identity/relationship dependencies. Partial suspension requires a closed exact interruption-aggregation artifact plus matching realized intervals. Coverage snapshot completion and availability chronology are causal. M1b channel selection is explicit and context-hashed. Present-row cutoff follows the selected witness; later unavailable corrections stay audit-side. Query/context/policy authority is checked before typed read errors. Scheduled eligibility uses an exact retained generation policy and schedule artifact but grants no realization, tradability, or bar usability.

Scoped Terra and Sol re-reviews found two residual Important defects: a bounded uncertainty ending exactly at a segment start was falsely overlapping, and incomplete generation-policy lineage checks could still be masked by corrupt observation bytes. Fix round 2 corrected the half-open predicate and extracted one shared Task 2 policy validator used both by generation and Task 4 pre-read authority checks. Both scoped re-reviews then approved with no new Critical or Important issue.

Fresh controller acceptance passed 69 Task 4 tests in 54.06s, 106 Task 2/3 tests in 11.00s, 339 M1b identity/universe tests in 3.82s, and all 1,334 tests in 109.88s. Ruff lint, format (138 files), mypy (106 source files), source/wheel build, and `git diff --check` passed. M1b persisted models, resolvers, enums, fixtures, and all M0-M1c contracts remain unchanged. No action mapping, normalization, provider, network, dependency, broker, evaluator, return, portfolio, backtest, or trading capability was added. The accepted publication subject is `feat: compose historical observation usability`; its exact hash is obtained from Git history after publication.

### Task 5 acceptance, 2026-09-11

Task 5 adds exact action-date methodology, action/session queries, locator-free date projections, truthful transition claims, and replayable first-post-session mapping. It replays unchanged M1c source policy, selections, facts, effect-to-terms associations, all three family owners, and complete fourteen-class terms/effect coverage. Only a positive occurred same-security pure forward/reverse split can map. Settlement incompleteness remains audit-only for this unit boundary. No factor or normalized value is authorized.

Fresh Sol review rejected the first candidate with five Important findings. Root verified effect source and date-bearing terms source conflation, unrelated terms hashes in effect-time mode, false strict relationships at designated endpoints, UTC-calendar attribution of offset-bearing cross-midnight evidence, and insufficient pure-split validation. The repaired mapper binds effect and date sources separately, requires exact terms listing applicability when terms supply the date, preserves truthful exactly-at-open/close relationships apart from the applied designation, and proves fixed pure-split shape, association, action kind, component completeness, same-security identity, and directional ratio. Source sessions are found from selected realized UTC intervals and dense schedule coverage, not the timestamp spelling or ambient timezone.

The first scoped re-review found two residual Important defects. Effect-time-only methodology was overconstrained to require terms, and source-session choice still depended on the label date. Fix round 2 permits absent terms and association lineage only when the exact selected effect alone proves the full pure-split predicate. Any supplied terms hash still requires exact association and selected-target equality. Equivalent offset-bearing and Z spellings of one instant now map identically; current and intervening session coverage is mandatory. The final scoped Sol review approved with no new Critical or Important issue. M1c's one-owner-per-family policy itself rejects overlapping effect owners; Task 5 adds no cross-source occurrence-equivalence seam.

The synthetic outcome uses H=2026-12-01 and finite V=2026-12-02 because accepted M1c complete coverage requires interval end after H, snapshot at or after the end, and availability by V. Fresh controller acceptance passed 54 Task 5 tests in 59.58s, 493 affected M1c/M1d tests in 103.16s, 38 M1c hardening tests, and all 1,388 tests in 170.90s. Ruff lint, format (142 files), mypy (110 source files), source/wheel build, `git diff --check`, and the protected `economic_test_support.py` SHA-256 passed. No M1c persisted contract/fixture, normalization, provider, network, dependency, broker, evaluator, return, portfolio, backtest, or trading capability changed. The accepted publication subject is `feat: map economic actions to session share basis`; its exact hash is obtained from Git history after publication.
