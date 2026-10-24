# Minimal SRC envelope replay preflight (Issue #528)

**Status: source-code candidate with focused local verification; M1e integration and independent acceptance remain blocked. Not an accepted SRC interface.**

This implementation assist supplements Matthew's [#394](https://github.com/KanujVerma/drift/issues/394) / [draft S2 PR #415](https://github.com/KanujVerma/drift/pull/415). The canonical `contracts/source-envelope.md` on Matthew's unmerged draft remains producer-owned and unchanged. [#393](https://github.com/KanujVerma/drift/issues/393) defines TRIAGE behavior; [#381](https://github.com/KanujVerma/drift/issues/381) / [PR #487](https://github.com/KanujVerma/drift/pull/487) is its separate offline consumer, not modified by this branch. The companion new Matthew assist is #529 for #380 MANDATE.

## Implementation owner, scope, and authority

- Accountable source-contract producer: Matthew; current authenticated GitHub coding assistant: Krish-Verma / GPT-6 under an explicit two-issue user direction.
- Exact added files: `scripts/source_envelope_replay_preflight.py`, `tests/unit/test_source_envelope_replay_preflight.py`, this document.
- Branch is isolated, based on current main; no overlapping existing PR paths, existing SRC/rights/provenance models, provider adapters, triage, portfolio, experiments, schema, interpreter, lockfile or private data changed.
- Proposal S2 is **not** an accepted wire. The script's input `synthetic-src-s2-review-v1` is a **local fixture shape**, not a proposed normative SRC producer type, permission grant or persisted data format.

Read [AGENTS.md](../../../../AGENTS.md), [Matthew's proposed S2 source contract](https://github.com/KanujVerma/drift/blob/matthew/394-m-src-slice/docs/architecture/adaptive-experiments/contracts/source-envelope.md) **on draft PR #415 rather than main**, [D01-D17](../decisions.md), [ADR 0012](../../../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md), the [workstream contract](../../workstreams.md), and related #393/#394/#376 before reviewing. Root relative links to the draft contract should be opened via PR #415, not assumed merged.

## Pure in-memory interface

`preflight_source_envelope_replay(payload: object) -> EnvelopeReplayPreflight` accepts only caller-supplied data and returns:

- `structurally_reviewable`: whether exact fixture fields, stated clocks, duplicate claims, revision identity, coverage interval and closure are internally consistent.
- `eligible_receipt_ids`: **unverified claimed** receipts with retained original content, time-eligible local receipt and normalization strictly before the synthetic decision cutoff, and no local structural errors. This does NOT authenticate rights or the source and is NOT a TRIAGE or trading admission.
- `duplicate_receipt_pairs`: pairs of separate receipts referring to the same **declared** original source event/native or observed edition and same retained digest, without discarding either receipt or suppressing consumer history.
- `conflicted_receipt_ids`: different complete hashes under the same claimed publisher/event/edition basis. These invalidate the preflight and must not silently choose first or latest.
- `coverage_at_cutoff`: `COVERED_EMPTY`, `COVERED_WITH_EVENTS`, `PARTIAL`, `FAILED` or `UNKNOWN`. A complete coverage claim requires matching query scope, interval bounds, positive or zero count consistent with status, proof reference, closed pagination and availability before cutoff. Untrusted closure reference strings do not prove real completeness.
- `reasons`: stable diagnostics for malformed, contradictory or cross-scoped assertions.
- `authorizes_ingestion_or_trading=False` and `proves_source_rights_or_origin=False` **unconditionally**.

For local observed editions, preserve publication `published_utc` separately from actual first receipt, normalized availability, and usable availability. Missing publication may coexist with a properly observed receipt; it cannot be replaced with receipt. Exact UTC `Z` evidence is required for known instants. Local usable availability cannot precede first receipt and normalization, and equality at the decision cutoff is conservatively excluded without separate causal evidence. A later corrected version is a new immutable version with a retained predecessor and relation claim; older receipts cannot be overwritten. A complete coverage interval must have ended before the claimed closure receipt became available. A later record does not rewrite an earlier cutoff, but an event version already usable at the current cutoff contradicts a claimed covered-empty interval for the same fixture scope. A historical-reconstruction policy name alone never makes a current archive observation available to a historical decision.

Exact duplicate evidence requires stable declared native event and edition, compatible native/local-observed version basis and complete digest/retention identity. Shared text/digest across different objects, providers, contexts or uncertain editions is not global duplicate proof. Source-native versus locally observed versions cannot silently impersonate each other. Two receipts still exist; #393 policy/context/conclusive-outcome history determines whether a repeat can be suppressed. The script does not interpret article text, sentiment, alert outcomes or past processing histories.

Feed health is separate: even a complete event receipt cannot prove complete feed coverage, and a failed query is not a verified no-news interval. `COVERED_EMPTY` requires a scoped completed interval with zero count and no supplied events; `PARTIAL` retains separately available event receipts, and `FAILED` needs an explicit failure evidence reference. Missing closure, unknown pagination or late coverage evidence yields `UNKNOWN` or explicit refusal rather than silent completeness.

No claimed hash, user-submitted `identity_evidence_ref`, producer label, original-version assertion, synthetic body path or completeness receipt authenticates source origin, entitlement, rights, historical data or content truth. No data access, permission, runtime integration, statement of scientific eligibility or promotion results from a reviewable fixture.

## Local verification and blocked integration

The October 23 retained-writer continuation inspected all formal review bodies and inline threads at the original head `5cb6b6f1b1a5fe359bf5f025449f83cb706e5b87`. Matthew's [review](https://github.com/KanujVerma/drift/pull/530#pullrequestreview-5595531172) requests source-inventory integration and style corrections; there are no inline threads. Pinned Ruff reproduced three E501 failures and formatting failures in both Python files. Formatting preserves both ASTs exactly. The continuation also removed one redundant, runtime-identity `typing.cast` after strict mypy rejected it; no temporal, receipt, correction, coverage or authority behavior changed.

Using unchanged CPython 3.14.6 and `uv.lock`, all **25 focused synthetic tests** pass. Targeted Ruff lint/format, strict `mypy src tests` (472 source files), sdist/wheel build, relative document links and Git whitespace checks pass. The runtime AST remains identical after ignoring the removed identity cast, and the test AST is unchanged. These checks are local evidence, not independent producer acceptance.

**Integration remains blocked.** The focused existing M1e inventory test still fails because `scripts/source_envelope_replay_preflight.py` is absent from its exact inventory. Independently applying its unchanged production AST guard to this actual source also refuses the method name `authorizes_ingestion_or_trading`, although the property always returns False. Adding only an inventory entry would therefore be insufficient. The retained guard writer and platform producer must coordinate explicit exact-path capability admission and controls. This PR does not modify or relax that protected guard, rename the source to avoid scanning, or waive either failure. Full new-head canonical CI must follow that separate admission decision; no full-pass claim is made.

At the **exact published branch head**, independently inspect these three files against #394 S2, #393 accepted behavior, #381 consumer and [#524](https://github.com/KanujVerma/drift/issues/524) source-rights evidence checker (distinct scope). After authorized integration, run the complete required gate:

```bash
uv run python -m pytest tests/unit/test_source_envelope_replay_preflight.py -q
uv run ruff check scripts/source_envelope_replay_preflight.py tests/unit/test_source_envelope_replay_preflight.py
uv run ruff format --check scripts/source_envelope_replay_preflight.py tests/unit/test_source_envelope_replay_preflight.py
uv run mypy src tests
uv run pytest
uv build
git diff --check
```

Also verify the branch diff has only the above three new paths, interpreter and `uv.lock` are unchanged, no U+2014 appears in changed files, all existing source grades/rights and triage behavior remain unchanged, and GitHub Actions exact-head results are not treated as scientific acceptance. AntiGravity should independently validate source version equality, multi-channel identity boundaries, replay determinism and all cases below, then report the true results including failures. The original source-authoring checkpoint deferred tests; the executed continuation checks above supersede that deferral without supplying independent acceptance.

### Positive, negative, and adversarial oracles

1. Complete synthetic version at a proven earlier cutoff is structurally reviewable, but has zero source authentication/permission.
2. Publication unknown with a measured receipt retains that distinction; publication earlier than receipt cannot backdate usability.
3. Event first received after the cutoff stays outside admitted receipts despite an older publisher timestamp.
4. V2 correction after cutoff retains its predecessor without rewriting V1 or being admitted early.
5. Two distinct receipts for the same proven-version bytes retain both receipts; duplicate pairs never force a TRIAGE suppression.
6. Textually identical different native event IDs or uncertain version basis do not produce duplicate pairs.
7. Same claimed edition with incompatible retained content digests is an explicit fail-closed conflict.
8. A correction without an earlier retained predecessor or relation evidence refuses; mixed identity basis is not a native correction.
9. Complete covered-empty with zero events differs from incomplete pagination, partial feed, unknown feed and actual failure.
10. Coverage receipt arriving later than cutoff cannot backfill earlier feed-completeness claims.
11. A partial feed can still retain a separately eligible event, but cannot imply global quiet coverage.
12. Absent native body, only a content digest, invented normalization clock or hypothetical historical policy does not establish original-version screening.
13. Malformed UTC, mismatched query scope, duplicated receipt ID, unexplained extra command field and subclassed containers refuse rather than silently repair.
14. Hostile news payload must remain inert. This script accepts no article body, network address, executable instruction or policy selection input.

## Outstanding owner and independent-review gates

Matthew: ratify S2 original source/version wire and issuer evidence, temporal uncertainty, relation policy and feed closure. Kanuj: confirm compatibility with #393/#381 context, policy-scoped duplicate behavior and consumer-side missingness. The source rights/grade custodian: authenticate real source/retention evidence separately from this code. AntiGravity: run and independently audit on exact PR head. Material decisions are not self-approved by GPT-6. This draft does not close #394, merge #415, activate news feeds, certify a pristine historical corpus or authorize any financial operation.
