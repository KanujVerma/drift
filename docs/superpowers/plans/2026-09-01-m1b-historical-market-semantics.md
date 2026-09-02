# Drift M1b Historical Market Semantics Scope Outline

**Status:** Explicitly deferred. Non-executable scope boundary only.

**Umbrella design:** `docs/superpowers/specs/2026-09-01-m1-point-in-time-data-design.md`

**Active plan:** `docs/superpowers/plans/2026-09-01-m1a-temporal-provenance.md`

## Purpose

This outline prevents asset-specific historical-market concepts from leaking into M1a. It is not an implementation plan, does not approve M1b work, and intentionally contains no execution checklist, task sequence, code sketch, file map, command, or full M1b design.

## Deferred Scope

M1b is expected to address historical US-equity semantics that are meaningful only after asset-neutral temporal provenance exists:

- issuer, security, share-class, and listing identity;
- dated ticker and provider-identifier mappings, including rename and reuse;
- historical universe membership and source-event revisions;
- listings, terminations, delistings, and unknown terminal outcomes;
- corporate actions and their announcement, availability, and effective times;
- raw versus adjusted price meaning and action-cutoff dependencies;
- exchange calendar and session identity, versions, UTC boundaries, holidays, early closes, and daylight-saving behavior;
- explicit missingness, halt, closure, termination, and zero-volume distinctions;
- tradability semantics and the boundary between historical membership and actual investability;
- equity-specific adversarial fixtures and cross-dataset validation.

## Inputs M1b May Rely On

M1b may consume M1a's exact-byte manifests, explicit channel-scoped availability evidence, immutable revision chains, exact-object validation decisions, and per-query tri-state cutoff results. It must not reinterpret M1a provenance as proof that market semantics are complete.

## Excluded From M1a

No M1a runtime type should name or implement securities, listings, tickers, universes, corporate actions, price adjustment, exchange calendars, sessions, bars, or tradability merely to anticipate M1b. Generic temporal types may support those concepts later without knowing their market meaning.

## Decisions Required Before an Executable M1b Plan

- approve the first asset and venue scope;
- approve the historical-information and tradability claims M1b must support;
- choose synthetic source contracts for identity, universe, action, price, and session evidence;
- decide whether any real source evaluation belongs in M1b or a later ingestion milestone;
- define raw and adjusted price acceptance boundaries;
- define calendar/session precision and versioning requirements;
- define behavior for unknown delisting value and unavailable source history;
- perform an M1b-specific design and adversarial review;
- approve a separate implementation plan.

## Entry and Completion Boundaries

M1b work may begin only after M1a is implemented and verified, a dedicated M1b design is approved, and a new executable plan is created. M1 is not complete when M1a alone is complete. No current document claims that Drift is ready for equity backtesting, provider ingestion, or trading.
