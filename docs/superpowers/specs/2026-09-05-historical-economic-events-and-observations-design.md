# Drift Historical Economic Events and Observations Design

Date: 2026-09-05. Status: independently reviewed design. No executable plan or implementation is authorized.

Canonical destination: `docs/superpowers/specs/2026-09-05-historical-economic-events-and-observations-design.md`.

Baseline: `14bad1733222758ee3836568a10a90f2a16aeac3`, verified against Git. M0, M1a, and M1b are complete. Neither M1c nor M1d is implemented or executable from this document. This specification is a design, not an implementation plan, provider choice, or experiment authorization.

## 1. Decision and scope

Split the former umbrella M1c into:

| Milestone | Scientific question | Owned contracts | Completion dependency |
|---|---|---|---|
| M1c, Corporate Actions and Economic Outcomes | What economic event was reported, when was it knowable, and what actually changed or was paid? | Versioned terms, occurrence, entitlement and settlement facts; exact cash/share components; claim status; event coverage; independent decision/outcome selection | Completed M1a/M1b and synthetic local fixtures |
| M1d, Source Observations, Sessions, and Normalization | What did the source report for this session, and which transformations are causally permitted? | Source observation contracts/versions; immutable schedule and realized-session assertions; orthogonal missingness; action-to-session mapping; cutoff-safe split views | Completed M1c contracts for normalization integration; M1a/M1b for observation/session facts |

This is a dependency join, not a universal ingestion sequence. Action facts do not need OHLCV or a schedule to be recorded. Source observations do not need actions merely to be preserved. Normalization and economically complete research need both. M1d must demonstrate the join before any backtest can use these semantics. A separate calendar-engine milestone adds no value; Drift consumes schedule artifacts.

Keep the initial decision universe: explicitly classified domestic operating-company common shares, primary listings on XNYS/XNAS/XASE, long-only, regular-session daily research. ETFs/ETPs, ADRs, foreign ordinary shares, REITs, preferreds, closed-end funds, SPACs, units, warrants, rights, OTC, secondary/foreign listings, intraday, extended hours, options, futures, crypto, shorting and leverage remain excluded.

The investment universe does not define every property a holder may receive. An eligible common share can distribute a REIT, right, or other excluded claim. Preserve receipt evidence without authorizing new investment in that property. If the future evaluator cannot handle the resulting path, it must mark the evaluation incomplete, not retroactively remove the original security from history.

## 2. Alternatives and causal justification

| Dimension | A: one combined milestone with typed families | B: action/outcome facts, then observations/sessions/normalization | C: generic immutable market-event stream with projections |
|---|---|---|---|
| Scientific clarity | Sound with careful internal boundaries, but many independent questions in one acceptance | Separates sourced economics from sourced measurement and joins them explicitly | Generic envelope is elegant; heterogeneous payload/temporal semantics move into projections |
| Leakage resistance | Potentially strong, one broad review must cover all cross-role paths | Strong narrow role checks first, explicit joint gate later | Depends heavily on each projection and broad stream access restrictions |
| Complexity | Moderate, substantial scope in one unit | Lowest incremental contract complexity; extra milestone coordination | Highest routing, generic typing, projection and replay complexity |
| M1a/M1b reuse | Good if additive | Direct reuse without modifying completed contracts | Risk of duplicating existing revision/selection machinery |
| Provider neutrality | Good | Good, facts and observations may come from different sources | Good at transport level, generic stream does not resolve source ambiguity |
| Testing/review | Early end-to-end fixtures but large adversarial space | Independent falsification followed by mandatory integration fixtures | Requires stream ordering, projection version and domain fixtures together |
| Evaluator boundary | Available after large delivery | Explicit inputs accumulated in causal stages | Evaluator may inherit projection-selection complexity |
| Implementation size | Largest single change | Smaller separately reviewable changes | Largest total change at this stage |
| Corrections | Typed revision families | Typed revision families with independent causal selection | General stream ordering alone cannot substitute for revisions of distinct facts |

Choose B. The strongest argument for A is that action application depends on sessions and some distribution factors depend on observations. B addresses this through an explicit M1d integration gate, not by pretending M1c can normalize alone. C offers no current scientific capability that M1a's revision envelopes plus typed families cannot provide more simply.

The causal tests are concrete: a split ratio, a merger agreement revision, or an evidenced cancellation can be falsified without a bar; a source daily aggregate can be preserved without knowing a split exists; neither establishes a correct normalized history until selected action facts, observation semantics and application boundaries are joined.

## 3. Evidence basis and compatibility

Repository facts outrank the older umbrella's pseudotypes. At the verified baseline:

- `src/drift/domain/securities.py` separates listing termination, unknown last trade, successor relationships and outcome evidence completeness, with no proceeds/return fields. `tests/unit/test_listing_semantics.py::test_known_termination_preserves_unknown_last_trade_independently` tests the separation.
- `M1bSelectionPurpose` in `src/drift/domain/assertions.py` has five closed M1b purposes. `NormalizedSelectionQueryV1` binds `as_known` to decision information and `current_interpretation` to ex-post audit. `CutoffSelectionProofV1` pins `drift-m1b-cutoff-selection-v1`. No existing outcome-reference implementation should be assumed from umbrella prose.
- ADR 0006 requires independent identity/lifecycle resolution; old executable semantics need old pinned code. ADR 0007 requires dependent result replay and historical source-definition selection. ADR 0008 checks selected mapping values against their keys and reconstructs equivalence from actual evidence. New market families must retain these guarantees.

Preserve all M0/M1a/M1b persisted V1 schemas, hashes, fixtures and interpretations. Reuse `RevisionEnvelopeV1`, temporal boundary claims, exact-byte validation and compatible `DatasetManifestV2` contracts. Add new market purpose/query/proof/reference families with their own versioned algorithms; do not expand the closed old purpose vocabulary or repurpose an old role/mode combination. Corrections create new source datasets, not changes to old manifests. No M1b lifecycle or universe record is rewritten because later action/outcome evidence changes.

This reviewed document supersedes the former M1c portion and related unresolved design questions of `2026-09-02-m1b-m1c-historical-equity-semantics-design.md`. That umbrella remains historical context and M1b provenance. Roadmap and lifecycle pointers say M1c and M1d are designed only and separately require implementation planning authorization. M1 historical semantics are not complete until both are accepted. Checkpoint records verified documentation state; no Session Handoff is needed for this completed design task.

## 4. Time, evidence and authorization contracts

Use three explicitly named temporal questions:

- Decision query: actual decision instant T, knowledge cutoff K through a named historical channel/policy, plus economic evaluation time E, with `K <= T` and `E <= T`. A normalization anchor/basis transition must also be no later than T. A known future announcement may be upcoming information, never an already-effective transformation.
- Outcome query: event/economic observation horizon H, plus evidence-vintage cutoff V and source channel/policy. It may use later-known facts to describe what happened through H. V must be bound, never an implicit moving “latest.”
- Derived view: source interval plus normalization anchor A, role and the appropriate K or V. A identifies the target share basis; it does not grant access to later knowledge.

Proposed additive contracts are `MarketSelectionQueryV1`, `MarketSelectionProofV1`, `MarketDecisionReferenceV1`, and `MarketOutcomeReferenceV1`. Names identify the new family, not executable code supplied by this specification. Query variants must reject contradictory fields and preserve exact purpose, role, target identity, interval/horizon, cutoff, channel, policy, manifests, validation decisions, schemas and context hashes.

| Consumer | Allowed selected facts | Forbidden authority |
|---|---|---|
| Decision action projection | Terms, occurrence/status and past realized facts definitely knowable by K, each freshly projected for the permitted decision purpose at E | Facts unavailable by K, outcome-reference relabeling, unrestricted source bundles |
| Decision observation/view projection | Observations available by K; actions available by K and definitely effective at the requested anchor; causally permitted schedule facts | Full-history adjustment factors, later corrections, unrestricted outcome artifacts |
| Decision schedule projection | Schedule assertions and closure/realized facts definitely knowable by K through a fresh decision projection | A later emergency outcome used to rewrite earlier scheduled knowledge; outcome-reference relabeling |
| Outcome projection | Selected economic and realized-session facts through H as evidenced by V, with partial/unknown preserved | Authority to satisfy a decision reference or historical structural membership |
| Audit-side validator | Complete exact source sets, considered/selected hashes and dependent replay | Automatic forwarding of audit context to decision code |

Proofs bind full normalized queries, exact record contracts, selected values, dataset completeness and interpretation algorithm identity. Public resolution reconstructs dependencies from validated records and compares complete results. Self-consistent hashes and frozen objects are integrity mechanisms, not signatures, authorization services or process isolation. Decision materialization exposes only selected content and selected references. When executable untrusted strategies eventually exist, a real process/data-access boundary is required; no such runtime is built here.

Role separation governs the query and consumer authority, not a permanent ban on source facts. December settlement cannot enter a June decision; once known it may support a later decision through a fresh permitted decision query and proof. The outcome reference itself can never be cast into a decision reference. Dataset roles do not grant historical knowledge. M1a uncertainty remains tri-state; source validity, integrity and permitted consumption are separate.

## 5. M1c economic fact architecture

### 5.1 Canonical ownership

`CorporateActionTermsVersionV1` owns reported terms for a stable source logical event. It binds M1a revisions, affected security, optional listing context, source action type/code, applicable dates, holder applicability, conditions and typed components. No dozens-of-optionals universal payload, provider factor as economic ratio, or event ID derived from correctable dates.

`EconomicEffectVersionV1` owns sourced occurrence/cancellation and the effect on the predecessor claim. It references applicable action/terms evidence when resolved and records whether the old claim persists, converts, is extinguished, or remains uncertain; what property becomes owed; and when that change occurred. A scheduled date passing does not prove occurrence. A sourced finalized status or approved derivation may establish it, with the exact evidence retained.

`EconomicSettlementVersionV1` owns a source report of an actual distribution/settlement occurrence, not an automatically distinct economic payout merely because its source ID differs. It retains typed delivered components, amount/quantity basis, actual date and residual obligations where known, plus effect/terms associations when resolved. Scheduled payable date and promised consideration are not proof of payment. An installment is another business occurrence; correcting an installment creates its revision. Do not overwrite installment one with installment two.

Effect/settlement associations explicitly distinguish resolved exact selected references, unresolved source-native references, and unknown association with reasons. A verified payment for a resolved security remains a valid source fact when its original terms or entitlement record is absent. Never synthesize a parent fact to satisfy a link. Association uncertainty and known paid components remain separately visible; overall terminal completeness is unknown/partial unless independently established. Conflicting known links block dependent use without erasing the retained source claim.

`EconomicOutcomeResolutionV1` is a query-bound result composed from these facts. It anchors to a security/action, optionally references selected listing termination evidence, and carries known components, unresolved components/reasons, claim status, completeness, H/V, references and hashes. It does not own a second copied set of authoritative source terms.

Separate dimensions include evidence completeness (`known`, `partial`, `unknown`), claim status (`continuing`, `converted`, `extinguished`, `unknown`) and consumer support (`supported`, `unsupported`, `indeterminate`). Complete evidence that a claim continues is not complete terminal proceeds. Known cash with unresolved residual recovery remains partial for terminal evaluation.

First composition uses a query-bound `EconomicSourceSelectionPolicyV1`, not a generic event matcher. The policy selects one reporting authority per fact kind and security over its declared economic-occurrence coverage scope. Non-overlapping partitions may compose only when their occurrence boundaries and revision ownership are proven disjoint. Corrected dates, overlapping claims, or events crossing a partition boundary must not assign one occurrence to two authorities; unresolved ownership makes the affected composition indeterminate. Policy, coverage, selected source IDs, logical occurrence/revision ownership and exact evidence hashes are replay inputs. Different sources may supply terms, effects and settlements because these are distinct fact kinds, but terms, entitlements and delivered settlement are never added together as separate receipts.

Retain corroborating and alternate reports audit-side; do not union or sum overlapping sources' records. Two reports of one payout contribute at most one resolved delivered component. Two genuine equal same-date installments remain distinct only with evidence of distinct occurrences, never by dates/amounts alone. Unresolved association or conflicting selected components blocks affected composition. Cross-source occurrence reconciliation beyond this explicit source-selection policy is a later extension requiring versioned equivalence evidence; no registry, fuzzy matching or global event stream is authorized.

### 5.2 Minimal exact terms and date distinctions

Cash components require amount, currency namespace/code, per-unit denominator and unit basis, gross/net/unknown source basis and conditions. Share components require recipient security identity, exact rational ratio and whether it means additional distributed units or resulting units per predecessor unit. Share substitution and distributed property differ because the parent claim may survive.

First wire conventions: finite exact decimal strings with no exponent or leading plus, no redundant leading integer zeroes or trailing fractional zeroes, no trailing decimal point, and all signed/scaled zero forms normalized to `0`; retain source precision separately. Rational numerator/denominator are reduced canonical integer strings with positive denominator. Reject NaN, infinity, denominator zero, contradictory signs and ambiguous ratio direction. Values use the existing canonical serialization/hash profile; source numeric text remains evidence. Positive ratio is mandatory for a claimed share conversion; missing ratio is explicitly incomplete terms.

Enforce these numeric conventions only in additive market-field validators. The existing `canonical_data` serializes Decimal with its existing string behavior; do not modify that serializer or reinterpret any M0/M1a/M1b numeric bytes or hashes.

Fraction treatment is sourced: issue fraction, round according to a stated rule, aggregate/sell for cash, or unknown. It is not universally cash-in-lieu. Terms whose applicability depends on holder type, election, appraisal, proration or a formula retain those conditions; the first supported shape cannot pretend one universal result.

Relevant dates may include declaration/announcement, approval, scheduled legal effect, actual legal effect, exchange-designated trading-basis/ex date, record cutoff, scheduled payable/distribution, actual distribution/settlement and due-bill interval/redemption. Do not require irrelevant dates. Preserve relevant unknowns and date-only bounds using M1a rather than invented midnight precision. There is no universal `ex <= record <= payable` validator.

FINRA's current rule places ordinary business-day ex-dates on record dates under T+1 but places large-distribution ex-dates after payable dates and permits late-information exceptions. Nasdaq's own notices separately identify due-bill and when-issued dates. Preserve actual historical designations and the applicable rule version; do not run today's settlement convention backward over all history. [FINRA 11140](https://www.finra.org/rules-guidance/rulebooks/finra-rules/11140), [Nasdaq ex-date explanation](https://www.nasdaqtrader.com/Trader.aspx?id=nasdaq-ex-date), [Nasdaq Liberty Broadband notice](https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2025-338)

### 5.3 Required support matrix

Required before first backtest means supported factual semantics or an explicit unsupported path that prevents complete evaluation. “First implementation” below means M1c typed facts, validation and selection only, not accounting.

| Event shape | Minimum distinctive facts | First implementation ruling | Deferred/out-of-scope boundary |
|---|---|---|---|
| Forward split | Resulting/predecessor share ratio, actual effect, trading basis, fraction terms | REQUIRED, supported | Unknown ratio/effect/basis blocks dependent transformation |
| Reverse split | Same, including sourced fraction treatment | REQUIRED, supported | No automatic round-down or universal cash-in-lieu |
| Regular cash dividend | Amount/currency/unit basis, entitlement-related dates, occurrence/payment evidence | REQUIRED, supported | Account-specific payment, withholding and tax accounting excluded |
| Special cash distribution | Same plus source nature, due-bill terms where applicable, residual claim if liquidation | REQUIRED, supported | “Special” alone does not select a rule; complex contingent amounts unsupported |
| Same-security stock dividend | Additional shares per eligible share, same-security recipient and fraction terms | REQUIRED, supported | Do not require a distinct child or confuse additional ratio with resulting ratio |
| Cash acquisition | Cash per cancelled claim, holder applicability, actual effect and settlement | REQUIRED, supported fixed mandatory form | Conditional announcement alone is not completed acquisition |
| Stock acquisition | Successor security, fixed conversion ratio, claim conversion, fraction terms | REQUIRED, supported fixed mandatory form | Election/proration/collar/formula-dependent results unsupported unless final applicable fixed result is evidenced |
| Mixed acquisition | Exact cash and share components plus same conditions | REQUIRED, supported fixed mandatory form | Generic label “mixed” does not imply universal fixed consideration |
| Simple mandatory spinoff | Surviving parent, recipient security and ratio, entitlement/basis dates, fractions | REQUIRED basic facts, supported fixed form | Delayed/unknown child valuation or excluded-property handling can leave evaluation unsupported |
| Mandatory fixed class conversion | Predecessor/successor, fixed ratio, actual conversion, fractions | REQUIRED basic facts, supported fixed form | Elective/conditional conversion behavior deferred |
| Bankruptcy/reorganization | Independent claim status, evidenced effect, actual cash/share/no-consideration facts and residual claims | REQUIRED known/partial/unknown representation | General recovery waterfalls, disputed claims, contingent recoveries and election engines SAFE TO DEFER |
| Liquidation | Separate installments, dates and residual/closure evidence | REQUIRED fixed facts and unknown remainder | A first payment is not proof all proceeds are known |
| Exchange delisting/venue transfer | M1b lifecycle evidence plus independent continuing/unknown claim outcome | REQUIRED explicit boundary | No inferred zero value, cash sale or claim extinguishment |
| Rights/warrants/contingent-value distributions | Retained occurrence and known property evidence, typed unsupported reason | REQUIRED detection for held common shares | Trading, exercise, subscription/election logic OUT OF INITIAL SCOPE; full semantics SAFE TO DEFER |

Simple spinoff/conversion facts are included because the cash/share component primitive already needed for mergers covers their fixed terms with one additional parent-persists distinction. This is an engineering scope judgment, not evidence that valuation is simple. An in-scope parent can distribute out-of-scope property: Darden's SEC-filed notice describes a REIT spinoff while the parent remains listed. [Darden announcement](https://www.sec.gov/Archives/edgar/data/1650132/000165013215000023/dri_oct21xrelease.htm)

Merger agreements prove terms, not consummation. Discover's initial agreement specified a fixed stock ratio and cash for fractional shares. Thermon's later proxy illustrates election and proration. Their different shapes support fixed-component admission and explicit unsupported conditional shapes. [Discover agreement](https://www.sec.gov/Archives/edgar/data/927628/000119312524042826/d780383d8k.htm), [Thermon proxy](https://www.sec.gov/Archives/edgar/data/1489096/000110465926047723/tm2612301-1_defm14a.htm)

### 5.4 Delisting and terminal outcomes

Listing termination is not security-claim termination. The SEC says shares may continue trading OTC after bankruptcy or exchange delisting, while a reorganization can later cancel old shares. That makes a mandatory one-to-one terminal outcome tied to a listing termination too narrow. M1b remains the listing authority; M1c resolves claim economics without reopening M1b. [SEC bankruptcy bulletin](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-84)

An explicit sourced cancellation with no consideration may establish a zero-value terminal fact. Unknown outcome, absent price, bankruptcy reason, and delisting alone may not. A post-delisting price is a price claim with date and methodology, not necessarily actual liquidation proceeds or final settlement. M1b's historical `outcome_evidence_status` is a source marker at its vintage, not permanent authority overriding later independently evidenced outcomes.

Original delisting research establishes that missing negative outcomes can materially bias studies. It does not convert sample-based imputation into individual historical truth. Rejecting an incomplete experiment, running sensitivity scenarios or approved imputation belongs to a later evaluator policy with its own provenance. [Shumway 1997](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1997.tb03818.x), [Shumway and Warther 1999](https://tylergshumway.org/Shumway-DelistingBiasCRSPs-1999.pdf)

## 6. Coverage and unsupported histories

No action row is not evidence of no action. Introduce versioned coverage assertions for each relevant source family. Minimum evidence is a scope definition (identities/venues, date interval, event classes or fields), exact source artifact inventory and coverage method, methodology/version hash, source completeness and revision-history statements, acquisition/snapshot cutoff and validation results. Bind exceptions and partial intervals. A marketing claim, a successful request, or a date-range filename is insufficient.

Coverage selection is causal and query-bound. `complete` means the named evidence/method supports completeness within that exact declared scope, not metaphysical certainty. The validator checks inventory, exact bytes, documented omission semantics and declared exceptions. When the available method cannot establish absence, return unknown. Coverage for split events does not establish coverage for spinoffs or terminal recoveries; coverage of final current rows does not establish historical revisions.

Unsupported events and uncertain coverage remain visible to audit/outcome validation. A future unsupported action cannot retroactively alter M1b membership or eligibility at a prior K/E. A run with an unsupported held path cannot silently discard the holding, truncate its loss, or report the remaining survivor sample as a complete result. A predeclared restriction is acceptable only within its exact historical information boundary and stated inference population. This specification does not define the evaluator's rejection/imputation policy.

## 7. M1d source observations and daily contract

### 7.1 Terminology and preservation

Use `source_observation`: one immutable version of exactly what a source artifact claimed under a declared observation contract. It is not objective market reality. Corporate-action basis is a separate qualifier: `unadjusted_as_reported`, `provider_split_adjusted`, `provider_distribution_adjusted`, `provider_total_return`, or `unknown`. A provider-adjusted or ambiguous claim may be retained, but it cannot masquerade as a source observation on a proven unadjusted basis or satisfy the first accepted decision profile.

`DailySourceObservationVersionV1` binds the revision/source record identity, security/listing evidence, source-local session label and any claimed interval, exact source artifact and record hashes, observation-contract hash, currency/precision, nullable field values with native flags, and availability. Repeated source methodology belongs once in the immutable `ObservationContractV1`; each row binds it. M1d adds a separate session-binding/usability result so a factual bar can survive conflicting or missing calendar evidence.

The generic observation contract requires explicit, possibly unknown, declarations for market population (consolidated, primary venue, named venue, provider composite), feed/tape and participants, per-field price kind and eligible population, interval and endpoint convention, sale-condition policy, odd-lot/auction handling, official-open/close and fallback rules, volume units/population, currency and precision, source timestamp meaning, reporting/correction horizon, source adjustment basis, row-omission and zero/null semantics, and revision availability. Native matrices/codes remain in hashed adapter methodology artifacts with a declared mapping; Drift owns the canonical meanings and admission checks.

### 7.2 Initial accepted daily profile

For synthetic M1d acceptance, use an explicit `RegularSessionTradeBar` profile: USD, one declared eligible-trade population for O/H/L/C, first eligible trade as open, extrema as high/low, last eligible trade as close, and volume from a separately declared share-quantity population. Bind exact regular-session UTC bounds and local label plus endpoint and closing-auction treatment. For example a closing auction timestamp exactly at close is included only under a declared compatible event policy, not by unexplained interval arithmetic.

Require a validated in-scope listing and resolved open session for usable profile admission. Official auction or official-close values from a different population are separate companion fields/observations; they may serve as close only if the contract proves the population invariant. Thus OHLC range checks apply only to a proven common-population profile. Unknown currency, scope, adjustment basis, or required field meaning blocks admission, not evidence retention. Choosing an actual source population is a later adapter gate.

NYSE describes both core auctions and trading hours; those hours do not by themselves define vendor OHLCV. Nasdaq feed specifications distinguish field eligibility and official values. This supports explicit per-field contracts rather than a universal bar definition. [NYSE hours](https://www.nyse.com/trade/hours-calendars), [Nasdaq Last Sale specification](https://nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NLSSpecification3.0.pdf), [Nasdaq cross FAQ](https://www.nasdaqtrader.com/content/productsservices/trading/crosses/openclose_faqs.pdf)

Source correction appends a new logical observation version. Late or corrected values are selected by K for decisions and V for outcome/audit use. Preserve the old artifact. A completed daily close cannot be consumed at that session's open: its observation interval and publication/availability must be complete by K, with K no later than T. A current corrected aggregate without historical evidence cannot claim historical availability; contemporary collection time is not retroactive publication evidence.

## 8. Sessions, calendars and missingness

### 8.1 Immutable schedule artifacts

`ScheduleArtifactVersionV1` binds venue MIC, regular-session scope, local-date coverage, timezone, schema and exact schedule bytes, producer/version/code or package artifact, runtime/dependency/tzdb identity, official-source/methodology evidence, generation time and M1a availability/revisions. `generated_at` is not upstream knowability.

The required semantic content is an immutable assertion for every queried covered venue date: scheduled regular/early-close/closed/unknown, local label, UTC boundaries when open, reason and evidence. Every closed date need not be physically materialized if an equivalent complete-coverage derivation is explicit, versioned and bound. Absence from an unproven list never establishes closure. Duplicate/conflicting keys, coverage gaps presented as closed, and open/close inversion fail usable schedule validation.

`RealizedSessionOutcomeVersionV1` separately records what actually occurred: happened as scheduled, did not open, late open, early close, interruption, or unknown, with actual boundaries where evidenced. Its identity is venue/date/scope; a prior schedule reference is optional context. An emergency closure may contradict an earlier valid known schedule. Realized facts known by K may inform a fresh decision projection, while later facts cannot rewrite earlier scheduled knowledge. A source bar associated with a closed/unknown session is retained with conflict/unusable/indeterminate status, not deleted or reclassified as nonexistent.

Current NYSE/Nasdaq calendars establish present regular hours and named holidays, not an entire historical calendar corpus. SEC and exchange notices provide representative emergency examples. Changes append schedule/outcome versions. [Nasdaq schedule](https://www.nasdaq.com/market-activity/stock-market-holiday-schedule), [SEC 2001 emergency order](https://www.sec.gov/rules-regulations/2001/09/emergency-order-pursuant-section-12k2-securities-exchange-act-1934-taking-temporary-action-respond), [Nasdaq 2018 closure](https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2018-98)

`exchange_calendars` is a candidate producer, not adopted authority. Its published source includes XNAS/XASE aliases to XNYS; that is an implementation caveat, not proof that all three venues always shared schedules. Bind and validate venue-specific artifacts even if generated rows match. Python `zoneinfo` may use host or packaged timezone data, so retain tzdb identity and exact normalized output. Do not construct a Drift recurrence/holiday engine. [calendar dispatcher](https://github.com/gerrymanoim/exchange_calendars/blob/4.13.2/exchange_calendars/calendar_utils.py), [Python zoneinfo](https://docs.python.org/3.14/library/zoneinfo.html), [IANA timezone theory](https://data.iana.org/time-zones/theory.html)

### 8.2 Orthogonal missingness

| Dimension | Authority | Representative states |
|---|---|---|
| Schedule/session | Selected schedule and realized-session evidence | Open, early close, closed, unknown, interrupted |
| Listing lifecycle | M1b selected facts only | Active, not yet listed, suspended, terminated, indeterminate |
| Source coverage | Validated coverage/inventory/methodology | Expected complete, not expected, partial, unknown |
| Observation claim | Verified source records and documented omission semantics | Present, partial fields, explicit no qualifying trade, absent, unknown |
| Artifact integrity/access | Exact-byte resolver | Verified, corrupt, unavailable |
| Cutoff availability | M1a selection | Eligible, ineligible, indeterminate |
| Usability | Query-bound composition | Usable, unusable, indeterminate, with all component references |

`provider_gap` is a derived reason requiring an open session, active relevant listing, expected-complete coverage, verified inventory and absence under documented source semantics. If those premises are unknown, the reason is unknown. `no_qualifying_trade` requires a documented marker or verified qualifying-trade evidence; missing row or zero volume alone does not establish it. Corrupt bytes stop parsing and never become an absent record.

A partial-session halt cannot be relabeled full-session suspension. It may coexist with a valid daily aggregate if its construction is proven; otherwise affected usability is indeterminate. Known closed, terminated and absent can coexist. Do not choose one dominant enum that erases the others. Missing is not zero return. Missingness never mutates identity, lifecycle or universe membership. Forward-fill through suspension and imputation are not offered here.

### 8.3 Narrow research availability

Do not add a capability named tradability or a timeless `tradable` flag. `ListingSessionEligibilityResultV1`, if composition is needed, means only that the listing satisfies the declared historical research structural/lifecycle/scheduled-session policy at the exact query. It binds M1b results, schedule selection, K/E, policy and all dependency hashes. It does not depend on a provider bar and does not establish fills, order eligibility, broker support or execution access. `ObservationUsabilityResultV1` is separate. A later evaluator may require both without using a provider gap as retrospective universe exclusion.

## 9. Derived normalization and leakage defenses

Source values never change in place. A `NormalizationPolicyV1` declares role, source/target unit basis, anchor, action selection and application rules, exact arithmetic, per-field factor applicability and output quantization. A `NormalizationDerivationV1` binds exact selected source/action versions, coverage, session mappings, query, algorithm/code/environment identities and ordered steps. A `DerivedObservationViewV1` binds that derivation and exact materialized output hashes. These are scientific artifact contracts, not an executable implementation plan.

First M1d implementation materializes source-basis and split-normalized views only. Distribution-continuity and total-return calculations are later extensions and must be outcome-only initially. Their terminology and required lineage are specified now to prevent a provider-adjusted return from entering the source path. No return, portfolio, reinvestment, indicator or performance engine is built in M1d.

### 9.1 Canonical split units

For `q = resulting shares / predecessor shares`, pre-action prices converted into the post-action basis use `price_factor = 1/q`; share quantities/eligible share-volume use `quantity_factor = q`. Factors are exact reduced positive rationals. The same factor is not blindly applied to dollar volume, number of trades, lot counts or every provider volume field. Preserve source-native factor conventions separately.

| Event | q | Pre-event price factor | Pre-event share-volume factor |
|---|---:|---:|---:|
| 2-for-1 | 2/1 | 1/2 | 2/1 |
| 3-for-2 | 3/2 | 2/3 | 3/2 |
| 1-for-10 | 1/10 | 10/1 | 1/10 |

Pure split price-times-quantity is conserved before quantization. This is a unit transformation invariant, not a claim about realized market price or account rounding. Compose exact factors without intermediate rounding; the policy pins final output scale and rounding, with exact factors retained.

### 9.2 Action-to-session mapping

M1d resolves `first_post_action_session` from sourced exchange trading-basis/effective evidence and the selected venue schedule/outcome context. A source ex-date explicitly meaning the first ex-basis trading session can map directly when the date is proven open. Legal effective-after-close evidence means that completed session remains on the prior basis. An exact before-open basis transition can apply to the upcoming session. A closed date, incompatible venue, missing designation or date-only ambiguity is indeterminate unless a source-defined or approved versioned rule uniquely resolves it. Do not silently roll a date to the next package session.

For source session S normalized to anchor A, apply only steps with `S < first_post_action_session <= A`. The first post-action bar is already post-basis. In decision normalization, E is the effective-action cutoff, not inert metadata. Every applied trading-basis transition must be definitely no later than E, the anchor's selected basis instant must be no later than E, and `E <= T` and `K <= T` must hold. Bounded transition evidence must establish these inequalities, not merely overlap the cutoff. Keep K, E and T distinct. Reject a July T/K query with May E and a June action/July anchor, as well as a May decision requesting a June anchor even when the split was announced by K. A future announcement feature remains separate. A basis session may label an already-effective opening transition; that does not authorize its incomplete daily close.

Same-session actions require known compatible unit basis and order when order changes meaning. A cash amount per old share is not an amount per new share. Sort only after economically relevant precedence is established; a UUID or source sequence must not invent missing economic order. Pure split steps may be proven order-independent, but the derivation still binds the inputs and its composition rule. Unknown order/basis blocks the affected transformation.

### 9.3 Distribution and outcome boundaries

A possible future cash continuity factor `(P-D)/P` depends on exact selected prior close P, distribution D, currency and unit basis. It is not a corporate-action fact and is not total economic return. Cash-dividend price transforms leave historical share volume unchanged; split reciprocity does not apply to cash. Nonpositive results, missing P or incompatible currency/basis are unsupported under that formula, not clipped. An illustrative `100 -> 99` price change with a separately entitled 2 cash units has different price-only and combined economics; actual entitlement, receivable/payment and reinvestment timing remain future evaluator responsibilities. Preserve the dividend in the outcome stream even if price normalization is unavailable.

### 9.4 Why causal rejection remains necessary

A future split applied as one constant to an entire earlier window may leave ratios unchanged. It is false that every future-adjusted feature is numerically biased. Dollar thresholds, cross-security nominal price comparisons, quantities, rounding and metadata can nevertheless change or expose future information. Drift rejects future-action decision authority at the input boundary rather than attempting to prove every possible strategy scale-invariant. LEAN's documented full-history adjusted modes and Zipline's perspective-based adjustment machinery are useful comparisons, not substitutes for K and exact provenance. [LEAN normalization](https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/us-equity/requesting-data), [Zipline adjustment source](https://raw.githubusercontent.com/stefan-jansen/zipline-reloaded/main/src/zipline/data/adjustments.py)

## 10. Replay and external reuse

| Replay architecture | Strength | Limit | Ruling |
|---|---|---|---|
| Git-pinned checkout | Human-auditable exact source revision | Does not retain interpreter, built packages, system libraries, tzdb or data | Necessary source identity, insufficient alone |
| Current interpreter dispatches old versions | Convenient replay through one runtime | Permanent maintenance/security/compatibility burden; retaining a spec is not executable dispatch | Optional later, not required now |
| Immutable execution artifact | Retains a specific runnable dependency/runtime closure | Digest alone says nothing about source/data semantics and retention still matters | Required retained closure before promotion-quality experiments |
| Hybrid | Git/source artifact plus semantic/input/output hashes and runnable environment | More provenance to retain | Recommended minimum before actual experiments |

An experiment must bind exact input manifests and selected records, semantic contract/policy versions, resolver/normalizer implementation hash, source revision/archive hash, dependency-lock and package artifact hashes, interpreter/platform identity, tzdb, schedules and output hashes. Retain a runnable immutable environment artifact or equivalent complete closure, not just a mutable image tag. This design specifies the boundary; it does not build packaging infrastructure or reopen M1b version dispatch. [uv locking/sync](https://docs.astral.sh/uv/concepts/projects/sync/), [Docker digest pinning](https://docs.docker.com/build/building/best-practices/#pin-base-image-versions)

Under ADR 0005, Drift owns temporal selection, identity joins, coverage, source meaning, action terms/outcomes, role boundaries, normalization lineage, missingness and replay validation. Commodity implementations remain candidates:

| Source/system | Useful concept | Must not import as authority |
|---|---|---|
| CRSP | Separate distributions/delisting components, received identities, price/share factors, explicit methodologies | Native sentinels/factor conventions, return fields, storage-date conventions or final data as historical knowledge |
| LEAN | Raw/adjusted mode comparison, split events/factors and separate corporate events | Midnight simulation delivery as announcement/payment evidence; portfolio side effects; full-history adjustment authorization |
| Zipline-reloaded | Separate bar/adjustment readers, perspective boundary, reciprocal split quantity changes | Floats/opaque factors without source-cutoff proofs; view perspective as knowledge time |
| NautilusTrader | Explicit bar price type, aggregation and internal/external origin | External-origin label as sufficient market-population or correction semantics |
| exchange_calendars | Candidate generated schedule rows | Alias equivalence or a package version as historical exchange truth |
| Arrow/Parquet | Exact typed physical representation and metadata pointers | Embedded metadata as proof of semantics, authorization or immutable lineage |

No dependencies are added. Adoption later requires current licensing, compatibility, security and reproducibility checks, measured contract tests and an ADR if architectural. [Nautilus data concepts](https://nautilustrader.io/docs/latest/concepts/data/), [Arrow format](https://arrow.apache.org/docs/format/Columnar.html), [Parquet format](https://parquet.apache.org/docs/file-format/)

CRSP documentation requires special care: FIZ/SIZ and CIZ are not merely aliases. Published migration definitions distinguish delisting fields and storage conventions; indexed cross-reference text says CIZ compounds daily data where legacy monthly holding-period calculations were used. Exact dividend-reinvestment conventions must be checked against the delivered release's calculations guide; the design does not rely on an unverified claim about the latest monthly methodology. Current Morningstar library lists a July 2026 CIZ guide while old PDFs redirect; research inspected indexed CIZ descriptions and accessible metadata, not every latest field. Later acceptance must pin generation, release, methodology and delivered bytes. No CRSP adapter compatibility is claimed. [CRSP migration metadata](https://www.crsp.org/wp-content/uploads/appendix/FlagType_MU.html), [cross-reference](https://www.crsp.org/crsp_pdf/crsp-us-stock-indexes-databases-siz-to-ciz-cross-reference-guide/), [Morningstar library](https://indexes.morningstar.com/research-data-products/document-library)

## 11. Material disagreements, with evidence on both sides

### D1. Keeping all former M1c responsibilities in one implementation

1. Disagreement: one milestone is unnecessarily broad, although scientifically possible.
2. Strongest support: normalized views require actions, sessions and observations together.
3. Strongest contrary evidence: independent event/observation facts can be validated before their join.
4. Repository evidence: umbrella typed families already separate them; ADR 0006 rejects conflation of independent facts.
5. Primary evidence: exchange action notices describe ratios/dates without daily bars; framework adjustment readers are distinct from bar readers.
6. Importance: a single review mixes source-economics correctness with measurement and transform correctness.
7. Smallest alternative: two milestones plus a mandatory M1d integration acceptance gate.

### D2. Every economic outcome mandatorily belongs to a listing termination

1. Disagreement: listing exit cannot serve as universal terminal-claim anchor.
2. Strongest support: M1b termination references provide a simple and authenticated handoff.
3. Strongest contrary evidence: claims can persist after delisting and distributions occur without termination.
4. Repository evidence: security and listing are separate, and termination has no proceeds fields.
5. Primary evidence: SEC bankruptcy bulletin permits continued OTC trading; Darden retained its parent listing.
6. Importance: prevents fabricated cash-out/zero and loss of later recoveries.
7. Smallest alternative: security/action economics with optional verified listing context and explicit claim status.

### D3. Final terms or scheduled payable date prove actual outcome

1. Disagreement: declaration, entitlement and settlement are different sourced facts.
2. Strongest support: one revised terms record reduces schemas and duplicated data.
3. Strongest contrary evidence: conditions, cancellation, installments and delayed settlement are distinct occurrences.
4. Repository evidence: M1a corrections revise a fact; they are not an economic occurrence engine.
5. Primary evidence: merger agreements and FINRA/Nasdaq due-bill date distinctions.
6. Importance: prevents promised cash from becoming received cash and prevents one installment replacing another.
7. Smallest alternative: linked terms/effect/settlement ownership with query-bound outcome composition.

### D4. Excluding unsupported future-event histories is safe by default

1. Disagreement: retrospective exclusion is selection on future information.
2. Strongest support: restricting scope avoids silently wrong numerical outcomes.
3. Strongest contrary evidence: omission can be correlated with losses or major corporate events.
4. Repository evidence: ADR 0007 preserves explicit historical membership and distinguishes absence/withdrawal.
5. Primary evidence: original delisting-bias research documents outcome-correlated omissions.
6. Importance: a seemingly clean dataset can manufacture survivor-biased research.
7. Smallest alternative: keep the original universe and mark unsupported held paths/incomplete runs explicitly.

### D5. A single raw OHLCV shape or universal range invariant is sufficient

1. Disagreement: source aggregation and official values have field-specific semantics.
2. Strongest support: common-population OHLC is simple and permits meaningful numerical checks.
3. Strongest contrary evidence: field inclusion, auction and fallback populations can differ.
4. Repository evidence: umbrella leaves source construction largely as provider-evaluation questions, with no implemented bar contract.
5. Primary evidence: exchange feed and cross documentation distinguishes reported field meanings.
6. Importance: rejects neither valid source evidence merely for mismatch nor accepts unexplained mixed values as equivalent.
7. Smallest alternative: preserve generic field-basis claims, admit a narrow proven common-population profile.

### D6. A package calendar or today's schedule is historical truth

1. Disagreement: package behavior, published schedules and realized sessions are distinct.
2. Strongest support: mature libraries include extensive holidays and exceptional closures.
3. Strongest contrary evidence: aliases, corrections and emergency outcomes require independent provenance.
4. Repository evidence: M1a separates availability from effect and ADR 0008 requires exact selected content.
5. Primary evidence: emergency closure notices, calendar dispatcher and Python tzdb-source documentation.
6. Importance: prevents a later closure or changed runtime from silently rewriting an earlier experiment.
7. Smallest alternative: compact immutable date coverage, independent realized outcomes and pinned producer/tzdb evidence.

### D7. Every use of future-adjusted data necessarily changes a strategy result

1. Disagreement: that numerical claim is stronger than the evidence.
2. Strongest support: future events can change nominal prices and reveal their occurrence.
3. Strongest contrary evidence: a uniform positive scaling cancels in within-series price ratios.
4. Repository evidence: umbrella causal role rule is valid without asserting all transformations change all features.
5. Primary evidence: LEAN documents full-history modes; the scale-invariance counterexample is elementary algebra.
6. Importance: accurate reasoning makes the leakage boundary defensible.
7. Smallest alternative: retain strict causal admission, state numerical bias only when demonstrated.

### D8. Missing real sources block a synthetic contract implementation plan

1. Disagreement: lack of provider, historical calendar corpus, start year or licensing does not block provider-neutral M1c contracts.
2. Strongest support: real coverage requirements can expose hidden edge cases.
3. Strongest contrary evidence: the required shapes and unknown/unsupported behavior are falsifiable synthetically.
4. Repository evidence: M1a/M1b were completed with synthetic local fixtures and explicit validation boundaries.
5. Primary evidence: source documentation already establishes the distinctions; acquisition evidence is needed only for claims about an actual source.
6. Importance: prevents premature vendor choices and false planning blockers.
7. Smallest alternative: separate design decisions from later adapter/experiment acceptance gates as in section 14.

## 12. Adversarial acceptance matrix

These are required future acceptance behaviors, not claims that tests exist or passed. Tests must use actual validated source fixtures and replay dependencies, not fabricated “trusted” result objects.

| Attack/fixture | Required result | Milestone |
|---|---|---|
| May announcement, June split | May can expose announcement, cannot apply June basis | M1c/M1d |
| Announced split cancelled; scheduled date passes | Cancellation preserved; no inferred occurrence | M1c |
| Forward/reverse split, round-up fraction terms | Exact ratios and sourced fraction treatment retained | M1c |
| Regular dividend with separate ex/payment | Entitlement and payment facts remain distinct | M1c |
| Special dividend paid before ex, due bills | No universal chronology rejection; entitlement not inferred from record holder alone | M1c |
| Cash merger agreement without completion | Terms known, occurrence/outcome not fabricated | M1c |
| Fixed stock/mixed merger; elective/prorated comparator | Fixed facts supported; conditional path explicit unsupported/partial | M1c |
| Spinoff with surviving parent, child begins later | Preserve property and independent identity/timing; no zero-value default | M1c/M1d |
| REIT/right received by eligible parent | Preserve receipt; no new-investment authority or retrospective exclusion | M1c |
| Delisted, still outstanding OTC claim | Listing terminated, security outcome continuing/unknown | M1c |
| Unknown bankruptcy outcome versus evidenced no-consideration cancellation | Unknown remains unknown; only evidenced case may record zero | M1c |
| Cash installment plus unknown residual, then later installment | Distinct business events, no overwrite or premature completeness | M1c |
| Corrected action amount/date after K | Earlier selected terms replay; later outcome may use correction by V | M1c |
| Two genuine distributions same date versus duplicate source event | Distinct components preserved; no date-key deduplication | M1c |
| Two selected sources report one identical payout | Source-selection policy permits one occurrence only; overlapping unresolved authority is indeterminate, never additive | M1c |
| Two genuine equal same-date installments | Distinct occurrence evidence preserves both; no amount/date deduplication | M1c |
| Corrected event date crosses source-authority partition | Bind revision ownership once; unresolved overlap blocks composition | M1c |
| Actual sourced payment with absent terms/effect | Preserve known paid component and typed unresolved associations; residual outcome remains unknown/partial | M1c |
| Terms, entitlement and payment describe one distribution | Preserve each fact role without counting three receipts | M1c |
| Omitted event class/history coverage | No-action/completeness conclusion indeterminate | M1c/M1d |
| Future outcome reference injected into decision bundle | Rejected at nested role/query/proof/content boundary | M1c/M1d |
| Genuine proof with substituted selected value or forged dependent result | Rejected by exact value/dependency replay | M1c/M1d |
| Same-security stock dividend | Same recipient permitted; additional/resulting ratios not conflated | M1c |
| Corrected daily observation after K | New immutable version; historical decision unchanged | M1d |
| January $100 back-adjusted by future June split | Decision view rejected; ratio-invariant and dollar-threshold examples both demonstrated | M1d |
| May decision requests June anchor for known future split | Reject forward-anchor escape despite available-by-K terms | M1d |
| July T/K, May effective cutoff E, June split, July anchor | Reject because effective transition and anchor basis exceed E | M1d |
| Same-session completed daily close requested at open | Reject incomplete/unavailable observation at T/K | M1d |
| Past realized payment/closure becomes known before a later decision | Fresh decision query permitted; direct outcome-reference relabeling rejected | M1c/M1d |
| Price adjusted, share volume unadjusted | Reject inconsistent declared split transform | M1d |
| Sequential split factors | Exact reciprocal composition, no intermediate rounding | M1d |
| Same-session split/dividend with unknown unit basis | Affected transform indeterminate, never arbitrary tie ordering | M1d |
| Provider-adjusted or unknown-basis historical bar called source-unadjusted | Evidence retained; admission rejected | M1d |
| Official close differs from H/L population | Preserve separate field/mixed claim; common-profile admission fails unless invariant proven | M1d |
| Volume-only qualifying report or zero-volume sentinel | No synthetic close or no-trade inference | M1d |
| Normal bar on closed/unknown schedule | Preserve factual claim; conflict/unusable/indeterminate binding | M1d |
| Early close; winter/summer DST; coverage boundary | Exact pinned local/UTC session identity and interval | M1d |
| Forecast open, later emergency did-not-open | Earlier schedule remains replayable; separate outcome retained | M1d |
| Realized closure without retained prior schedule | Outcome record valid; contextual schedule unknown | M1d |
| Missing date in unproven calendar list | Unknown, not closed | M1d |
| Compact complete schedule coverage versus explicit closed rows | Equivalent derived date assertions bind exact methodology/input hashes | M1d |
| Changed library/tzdb/schedule with identical or changed rows | Appropriate environment/input identity changes; old artifact replayable | M1d |
| Not yet listed, terminated, full suspension, partial interruption | Independent M1b facts; no row-driven lifecycle inference | M1d |
| Absent row with and without complete inventory/coverage | Provider-gap reason only with all premises; otherwise unknown | M1d |
| Corrupt artifact | Parsing fails; no absence fact emitted | M1d |
| Source exists only after K | Decision unavailable; later outcome/audit may select | M1d |
| Forward-fill through suspension or missing as zero | Unsupported operation, no fabricated observation/return | M1d |
| Code/policy changes while output numbers match | Derivation provenance changes | M1d |

M1c completion requires all relevant economic/source-replay rows, exact round-trip serialization, independent review and existing compatibility gates. M1d completion additionally requires all observation/session/mapping/split-view rows and the cross-milestone leakage join. Neither completion is provider acceptance or evaluator readiness.

## 13. Provider acceptance and evaluator handoff

The later bake-off evaluates capabilities, not a vendor score assumed now:

| Layer | Required acceptance evidence |
|---|---|
| Identity/universe | Historical mappings/classification/listings, delisted coverage and exact M1b contracts |
| Economic events | Native IDs/types, fixed component bases, dates/precision, occurrence/cancellation, recipient IDs, revisions, unsupported conditions |
| Economic outcomes | Actual consideration/settlement evidence, partial residuals, continuing versus extinguished claims, no imputation disguised as truth |
| Observations | Proven source basis, per-field OHLCV methodology, feed/venue scope, auctions/conditions, currency/precision, correction horizon and omission semantics |
| Sessions | Retained methodology/notices, date coverage, venue-specific schedule and realized exceptions, exact generated bytes/tzdb |
| Coverage/revisions | Inventory/methodology/version, scope intervals/classes, exact snapshots, gaps and completeness limitations |
| Acquisition/replay | Reproducible bulk/snapshot process, stable identifiers, exact bytes, licensing/retention rights and environment closure |

No provider must supply every layer. Composed sources are acceptable only with explicit identity joins, conflict handling, coverage and combined provenance. An adapter cannot pass through an undocumented native factor or source return and make the evaluator reinterpret it. Real-source acceptance uses retained files/notices; no data acquisition is part of this task.

The future evaluator receives: PIT-safe decision information and historical eligible universe; selected source observations and allowed split views; separately selected subsequent action/effect/settlement facts and terminal/continuing/unknown outcomes; exact schedule and realized-session definitions; orthogonal missingness/usability/support results; full audit-side provenance and reproducible selected data. Decision code receives the restricted materialization, not the audit manifest bundle. The evaluator must own holding, cash/receivable, reinvestment, unsupported-run and imputation policy, but must not reinterpret raw provider ambiguity.

## 14. Readiness, limits and non-goals

No unresolved source choice blocks a provider-neutral synthetic M1c implementation plan. This design selects the action shapes, fact ownership, exact ratio representation, temporal roles, coverage minimum and additive query family. Planning still requires explicit user authorization and independent acceptance of this specification; neither is inferred from its presence.

Synthetic M1d planning likewise need not wait for actual data. Its generic profile, exact arithmetic, ambiguous mapping rejection and role family are defined here. An actual adapter must later settle the concrete population/condition mappings and prove coverage. Historical start year, complete calendar corpus, venue differences, source revision capture, licensing and retention are acquisition/real-experiment gates. A future source may fail them; the synthetic contract must report that honestly.

Before real experiments, complete M1c/M1d and separately authorize/design the evaluator, prove the actual source profile/coverage, retain source and calendar evidence within licensed rights, and bind runnable replay artifacts. A corrected-current-only source cannot claim historical decision availability without evidence. Unknown or partially covered histories cannot be promoted as fully resolved by a convenience fallback.

Evidence limits: current exchange pages are not a complete historical corpus. Calendar aliases prove producer implementation choices only. The latest CRSP guide migration prevented full direct field-level extraction; indexed older concepts and accessible primary metadata support comparison, not an accepted adapter. One UTP specification URL was unavailable during direct rechecks; use the cited exchange documents for present claims and reacquire/version exact feed documentation during provider acceptance. The original 1997 delisting abstract and original 1999 indexed paper were inspected; direct 1999 PDF access timed out. No unsupported quantitative empirical estimate is adopted.

Explicit non-goals: executable implementation plans, M1c/M1d production code, provider adapters or downloads, database/framework/dependency adoption, broker integration (including Robinhood/Alpaca), MCP, live trading, orders/execution, portfolio/risk engine, agent runtime, recursive research, OpenAI SDK, LangGraph, Qlib, ML models, strategy generation, returns/performance metrics/Sharpe, optimizer, cloud deployment, live streaming, intraday/extended hours and all excluded instruments. Synthetic examples explain contracts only.

## 15. Design verification and completion reporting

The verified baseline is `14bad1733222758ee3836568a10a90f2a16aeac3`. Three focused research workers covered actions/outcomes, observations/normalization, and sessions/missingness/replay. An Astra synthesizer produced the design candidate. The controller checked material claims against live code/tests and primary sources. A fresh Astra reviewer independently read the request, specification, ADR and lifecycle changes, then re-reviewed the corrections. Final review: Approved, with no residual concrete planning blockers.

| Review finding | Resolution in this design |
|---|---|
| Two sources reporting one payout could produce duplicate components | Query-bound reporting authority, disjoint occurrence/revision ownership and paired one-payout/two-installment acceptance cases |
| Missing prior terms/effect could erase independent settlement evidence | Typed unresolved associations retain known paid facts; dependent completeness remains separate |
| A later decision time could bypass an earlier requested effective cutoff | Applied transitions and anchor basis must be definitely no later than E, independently of K and T |

The controller also clarified that new numeric normalization belongs to additive market-field validators, never the existing canonical serializer. All findings above are closed design gaps, not claims of implemented fixes or newly passing runtime tests.

Final repository gate on 2026-09-05: `uv run pytest` passed all 793 existing tests; `uv run ruff check .` passed; `uv run ruff format --check .` passed; `uv run mypy src tests` passed; `uv build` produced the source distribution and wheel. Initial sandbox access to the existing uv cache failed; the authorized escalated checks succeeded. No source, test-source, dependency, or executable-plan changes were made. The new adversarial matrix is a future acceptance requirement, not a test suite run in this task.

Checkpoint scope is this specification, ADR 0009, and existing instruction/README/roadmap/overview/umbrella pointers. Unrelated `.DS_Store` files and the pre-existing M1b handoff are excluded from the documentation commit. No new Session Handoff is needed: decisions, review resolutions, verification and the next authorization boundary are canonical here. The actual commit hash and final Git status are reported from Git, not embedded self-referentially. Next action is user review followed, only if authorized, by M1c implementation planning.
