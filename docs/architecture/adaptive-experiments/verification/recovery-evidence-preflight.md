# Offline recovery evidence preflight (Issue #520)

**Status: focused-verified implementation candidate; integration admission pending.** Matthew is the accountable platform owner. This is Krish-Verma / GPT-6's bounded code assist, derived from Matthew's [#395 proposal](https://github.com/KanujVerma/drift/issues/395) and draft [PR #416](https://github.com/KanujVerma/drift/pull/416). The authoritative [recovery.md on Matthew's draft branch](https://github.com/KanujVerma/drift/blob/matthew/395-m-recovery/docs/architecture/adaptive-experiments/recovery.md) remains on Matthew's isolated, unmerged draft and has not been modified. Independent evidence and custody acceptance belongs to [#397](https://github.com/KanujVerma/drift/issues/397).

## Purpose and boundaries

The pure function `preflight_recovery_evidence(payload)` checks whether an **already collected, synthetic or trusted externally retained** recovery report is structurally complete. It never reads a manifest or filesystem, executes a command, touches an archive, validates source authenticity, contacts providers, changes runtime settings, disables features or restores private state. It does not verify that a named reviewer, trusted issuer, grant or receipt is real. Matching digests are equality checks only, not authentication.

All output from this function is **untrusted as a recovery claim**. `structurally_reviewable=True` means required fields exist, declared status is `passed` for CODE, PRIVATE_STATE and RUNTIME, each dimension points to distinct evidence, original manifests agree, the stated execution hold is clear and the independent review reference is not literally the author's identity. The function always returns `authorizes_recovery_or_execution=False`. Actual independent #397 review and original bytes/permissions are mandatory before any conclusion.

## Targets and required data

All targets require a run/manifest ID, exact lowercase SHA-256 manifest fingerprint, a separate grant verification reference, immutable history anchor, independent reviewer/custody reference and the three separate dimensional receipts with revision, environment and matching manifest hash. Refuse missing, malformed, contradictory, reused, failed, cancelled, pending or unavailable dimensions. The record must include `execution_hold_state` (`CLEAR`, `HELD`, `UNKNOWN`); HELD/UNKNOWN refuses resumption readiness. Even CLEAR remains a caller claim pending a trusted reconciliation.

| Target | Additional structural evidence |
| --- | --- |
| `FEATURE_OFF` | Externally accepted corrected current kernel commit/receipt, exact disabled-feature config digest, current state witness, supported-path receipt |
| `ISOLATED_ORIGINAL` | Original tree identity, custody grant, isolated destination resolution witness, transactional snapshot consistency, original runtime pin, exact historical scope |
| `FROZEN_CONTROL` | Same accepted corrected kernel, immutable frozen-policy digest, arm A account isolation and common evaluation-rule receipt; campaign arm C is **not** Recovery Target C |

For all three targets, relevant original bytes, grants, custodian, immutable revision/correction history, actual database/OS/ACL/host evidence, symlink/junction handling, replay and separate code/private-state/runtime tests **must be authenticated elsewhere**. A self-described `receipt_ref` or SHA hash does not prove any of these facts.

## Proposed consumer contract

`RecoveryPreflight(structurally_reviewable: bool, reasons: tuple[str,...])` is a pre-review linter result, not a machine-actionable gate. `reasons` are stable diagnostic strings such as `PRIVATE_STATE.status.not_passed`, `RUNTIME.manifest_mismatch`, `independent_verifier.self_review`, `snapshot_consistency_receipt_ref.missing` and `execution_hold_state.not_resolved_for_resumption`. Status values reflect the proposed R2 language: passed, failed, pending, cancelled, blocked, not_run and unavailable. N/A requires explicit evidence-bound scoping in a future accepted contract; this preflight never silently counts it as success.

Dependent comparisons require concrete string operands. Malformed target, hold, reviewer, manifest fingerprint or frozen-arm objects produce refusal reports without invoking their equality, inequality or hashing callbacks. The component status, receipt-reference and manifest checks retain their existing concrete-type boundaries. A non-string root manifest fingerprint cannot become a comparison operand for an otherwise valid component digest. These checks do not coerce object/subclass values into strings or authenticate any caller claim.

No automated consumer may use `structurally_reviewable` to initiate restore, open an order, clear an UNKNOWN execution hold, grant runtime permissions or certify a scientific control.

## Verification checkpoint and independent acceptance

The user's current necessary-test instruction is recorded in the [2026-10-23 continuation claim](https://github.com/KanujVerma/drift/issues/520#issuecomment-6370051190), superseding the older authoring-session deferral. The repair addresses [Matthew's full formal review](https://github.com/KanujVerma/drift/pull/522#pullrequestreview-5595082497), including the adjacent same-class frozen-arm comparison, without altering the public result schema or R2 target distinctions.

Actual local results with locked CPython 3.14.6:

- Tests-only RED on original source: **10 failed, 39 passed**, reproducing the five unsafe scalar comparison surfaces with hostile objects and string subclasses.
- GREEN after repair: **49 focused tests passed**. All hostile equality, inequality and hash callbacks remain uncalled. Existing target/dimension, manifest-mismatch, self-review, receipt reuse and unresolved-hold controls remain intact; all results retain the false authority property.
- **168 additional probes passed:** 108 exact original/repaired result comparisons across ordinary target, hold, reviewer and manifest controls, plus 60 object/subclass spoof controls whose callbacks would return true or false rather than raise. Every malformed spoof refuses with zero callbacks.
- Whole-repository Ruff lint and format checks passed on 564 files, including the four reviewed E501 fixes. Strict `mypy src tests` passed on 472 files. Source distribution and wheel built successfully.
- Git whitespace/scope and both local Markdown-link checks passed. All 12 original fixture/test functions are unchanged by AST comparison; Python pins, lockfile, package metadata and shared guard bytes remain unchanged.
- The unchanged ordinary production AST profile accepts the actual final script. Four parsed-only socket, environment-read, subprocess and dynamic-evaluation injections refuse; none of the injected operations was executed. AST inspection confines source changes to the four dependent comparison statements and preserves the public schema, helpers and constants.
- One focused inventory probe failed at `tests/integration/test_m1e_compatibility.py:976`, solely because `scripts/recovery_evidence_preflight.py` is absent from `INERT_SOURCE_PATHS`. The shared guard remains unchanged.

This exact source needs separately scoped inventory and actual scanner-dispatch membership. It requires no new capability exception; existing #552-#555 requests cover other paths and are not silently expanded. Preserve unknown-path negatives, source pins and the separate #502 -> #487 / #394 gates. Full local pytest was not rerun against this known inventory failure. Earlier [canonical run 39540044424](https://github.com/KanujVerma/drift/actions/runs/39540044424) failed at the original head and does not qualify the repair. Fresh canonical CI and independent acceptance remain pending.

On the exact published PR head, reproduce focused checks with:

```bash
uv run python -m pytest tests/unit/test_recovery_evidence_preflight.py -q
uv run ruff check scripts/recovery_evidence_preflight.py tests/unit/test_recovery_evidence_preflight.py
uv run ruff format --check scripts/recovery_evidence_preflight.py tests/unit/test_recovery_evidence_preflight.py
uv run mypy src tests
uv build
git diff --check
```

Follow [AGENTS.md](../../../../AGENTS.md) and the [canonical workflow](../../agent-workflow.md), with full `uv run pytest` after accepted guard integration is composed. Automatic hosted CI remains enabled. Further checks of custody, symlink escape evidence, expired grants or actual kernel/run/environment evidence remain independent. Host probes and real state recovery need separate authority and are outside this PR.

**Acceptance request:** Matthew to review candidate field semantics against his R2/actual custodian, #397 independently verifies evidence/conflicts and confirms a supported enforcement mechanism, and Krish/Kanuj review their scientific consumers where affected. Original #395 and #396 writer reservations, all code/persisted schemas, secrets, dependencies and interpreter pins remain untouched. Do not merge this draft or claim recovery is solved from a green code check alone.
