# Product direction

Drift's intended product is an autonomous, self-improving AI portfolio manager,
not a quantitative research platform. Research, simulation and safety are
means to that end, not proof that the product already works or has an edge.
This page records the owner-approved direction in [#672](https://github.com/KanujVerma/drift/issues/672).
See [architecture](ARCHITECTURE.md) for current capabilities and boundaries and
[roadmap](ROADMAP.md) for outcomes and sequencing.

## Approved direction

- Invest actively over days to months, with adaptive risk inside a balanced
  mandate. Discover opportunities independently and consider user suggestions.
- Combine fundamental, quantitative and thesis-driven analysis. Primary inputs
  are market data, filings, earnings, news, X and official announcements; Reddit
  is secondary. Source availability and rights are not implied by this list.
- Use lightweight continuous monitoring, daily research and event-driven
  reviews. Learn from outcomes and adopt validated improvements. A review is not
  automatically a trade.
- Operate with bounded autonomy. Escalate opportunities outside the mandate to
  the user with evidence and reasoning rather than expanding authority.
- Aim for risk-adjusted outperformance of the S&P 500. This is a target, not a
  demonstrated investment edge or a guarantee. Report investment performance
  and system economics separately, including relevant costs and uncertainty.
- Start with conversation; add a dashboard only if justified. Prefer free
  resources and allocate research resources adaptively within authorized limits.
- Robinhood is the only intended broker. Paper validation comes before a future,
  separately authorized $100 pilot. Neither intention permits a broker
  connection, an order or use of capital today.
- Future model evaluation is limited to GPT-6.1 Terra Extra High and GPT-6.2 Sol
  Extra High, then Hermes only if justified. Jev and other models are deferred.
  This is a plan, not permission to run evaluations or incur costs.

## Not yet approved

Numerical risk, exposure, position, drawdown, turnover and other thresholds remain
unset for the product mandate; example or test values are not approval. Source
providers, data rights, model budgets, operational access and spending require
appropriate decisions. Paper-connected operation and real-money trading require
separate explicit authorization, evidence and safeguards. The $100 figure is
future pilot intent, not an account funding or trading grant.

The legacy D04 and D10 decisions remain in Git history and record historical
reasoning about specific studies. Their weekly routine portfolio-review cadence
and ETF-first framing are not binding product roadmap:
the direction above is daily research with event-driven reviews, without an
ETF-first requirement. This does not invalidate historical experiments or remove
applicable technical, evidence, replay and safety constraints.
