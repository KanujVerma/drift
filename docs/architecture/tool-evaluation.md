# External Tool Evaluation

**Evaluated:** 2026-09-01

This note preserves a concise shortlist so later work does not repeat the same
discovery. It does not select a dependency or authorize integration. Reverify
release status, license, compatibility, security, and trust-boundary fit before
adopting any entry.

| Tool | Possible use | Current disposition | Decisive caveat |
|---|---|---|---|
| [OpenTrade](https://github.com/OpenTradeOSS/OpenTrade) | Approval, monitoring, and background-agent UX reference | Observe only; do not embed or fork | Experimental Apple Silicon app that can place real Robinhood orders; Elastic License 2.0 |
| [Qlib](https://github.com/microsoft/qlib) | Point-in-time concepts, data handlers, factor research | Candidate for isolated evaluation, not selected | Published Python support currently ends at 3.12; Drift must own data and PIT guarantees |
| [RD-Agent](https://github.com/microsoft/RD-Agent) | Automated hypothesis and factor/model research | Defer | Agentic workflow is premature before deterministic experiment and evaluation contracts |
| [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) | Event-driven simulation, order lifecycle, paper/live parity | Later comparison candidate | LGPL-3.0, evolving APIs, opinionated runtime, and no ready Robinhood Agentic adapter |
| [QuantConnect LEAN](https://github.com/QuantConnect/Lean) | Fee, fill, slippage, brokerage, and multi-asset simulation models | Later comparison candidate | Large C# engine with Python surface and platform workflow complexity |
| [Zipline-reloaded](https://github.com/stefan-jansen/zipline-reloaded) | Equity factor pipelines, calendars, and corporate actions | Evaluate only if its Pipeline API is needed | Research-oriented and not a modern live execution substrate |
| [vectorbt](https://github.com/polakowo/vectorbt) | High-throughput vectorized research | Do not embed without legal review | Commons Clause licensing and no intrinsic PIT or execution realism |
| [Backtrader](https://github.com/mementum/backtrader) | Python backtesting | Reject for new core work | Aging original stack; active forks and licenses require separate review |
| [MLflow](https://github.com/mlflow/mlflow) | Experiment UI, artifact export, and model registry | Defer as an optional adapter | Overlaps Drift's canonical run/evidence records and cannot prove PIT correctness |

## Current build and reuse boundary

Drift builds its scientific and trust contracts. Potentially reusable commodity
capabilities include storage formats, numerical libraries, market calendars,
simulation engines, visualization, model-training infrastructure, and official
broker APIs. External components must remain behind narrow interfaces, and their
outputs become evidence only after Drift records the relevant versions, hashes,
data policies, and assumptions.

No tool in this note is part of M0 or the proposed M1. Qlib remains optional; no
Python 3.12 environment, adapter, configuration, or workflow is approved.
