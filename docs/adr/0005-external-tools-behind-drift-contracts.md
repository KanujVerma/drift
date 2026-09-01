# ADR 0005: External Tools Stay Behind Drift Contracts

## Status

Accepted on 2026-09-01.

## Context

Quantitative research, simulation, model training, visualization, and broker
connectivity have mature external implementations. Adopting one as Drift's
architecture by default would also import its data, runtime, licensing, and
trust assumptions. Rebuilding commodity infrastructure without evaluation
would create a different form of unnecessary complexity.

## Decision

Drift owns its scientific and trust contracts, including point-in-time
provenance, evidence lineage, experiment accounting, promotion boundaries, and
future deterministic policy and broker-neutral reconciliation contracts.

Commodity infrastructure may be reused when a current evaluation shows that it
satisfies those contracts with less total complexity and acceptable licensing,
security, reproducibility, compatibility, and operational tradeoffs.

A tool with incompatible runtime requirements may run in an isolated environment
and exchange only explicit, versioned, content-hashed artifacts with Drift. That
boundary is an option, not a commitment to any named tool. An optional tool does
not force a core-runtime change; any such change requires a separate decision.

Before adoption, reverify the tool's current release, license, supported
platforms and Python versions, security posture, data assumptions, test evidence,
and effect on Drift's trust boundaries. Record a new or updated ADR when adoption
materially changes the architecture.

## Consequences

Drift has no blanket build-first or reuse-first rule. Candidate tools remain
tentative until measured against a concrete Drift interface and acceptance test.
The dated shortlist in `docs/architecture/tool-evaluation.md` is research context,
not an adoption decision.
