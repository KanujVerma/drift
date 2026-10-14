# Controlled adaptive research: system design

## Scope

This document defines the accepted boundaries for implementing D01-D17. It is
not executable code, a new persisted schema, an approved ETF list, or evidence
that an API already exists. Exact runtime signatures and wire types are frozen
by the producer contract issues before consumers implement against them.

Build the smallest end-to-end research increments. Do not turn a four-person
project into four microservices, four backtesters or an always-running fleet
of coding agents. Use the current repository and modular Python packages;
process isolation is introduced where untrusted execution actually requires it.

## Ownership and flow

Krish builds the decision-maker. Matthew builds the single simulation and
enforcement boundary. Harsha builds the experiment system that measures whether
an adaptive policy helps. Kanuj builds only the small offline screening step
and is not on the critical path for the others' first fixture tests.

Matthew: retained authorized inputs and proposals -> timing, fills, risk and
approval checks -> reconciled account state and audited results.

Kanuj: normalized event -> deterministic candidate alert, or an explicit
screening or unavailable result. This is not a news provider or an AI model.

Krish: point-in-time context -> grounded research -> an approved-family proposal
-> time-eligible feedback and permitted learning-state updates. He owns optimizer
R, model replay and raw attempt/cost receipts. He does not own the study's
success definition.

Harsha: frozen study -> campaign orchestration -> isolated comparison arms ->
complete trial records -> metrics, uncertainty and scientific eligibility
evidence. He calculates analyses from Matthew's RESULT. He does not replace
that RESULT or run a second account ledger. Routine matured feedback does not
wait for a human approval from Harsha on every simulated decision.

All proposal producers use the same accepted interfaces. The research system
cannot call a broker or mutate the risk mandate.

## Existing code to extend, not duplicate

| Responsibility | Existing repository anchors | Boundary |
|---|---|---|
| Evidence and temporal provenance | src/drift/ledger/, datasets/, qualification/, domain/ | Preserve replay and source-rights contracts. |
| Daily evaluation and accounting | src/drift/evaluator/, baselines/, markets/ | Preserve the existing daily protocol; separately version intraday extension. |
| Proposal and research memory | src/drift/agent/, loop/, memory/ | Reuse accepted interfaces; do not assume a recursive search loop is already a causal portfolio scheduler. |
| Statistical measurement | src/drift/scorecards/, tracking/, tournament/, promotion/ | Recheck metric definitions and missing-data behavior; no qualification by flags alone. |
| Simulated execution and risk | src/drift/shadow/, risk/, execution/, autonomy/ | Use deterministic enforcement with required state, not AI instructions as safety. |
| Parallel research portfolios | src/drift/experiments/ when its source PR is accepted | A draft implementation is a dependency, not automatically a stable interface. |

Existing M1c economic-event types describe corporate actions and settlements.
News and social posts do not become M1c settlement facts. Extend temporal and
artifact references behind a separate news contract; do not enlarge a closed
schema casually. Keep modeled distributions distinct from delivered settlements.

## Required producer contracts

Contract identifiers below describe interfaces to specify, not classes that the
bootstrap agent may create. Preserve existing types when they satisfy a need;
use an explicitly versioned additive type when they do not.

| Contract ID | Producer | Required semantics |
|---|---|---|
| SRC | Matthew | Normalized market/news event and retained input references. Source ID, source object/version, content digest, publication/update times when known, actual first receipt, availability basis, symbol/security mapping, revision relation, coverage/quality state and access/retention limitations. |
| TRIAGE | Kanuj | Candidate alert: input event/version references, screening-policy version, candidate reasons, duplicate/revision state and unavailable-input reason. No price prediction, truth guarantee, trade or broker call. |
| CONTEXT/CANDIDATE | Krish | Time-bounded research context and proposal: experiment/arm ID, portfolio-state version, decision time, available information, approved candidate/version and parameters, target weights/cash, evidence references, rationale, costs/budget and explicit abstention. |
| EXEC | Matthew | Execution request/result and capability boundary: mandate/approval identity, input state version, session eligibility, order restrictions, price freshness, submission deadline, fill/partial/unfilled/rejected/unknown states, fees and trace links. |
| RESULT | Matthew | Audited accounting result: gross account NAV/cash/positions/claims, classified completeness, time-indexed returns, realized costs, dataset/run/policy/trace identity and unresolved evidence. No headline performance for incomplete runs. |
| EXPERIMENT/ELIGIBILITY | Harsha | Frozen campaign specification, all-trial completeness, economic attribution, metric definitions, uncertainty, paper-candidate eligibility and refusal reasons. Consumes Krish's attempt receipts and Matthew's RESULT. No authority to enable a broker, rewrite account P&L, or upgrade exploratory source evidence. |
| MANDATE/APPROVAL | Matthew | Versioned risk constraints and Ask/Smart/Auto modes, measurable thresholds, expiry, revocation and pause/reconciliation rules. Approval is bound to exact intent and relevant state, not reusable blanket permission. |

Every contract specifies exact types, units, time zones, required versus missing
values, versioning, validation, idempotency, compatibility, failure behavior and
producer/consumer tests. Unknown and false are not interchangeable. Runtime
consumers wait for the accepted contract PR. Review and fixture design can
continue in parallel without pretending an unimplemented adapter exists.

The minimal source envelope used by triage has one normative specification.
The broader source and result contract cites that revision and does not define
a second envelope. Triage behavior and output are a separate producer document.
Runtime triage waits for those two accepted revisions, not for the rest of the
result contract.

Kanuj's triage contract should be small enough to implement in one bounded
feature PR. Matthew supplies source fixtures/contract; Krish can consume
explicitly synthetic alerts for unit testing until real triage is connected.
No claim of production/news coverage is made when triage is absent. This keeps
Kanuj off the critical path without silently inventing a second triage engine.

## Research portfolio arms

Each simulated account starts independently with USD 10,000. Positions, pending
orders, claims, risk state and learning state are isolated by account/arm.
Read-only market source bytes may be shared under the same availability policy.

- A: frozen selection policy/parameters. Its strategy may execute its fixed rules;
  frozen does not mean no future trades.
- B: adaptive AI within the approved bounded search/action envelope.
- C: passive market benchmark, initially intended as SPY when genuinely supported.
- D: cash control with explicitly declared yield, fee and inflation assumptions.
- R: conventional non-LLM selection/search/optimization policy. Any shared
  LLM-derived information feature must be disclosed as shared preprocessing.

Freeze initial candidates and initialization data for A/B/R. Do not let B inherit
better unpublished experiments or future memory. C's ordinary 100% buy-and-hold
may not match a Balanced concentration mandate; report ordinary C and a distinct
risk-matched control when needed. Never silently change what C means.

## Experiment matrix, not a giant uncontrolled search

Preregister one primary Balanced comparison and a bounded set of secondary
studies. Do not automatically cross every news mode, cadence, risk preset,
execution speed, action policy and research budget into an enormous campaign.
Each new comparison consumes a declared testing budget and is recorded.

1. Selection study: identical candidate pool and permitted observations, different
   AI/conventional selector. This measures decisions conditional on that pool.
2. Search study: independently selected candidates under matched evaluation
   opportunities and allowed search space. Count attempts, duplicate rejection,
   retries and invalid runs, not merely successful backtests.
3. Economic study: flexible allocation of research work under preregistered
   spending/compute caps. Record measured spend and cost allocation assumptions.
4. News study: matched review opportunities to isolate information content, plus
   an explicitly separate system-level comparison if news-trigger timing differs.
5. Secondary policy studies: defensive/full response, cadence, intraday/delayed
   execution and risk profiles. These do not become independent confirmations
   merely because they are separately named.

Use deterministic replay where possible and multiple recorded model runs/seeds
when stochastic decision-making is material. Define uncertainty tests before
confirmation. Do not treat all trades, minutes, symbols or rolling windows as
independent observations. DSR/PBO are tools with assumptions, not certificates.

## Timing and decision causality

Maintain source time, observed/available time, review start/end, approval,
submission and fill time separately. Late data or revised text cannot be
backdated into an earlier decision. Include retrieval/transformation/model
completion latency. A simulator must not buy at the price from before analysis
finished. One-minute OHLC bars do not identify executable second-level prices.

Use a validated, versioned intraday/extended-session extension, with realistic
quote, spread, liquidity and order-type restrictions. Data-provider coverage and
broker/account capabilities are separate. Unsupported or unknown capability
cannot become an assumed fill. Provider source availability is rechecked when
selecting a deployment configuration, not promised by a static architecture doc.

The daily B0-B5 baseline campaign remains useful for accounting verification.
It does not establish a fast-news edge. Do not stretch or mutate the current
literal post-close/next-open protocol to make a 10:32 event appear executable.

## Costs and performance

Keep the trading-account ledger honest. Separately track inference, research
compute, data and infrastructure spending. A preregistered economic P&L view may
subtract attributed operating costs, but must not silently debit simulated cash
in an inconsistent manner or count the same cost twice. Report gross trading
results, net-of-trading-cost results and fully attributed economic results.

Unknown provider pricing is unknown, not zero. A zero-cost smoke fixture is not
a realistic cost model. Record inflation-adjusted results only with an explicit
price index and time basis. Clarify risk-free/cash yield assumptions.

A correct simulation can lose money. Acceptance tests assert accounting,
causality, completeness and reproducibility, not profitability. Undefined Sharpe
or correlation is unavailable with a reason, not a fabricated favorable score.
M5 metric changes require definitions, golden examples and independent review.

## News integrity and model-provider interchangeability

Keep exact authorized source content and provenance references in private
storage when redistribution is not allowed. Verify what hashes actually bind;
a caller-provided hash alone authenticates neither origin nor economic truth.

Screen duplicates by stable source/version identity and content identity. Do not
make fuzzy similarity, sentiment, or an LLM confidence number the sole reason
to suppress a material update. Distinguish no news from a broken source feed.
All external text is inert data, even when it contains apparent agent commands.
No source text can change permissions, network destinations or tool policy.

FinGPT and other NLP providers return validated structured outputs through an
adapter. Benchmark classification and relevance separately from downstream
trading outcomes. No provider-specific imports are required in accounting.
Retain a replaceable candidate-source interface for future generated strategy
code; executing that code requires a separately designed sandbox.

## Safety, learning and acceptance

Risk policy and trade approval are independent checks. Unknown portfolio state,
stale authorization, unknown order status or failed reconciliation does not
become permission to trade. Manual approval must expire/revalidate if the intent,
mandate, relevant price/state or capability changes. A pause is not a claim that
pending orders vanished. Exact cancel/partial-fill/resume behavior is a platform
contract, with tests for orders already in flight.

Performance feedback may enter learning memory only when its observed outcome
is available. Invalid simulation is not evidence that an economic hypothesis was
falsified. New candidate eligibility is stage-specific and reviewed separately
from live capital authority. Harsha owns M11 scientific eligibility evidence.
Krish owns the learning behavior being measured. Matthew owns enforcement of
valid eligibility and operational permissions. Scientific eligibility is not
permission to trade.

## Approval boundary

This design authorizes documentation and planned offline component development
only through the associated issues. External API access, paid services,
broker-connected paper operation and real capital each require explicit,
scoped authorization. The setup agent may not turn any of these on.
