# ADR 0004: Research and production separation

## Status

Accepted for M0.

## Context

Research outputs may be incomplete, wrong, or intentionally exploratory. They
must not inherit the authority to affect a production environment.

## Decision

M0 is a research-only zone. It stores compact provenance and artifact
references, but has no production credentials, execution interface, broker
connection, portfolio state, deployment configuration, or write path to any
production system. A future promotion process may consume hashed research
evidence only through a separately designed control plane.

## Consequences

The boundary is explicit in code, dependencies, configuration, and
documentation. A future workflow can add approval records and retention rules,
but it must not turn the evidence kernel into a trading or production runtime.
