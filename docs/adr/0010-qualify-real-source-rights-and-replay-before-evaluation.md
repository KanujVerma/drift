# ADR 0010: Qualify Real-Source Rights and Replay Before Evaluation

## Status

Proposed and independently reviewed architecture decision, 2026-09-12.
Implementation is not authorized. The canonical rationale, evidence, provider
screen, golden cases, and acceptance boundary are in the
[M1e design specification](../superpowers/specs/2026-09-12-license-gated-real-source-qualification-replay-closure-design.md).

## Context

M1b through M1d define synthetic contracts for historical identity, economic
facts, source observations, sessions, and normalization. The next decision is
whether to build an evaluator first or test those contracts against real data.
An evaluator built before examining real omission, correction, session, and
licensing behavior risks encoding convenient assumptions. Qualifying a vendor
by name is also insufficient because one product can pass one layer and fail
another, and technically downloadable data may not be legally retainable for
durable replay.

## Decision

- M1e is a bounded, license-gated real-source qualification and offline replay
  closure pilot. It precedes evaluator or backtester implementation.
- Qualification attaches to an exact provider, product, publisher, licensed
  entity and purpose, date/universe/field scope, delivered snapshot,
  methodology, and qualification-profile version. No vendor-wide grade exists.
- Identity, actions, outcomes, observations, sessions, revisions, coverage,
  rights, acquisition completeness, and replay closure receive independent
  `PASS`, `PARTIAL`, `FAIL`, or `UNKNOWN` results. Critical `PARTIAL` or
  `UNKNOWN` results do not become implied acceptance.
- The pilot reuses M1a through M1d manifests, references, validators, decisions,
  and hashes. It adds provider-neutral receipt, rights-assessment, snapshot, and
  environment-closure artifacts only where existing ownership ends.
- Exact provider-native bytes, schema and methodology evidence, acquisition
  completeness, and applicable legal terms are retained when permitted. A hash
  without legally retained bytes cannot establish replay.
- Historical replay is offline, isolated, credential-free, and immutable.
  Current development and any future promotion or production environment are
  separate security lanes.
- M1e may finish with an evidenced negative qualification. Such a result closes
  the pilot but does not authorize real-data evaluator use.
- A future evaluator receives only accepted provider-neutral M1b through M1d
  artifacts, explicit limitations, snapshot identity, rights identity, and
  replay identity. It receives no provider client or implicit latest data.

## Consequences

The decision delays evaluator implementation until at least one exact source
scope has survived rights, semantic, acquisition, and replay tests. It prevents
provider convenience from redefining Drift's contracts and accepts that source
composition may later be necessary. Composition will require independent
qualification of each source, explicit identity and occurrence joins, and the
intersection of all license restrictions.

The initial environment closure is runner-neutral metadata plus one demonstrated
platform-specific offline bundle. A portable lockfile or copied virtual
environment alone is insufficient. OCI packaging is an escalation path, not a
new default dependency.

M1e does not add an evaluator, backtester, provider connection, recurring
ingestion, production credentials, broker, portfolio, strategy, order, or
trading capability. An executable M1e plan requires the user decisions listed
in the design specification.
