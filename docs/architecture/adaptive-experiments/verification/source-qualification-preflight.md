# Source qualification evidence preflight (Issue #524)

**State: focused-verified code candidate; integration and independent acceptance pending; source NOT qualified.**
This separate implementation assist is linked to Matthew's [#378](https://github.com/KanujVerma/drift/issues/378) and his [draft #408](https://github.com/KanujVerma/drift/pull/408). The original `data-plan.md` is unmerged, remains Matthew's file, and is **not** rewritten by this candidate. Neither a source provider nor a license custodian has been contacted.

## Purpose, owner, and exact scope

The owner-directed second pair of Matthew assists consists of #524 (source evidence) and #525 (execution evidence). Matthew remains the accountable platform/source producer. Krish-Verma / GPT-6 is the authenticated isolated code publisher for this issue only. This branch adds exactly:

- `scripts/source_qualification_preflight.py`
- `tests/unit/test_source_qualification_preflight.py`
- `docs/architecture/adaptive-experiments/verification/source-qualification-preflight.md`

No edits to existing provider/source adapters, data grades, acquired records, account rights, venue identity, SRC contracts, M2 evaluator, source plan, contract decisions, replay baselines or runtime pins are authorized. Read [AGENTS.md](../../../../AGENTS.md), [D01-D17](../decisions.md), [ADR 0012](../../../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md), and Matthew's #378 E01-E10 proposal. [#394](https://github.com/KanujVerma/drift/issues/394) owns the future minimal source envelope, [#365](https://github.com/KanujVerma/drift/issues/365) owns venue changes, and [#376](https://github.com/KanujVerma/drift/issues/376) owns broader SRC and RESULT. This code changes none of those contracts.

## Code contract (pure in-memory review, never a provider permission)

Call `preflight_source_qualification(payload: object) -> SourcePreflight`. Supply only **self-described, untrusted** Python dictionary/list/string evidence indices. No I/O, clock access, provider calls, file reads/writes, subprocesses or credentials are used.

The proposed provisional payload contains a strict `profile` from `news_historical`, `news_prospective`, `market_historical` and `market_prospective`; a candidate, provider/product, purpose and query scope reference; preparation and independent-review names; exact dimension records; and a sample historical/prospective decision cutoff with an ordered original-version/correction history. This is **not** a final SRC wire type.

Every profile requires separately scoped evidence-index entries for public API documentation, actual account entitlement, licensed purpose, retention/replay rights, source identity, interval coverage and economic cost basis. Historical profiles additionally require original archive and historical availability evidence. Market profiles require legitimate point-in-time listing, venue, calendar, price/quote/size and corporate-action dimensions. News profiles require original content, publication/receipt clocks, correction lineage and feed-health/query closure. Prospective profiles require a declared collection scope.

Each dimension has exactly `status`, `evidence_ref`, `scope_ref` and `observed_utc`. Only API documentation may be merely `documented`; all dependent dimensions must be reported `verified` to count as structurally reviewable. `unknown`, `denied`, merely `documented`, missing evidence, scope mismatch, malformed UTC or unknown fields return diagnostic refusals. **A submitted label of verified is not independent verification.** Reference strings do not prove licensing, entitlement, retention, coverage, document origin or reviewer authority. Actual evidence must be retrieved and authenticated outside this helper under separate permission.

The version sample requires actual named original byte references, source publication, local first receipt and normalized availability as UTC instants. Corrections form an ordered, explicitly linked sequence: the first predecessor is `None`, and each later predecessor must be the exact concrete string identifying the preceding version. Objects and string subclasses cannot spoof lineage through comparison callbacks. For a decision cutoff, only a version whose normalized availability is **strictly earlier** than cutoff can be selected; equality has no verified tie-breaker in this provisional index. A later corrected body cannot replace its unseen earlier version. Duplicate version IDs, broken lineage, omitted original payload, prior-to-receipt availability and ambiguity fail closed. This is a conservative synthetic selection check; it cannot establish the truth of claimed receipt times or retrospectively create a pristine 2021 information set.

Reviewer identity, dimension/root scope and selected-version comparisons also validate concrete scalar operands before equality. Malformed reviewer, scope, chosen-version or predecessor values return refusal reports without executing caller-defined equality, inequality or hashing. No value is coerced into a string. The original profile, status, required-dimension, cutoff and public result contracts remain unchanged.

The result is `SourcePreflight(review_ready, selected_causal_version_id, reasons)`. `review_ready=True` means a declared fixture is structurally complete **for an external evidence reviewer**, not that its contents are true. `establishes_rights_or_source_grade` and `authorizes_provider_access` are *always False*. No consumer may turn a selected version ID into a trading feature, historical grade, rights clearance, verified zero cost or source-admission grant.

## Verification checkpoint and independent handoff

The user's current necessary-test instruction is recorded in the [2026-10-23 continuation claim](https://github.com/KanujVerma/drift/issues/524#issuecomment-6370820891), superseding the original authoring-session testing deferral. This repair addresses [Matthew's formal review](https://github.com/KanujVerma/drift/pull/526#pullrequestreview-5595526996), including the adjacent same-contract scope and selected-version comparison surfaces. All other paths remain read-only.

Actual local results with pinned CPython 3.14.6 and unchanged `uv.lock`:

- Tests-only RED on original source: **20 failed, 45 passed**, reproducing lineage false positives and callback execution in predecessor, reviewer, root-scope and selected-version comparisons.
- GREEN after repair: **65 focused tests passed**. Spoofing and raising object/string-subclass controls refuse with zero callbacks. Wrong ordinary predecessor strings retain their lineage diagnostics. All four profiles retain valid original selection at correction cutoff equality and corrected-version selection one microsecond afterward, with deterministic replay and unchanged input.
- **320 additional probes passed:** 240 original/repaired comparisons preserve exact results and reasons across profile, cutoff, selected-version and predecessor controls; 80 hostile scalar probes refuse without callbacks. These are synthetic diagnostics, not authenticated source or rights evidence.
- Repository Ruff lint and format checks passed on 564 files, including the reviewed E501 correction. Strict `mypy src tests` passed on 472 files under both default and Linux targets. Source distribution and wheel built successfully.
- Git whitespace/scope and four local Markdown-link checks passed. All 14 original fixture/test functions are unchanged by AST comparison; interpreter pins, lockfile, package metadata and shared guard bytes remain unchanged.
- The unchanged ordinary production AST profile accepts the actual final source. Four parsed-only socket, environment-read, subprocess and dynamic-evaluation injections refuse; none of those injected operations was executed. Source changes are confined to four comparison regions; public schema, helpers, imports and declared constants remain unchanged by AST inspection.
- One focused inventory probe failed at `tests/integration/test_m1e_compatibility.py:976`, solely because `scripts/source_qualification_preflight.py` is absent from `INERT_SOURCE_PATHS`. The shared guard remains unchanged.

This exact path requires separately scoped inventory and actual scanner-dispatch admission under [producer request #559](https://github.com/KanujVerma/drift/issues/559), which covers the source-qualification and execution-trace helpers. No new capability exception is needed, and the request does not itself admit the source. Preserve unknown-path negatives, pins and the separate #502 -> #487 / #394 gates. The full local pytest suite was not rerun against the known inventory failure. Earlier [canonical run 39541988477](https://github.com/KanujVerma/drift/actions/runs/39541988477) failed at the original head and does not qualify this repair. Fresh canonical CI and independent acceptance remain pending.

On the exact published head, inspect the three files, README/AGENTS rules, Matthew #378 PR #408, the merged M1b-M1e provenance/rights controls and protected file diff, then reproduce focused and static checks:

```bash
uv run python -m pytest tests/unit/test_source_qualification_preflight.py -q
uv run ruff check scripts/source_qualification_preflight.py tests/unit/test_source_qualification_preflight.py
uv run ruff format --check scripts/source_qualification_preflight.py tests/unit/test_source_qualification_preflight.py
uv run mypy src tests
uv build
git diff --check
```

Follow the [canonical workflow](../../agent-workflow.md), including full `uv run pytest` after accepted guard integration is composed. Compare `main` and branch for unintended changes and verify the unchanged interpreter/lockfile. Automatic hosted CI remains enabled and does not substitute for independent AntiGravity validation. No source/provider acquisition, real historical replay or rights inspection was performed.

### Required adverse and positive oracles

1. Complete synthetic index selects the original available version and carries no external permission.
2. Public API claim alone cannot pass account entitlement, licensed purpose, retention or cost.
3. Later corrected content is excluded from an earlier decision, even if latest bytes exist.
4. Missing original payload/reference, duplicate revision ID or broken supersession chain is refused.
5. First receipt later than normalization, version publication after local receipt, or ambiguous equal cutoff is refused.
6. A second venue, incomplete calendar/quote coverage, or unsupported historical profile has its own missing dimension; none can borrow another profile's `verified` status.
7. Cross-product scope reference, missing dimension and undocumented extra field are refused.
8. Non-UTC timestamp, malformed nested structure, attempted self-review or subclassed map is refused.
9. Source rights revocation or a changed source/product/term revision must trigger a *new independently authenticated* qualification process; strings in this helper cannot settle it.
10. An impossible provider-rights claim must remain only an untrusted self-assertion, never promotion-grade evidence.

This remains a candidate helper even if every synthetic unit test passes. The real gate still requires actual provider/account/rights receipts, original-version bytes lawfully retained, measured coverage and independent source/scientific acceptance. No data was acquired, sampled, regraded or promoted, and no reviewer approval or merge is asserted.
