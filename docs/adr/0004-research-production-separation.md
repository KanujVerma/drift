# ADR 0004: Research and production separation

## Status

Accepted for M0.

## Context

Research outputs may be incomplete, wrong, or intentionally exploratory. They
must not inherit the authority to affect a production environment.

## Decision

The long-term trust model has three explicitly separate zones: Research
Sandbox, Promotion Control Plane, and Production / Execution. M0 implements
foundations for the Research Sandbox only. It stores compact provenance and
artifact references, but has no production credentials, execution interface,
broker connection, portfolio state, deployment configuration, or write path to
any production system. A future Promotion Control Plane may consume hashed
research evidence, but the Research Sandbox must never receive authority over
Production / Execution.

## Consequences

The boundary is explicit in code, dependencies, configuration, and
documentation. A future workflow can add approval records and retention rules,
but it must not turn the evidence kernel into a trading or production runtime.
