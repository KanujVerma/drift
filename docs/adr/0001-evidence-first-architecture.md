# ADR 0001: Evidence-first architecture

## Status

Accepted for M0.

## Context

Research conclusions need enough provenance to be revisited, including failed
trials and the inputs that informed them. A mutable summary alone cannot show
when a conclusion changed or what evidence was available at the time.

## Decision

M0 stores frozen, validated research objects and records state changes as
canonical, hash-chained audit events. The ledger orders events with a database
sequence and verifies its own stored representation before replay. Generated
narratives are not facts. Any narrative claim must remain untrusted unless it
traces to validated experiments, evidence records, and retained provenance.

## Consequences

The initial system favors inspectable provenance over automated decision-making.
It records strategy metadata but does not execute a strategy, trade, backtest,
or access a broker or market-data service. Future work must preserve the clear
distinction between research evidence and production action.
