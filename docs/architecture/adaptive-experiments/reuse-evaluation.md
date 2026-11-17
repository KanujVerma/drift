# External patterns to evaluate, not blanket dependencies

## Rule

Preserve Drift's existing scientific and accounting contracts. A popular project
is a source of implementation patterns, not proof of financial performance or
permission to copy data/model weights. Record upstream commit/version, exact
files, license/NOTICE obligations, dependencies, compatibility, security and
acceptance tests before any future code reuse. The coordination bootstrap
installs and vendors nothing.

## Owner-approved adoption program

Kanuj approved the component-level recommendations on October 25, 2026 and
requested owner-routed implementation and G2 completion. The authorization and
exact documentation scope are recorded in [#566](https://github.com/KanujVerma/drift/issues/566).
The original [source review and acceptance cases](verification/external-reuse-review-2026-10-25.md)
are preserved as a dated research artifact. Its proposal labels describe the
review at publication; this approval selects the adoption **direction**, not an
upstream security certification, accepted producer wire or completed integration.

[Workstream ownership](../workstreams.md) remains authoritative. No work is
assigned to the historical Harsha workstream. Kanuj owns measurement and the
scientific consumer, Krish owns research producers, and Matthew owns platform
mechanisms. Issue claims and independent acceptance remain required.

| Accountable owner | Concrete reuse work | Boundary and finish line |
| --- | --- | --- |
| Kanuj | Portfolio-preserving causality, warmup and comparison tests informed by Freqtrade; original-evidence completeness and cost attribution; scientific trial integration under #485. | Exercise real existing producer/evaluator paths with positive and deliberately invalid controls. Do not introduce a second evaluator or certify own scientific acceptance. |
| Krish | Isolated Qlib research/model feasibility for R-ML; later bounded RD-Agent, TradingAgents and FinGPT producer comparisons. Routed in [#567](https://github.com/KanujVerma/drift/issues/567), with #501/#375 retaining algorithm authority. | Retained eligible inputs yield replayable validated scores/proposals and complete attempt/cost records. No account writes, execution credentials, automatic replacement of primary R or M9 activation. |
| Matthew | Normal-loop failure scenarios informed by Passivbot/Hummingbot; durable UNKNOWN/reconciliation; separate LEAN semantic-conformance comparison. Routed in [#568](https://github.com/KanujVerma/drift/issues/568), with #411/#380/#508 retaining producer authority. | Genuine fills, account state and uncertainty survive failure/restart. No local lost-order label becomes confirmed rejection; no second authoritative financial ledger. |

### First: strengthen the real G2 path

Use the existing producer/evaluator and original-record interfaces. New tests
should expose a missing behavior, not build another independent demonstration
that merely agrees with itself. Exact implementation claims and results belong
in [#564](https://github.com/KanujVerma/drift/issues/564) and its linked PR.

**Causality cases (Kanuj acceptance, Krish/Matthew mechanisms):**

- Preserve the full eligible cross-sectional universe and all data genuinely
  available at cutoff T. Poison only later information and require the semantic
  as-of inputs and first decision to remain unchanged. Whole future-containing
  bundle hashes and operational UUIDs are not the comparison oracle.
- Compare to an actually truncated snapshot, not a single-security backtest that
  changes B4/B5's ranking problem. Include a deliberately leaking negative so a
  test cannot pass because it failed to vary relevant future input.
- Test historical revisions by first availability, cache/training cutoff
  eligibility and every supported disposition. Untriggered branches remain
  untested. A future event announced before T is not automatically lookahead.
- Check actual decisions as startup history varies within declared requirements.
  Below B4/B5's accepted history floor, unavailable/empty research input must not
  become a sell-all. Do not rewrite the frozen baseline algorithms silently.
- For model producers, compare exact request/retrieval bytes and replay captured
  output. A fresh stochastic model call is not an equality oracle.

**Operational cases (Matthew mechanism, Kanuj acceptance):**

- Exercise lost acknowledgement, fill-before-acknowledgement, duplicate and late
  fills, cancellation/fill races and cold restart through normal orchestration.
- Distinguish a locally failed tracker from a positively confirmed broker
  rejection. An uncertain committed request cannot authorize automatic retry.
- Preserve stale/missing-account refusal, independent mandatory risk behavior,
  durable failure latches and complete original evidence. A bounded diagnostic
  buffer is not an audit record; overflow cannot certify completeness.

No Freqtrade, Passivbot or Hummingbot implementation is vendored by adopting
these test approaches. Any later copying/importing follows the admission
checklist below and its own exact file/revision/license review.

### Then: one concrete research worker, not a generic plugin framework

Evaluate Qlib's existing `RollingGen` and model machinery behind the current
research interfaces. Its stock-ranking examples do not define labels or an
objective for Drift's B3/B4/B5 selection problem. Krish must specify the feature
units, label horizon, chronological fit windows, overlap exclusion, seeds,
model/parameter search and failure behavior before a worker is admitted.

Use a separately pinned worker when dependencies conflict with Drift's pinned
runtime. Do not modify the core interpreter or lockfile merely to accommodate
an optional library. Retain all attempted fits, exact model and prediction
artifacts, training-data identity and raw costs. An external recorder may be a
diagnostic index, not an alternative authoritative trial registry.

The acceptance batch must include an eligible prediction, a future-trained
prediction, missing features, nonfinite scores and exact replay. Primary R
remains separately frozen; a Qlib experiment is labelled R-ML until a reviewed
study decision changes its role.

Later RD-Agent/TradingAgents/FinGPT comparisons preserve identical evidence
rights, strategy menu and evaluation opportunities, with named aggregate budget
and cost accounting. More roles or repeated agreement do not constitute
independent evidence. Generated code remains outside the trusted evaluator
process and requires its own isolation/eligibility design. Conditional M9
remains conditional.

### Challenge the backend separately

Matthew's LEAN comparison uses hand-computable common scenarios: whole-share
rebalance with explicit costs, a supported corporate action, and declared
calendar/partial-or-unfilled execution behavior. Align adjustment conventions,
prices, timing, rounding, data vintages and fill assumptions before comparing
cash, positions, fills and costs. Report unsupported cases rather than silently
approximating them.

Measure adapter complexity and maintenance burden as well as discrepancies.
Neither sunk cost in Drift nor popularity of LEAN decides the outcome. A backend
migration requires a separate accepted decision preserving original evidence
interfaces; an external oracle is not automatically financial truth.

### G2 is not a library-installation milestone

G2's definition remains the [Stage 1 roadmap](stage1-roadmap.md#5-acceptance-gates-and-sequence)
and [independent acceptance specification](release-acceptance.md). The original
scheduler grant, K1 validation/availability and platform issuer/witness mapping
remain routed through #512/#513, #507 and #508 respectively. Admission and
mandatory mandate boundaries remain #423/#380; #485 owns the typed scientific
trial projection and #383 the integrated acceptance.

The scientific consumer may not turn local-consistency flags into accepted
producer authority. Passing synthetic execution, independent contract
acceptance, source-qualified historical scoring and operational permission
remain different facts. Missing acceptance is not repaired by changing a
boolean or closing an issue.

Qlib, RD-Agent, TradingAgents, FinGPT, LEAN migration, HFT, crypto and live-tool
integration are **not new G2 prerequisites**. Keep optional research from
expanding the critical path. Current blockers, evidence and reviewer decisions
live on the linked issues, not in a duplicate status table here.

### Admission record for every actual reuse

Before importing, copying or running an upstream component, record its exact
commit and files, root/file/dependency/model/data terms and required notices;
locked environment and compatibility; read-only evidence boundary; time/source
eligibility; typed output and refusal semantics; resource/cost limits; complete
original artifacts; positive/adversarial tests; and accountable independent
review where applicable. The dated review's upstream hashes are inspection
anchors, not proof that a branch still points there or that every transitive
component is approved.

A reusable component earns adoption through less maintained code, stronger
verified coverage or a measured capability improvement. Record a KEEP/REJECT
outcome when tested. Free source does not mean free inference, infrastructure,
data, slippage or trading fees. No account connection, paid call, market-data
purchase, leveraged strategy or live deployment follows from this program.

## Candidate references

| Reference | Relevant contribution | Drift action | Not adopted automatically |
|---|---|---|---|
| Microsoft RD-Agent / R&D-Agent-Quant | Separates research proposals, development, execution and feedback; studies adaptive research scheduling. | Apply clear task specifications, failure feedback and bounded research budgets in existing M6-M8. | Whole agent runtime, unbounded code generation or bandit scheduling in the bounded MVP. |
| Microsoft Qlib | Experiment/run recording and modular quantitative research workflows. | Use explicit campaign/run/record identities and reproducible artifact references in Drift's existing ledger. | A second backtester, separate authoritative experiment database or automatic MLflow migration. |
| AI4Finance FinGPT | Financial sentiment, extraction and retrieval-augmented text analysis with task benchmarks. | Evaluate NLP adapters and labeled fixtures for Krish's significance layer. | Claims that sentiment accuracy implies profit, an entire model stack or source scrapers. |
| AI4Finance FinNLP | Provider-specific data-adapter examples. | Reference normalization patterns only after access and security review. | Old scraping code, embedded credentials, assumed lawful access or absence of data treated as neutral news. |
| QuantConnect LEAN framework | Distinct signal, portfolio construction, risk and execution responsibilities. | Preserve modular intent/risk/execution separation and explicit scheduling in Drift. | Replacement of the M2 accounting engine or inference that its fills match our data. |
| Backtest-overfitting literature | Selection bias from repeated trials; DSR/PBO methods with statistical assumptions. | Preregister comparisons, log all attempts, preserve confirmation data and report uncertainty. | A universal numerical pass threshold or a claim that one statistic proves an edge. |

The open-source licenses reported by RD-Agent/Qlib/FinGPT/FinNLP are MIT and
LEAN is Apache-2.0. Verify the exact reused revision and separate model/data
terms before implementation. Do not treat README benchmark claims as replicated
Drift evidence. No star-count, return, speed or cost claim is necessary to justify
these design boundaries.

## Sources

- RD-Agent: https://github.com/microsoft/RD-Agent
- R&D-Agent-Quant: https://arxiv.org/abs/2505.15155
- Qlib: https://github.com/microsoft/qlib
- Qlib experiment recorder: https://qlib.readthedocs.io/en/stable/component/recorder.html
- FinGPT: https://github.com/AI4Finance-Foundation/FinGPT
- FinGPT retrieval paper: https://arxiv.org/abs/2310.04027
- FinNLP: https://github.com/AI4Finance-Foundation/FinNLP
- LEAN: https://github.com/QuantConnect/Lean
- LEAN framework: https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview
- The Deflated Sharpe Ratio: https://doi.org/10.3905/jpm.2014.40.5.094
- The Probability of Backtest Overfitting: https://escholarship.org/uc/item/4w1110bb
- GitHub issue dependencies: https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/creating-issue-dependencies
- GitHub code owners: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners
- Cursor rules: https://cursor.com/docs/rules

## Coordination implications

GitHub dependencies represent blockers, not task ownership locks or an agent
scheduler. Closing a dependency does not automatically validate contracts or
correct state labels. CODEOWNERS routes review; it does not lock files and does
not automatically request reviews on draft PRs. Cursor rules and AGENTS.md guide
agents; they are not an enforcement boundary. Keep critical rules in tests,
review and permissions as well as prose. Do not deploy new automation in the
bootstrap merely to suggest that idle agents can wake themselves.
