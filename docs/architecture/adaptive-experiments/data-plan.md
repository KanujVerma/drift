# Candidate source configurations and qualification gates

## Purpose and authority

This is Matthew's **draft source-options proposal** for
[#378](https://github.com/KanujVerma/drift/issues/378), not an accepted source
contract, account entitlement, acquisition instruction or operational approval.
The sole deliverable is this document. It does not create a provider adapter,
change an evaluator, qualify a dataset or authorize spending.

The accepted baseline is main commit
`54708219563ada3e8b115b609a522dec694bc274`. Read
[AGENTS.md](../../../AGENTS.md), [onboarding](onboarding.md),
[D01-D17](decisions.md), [design](design.md),
[requirements crosswalk](requirements-crosswalk.md),
[workstreams](../workstreams.md) and [agent workflow](../agent-workflow.md).
The decisions blob is `2604dbb34d4bedeb6888342f336d2e62dedd4513`.
[ADR 0012](../../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md),
[ADR 0015](../../adr/0015-three-feature-workstreams-and-explicit-writer-handoffs.md)
and [ADR 0016](../../adr/0016-controlled-adaptive-research-with-versioned-execution.md)
govern evidence lanes, ownership and adaptive execution boundaries. Preserve
[trust boundaries](../trust-boundaries.md) and the implemented M1b-M1e
rights/provenance interfaces. ADR 0010's file still says proposed; ADR 0012 is
the accepted sequencing amendment. Do not silently promote every linked draft.

D02/D03/D09 make authorized news and other timestamped inputs first-class.
D06 requires separately verified intraday/extended-session capabilities, with
full overnight support deferred. D10 proposes roughly 10-15 diversified ETFs;
the final list is not accepted. D11's intended 2021-2023 development, 2024
validation and 2025 holdout roles are limited by actual support and access
history. D07/D12/D13 require honest costs, matched information and complete
attempt records. A feed purchase, API capability or historical date label does
not satisfy those decisions by itself.

The [provider selection record](../m1e-provider-selection.md), dated
2026-09-19, and ADR 0012 contain **historical documentary and reported empirical
screening**. Their account tests, data limitations and paused purchase decisions
are retained as evidence at that revision. No authenticated account, private
receipt, subscription, dataset or credential was inspected for this proposal.
Those screens are not a current account-access readback.

## Evidence interpretation

Public primary documents below were read on **2026-10-13 America/Los_Angeles**
(2026-10-14 UTC). The check date is this research pass's date, not a claim that
the vendor published or froze its terms on that date. Where a page has no exact
revision identifier, its document version is unknown; record a specific terms
revision and applicable agreement before acquisition. Links are not retained
native data or immutable contractual evidence.

The following labels describe this proposal's evidence, not new persisted enums:

- **DOCUMENTED:** a bounded statement in a cited first-party document.
- **HISTORICAL RECORD:** evidence reported in the pinned repository record,
  with its original date and limitations; not re-observed here.
- **UNVERIFIED:** an account, coverage, licensing or technical fact not proved
  by this public-documentation pass. Do not substitute a favorable default.
- **DISCREPANCY:** relevant documents differ or leave a scope ambiguity that
  needs resolution. Retain both sources rather than select the convenient one.
- **PROPOSED:** a configuration or gate requiring producer/consumer acceptance.

Qualification is attached to an exact provider, product, feed/publisher,
licensed entity, permitted purpose, universe, date/field/session scope,
delivered snapshot and methodology version. There is no vendor-wide PASS.
Evaluate each required dimension independently under the existing M1e profile;
a critical PARTIAL, FAIL or UNKNOWN is not acceptance. A favorable weighted
vendor score cannot compensate for missing rights or original-version evidence.

Across **every** candidate below, current user entitlement, delivered coverage,
raw-byte retention/redistribution rights, post-termination replay rights and
actual incurred costs remain UNVERIFIED unless separately evidenced. Published
capability is not an account-specific permission. Apparent absence from a page
is not proof that a product lacks a feature.

## Primary-source register

Each entry was checked on the research date above. The cited section identifies
the supported claim; it does not certify the rest of the product.

| ID | Primary document and inspected section | What this proposal can use |
|---|---|---|
| A1 | [Alpaca Market Data API](https://docs.alpaca.markets/us/docs/about-market-data-api), Trading API subscriptions and authentication | Published Basic/Plus feed distinctions, indicative list price and access limits; no user entitlement |
| A2 | [Alpaca Historical Stock Data](https://docs.alpaca.markets/us/docs/historical-stock-data-1), Data Sources | Named IEX/SIP/BOATS/derived overnight feeds and the subscription wording discrepancy |
| A3 | [Alpaca Historical News](https://docs.alpaca.markets/us/docs/historical-news-data), overview | Documented Benzinga publisher and claimed historical start, not original-version replay |
| A4 | [Alpaca News articles reference](https://docs.alpaca.markets/us/reference/news-3), query parameters and responses | Updated-date ordering, optional content, pagination and access-dependent bounds |
| D1 | [Databento corporate-actions guide](https://databento.com/docs/venues-and-datasets/corporate-actions), PIT corporate actions | Documented all-version versus latest-record selection |
| D2 | [Databento Security Master](https://databento.com/docs/schemas-and-data-formats/security-master), Fields and Identifiers | Listing/security/issuer scope and distinct record/effective timestamps |
| D3 | [Databento instrument definitions](https://databento.com/docs/schemas-and-data-formats/instrument-definitions), time-series/reference separation | Direct-feed definitions and separately sourced/licensed reference information |
| D4 | [Databento symbology](https://databento.com/docs/standards-and-conventions/symbology) | Documented historical symbol preservation; retrieval succeeded after the preflight's earlier failure |
| G1 | [algoseek US Equity TAQ guide](https://algoseek.com/docs/datasets/taq-guide), version 1.5, July 2021 | Published trade/quote event semantics, extended-session range and cancellation/correction treatment |
| G2 | [algoseek equities products](https://algoseek.com/equity/) | Product discovery only; an offer is not a delivered/licensed scope |
| S1 | [SEC developer resources](https://www.sec.gov/about/developer-resources), Data APIs and EDGAR access | Public submissions/XBRL APIs and filing/archive discovery |
| S2 | [SEC Accessing EDGAR Data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data), Fair access | Published request-limit and efficient-access requirements |
| X1 | [X API overview](https://docs.x.com/x-api/getting-started/about-x-api), v2 features/pricing | API existence, documented edit-history features and usage charging; no account scope |
| X2 | [X Developer Policy](https://docs.x.com/developer-terms/policy), use cases and Content compliance | Use-case approval and offline-content update/deletion obligations |
| T1 | [Truth Social terms](https://help.truthsocial.com/legal/terms-of-service/), User representations and Prohibited activities | Restrictions relevant to automation and systematic collection; no scraping permission |

The attempted [Databento terms URL](https://databento.com/terms) returned a
JavaScript-required shell rather than readable terms. It is an **unavailable
terms source**, not evidence of permissive licensing. No sign-in or account
creation was attempted. Exact applicable Databento and algoseek agreements,
Alpaca/Benzinga content terms and user-specific orders remain unverified.
Inspecting public terms is documentary triage, not an account-specific legal
clearance. A permitted research use and durable replay use need their own
evidence and authorized ruling where material.

## Candidate evidence matrix

### Market and reference capabilities

| Candidate/product and publisher | Identity, versions and temporal evidence | Data/session/fill-support scope | Limitations and evidence |
|---|---|---|---|
| Alpaca stock data; exact `iex` or `sip` feed, with the named upstream exchange/SIP sources | Provider symbol mapping and correction/vintage behavior must be bound to the exact product. The baseline adapter reports unversioned derived bars and scheduled reconstruction limits. Source timestamps never prove this user's first receipt. | A1 advertises US stocks/ETFs, historical access since 2016, Basic real-time IEX versus Plus broader coverage, and a latest-15-minute historical restriction. A2 describes SIP bid/ask/trade coverage. These claims do not establish delivered extended-session completeness, halts, quote freshness or fills. | DOCUMENTED A1/A2; HISTORICAL RECORD in ADR 0012/provider selection. Current access and feed scope UNVERIFIED; subscription wording DISCREPANCY below. |
| Databento market dataset plus separately specified reference products/publishers | D2 distinguishes `listing_id`, `security_id`, `issuer_id`, `ts_record` and `ts_effective`. D4 documents keeping historical symbols at their event-time identity. D1's `pit=True` retains historical event versions; its default selects latest records. None is this user's actual receipt timestamp. | D3 distinguishes venue-feed definitions from other reference endpoints. Select the actual dataset, publisher, schema, dates, quote/trade depth and status coverage before asserting regular or extended-session support. A venue-specific quote is not automatically a consolidated executable price. | DOCUMENTED D1-D4. Paid reference access was not available in the historical free-account screen. Current entitlement, delivered revisions, halts, joins and replay rights UNVERIFIED. |
| algoseek US Equity TAQ; exact SIP-derived delivery and contracted reference products | G1 describes receipt-ordered trade/quote events and cancellation/correction events. These vendor timing claims are distinct from local receipt. The September repository screen reports overwritten reference assertions; it does not establish a current revised-reference product's behavior. | G1 documents trades/bid-ask quotes and a 04:00-20:00 range labelled EST, with holiday/early-close information. Its timezone wording needs a product-specific DST interpretation; never silently convert it to fixed UTC or infer full overnight coverage. | DOCUMENTED G1; HISTORICAL RECORD for the reference-overwrite finding. Contracted years/ETFs, condition flags, missing events, halts and local delivery fidelity UNVERIFIED. Raw TAQ capability does not repair an unrelated reference-vintage gap. |

### Information-source capabilities

| Candidate/product and publisher | Identity, original versions and availability | Scope and missingness | Limitations and evidence |
|---|---|---|---|
| Alpaca news API with Benzinga as documented publisher | A3 claims history from 2015. A4 sorts by updated date, allows optional content and exposes paginated interval queries. Those features do not prove that every pre-update body or historical first-availability assertion can be recovered. Require event/version lineage and original content/receipt evidence under accepted SRC. | Symbol-filtered stories need issuer/security mapping and the exact query scope. Do not exclude contentless articles and then claim the source was empty. A finite page is not complete coverage. News delivery has no market-session or fill guarantee. | DOCUMENTED A3/A4. User news entitlement, content license, original-version archive, retrospective availability and complete ETF coverage UNVERIFIED. A historical search start is not an original-vintage certificate. |
| SEC EDGAR public filings/submissions/XBRL; SEC distribution with filing authors identified separately | Bind filing accession, filer/issuer mapping, document identity and amendment relations. Filing, acceptance/dissemination and actual first receipt are separate times. An XBRL-derived record is not a substitute for the exact original filing or original availability evidence. | S1 documents public API/archive access. This is filing coverage, not all news/social coverage or an ETF constituent-news mapping. S2 requires fair access; absence from one query is not absence of all relevant filings. No session quote/fill support is supplied. | DOCUMENTED S1/S2. Specific form/date completeness, author authenticity, retention/redistribution conditions and historical first-observed availability remain UNVERIFIED for the proposed use. Do not confuse public data access with EDGAR filing/submission authority. |
| X API v2 public-post configuration; X distribution and separately attributed authors | X1 describes edit history, but the exact endpoint, account access, retrieved versions and first receipt must be proved. Author IDs, edits and URLs do not authenticate an economic claim. X2's content-compliance obligations can conflict with perpetual immutable content retention. | Public-post scope only is proposed; no protected content, private messages, scraping or inferred full historical archive. Coverage, deletions, edits and query/filter limits need explicit treatment. No execution-price evidence. | DOCUMENTED X1/X2. Access, approved use case, rates, exact costs and durable replay exception UNVERIFIED. Do not preserve prohibited content, including through a derived-content loophole, to make replay pass. |
| Truth Social information-source option, not an acquired feed | No authorized historical API, original-version service or local receipt evidence was established in this pass. A public webpage is not a retention/access grant. | T1 restricts automated/non-human access, systematic collection and unauthorized extraction. A prospective or historical source configuration requires an applicable written permission/product route before even a payload probe. No quote/fill coverage. | DOCUMENTED restriction T1; API/account/rights/coverage/cost dimensions UNVERIFIED. Automated scraping is not a fallback. Omit this source from an executable campaign unless its dependent gates are resolved. |

### Access, rights and cost matrix

| Candidate | Current user access and permitted purpose | Retention, redistribution and offline replay | Published costs versus actual costs | Safe documentary disposition |
|---|---|---|---|---|
| Alpaca market | UNVERIFIED; old Basic-account results are not a current readback. Separate historical/recent/live feed permissions and user/entity purpose. | Exact raw, normalized and derived artifact rights, redistribution and post-account retention UNVERIFIED. | A1 lists Basic as free and Algo Trader Plus at USD 99/month on the check date. This is an indicative advertised price, not this user's plan, full fee schedule or actual spend. | Existing exploratory lineage only; propose a separately authorized access/rights check. Do not raise its grade. |
| Databento market/reference composition | UNVERIFIED by dataset, publisher, reference product and licensed entity. Free credits or account existence do not prove reference access. | Exchange, reference and account agreements need separate inspection; the terms retrieval was unavailable. Durable exact-byte/post-termination rights UNVERIFIED. | Current complete quote, exchange/non-display fees and actual spend UNVERIFIED. The recorded annual-reference purchase deferral remains a boundary, not today's price. | Documentary candidate for independent qualification; no purchase or outreach here. |
| algoseek TAQ/reference composition | UNVERIFIED; historical sandbox access does not grant a new lease, perpetual package or purpose. | Exact contract/product rights and indefinite retained bytes UNVERIFIED. An old reference screen's overwrite limitation remains unresolved for historical decisions. | Exact quote, license options, fees and actual spend UNVERIFIED. | Candidate raw-market/retrospective/prospective component; never assume sole-source historical suitability. |
| Alpaca/Benzinga news | Separate news/product/content entitlement UNVERIFIED even if stock access works. | Original-body storage, model/research use, corrections/deletions, redistribution and durable replay rights UNVERIFIED. | News-product charges and actual spend UNVERIFIED; stock-plan pricing cannot be copied into this row. | Conditional historical/prospective information candidate with original-version and rights gates. |
| SEC filings | Public interfaces DOCUMENTED; automated use must follow current fair-access requirements. Source-specific permitted use is still assessed. | No blanket assertion of rights over third-party filing content. Exact retained-document and redistribution/replay basis UNVERIFIED. | No subscription purchase is proposed; collection/storage/processing costs are UNVERIFIED, not zero. | Supplemental primary filings candidate, not a replacement for missing news history. |
| X | Approved account/use case and endpoint scope UNVERIFIED. | X2 requires stored content to follow changes/deletions; durable immutable replay needs an explicit compatible rights basis. It is not established. | X1 describes usage charging; prices, permitted spend and actual receipts UNVERIFIED. Policy and overview tier descriptions require current agreement reconciliation. | Optional and excluded from dependent immutable-replay claims until the conflict is resolved. |
| Truth Social | No applicable automation/collection permission established. | Applicable written rights and original-version/retention terms UNVERIFIED; public visibility supplies none. | Product availability, quote and actual cost UNVERIFIED. | No automated acquisition candidate under present evidence; preserve the gap rather than scrape. |

Alpaca documentary discrepancy: A1 distinguishes Basic real-time IEX access
and a historical latest-15-minute restriction, whereas A2 describes IEX as the
only stock feed usable without subscription. The old repository record reports
successful older SIP queries. Preserve all three scopes/dates. Do not treat a
past request or one current page as proof of current SIP entitlement, and do
not extrapolate stock entitlement to news. Matthew needs exact plan/feed/endpoint
and agreement evidence before an acquisition proposal can clear this gate.

No price entry authorizes spending. Unknown fees, exchange/non-display charges,
storage, compute or news costs remain unknown. Krish owns raw inference/attempt
receipts; Harsha owns accepted attribution; Matthew's account ledger remains
authoritative. Do not subtract the same fee twice or invent free inference.

## Proposed configuration choices

These alternatives are research plans, not selected products or released APIs.
Each component and every cross-source join needs its own qualification evidence.

1. **Exploratory development:** continue to reference the accepted Alpaca
   development lineage without widening the existing adapter's scope. A future
   intraday market/news component needs its own issue and accepted interfaces.
   Add an authorized news or filing source only with disclosed coverage,
   timing, rights and costs. Preserve non-promotable classification; this is
   no evidence that the present daily adapter already implements fast-news
   simulation. Retain a separately defined price-only comparison where the
   study explicitly permits it, never as a silent replacement for missing news.
2. **Historical qualification candidate:** evaluate an exact Databento
   market/reference composition, or algoseek raw observations joined to a
   separately qualified reference source, plus an independently qualified
   original-version news archive where required. Match security/listing
   identity, timestamp meaning, scope and the intersection of applicable
   restrictions. Neither raw quotes nor one PIT flag qualifies the complete
   composed dataset. Acquisition, payment and actual pilot execution are
   separate approvals.
3. **Prospective archival candidate:** plan collection of authorized market,
   news and supplemental filing inputs from a declared start, preserving exact
   permitted versions and measured receipts. It can test future causal
   availability only after accepted interfaces and an explicit operation grant.
   It cannot manufacture the original 2021-2025 history. X/Truth Social stay
   optional and must satisfy their own access/rights gates; missing social
   coverage is reported, not silently replaced with scraped content.

No option promises a news edge, realistic fill, profitable result or paper
account availability. Full overnight operation stays deferred under D06 even
if a vendor advertises an overnight feed. Scheduled calendar knowledge is not
realized-session evidence; modeled corporate-action terms are not delivered
settlements. The existing single daily evaluator/replay contract is preserved.

## Point-in-time ETF eligibility proposal

Use a preregistered **eligibility procedure**, not a hindsight-selected list.
The target remains approximately 10-15 liquid, diversified, unlevered ETFs,
with no shorting, options, crypto or automatic universe expansion. This
document accepts no numerical liquidity, spread, age or turnover threshold.

Before the campaign's selection cutoff:

1. Declare permitted exposure categories and diversification constraints under
   the accepted mandate. Record fund structure, investment objective and
   overlap from point-in-time issuer/reference evidence. Overlapping ETFs are
   not independent exposures; a current holdings page is not past holdings.
2. Require the fund/security/listing to exist and be addressable at that cutoff,
   including relevant historical names, venue, currency, inception/listing
   dates and delisting/merger relations. No ticker-only joins or survivorship
   filtering using today's available list.
3. Define the measurement window, fields and proposed numerical liquidity/spread
   criteria before evaluating confirmation returns. Use only data available
   by the cutoff; freeze a deterministic selection/tie-break rule and rejected
   candidate reasons. Matthew proposes the rule, Krish reviews research use
   and Harsha reviews selection/confirmation leakage. Missing criteria require
   acceptance, not a guessed executable default.
4. Require source/date/session coverage, corporate-action/identity treatment,
   quote suitability and required information coverage under the exact purpose.
   Missing evidence yields an explicit dependent gap. If fewer than the target
   count survive, disclose the smaller feasible set and request a scoped study
   ruling; do not pad with unsupported funds or relax a source floor.
5. Freeze the eligible manifest and rejected set with cutoff, policy version,
   reference revisions, scope, source limitations and permitted lifecycle-change
   treatment. Later entry/exit handling requires the study's accepted rule.
   Do not retrospectively reselect using future returns, realized winners or
   today's known survival. No evaluated ranking or actual ETF list is claimed
   by this public-documentation task.

The pinned [#365](https://github.com/KanujVerma/drift/issues/365) evidence names
SPY and IWM as NYSE Arca examples and QQQ as Nasdaq. They are identity/venue
examples, not an approved cohort. At the baseline,
[`ListingVenue`](../../../src/drift/domain/securities.py) contains XNYS, XNAS
and XASE, not ARCX. The
[exploratory adapter](../../../src/drift/adapters/alpaca_exploratory.py) and
[daily engine](../../../src/drift/evaluator/engine.py) also have bounded
venue/calendar contracts. Do not mislabel Arca as XNYS or assume one simplified
calendar is authoritative for every venue. Reuse #365 for an accepted venue
extension and any writer acquisition; its old ready label does not accept that
extension. No enum, clock, engine or test change is part of #378.

## Capability gates and dependent ownership

Every gate records its purpose, exact evidence, independent dimension result,
limitation, reviewer and authorized next action. No in-memory or persisted
gate implementation is created here.

| Gate | Required evidence before the dependent use | Owner/action when missing |
|---|---|---|
| Access and rights | Exact licensed entity/product/feed/purpose and scope; permissible raw/normalized/derived retention, redistribution and post-termination replay; source-specific restrictions | Matthew prepares the bounded assessment; the account/license custodian and authorized rights reviewer supply permitted evidence. No credential use, sales message or subscription under this task. |
| Historical source/version availability | Native versions and correction lineage, provider assertion availability, user receipt where required, complete retrieval scope and a justified historical availability basis | Matthew specifies the source gap; Harsha rules on the affected historical-study claim. Missing original news versions do not pass by using latest text. |
| Security and venue identity | Historical issuer/security/listing mappings and legitimate session/venue contracts, including mixed-venue cases | Reuse #365 and its approved producer/writer routing; retain venue gaps. Its workstream label is not a file-transfer receipt. |
| Information interface | Accepted #394 minimal envelope and broader #376 SRC/RESULT references for the consumed fields; #393 owns triage behavior | Matthew supplies producer specifications; Kanuj reviews only the triage boundary. Drafting source options does not require all these contracts to be finished. |
| Execution resolution and sessions | Accepted #379 timing/capability version, causal analysis completion, quote/trade eligibility, latency/spread/size/partial-fill assumptions, halt and missing-session treatment | Matthew produces EXEC; Krish reviews consumed execution semantics. Bars do not invent precise fills, and feed access does not prove broker capability. |
| Mandate and operational permission | Accepted #380 risk/approval binding and an exact later operation grant, plus #384 readiness when applicable | Matthew specifies enforcement. A document, design acceptance or simulator output enables no provider/broker operation. |
| Scientific/economic claim | Accepted Harsha methodology/experiment/attribution rules under #377/#392/#382, complete attempts and cost evidence, uncontaminated confirmation basis | Harsha owns scientific rulings; Krish supplies attempt receipts; Matthew supplies authoritative RESULT. No favorable missing statistic or zero cost. |

The consumer drafts [#407](https://github.com/KanujVerma/drift/pull/407),
[#398](https://github.com/KanujVerma/drift/pull/398) and
[#400](https://github.com/KanujVerma/drift/pull/400) are inputs at respectively
`f9ef5dfbe124865167a271430d66d3e225fdeed3`,
`d034f20c5a017469f4a5be48605359434160fa82` and
`cfdce9a68b43f74007c4e63def4f0d46dc46544f`, not accepted dependencies.
[#406](https://github.com/KanujVerma/drift/issues/406)/DP-R1 and DP-R8 remain
unaccepted at the checked source baseline. This document neither chooses their
wire/feedback rulings nor declares them universal prerequisites for #378.

### Historical and prospective claims

Historical news dated 2021 but fetched as a revised 2026 body cannot establish
the original information set at a 2021 cutoff. A snapshot frozen today can
support retrospective audit or future replay of today's acquisition, not
recover deleted/overwritten versions from before acquisition. Record model
pretraining, tuning/access history, source revisions and hindsight mapping
limits separately; even authentic original text does not prove a pristine
holdout. Harsha owns acceptance of the scientific claim and DP-R8 feedback use.

Missing original historical news can block a specific pristine news experiment
without blocking independent market/accounting development, explicitly labelled
retrospective work, synthetic document examples or prospective planning. A
prospective campaign needs its own preregistered dates and permitted archive;
it does not turn 2025 into an untouched holdout after the fact. Preserve actual
provider evidence floors and measured omissions. Stop the dependent claim or
request a declared alternative study; never silently backfill missing text,
backdate receipt, resample a favorable window or relabel exploratory output.

## Future permission requests, not operations

These are bounded request classes to prepare for later review. They do not
grant provider access and are not runnable while material fields remain unknown.
Keep one source/product per request and record rejected or incomplete attempts.

- **R1: account and rights evidence.** Request custodian-supplied, appropriately
  redacted plan/product/order and applicable terms revisions for the proposed
  licensed entity and purpose. Name rights reviewer, retention horizon,
  permitted outputs and protected storage. No API keys in chat/Git. Do not
  create accounts, contact vendors, purchase or claim clearance from silence.
- **R2: measured capability sample.** Only after R1 and the exact operation
  grant, propose at most one approved ETF, one named historical session and a
  separately named news interval, using selected read-only endpoint(s) and
  explicit feed/fields/time bounds. Proposed ceiling: three measured requests,
  one MiB of retained payload, zero new spending, no automatic pagination,
  retries, paid fallbacks or broker endpoints. The approver must resolve actual
  product, symbol, date/session, account, rights, destinations, expiry and
  storage before execution. A capped sample is not complete coverage. Preserve
  measured request/response identity, receipt timing, fees and explicit gaps;
  keep permitted payloads outside Git. Stop on a fee, denied right or scope
  mismatch. These ceilings limit a proposed probe, not scientific thresholds.
- **R3: historical version/rights qualification.** Request an exact versioned
  snapshot and scope, native record/receipt/terms evidence and existing M1e
  dimension/closure checks. Databento reference access and an immutable news
  archive need separate entitlements. X's content-compliance conflict needs an
  explicit compatible arrangement or exclusion; Truth Social needs applicable
  collection permission. No source gets permission through another provider.
- **R4: prospective collection.** Specify approved source set, start/end,
  destinations, recurrence, budgets, credentials custodian, retention/deletion
  behavior, monitoring, expiry and stop conditions under accepted contracts.
  This is a separate operation/readiness decision; #378 starts no collection.

If a canonical document needs correction outside this file, describe the exact
stale statement, evidence and producer-owned write-set in the review packet.
Posting elsewhere or changing that document needs separate authorization under
the present grant. Preserve #350/#367 and #376 writer reservations; future
stewardship, a quiet branch or this proposal is not release/acquisition.

## Synthetic document acceptance examples

These transcripts assert expected **documentation classifications**, not runtime
tests, authentic coverage, trading outputs or final #394 envelope fields.

### E01: API exists, account access unknown

The public page offers consolidated quotes; the user's exact feed and plan
are not evidenced. Expected: DOCUMENTED API capability, UNVERIFIED entitlement,
dependent acquisition gated. Do not infer Basic news access from stock access
or choose one side of Alpaca's subscription discrepancy as empirical proof.

### E02: later body at an earlier cutoff

A story is published at 13:00 UTC, revised at 13:10, and first received locally
at 13:12. Only the revised body is retained. Expected: no use of that body at
13:05, no claim that publication equals receipt, and no pristine original-body
replay. Prospective planning may continue with an honestly declared start.

### E03: hash without durable rights or bytes

A content digest and URL survive, but retention permission is unresolved or
the original bytes cannot lawfully be retained. Expected: replay closure is
not established. Do not redownload latest content as the original or treat a
matching digest as origin authentication. If X content is removed, comply with
applicable obligations rather than retain it to manufacture an immutable run.

### E04: mixed venues

The illustrative cohort contains SPY/IWM on Arca and QQQ on Nasdaq as recorded
by #365; the baseline enum cannot represent ARCX. Expected: retain the genuine
identity and name the venue/multi-clock gap. No substitution of XNYS, fake common
venue, changed enum or omission of the inconvenient member to claim success.

### E05: pre-market event without execution evidence

News is received at 08:00 New York local time, but the selected evidence covers
only regular-session observations. Expected: pre-market execution unavailable
under this configuration. A separately accepted next-session comparison may be
planned; do not fabricate an 08:00 fill or assume a vendor's 04:00-20:00 wording
settles DST, halts, latency or broker capability.

### E06: minute bars are not precise fills

Analysis completes at 10:32:45 while the only market input is the 10:32 OHLC
bar. Expected: no favorable fill at an earlier within-minute price; quote size,
spread, causal timing and execution limitations remain explicit under #379.
An advertised quote product is not an observed executable quote.

### E07: empty, incomplete and broken information feeds

A complete authorized query with a measured scope returns no stories; another
returns only page one; a third fails or lacks required content. Expected:
distinguish evidenced scoped-empty coverage, incomplete coverage and unavailable
feed. None means globally no news, safe trading, neutral sentiment or zero cost.
Discarding contentless records cannot silently improve completeness.

### E08: eligibility known after the cutoff

A fund begins listing after the campaign cutoff, or is included only because
its later returns/survival are known. Expected: exclude it from that frozen
selection or request a separately versioned prospective condition. Current
constituents and successful future data availability cannot backfill eligibility.
Unknown historical listing/venue evidence stays unresolved.

### E09: versioned reference and composed rights

An event has two provider versions; the account can retrieve only the default
latest view. Another feed supplies raw quotes but its reference join/right is
unresolved. Expected: name the missing assertion history, access or lawful join
instead of declaring the whole composition qualified. `ts_record`, event time,
local receipt and licensed retention are separate evidence dimensions.

### E10: incomplete costs and source floor

The advertised stock plan price is known, but news, exchange and storage costs
are not. A required history window begins before the source's supported floor.
Expected: disclose unknown complete economic cost and unavailable earlier scope;
do not copy stock pricing to news, replace missing cost with zero, truncate to a
favorable window or lower a qualification floor to fit D11's intended dates.

## Acceptance mapping and review boundary

| #378 criterion | Section/examples supplying it |
|---|---|
| API existence versus actual account entitlement | Evidence interpretation; capability/access matrices; E01 |
| Rights, retention, redistribution and durable replay | Access/rights matrix; gates; R1/R3; E03/E09 |
| Original versions, publication/update/first receipt and historical availability | Information matrix; historical/prospective claims; E02/E09 |
| Historical security/venue mapping | Market matrix; ETF rule; #365 boundary; E04/E08 |
| Regular/extended-session and bid/ask/fill assumptions | Market matrix; EXEC gate; E05/E06 |
| Provider limitations, complete dated primary evidence and unknown states | Source register; all matrices; Alpaca discrepancy; E01/E07/E10 |
| Defensible 10-15 ETF eligibility without hindsight-return selection | Point-in-time eligibility proposal; E08 |
| Reuse #365 and preserve all other write reservations | Venue paragraph; dependent ownership; review boundary |
| Historical news gap versus independent prospective planning | Proposed configurations; historical/prospective claims; E02 |
| No presumed social scraping rights or free feed entitlement | X/Truth Social rows; rights gates; E01/E03 |
| Narrow future permission request without execution | R1-R4; explicit ceilings, missing approval fields and stop conditions |

Required unresolved decisions: exact product/feed/entity and use rights;
retention/deletion compatibility; original-version and actual coverage evidence;
final ETF manifest and preregistered numerical criteria; mixed-venue contract;
accepted SRC/EXEC/MANDATE/research/experiment revisions for dependent consumers;
measured cost/attribution and historical confirmation eligibility. Missing
evidence blocks its dependent use, not unrelated documentary work.

Krish reviews research consumption and information/cost compatibility. Harsha
reviews historical selection, confirmation, missingness and measurement/cost
implications. Kanuj reviews only an affected triage-envelope boundary, with #394
remaining the sole normative minimal envelope. Matthew cannot self-accept
material architecture, scientific or rights rulings. AI review and document
checks are separate from producer/human acceptance and source qualification.

The review packet names exact file bytes/hash, baseline/HEAD, full uncommitted
diff, writer claim and reserved paths, pinned decisions, draft consumer inputs,
acceptance mapping, actual check commands/results and unavailable evidence.
Live progress belongs on #378; do not turn this proposal into an issue-status
database. Changed source documentation or accepted contracts need affected
revalidation before dependent use.

For this prose-only file, validate dated citations, relative links/anchors,
fences/tables, UTF-8/LF/EOF, whitespace, forbidden U+2014 and sole-file scope,
including the untracked file itself. There is no YAML/frontmatter, executable
example, saved validation script or runtime test here. No full pytest, Ruff,
mypy or build is required solely because this document changed. Keep pins,
dependencies, fixtures, schemas and all other files untouched.

No provider/model API call, data download, secret/private-state access, purchase,
email, broker operation, order, recovery/containment probe, host/network change,
deployment, live capital, commit, push, PR, formal review post, merge or issue
closure is authorized by this document. The current local documentation task
stops at the exact diff, checked review packet and issue-bound checkpoint.
