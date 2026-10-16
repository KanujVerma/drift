# Stage 1 strategy-adaptation decisions: S01-S38

## Authority, lineage and scope

These 38 decisions record Kanuj's sequential Stage 1 architecture discussion, accepted as **research/product direction** through October 16, 2026. They are numbered **S01-S38** to distinguish them from the separate, already accepted **D01-D17** broader adaptive product decisions in [decisions.md](decisions.md). The first 17 items in this Stage 1 discussion are **not** identical to D01-D17. Neither register replaces or retroactively renumbers the other. The narrower Stage 1 protocol is an initial controlled study under the broader product direction, not cancellation of longer-term event, intraday, advanced allocation, or news goals.

**Evidence and permission:** An owner-approved design direction does not establish an implemented mechanism, accepted producer contract, a qualified data source, a completed independent review, a valid backtest, AI advantage or permission to use a provider, trade in a paper account or deploy real capital. This document and the companion [Stage 1 implementation roadmap](stage1-roadmap.md) need review and merge under [coordination issue #418](https://github.com/KanujVerma/drift/issues/418). All numerical limits, final ETF selection, source rights, model versions, costs, forecasting formula, success thresholds and wire semantics remain separately gated until their evidence-backed specifications are accepted.

**Terminology:** The existing independent account arms in [design.md](design.md) are frozen strategy A, adaptive AI B, passive C, cash D and conventional R. The letters A and B appearing in particular decisions below refer to **option/experiment variants**, not necessarily those account names. All compared investment accounts are independent, initially USD 10,000, with identical eligible time-of-decision information, constraints and execution assumptions within a comparison.

## Research question and controlled action space

### S01. Prioritize adaptive portfolio decisions over news-first evaluation
**Decision:** The first question is whether AI-directed adaptation improves portfolio decision-making, rather than whether an LLM classifies news well. News remains an important later input and ablation under D02/D09/D12.

**Rationale:** Starting with the investment decision isolates incremental selector value; introducing unqualified news simultaneously could confound source quality, timeliness, extra information and actual AI decision quality.

### S02. Stage the AI action space rather than allowing everything immediately
**Decision:** Stage 1 selects one of three existing approved, fixed strategies. Later Stage 2 can test changing allocations or combining approved strategies; Stage 3 can test tuning approved parameters. Arbitrary generated executable strategies are outside this initial study and need separate security/eligibility controls.

**Rationale:** More flexible actions increase both experimental degrees of freedom and the chance of silently comparing different risk exposures. Preserve the broader D01 extensibility without claiming later capabilities are implemented.

### S03. Stage 1 candidates are B3, B4 and B5, not discretionary cash
**Decision:** The AI selects among **B3 monthly equal-weight rebalance, B4 12-minus-1 cross-sectional momentum, and B5 low-volatility selection**. The AI cannot choose a standalone all-cash strategy. Retain passive and cash as independent controls, and consider explicit trend/cash strategies in a separately named future experiment.

**Rationale:** A bounded menu provides a measurable strategy-selection problem. Cash resulting from rounding, incomplete fills or a deterministic risk overlay is **not** an AI-selected cash strategy. Preserve the actual frozen strategy algorithms and hashes.

### S04. Switching takes effect at the next eligible market open
**Decision:** After a valid monthly AI selection, calculate the newly selected strategy's fixed target portfolio and submit the authorized transition for the **next eligible open**, with actual simulated eligibility, costs, available state and possible partial/unfilled outcomes. A switch need not wait for the selected strategy's ordinary monthly rebalance.

**Rationale:** Otherwise strategy selection could take effect at inconsistent times, while same-close fills would leak unavailable execution prices. Require an accepted switch/transition contract, rather than assuming the current evaluator already changes strategy identity midrun.

### S05. Monthly switching is the primary study cadence
**Decision:** Make AI/R strategy-switch opportunities monthly, with all arms following comparable checkpoints. Event-triggered strategy reviews and faster changes belong to separate later experiments. Within a strategy, its existing approved trading rules may still generate orders independently.

**Rationale:** Monthly checkpoints contain turnover, decision count and timing confounders. This is a Stage 1 restriction, not a repeal of D03/D04/D06's wider monitoring and event-driven roadmap.

### S06. Each selector sees all candidates' completed counterfactual outcomes
**Decision:** At decision time, show audited completed performance of all B3/B4/B5 reference portfolios, including candidates the selector did not choose, plus its own matured decisions. R receives equivalent eligible information.

**Rationale:** Learning only from the selected account would hide relevant counterfactual evidence. Reference portfolios are separately simulated; their gains are **not** credited to the AI's realized account.

### S07. Require common 253-session warmup before scoring
**Decision:** Start scored selection only after every B3/B4/B5 strategy has an eligible common history, using **at least 253 completed sessions** for the existing B4 12-minus-1 requirement. B5 currently needs 61 sessions.

**Rationale:** Missing lookback must be represented as ineligible/unavailable, not as an empty target or a disguised instruction to liquidate. Missing source coverage can extend or invalidate warmup.

### S08. Separate warmup, observation and scored evaluation
**Decision:** Warmup establishes strategy indicator eligibility; a subsequent observation period develops completed comparable candidate-performance history. Neither is scored as AI investment outperformance.

**Rationale:** Warmup and learning history serve different purposes. This avoids treating the first eligible momentum calculation as a mature performance history.

### S09. Use 126 completed observation sessions, then fresh accounts
**Decision:** After the 253-session warmup, collect **126 completed market sessions** (approximately six months) of observation, then initialize fresh independent USD 10,000 scored accounts. Explore approximately three- and twelve-month observations only as preregistered development sensitivities.

**Rationale:** Six months supplies meaningful candidate feedback without choosing a start date based on subsequent returns. Incomplete or ineligible sessions cannot be silently counted.

### S10. Use hybrid long-term and recent memory
**Decision:** Preserve an auditable complete history, while the model's standardized decision context emphasizes the most recent **126 completed sessions** through frozen summarization/selection rules.

**Rationale:** An exclusively short window discards recurring regimes; an unbounded transcript can be expensive and distract from recent evidence. No future or unmatured outcome may enter memory.

### S11. Begin with diversified, multi-asset-class ETFs
**Decision:** Research a roughly 10-15 ETF universe representing U.S. and international stocks, Treasuries, investment-grade credit and potentially gold. Avoid an equities-only Stage 1 comparison.

**Rationale:** Different market regimes create meaningful reasons to prefer momentum, low volatility or equal weight. Broad exposures still entail correlation, rate and credit risks.

### S12. Freeze the ETF universe before scoring
**Decision:** Approve and version an exact ETF list before a scored campaign. The AI cannot add instruments opportunistically. Enforce time-eligible listings, historical availability, rights, adjusted prices/corporate actions and authentic market venue/calendar support.

**Rationale:** Hindsight-selected ETFs can manufacture an apparent strategy edge. The final proposed list remains **unapproved** pending data qualification and portfolio feasibility tests.

### S13. Update feedback monthly with matured observations
**Decision:** At each monthly checkpoint, provide completed B3/B4/B5 performance, risk, 1/3/6-month market/strategy trends where data exists, and the selector's matured outcomes. Use the same predetermined features and availability cutoffs for AI and R.

**Rationale:** Frequent intermediate reflection without a frozen feature/timing policy adds invisible degrees of freedom. Missing or not-yet-matured information is unavailable, not zero.

### S14. Abstention preserves the current valid strategy, never auto-cashes it
**Decision:** If the AI abstains, produces invalid output or cannot support a switch, retain the active strategy **only while its current holdings and evidence remain valid**. A critical mandate, accounting, price, permission or source failure invokes predefined fail-closed containment/refusal, not assumed continued compliance.

**Rationale:** An unplanned cash liquidation would be a hidden defensive strategy. A hard evidence or safety failure cannot be covered up as a harmless abstention.

### S15. Preregister two initial-selection protocols
**Decision:** **Primary:** every adaptive selector starts scored evaluation in B3, with its first possible switch after the first complete scored month. **Secondary:** AI and R may choose B3/B4/B5 at the scored start using only the 126-session observation history. Report protocols separately.

**Rationale:** Equal B3 starts isolate adaptation from favorable initialization. The secondary protocol tests whether pre-start learning itself has value without choosing the better protocol from the final results.

### S16. Require a grounded rationale for every proposed switch
**Decision:** A switch proposal includes time-eligible evidence identifiers, expected advantage, costs, risks, comparison to staying put and an explanation. A deterministic validator checks format, eligibility, authority and evidentiary references.

**Rationale:** The validator ensures procedural validity, **not** that a market forecast is correct. Explanations and provenance make invalid or hindsight-influenced decisions auditable.

### S17. Do not impose an arbitrary predicted-gain hurdle
**Decision:** Stage 1 requires grounded evidence and explicit switching-cost consideration, but no invented minimum percentage of forecast improvement to permit a switch. Reconsider a calibrated hurdle in a distinct study.

**Rationale:** An unvalidated threshold could bias switching opportunities and conceal poor predictions. Risk limits and ordinary cost economics still apply.

## Competition, objectives and risk

### S18. Challenge AI with a real risk-aware conventional selector
**Decision:** Make **R**, a frozen risk-aware deterministic selector using eligible completed returns, volatility, drawdowns and estimated switching costs, the primary adaptive competitor. Include **R-simple**, the previous-six-month return winner, as a simpler diagnostic.

**Rationale:** Beating only a recent-winner heuristic would not establish incremental AI value over a reasonable conventional decision rule. R's exact mathematical formula and hyperparameters must be researched on development data and frozen before scoring.

### S19. Optimize net investment returns subject to Balanced risk constraints
**Decision:** The primary investment objective is higher **net-of-trading-cost returns**, subject to the same preregistered Balanced mandate. Report drawdowns, volatility, turnover, benchmark comparisons and separately attributed inference/data/research spending; economic value is evaluated as well.

**Rationale:** A higher-return selector that silently takes more risk or incurs greater operating costs may not be better. Risk limits do not guarantee a realized maximum drawdown.

### S20. Compare rejection with incoming risk adjustment
**Decision:** **Primary fixed-risk version:** reject an incoming strategy switch if its proposed target violates the mandate, retaining the existing strategy if that portfolio is still valid. **Secondary version:** a deterministic risk overlay may adjust the incoming proposal into compliance. Existing critical violations follow independent containment/remediation rules under S22.

**Rationale:** Rejection isolates selection quality. Allowing a risk overlay to repair proposals could improve usability but introduces a second performance-changing mechanism and must be tested separately.

### S21. In the adjustment version, trim only violating positions
**Decision:** For a proposed incoming portfolio that breaches a numerical limit, test a deterministic **minimum necessary trim** of offending holdings; keep resulting residual capital in cash unless another separately approved rule permits redistribution. Do not proportionally rescale the whole book by default.

**Rationale:** A targeted trim preserves more of the selected strategy's intended holdings. The risk overlay, not the AI, owns adjustments. Multi-asset-class conflicts, ordering, ties, rounding, feasibility and unfilled reductions require an explicit algorithm; if no valid adjusted target exists, reject/fail rather than fabricate compliance.

### S22. Correct existing mandate breaches independently of monthly AI switches
**Decision:** Detect and log a previously valid holding that drifts beyond a hard exposure limit and attempt deterministic correction at the **next eligible simulated execution opportunity**. Correction uses verified prices/state, actual fill results and disclosed trading costs, under common policy for comparable arms.

**Rationale:** A monthly decision schedule does not excuse ongoing hard-risk breaches. Emergency refusal of new risk must be distinguished from permitting independently validated risk-reducing actions. The current shadow risk gatekeeper's latched kill switch does **not** by itself implement protective selling or an automatic remediation scheduler.

### S23. Evaluate fixed and dynamic risk approaches separately
**Decision:** **Primary:** fixed precommitted position, asset-class, leverage/short and permissible-turnover rules. **Secondary:** test a dynamic risk overlay, such as volatility targeting and drawdown-triggered defensive reductions, while preserving hard fixed constraints and applying identical overlay rules across comparable selectors.

**Rationale:** Dynamic changes may reduce risk or simply lower returns, alter turnover and create a cash position without AI selecting it. Never conflate a defensive overlay with improved AI reasoning or promise guaranteed loss caps.

### S24. Owner-led numerical research, with independent technical review
**Decision:** Kanuj and the research assistant lead primary literature review, candidate values, explicit assumptions and feasibility tests. Matthew challenges enforceability and implementation; Harsha challenges experimental comparability and statistics. Kanuj approves numerical study configuration after evidence and reviews.

**Rationale:** Expert division of labor does not require delegating the architecture judgment itself. No owner or coding agent invents an unreviewed production default, and review of one's own implementation is not independent acceptance.

### S25. Concentration uses ETF and asset-class limits in Stage 1
**Decision:** Enforce individual ETF and broad asset-class maximums; screen the universe for excessive underlying overlap and track correlations and concentrations. Full point-in-time ETF constituent look-through is **not mandatory** for the first experiment.

**Rationale:** A fund-level and class-level risk model is measurable with qualified available data; historical holdings-level look-through would create substantial new provenance dependencies. ETF diversification cannot be equated with independence of underlying holdings.

### S26. No mandatory minimum asset-class weights
**Decision:** Impose **maximum** risk exposures only, not minimum required allocations to stocks, bonds or gold. A selected strategy may omit an asset class unless another accepted hard requirement prevents it.

**Rationale:** Minimum holdings create an additional allocation algorithm that could override B4/B5 decisions. For any strategy exceeding a maximum class cap, use the appropriate S20 primary rejection or secondary adjustment.

## ETF universe and execution assumptions

### S27. Broad funds first, not sector-rotation ETFs
**Decision:** Prefer diversified U.S./international stock funds, government and investment-grade bonds and gold. Do not introduce sector-specific funds, leveraged ETFs, options, crypto or individual stocks in Stage 1.

**Rationale:** This tests which strategy works across broad market regimes, not a second concurrent sector-selection problem. Overlap, structural details and investability still need verification.

### S28. Research a 12-ETF balanced candidate universe including QQQ
**Decision:** The **provisional** universe is six equity ETFs (**VOO, IJH, IJR, VEA, VWO, QQQ**), five bond ETFs (**SHY, IEF, TLT, TIP, LQD**) and one gold trust (**GLD**). QQQ was explicitly added after the initial 5-equity/5-bond/1-gold design. Equal-ETF B3 at initiation would approximately allocate **50% equity, 41.7% bonds, 8.3% gold** before rounding. Preregister an **11-ETF no-QQQ** sensitivity.

**Rationale:** QQQ adds a growth-tilted candidate useful for distinguishing candidate strategies, but substantially overlaps VOO. The main universe must be frozen **before scoring**, without selecting between 11 and 12 based on final performance. Check prices, dividends, fund formation dates, historical rights, venue/calendar eligibility, liquidity, correlations and strategy output distinctness. GLD's trust structure is not a conventional equity-fund holding. The proposed tickers are **not yet data-qualified or approved for scored runs**.

### S29. Primary deterministic costs; market-dependent robustness
**Decision:** Use a sourced, conservative, deterministic per-ETF cost model for spread, slippage and applicable fees in the **primary** comparison. Add a separately preregistered **secondary** model sensitive to available historical liquidity, volatility and spreads.

**Rationale:** Identical reproducible execution economics make selector comparisons interpretable. A zero-cost synthetic smoke test is acceptable for accounting verification, **not** for economic claims. Do not double-count trading costs or mislabel unknown provider fees as zero.

## Learning, research and additional rivals

### S30. Structured decision context before autonomous research
**Decision:** **Primary Stage 1A** supplies a fixed-format, point-in-time report of candidate performance, market state, drawdowns, switching costs and prior matured feedback. **Secondary Stage 1B** permits approved autonomous research under explicit source, tool, time and budget limits.

**Rationale:** Structured inputs isolate whether the selector adds value. Autonomous research introduces availability, leakage, permission and cost confounders. Model pretraining knowledge of historical events is not neutralized by timestamp-filtering retrieval.

### S31. Learn through fixed rules and evolving memory before retraining weights
**Decision:** During Stage 1, freeze model weights/version, prompts, permitted tools, learning algorithm and memory-update procedure; only time-eligible **memory contents and decisions** evolve. Later separately test finetuning or other documented model parameter changes.

**Rationale:** This tests genuine feedback use without repeatedly redesigning the model after seeing trial outcomes. A model update creates a new experimental condition requiring its own training, evaluation and governance.

### S32. Preserve verified evidence separately from mutable AI reflections
**Decision:** Keep immutable, timestamped observations and account results in an authoritative log. The AI may append, revise and supersede **evidence-linked hypotheses/reflections**, with provenance and versions, but cannot change those observed facts or governing memory rules. Snapshot both layers at each choice.

**Rationale:** Letting the AI learn from its mistakes is useful; letting it silently erase contradictory results destroys scientific auditability. Reflections are hypotheses, not verified market facts.

### S33. Single decision-maker primary; multi-agent committee secondary
**Decision:** Compare a primary single AI selector with a separately defined multi-agent committee of market, risk and strategy analysts plus a final decision-maker, subject to matched eligible information, action space and disclosed inference budgets/costs.

**Rationale:** Specialized collaboration might improve reasoning, but extra model calls are not free and a verbose rationale is not evidence of better investment outcomes. All AI risk commentary is advisory to deterministic enforcement. D01-D17 do not activate any conditional production M9 agent fleet.

### S34. Add R-ML without weakening R
**Decision:** Keep **R** (S18) as the primary conventional risk-adjusted rule and **R-simple** as a secondary heuristic. Additionally study **R-ML**, a conventional statistical/machine-learning predictor trained only on eligible development data to forecast the next strategy winner, with architecture/features/tuning frozen before scored evaluation.

**Rationale:** A credible AI claim should survive strong non-LLM competition, not just a simplistic baseline. R-ML is a more complex **secondary** comparator, not a reason to refit R to the holdout.

### S35. Historical discovery, prospective confirmation
**Decision:** Perform chronology-respecting historical evaluation using actually qualified data, then freeze a chosen architecture and evaluate it on **newly arriving, broker-free shadow observations** before stronger claims. Treat historical tests as potentially contaminated by developer tuning or model pretraining; audit the intended 2021-2023 development, 2024 validation, 2025 historical holdout roles.

**Rationale:** Calling a historical period a holdout does not make it pristine. Prospective observations better test generalization, although neither a short forward run nor paper accounting proves live profitability. Separate broker-connected paper authority is not granted.

### S36. Demand statistically credible and economically meaningful advantage
**Decision:** Primary success requires net return advantage over frozen R under matched constraints and execution; valid, independently checked uncertainty and multiple-comparison treatment; risk comparability; and sufficient gain to justify measured/attributed AI operating costs. Report **success / promising but inconclusive / unsuccessful** with predefined conditions.

**Rationale:** A positive return difference may be luck, market beta, increased risk or uncontrolled selection over many experiments. Freeze metric definitions, inference plan, minimum prospective evidence and materiality thresholds **before** evaluated outcomes. Do not label Sharpe values defined by the current questionable M5 formula as verified.

### S37. Hybrid scientific and exploratory experiment planning
**Decision:** Use a small **preregistered primary sequence** to establish basic AI-versus-R value; simultaneously permit a separated **exploratory grid** across multi-agent, research, risk overlays, cost models and other variants. Independently validate candidates on fresh, untouched data and prospective observations.

**Rationale:** A large grid aids discovery but picking its historical winner and declaring it confirmed is selection bias. Exploration may run in parallel, but cannot retroactively change the frozen primary study, holdout or claims.

### S38. Parallel research and engineering with strict gates
**Decision:** Conduct research/specification and bounded synthetic/offline infrastructure work **in parallel**. Researchers qualify universe, cost/risk limits, R/R-ML methodology and success thresholds while implementers build contract-bound strategy-switching, records, memory and risk/execution tests. No scored study starts until required contracts, permissions, data, frozen study and independent reviews are accepted.

**Rationale:** Waiting for all final numbers to begin harmless fixture work wastes time; hardcoding guesses or treating drafts as operational approval invalidates results. Every runtime slice needs an issue, a single owner/writer and exact authorized paths. No broker/network/paid-source access follows merely from this decision.

## Cross-cutting unresolved decision gates

- **Numerical Balanced mandate:** position/class caps, order/turnover bounds, allowable drift, remediation order, volatility target, drawdown triggers and reopening rules; compatibility with actual B3/B4/B5 targets must be demonstrated. An exploratory 25% ETF cap or 8-12% volatility target is a **research candidate only**, not a frozen value.
- **Input and strategy eligibility:** qualify the exact ETF universe, point-in-time history, venue calendars (including NYSE Arca versus Nasdaq), splits/distributions, prices, warmup and observation windows. The existence of a source file or a historical replay does not confer market-data rights or grade.
- **AI and R contracts:** exact mathematical R rule, R-ML training protocol, AI prompt/model version, deterministic memory policy, invalid-output/abstention behavior, provenance and actual attempt/cost receipts.
- **Risk/containment:** separate acceptable incoming adjustments, existing-breach protective action, latched kill switch, in-flight/UNKNOWN submissions and reconciliation. No assumption that a risk-reducing order can bypass an unresolved kill-switch policy.
- **Scientific preregistration:** exact campaign, warmup/observation cutoffs, exposure matching, benchmark C versus separately risk-matched C, trading/cash-yield/operating cost treatment, metrics and uncertainty, tainted holdout flags, forward duration and stop conditions.
- **Release boundary:** simulator, historical analysis, prospective broker-free shadow observation, broker-connected paper and real capital are different capabilities. Only separately scoped authority can advance the latter two.

The detailed ownership, sequencing, test evidence and acceptance gates belong to [stage1-roadmap.md](stage1-roadmap.md). Live status and assignment remain in GitHub issues and PRs; this document does not mirror them.
