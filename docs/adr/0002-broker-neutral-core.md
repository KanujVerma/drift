# ADR 0002: Broker-neutral core

## Status

Accepted for M0.

## Context

Evidence capture must remain useful without coupling research records to a
broker, market-data provider, credential format, or production system.

## Decision

M0 exposes only local research models, canonical serialization, hashing, a
SQLite ledger, and local maintenance scripts. It contains no broker API, order
placement, market-data client, OAuth, network client, production configuration,
or credential loading.

## Consequences

The core can be reviewed as research infrastructure without production access
risk. Integrations, if ever approved, must be separate from the core and must
not weaken its evidence or trust boundaries.
