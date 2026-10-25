# Drift: external-code reuse review and proposed implementation backlog

Reviewed: 2026-10-25
Status: research and architecture proposal, not an accepted ADR, implementation claim, security certification, or trading authorization.

## Scope and confidence

This review screens the 20 repositories supplied by Kanuj and adds the research projects already relevant to Drift: Qlib, RD-Agent, LEAN, TradingAgents, FinGPT, and FinRL. It combines repository documentation with selected source inspection. No third-party bot was installed, executed, connected to an exchange, or performance-benchmarked. A README's performance or reliability claim is not a reproduced result.

Drift references inspected:
- docs/architecture/adaptive-experiments/decisions.md
- docs/architecture/adaptive-experiments/stage1-roadmap.md
- docs/architecture/adaptive-experiments/reuse-evaluation.md
- src/drift/intelligence/conventional_selector.py

The Stage 1 target remains a controlled comparison of monthly B3/B4/B5 selection over a qualified ETF universe, with isolated accounts, matched information, risk and execution policies, retained original evidence, and separate research costs. Crypto, leverage, arbitrary generated code, and freeform asset allocation are not silently added by this review.

## Recommended adoption order

1. Adapt Freqtrade's bias and startup-history testing approach into tests around Drift's actual paths.
2. Adapt Passivbot's offline normal-loop harness and Hummingbot's late-fill/order tracking tests into Drift's execution conformance suite.
3. Evaluate Qlib as an isolated training/feature worker for a separately frozen conventional ML comparator. Do not replace the primary R formula without its own decision.
4. Evaluate LEAN against Drift on an explicit synthetic conformance corpus before considering any backend migration.
5. Trial RD-Agent, TradingAgents, and FinGPT as bounded research producers in later named experiments. They receive evidence, not execution credentials.

## The 20-project screen

| Repository | Proposed disposition | Primary source |
|---|---|---|
| freqtrade/freqtrade | High priority: bias/warmup diagnostics and research workflow. Whole crypto runtime is not the integration target. GPL-3.0 requires compatibility review before copying code. | https://github.com/freqtrade/freqtrade ; https://www.freqtrade.io/en/stable/lookahead-analysis/ ; https://www.freqtrade.io/en/stable/recursive-analysis/ |
| Drakkar-Software/OctoBot | Later operator UX and plugin/configuration reference. Do not import a second accounting system. GPL-3.0. | https://github.com/Drakkar-Software/OctoBot |
| chrisleekr/binance-trading-bot | Selective strategy-package, idempotency and operator-UI reference. Inspect current main, not the old master branch. Account profiles share a wallet, unlike isolated experimental arms. | https://github.com/chrisleekr/binance-trading-bot/blob/main/README.md |
| binance/binance-skills-hub | Later read-only API/schema reference if crypto is separately authorized. Not a research engine or mandatory risk boundary. Verify applicable skill licensing before reuse. | https://github.com/binance/binance-skills-hub |
| binance/ai-trading-prototype | Educational architecture and negative accounting example, not an execution dependency. README explicitly warns against application use and documents a commission limitation. | https://github.com/binance/ai-trading-prototype |
| nkaz001/hftbacktest | Future intraday execution sensitivity laboratory. Replay assumptions, queue uncertainty and lack of market impact must remain explicit. | https://github.com/nkaz001/hftbacktest ; https://hftbacktest.readthedocs.io/en/latest/order_fill.html |
| YuriyKolesnikov/rl-trading-binance | Later RL comparator research only. Action space, curated data and training protocol do not match the Stage 1 study. | https://github.com/YuriyKolesnikov/rl-trading-binance |
| yasinkuyu/binance-trader | Low priority example. No demonstrated advantage for Drift's current integration task. | https://github.com/yasinkuyu/binance-trader |
| enarjord/passivbot | High priority: deterministic fake-live scenarios and live/backtest planner parity. Do not adopt its futures/grid strategy as Drift's strategy. | https://github.com/enarjord/passivbot ; https://github.com/enarjord/passivbot/blob/master/docs/fake_live.md |
| 51bitquant/binance_grid_trader | Low priority grid example; not the ETF strategy-selection study. | https://github.com/51bitquant/binance_grid_trader |
| Open-Trader/opentrader | Later UI, strategy-package and paper/backtest workflow reference. Verify core versus optional pro-component licensing independently. | https://github.com/Open-Trader/opentrader |
| sorry510/go_binance_futures | Selective explicit migration, controlled proposal and operational-state UX reference. Not a reason to rewrite Drift in Go. | https://github.com/sorry510/go_binance_futures |
| hotbridgeLab/future-trading-ai-agent | Small proposal/risk-mode reference. Fallback modes must be named experimental policies, not silent behavior changes. | https://github.com/hotbridgeLab/future-trading-ai-agent |
| ItzJulkar/binance-os-agent-strategies | Reject the headline live-MCP execution model for Drift. Local paper tools exist, but the promoted path authorizes real orders. | https://github.com/ItzJulkar/binance-os-agent-strategies |
| conor19w/Binance-Futures-Trading-Bot | Optional future strategy examples, not a core runtime dependency. Frozen strategy identity and matching execution remain necessary. | https://github.com/conor19w/Binance-Futures-Trading-Bot |
| Paparusi/Clawtrade | Later research/operator experience reference, not an automatically accepted all-in-one trading control plane. | https://github.com/Paparusi/Clawtrade |
| hummingbot/hummingbot | High priority: tracked/lost order handling, late fills, controller/executor responsibilities and tests. Translate status semantics explicitly. | https://github.com/hummingbot/hummingbot |
| Oceanjackson1/Binance-AI-Agent | API coverage reference only. Broad trading/transfer/withdrawal tools are not appropriate research-agent capabilities. | https://github.com/Oceanjackson1/Binance-AI-Agent |
| heider-x/sirius | Selective watchdog, no-overlap and operations patterns. The inspected scheduler logs threshold breaches; it does not disable the job. | https://github.com/heider-x/sirius |
| finlandhl/rebirth-trader | Exclude from code reuse without permission: inspected LICENSE is All Rights Reserved. | https://github.com/finlandhl/rebirth-trader/blob/main/LICENSE |

## Concrete source-entry points

These are inspection entry points, not a blanket license or a promise that modules import independently. Branch tips below were observed during review; compare exact source bytes and file-specific terms before adoption.

| Project | Commit reference observed | Files/components |
|---|---|---|
| Freqtrade | 150a10bc2b2c49959975693fafd668f7fb37de7d | freqtrade/optimize/analysis/lookahead.py; official lookahead-analysis and recursive-analysis documentation |
| Qlib | 54355232463878d2eebb91fe0ee5fa7fa1f5976c | qlib/workflow/task/gen.py; qlib/contrib/model/gbdt.py; Qlib Recorder documentation |
| RD-Agent | 484776c211e4fbbeef03e0ec00d6bbee7362a4f4 | rdagent/components/workflow/rd_loop.py |
| Hummingbot | 9af100d6822da7d2d0291a906c730ef172284ee2 | hummingbot/connector/client_order_tracker.py; test/hummingbot/connector/test_client_order_tracker.py |
| Passivbot | 772abadc10a5bbf258a84aa8209a9084699fa1bd | src/exchanges/fake.py; src/tools/run_fake_live.py; docs/fake_live.md; scenarios/fake_live/ |
| Sirius | cc10bddd84a325863fa04090e2e0fbb98b659638 | src/sirius/scheduler/runner.py; tests/test_infra.py |

Additional sources:
- RD-Agent paper: https://arxiv.org/abs/2505.15155
- Qlib: https://github.com/microsoft/qlib
- RD-Agent: https://github.com/microsoft/RD-Agent
- LEAN: https://github.com/QuantConnect/Lean
- LEAN architecture: https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview
- TradingAgents: https://github.com/TauricResearch/TradingAgents
- FinGPT: https://github.com/AI4Finance-Foundation/FinGPT
- FinRL: https://github.com/AI4Finance-Foundation/FinRL

## Work package A: causality and warmup conformance

Mode: new tests around existing authoritative Drift computation, not a replacement backtester. Reuse the experimental approach; do not assume GPL source can be copied without the distribution/license decision.

### Required cases

A01. Retain all evidence genuinely available at cutoff T, the full eligible ETF universe, original account state, strategy identity and policy. Mutate only evidence first available after T. Eligible features, model request bytes and the decision at T must remain invariant.

A02. Repeat using a physically truncated snapshot. Compare semantic as-of inputs and decisions, not unrelated operational UUIDs or whole-future-bundle hashes.

A03. Preserve cross-sectional ranking inputs across all ETFs. Removing other assets is a separate universe experiment, not a lookahead test.

A04. A historical observation revised after T must not replace its original vintage at T. A future scheduled event already announced before T is not forbidden merely because its economic date is later.

A05. Poison a cached feature/model output whose training or availability cutoff is too late. Cache existence must not override eligibility.

A06. Exercise every supported decision branch, including hold, abstain, unavailable and refusal. Untriggered paths are explicitly not tested, never declared unbiased.

A07. Vary startup history only within the strategy's accepted requirements. Report indicator and actual decision sensitivity. Below the required B4/B5 history, require unavailable/refusal, not empty-target liquidation.

A08. For LLM producers, compare the exact constructed request and retrieved evidence, then use captured responses for deterministic replay. A second stochastic API call is not the oracle.

A09. Do not silently change trading protections, portfolio capital or order types to make the production path appear equivalent. Diagnostic approximations receive a separate label.

Finish line: a positive and a deliberately leaking negative pass through the same real producer/evaluator path, with retained reproduction inputs and expected versus observed assertions.

## Work package B: offline operational scenario harness

Mode: run Drift's normal authorized orchestration against a deterministic fake transport and clock. No exchange account, credentials or network. Use existing financial and audit records, not a parallel fake PnL ledger.

### Required cases

B01. Submit accepted by transport; acknowledgement lost. Restart and reconcile without automatic duplicate submission.
B02. Partial fill arrives before order acknowledgement.
B03. Duplicate fill message does not duplicate cash/position changes.
B04. Out-of-order status observation does not erase a confirmed fill.
B05. Cancel races with a real fill. Preserve both original observations and derive state from evidence.
B06. Repeated lookup misses remain unresolved economic state until supported otherwise. Do not map a local failed/lost tracker label to proven rejection.
B07. Fill arrives after the active-order tracker drops an order. A retained reconciliation path still accounts for it.
B08. Crash after persistence but before caller acknowledgement. Cold readback finds the original record without reexecuting.
B09. Stale quote/account state blocks new exposure; missing data is not zero exposure.
B10. LLM worker hangs or times out. Deterministic risk, reconciliation and protective operations do not wait for it.
B11. Repeated job failures trip an actual persistent state transition under the approved policy, not only an error log. Restart does not silently reset the latch.
B12. Artifact cap or storage failure preserves incompleteness. A truncated diagnostic log cannot certify complete original evidence.

Do not copy Hummingbot's local FAILED semantics as Drift's broker finality. Do not copy Passivbot's bounded diagnostic event capture as an authoritative audit trail. An asyncio timeout is not isolation against noncooperative code.

Finish line: exact ledger, book, order and uncertainty assertions survive each injected failure and a fresh-process readback. No automatic retry creates a second economic order.

## Work package C: Qlib-backed experimental comparator

Reuse candidate: Qlib's actual model and rolling-task machinery, in a separately pinned worker if its dependency/runtime requirements differ from Drift's.

Pipeline:
1. Receive a frozen, qualified development snapshot with explicit first-availability cutoffs.
2. Generate labels for the actual decision target and horizon. Stock-ranking examples are not automatically B3/B4/B5-selection labels.
3. Use chronological rolling training/validation. Set label-overlap truncation explicitly; RollingGen's optional trunc_days is not automatic proof of no leakage.
4. Train a bounded conventional model, initially a simple baseline rather than an unrestricted search.
5. Retain training window, feature/label versions, hyperparameters, seed, dependency manifest, model artifact and all attempted fits.
6. Export scores and failure states into Drift's existing ResearchContext/ResearchCandidate and select_conventional_candidate boundary. No worker writes financial truth or grants itself execution permission.
7. Preserve R as the separately approved primary comparator. Name the new method R-ML until a reviewed study decision changes its role.
8. Charge original compute/data cost once under the frozen attribution policy. Missing costs remain unavailable.

Finish line: one eligible, one future-trained, one missing-feature and one nonfinite-score case, plus immutable prediction replay, all enforced through the same adapter. Qlib's recorder can be a diagnostic index, not another authoritative trial registry.

## Work package D: research-producer comparisons

Candidate producers: a single bounded model, analyst plus critic, TradingAgents, and later an RD-Agent worker. FinGPT is a possible input extraction/sentiment component, not an order rule.

Hold the experiment's evidence, candidate menu, review opportunities, risk policy, execution model and measurement constant. Freeze each method's prompts, tools, model versions, stopping/retry rules and budget. Retain every attempt, including failure and invalid proposals.

Compare output validity, evidence coverage, reproducibility, latency, total research cost and downstream net economic outcome. More prose, more roles or a confident explanation do not count as improved decisions.

Generated strategies belong in a distinct future study with enforced process/filesystem/network/resource boundaries and independent eligibility. They do not enter the trusted evaluator through arbitrary Python callbacks.

## Work package E: LEAN build-versus-reuse challenge

Do not defend the current evaluator solely because it already exists. Do not replace it solely because another engine is larger.

Run the same hand-checkable scenarios through the native evaluator and an isolated LEAN adapter: whole-share rebalance with costs, a declared corporate-action case, and a calendar/partial-or-unfilled execution case supported by both models. First align timing, price adjustment, fees, rounding, fill assumptions and data vintages. Missing capability is reported, not silently approximated.

Compare semantic outputs rather than unrelated internal hashes. Investigate every cash, position, fill and cost discrepancy. Compare integration code, dependencies and maintenance obligations as well as correctness.

A backend change needs a separate architecture decision and preservation of original evidence interfaces. Two independently authoritative PnL ledgers are not an acceptable permanent outcome. LEAN as a test oracle is not LEAN as an automatically trusted truth source.

## Admission checklist for any reused component

- Exact upstream revision and copied/imported files.
- Root and file-specific license, required notices, dependency and model/data terms.
- Dependency lock and compatibility test in the intended environment. Do not alter Drift's interpreter pin merely to install a candidate.
- Read-only input snapshot; no brokerage credentials for research workers.
- Explicit time-availability and source-rights checks.
- Typed outputs with strict validation; missing and uncertain states preserved.
- Stable reference to complete original output, request, code, model and cost evidence.
- Resource budgets and failure handling; no silent fallback to a different strategy or model.
- Test cases that fail before a real repair, focused regression and end-to-end verification.
- Independent review where the existing Drift contracts require it.

## Product priorities and exclusions

Immediate objective: one complete reproducible experiment that can be run, replayed and explained from original evidence. Reuse should shorten that path, not add a second control plane.

Defer crypto connectors, leveraged grid/martingale strategies, arbitrary generated code, a full multi-agent desk and HFT engineering until separately motivated and authorized. A license-compliant library adoption does not qualify source data or demonstrate investment value. A passing test suite does not grant operational authority.

No implementation, merge, external account connection, paid API call or claim of G2 closure was performed by this research review.
