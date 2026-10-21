# Source qualification evidence preflight (Issue #524)

**State: code candidate published, tests intentionally not executed, source NOT qualified.**
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

The version sample requires actual named original byte references, source publication, local first receipt and normalized availability as UTC instants. Corrections form an ordered, explicitly linked sequence. For a decision cutoff, only a version whose normalized availability is **strictly earlier** than cutoff can be selected; equality has no verified tie-breaker in this provisional index. A later corrected body cannot replace its unseen earlier version. Duplicate version IDs, broken lineage, omitted original payload, prior-to-receipt availability and ambiguity fail closed. This is a conservative synthetic selection check; it cannot establish the truth of claimed receipt times or retrospectively create a pristine 2021 information set.

The result is `SourcePreflight(review_ready, selected_causal_version_id, reasons)`. `review_ready=True` means a declared fixture is structurally complete **for an external evidence reviewer**, not that its contents are true. `establishes_rights_or_source_grade` and `authorizes_provider_access` are *always False*. No consumer may turn a selected version ID into a trading feature, historical grade, rights clearance, verified zero cost or source-admission grant.

## AntiGravity verification queue (deferred by user)

The implementation author deliberately **did not execute** these commands. When AntiGravity is asked to review this exact PR head, first inspect the three files, README/AGENTS rules, Matthew #378 PR #408, the merged M1b-M1e provenance/rights controls and the protected file diff, then run:

```bash
uv run pytest tests/unit/test_source_qualification_preflight.py -q
uv run ruff check scripts/source_qualification_preflight.py tests/unit/test_source_qualification_preflight.py
uv run ruff format --check scripts/source_qualification_preflight.py tests/unit/test_source_qualification_preflight.py
uv run mypy src tests
uv run pytest
uv build
git diff --check
```

Also run the exact canonical verification workflow in AGENTS.md/agent-workflow.md against the reviewed head, compare `main` and branch for unintended changes, and verify unchanged interpreter/lockfile. CI may start automatically when a PR is opened; do **not** substitute automatic CI status for independent AntiGravity validation.

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
