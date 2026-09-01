# Roadmap

## M0, current milestone

M0 provides validated immutable research objects, canonical serialization,
SHA-256 hash-chained audit events, and a transactional append-only local SQLite
ledger. It verifies and replays one consistent snapshot, while remaining a
local research-only system.

M0 deliberately excludes broker access, market-data access, order placement,
trading, backtesting, strategy execution, network clients, language-model or
agent orchestration, production configuration, and production credentials.

## Recommended M1, not implemented

M1 can add an explicitly reviewed research workflow around the evidence kernel.
Before any implementation, it should define:

1. A versioned research intake contract that creates hypotheses, dataset
   references, specifications, runs, and evidence through the existing
   append-only ledger.
2. A retention policy for bulky inputs and outputs, including who approves
   expiry, how locations and hashes remain auditable, and how expired artifacts
   are reported.
3. A separate, read-only promotion review record that links hashed research
   evidence to a human decision without introducing production credentials or
   execution authority.
4. Adapter acceptance tests that preserve M0's canonical event envelope,
   ordering, uniqueness, checkpoint, and verification guarantees if another
   storage engine is proposed.

M1 is a planning direction, not M0 behavior. It must preserve M0's research
boundary and cannot be treated as authorization to add trading or production
capability.
