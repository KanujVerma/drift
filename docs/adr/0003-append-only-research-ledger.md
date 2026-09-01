# ADR 0003: Append-only research ledger

## Status

Accepted for M0.

## Context

Research history must make revisions and failed trials visible. Failed trials
matter because repeated searches create a multiple-testing problem: selective
retention can make chance results look repeatable. The full search history,
including abandoned trials and prior backtest attempts in future milestones,
is necessary to interpret results and reproduce how a claim was reached.
Application conventions alone cannot prevent a later SQL update or delete from
erasing that history.

## Decision

M0 uses SQLite with a database-assigned monotonically increasing sequence, a
SHA-256 predecessor hash on every event, and one append-only checkpoint row per
event. SQLite triggers reject update and delete operations on both tables.
Verification reads events and checkpoints in one transaction, validates chain
and checkpoint invariants, and compares stored raw values to canonical output.

## Consequences

M0 detects altered rows, missing rows, reorder attempts, broken links, invalid
hashes, and noncanonical equivalent representations. The design is
tamper-evident, not tamper-proof: a privileged actor who coordinates a full
rewrite and recomputes all affected data can produce a self-consistent ledger.
External anchoring and access control are outside M0.
