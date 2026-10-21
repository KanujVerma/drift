# Offline recovery evidence preflight (Issue #520)

**Status: implementation candidate, untested.** Matthew is the accountable platform owner. This is Krish-Verma / GPT-6's bounded code assist, derived from Matthew's [#395 proposal](../../../../../../issues/395) and draft [PR #416](../../../../../../pull/416). The authoritative [recovery.md](../recovery.md) remains on Matthew's isolated, unmerged draft and has not been modified. Independent evidence and custody acceptance belongs to [#397](../../../../../../issues/397).

## Purpose and boundaries

The pure function \`preflight_recovery_evidence(payload)\` checks whether an **already collected, synthetic or trusted externally retained** recovery report is structurally complete. It never reads a manifest or filesystem, executes a command, touches an archive, validates source authenticity, contacts providers, changes runtime settings, disables features or restores private state. It does not verify that a named reviewer, trusted issuer, grant or receipt is real. Matching digests are equality checks only, not authentication.

All output from this function is **untrusted as a recovery claim**. \`structurally_reviewable=True\` means required fields exist, declared status is \`passed\` for CODE, PRIVATE_STATE and RUNTIME, each dimension points to distinct evidence, original manifests agree, the stated execution hold is clear and the independent review reference is not literally the author's identity. The function always returns \`authorizes_recovery_or_execution=False\`. Actual independent #397 review and original bytes/permissions are mandatory before any conclusion.

## Targets and required data

All targets require a run/manifest ID, exact lowercase SHA-256 manifest fingerprint, a separate grant verification reference, immutable history anchor, independent reviewer/custody reference and the three separate dimensional receipts with revision, environment and matching manifest hash. Refuse missing, malformed, contradictory, reused, failed, cancelled, pending or unavailable dimensions. The record must include \`execution_hold_state\` (\`CLEAR\`, \`HELD\`, \`UNKNOWN\`); HELD/UNKNOWN refuses resumption readiness. Even CLEAR remains a caller claim pending a trusted reconciliation.

| Target | Additional structural evidence |
| --- | --- |
| \`FEATURE_OFF\` | Externally accepted corrected current kernel commit/receipt, exact disabled-feature config digest, current state witness, supported-path receipt |
| \`ISOLATED_ORIGINAL\` | Original tree identity, custody grant, isolated destination resolution witness, transactional snapshot consistency, original runtime pin, exact historical scope |
| \`FROZEN_CONTROL\` | Same accepted corrected kernel, immutable frozen-policy digest, arm A account isolation and common evaluation-rule receipt; campaign arm C is **not** Recovery Target C |

For all three targets, relevant original bytes, grants, custodian, immutable revision/correction history, actual database/OS/ACL/host evidence, symlink/junction handling, replay and separate code/private-state/runtime tests **must be authenticated elsewhere**. A self-described \`receipt_ref\` or SHA hash does not prove any of these facts.

## Proposed consumer contract

\`RecoveryPreflight(structurally_reviewable: bool, reasons: tuple[str,...])\` is a pre-review linter result, not a machine-actionable gate. \`reasons\` are stable diagnostic strings such as \`PRIVATE_STATE.status.not_passed\`, \`RUNTIME.manifest_mismatch\`, \`independent_verifier.self_review\`, \`snapshot_consistency_receipt_ref.missing\` and \`execution_hold_state.not_resolved_for_resumption\`. Status values reflect the proposed R2 language: passed, failed, pending, cancelled, blocked, not_run and unavailable. N/A requires explicit evidence-bound scoping in a future accepted contract; this preflight never silently counts it as success.

No automated consumer may use \`structurally_reviewable\` to initiate restore, open an order, clear an UNKNOWN execution hold, grant runtime permissions or certify a scientific control.

## Deferred AntiGravity acceptance

Test files are published but **have not been executed by this implementation session**. On the exact PR head, run \`uv run pytest tests/unit/test_recovery_evidence_preflight.py -q\`, \`uv run ruff check scripts/recovery_evidence_preflight.py tests/unit/test_recovery_evidence_preflight.py\`, \`uv run ruff format --check scripts/recovery_evidence_preflight.py tests/unit/test_recovery_evidence_preflight.py\`, \`uv run mypy src tests\`, and the full canonical repository pytest/build/whitespace checks from AGENTS.md. Add property/adversarial cases for malformed nested maps, digest collision claims, re-used records, unverified authorities, wrong schema, symlink escape evidence, expired grant and changed kernel/run/environment. Host probes/real state recovery need separate authority and are not within this PR.

**Acceptance request:** Matthew to review candidate field semantics against his R2/actual custodian, #397 independently verifies evidence/conflicts and confirms a supported enforcement mechanism, and Krish/Kanuj review their scientific consumers where affected. Original #395 and #396 writer reservations, all code/persisted schemas, secrets, dependencies and interpreter pins remain untouched. Do not merge this draft or claim recovery is solved from a green code check alone.
