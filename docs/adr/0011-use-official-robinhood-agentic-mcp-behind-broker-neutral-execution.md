# ADR 0011: Use Official Robinhood Agentic MCP Behind Broker-Neutral Execution

## Status

Accepted architecture decision, 2026-09-19.

## Context

Drift requires live execution validation and capital allocation in later
milestones (M14 through M17). Historically, automated trading projects
integrating with consumer brokerages relied on unofficial private APIs (such as
`robin_stocks`), reverse-engineered authentication tokens, or brittle browser
automation. These mechanisms are fragile, violate brokerage terms of service,
risk account suspension, and fail Drift's trust and auditability standards.

Robinhood has released an official Agentic Trading MCP (Model Context Protocol)
service designed specifically for autonomous trading agents operating on
dedicated accounts.

## Decision

- Drift forbids any primary execution integration built on unofficial private
  APIs, `robin_stocks`, reverse-engineered authentication, or browser automation.
- The execution path for live validation is:
  Drift strategy/research output
  -> deterministic portfolio and risk intent
  -> broker-neutral execution interface
  -> official Robinhood Agentic MCP adapter
  -> dedicated Robinhood Agentic Account.
- The broker-neutral boundary defined in ADR 0002 remains strictly mandatory.
  Core research, backtesting, portfolio construction, and risk models must have
  no dependency on Robinhood protocols, formats, or credentials.
- Robinhood integration does not move earlier into M1 (historical data
  provenance) or M2 (evaluation). Robinhood is live execution and account state
  infrastructure, never Drift's historical research truth source.
- Live execution in M16 and beyond must incorporate deterministic safety
  controls: executor-level position and order limits, persistent kill switch
  surviving process restarts, pending order intent journals, broker readback and
  reconciliation, crash recovery, private runtime state outside Git, dry-run
  preview mode, tiny-capital rollout limits, cumulative daily loss stops, and
  asset allowlists.

## Consequences

- Execution relies on a vendor-supported, audited protocol rather than an
  adversarial reverse-engineered scraping mechanism.
- The system preserves strict isolation between research evidence and brokerage
  execution. If the broker MCP is unavailable or changed, core research and risk
  logic remain completely unaffected.
- Implementation of the Robinhood adapter is deferred to M16, after the
  evaluator (M2), deterministic risk controls (M13), and broker-neutral
  interfaces (M14) are verified.

## References

- Robinhood Agentic Trading announcement:
  https://robinhood.com/us/en/newsroom/robinhood-is-now-open-to-agents/
- Robinhood Agentic Trading overview:
  https://robinhood.com/us/en/support/articles/agentic-trading-overview/
- Trading with your Agent:
  https://robinhood.com/us/en/support/articles/trading-with-your-agent/
- ADR 0002: Broker-neutral core
- ADR 0004: Research-production separation
