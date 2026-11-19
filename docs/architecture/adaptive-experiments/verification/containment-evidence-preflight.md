# Offline containment evidence preflight (Issue #521)

**Status: focused-verified code candidate; integration admission and independent acceptance pending.** Matthew remains the accountable platform producer for [#396](https://github.com/KanujVerma/drift/issues/396) and its existing draft [PR #417](https://github.com/KanujVerma/drift/pull/417). The proposed original [containment.md on Matthew's draft branch](https://github.com/KanujVerma/drift/blob/matthew/396-m-contain/docs/architecture/adaptive-experiments/containment.md) (revision C2, unmerged) belongs to that writer; independent acceptance/evidence conflict handling remains with [#397](https://github.com/KanujVerma/drift/issues/397). Krish-Verma publishes the separate helper code under explicit user instruction.

## What the code does

`preflight_containment_evidence(payload)` is a pure Python function that checks a submitted **in-memory evidence index**, not actual confinement. It checks all 11 required A01-A11 denial scenarios and their distinct permitted positive controls, external-enforcer receipt labels and environment binding. It rejects missing/duplicate/unknown cases, failed/not-run denials or controls, same receipt for both results, missing external before/after anchors for A01/A11, missing direct alternate-client enforcement proof for A07, false real-network positive control in A08's offline profile, missing fallback refusal for A10 and a stated author/reviewer identity collision.

Its return `ContainmentPreflight(structurally_reviewable, reasons)` is for **review queue completeness only**, not an operational security verdict. Its `authorizes_worker_launch` is permanently false. No code in this branch opens a network connection, executes a worker, creates symlinks, reads the filesystem, launches a subprocess, applies sandbox rules or accesses live credentials/private bytes. Literal `evidence_origin="independent_enforcer"` is only a caller assertion, not issuer authentication. Matching hashes and references are also unverified until independently checked.

## Proposed in-memory receipt index

A submitted record names `source_commit` (40 lowercase hex), `policy_sha256`, synthetic `run_id`, `environment_ref`, `sandbox_image_ref`, grant verification, effective capability inventory, offline network policy, trusted enforcer and its independent evidence receipt, mechanism author, independent reviewer, external custody anchor, `network_profile="offline"`, `unconfined_fallback="refused"`, `evidence_origin="independent_enforcer"` and an array of A01-A11 claims. A case includes exact `case_id`, `denial_status`, `control_status`, separate receipt references, observed environment, enforcement path and evidence origin. A01 and A11 add independently anchored before/after identity. A07 adds direct alternate-path enforcement evidence, A08 a **fixture-only** control rather than a live network allowance, and A10 refusal of any unconfined retry.

The checker intentionally has no mechanism to make receipt strings, signatures, principal IDs, environment ACLs, DNS/IPv6 egress or direct client controls authentic. An independent, capability-aware recorder/verifier must examine the original trusted evidence in the exact authorized environment. A future accepted enforcement contract may change this provisional synthetic indexing format; do not promote it into normative C2 policy merely because tests pass.

All five literal policy boundaries require concrete strings before comparison: root network profile, fallback policy and evidence origin, each case's evidence origin, and A08's control kind. Reviewer and paired receipt comparisons require valid concrete text on both operands. Environment equality requires concrete strings on both sides; malformed references are already reported missing and are not compared. Wrong-valued objects or string subclasses cannot override these checks through equality, inequality or hashing callbacks. No value is coerced into a string, and no new host policy or receipt authority is defined.

## Verification checkpoint and independent handoff

The user's current necessary-test instruction is recorded in the [2026-10-23 continuation claim](https://github.com/KanujVerma/drift/issues/521#issuecomment-6370319832), superseding the original authoring-session test deferral. The repair addresses [Matthew's full formal review](https://github.com/KanujVerma/drift/pull/523#pullrequestreview-5595083518) and adjacent same-class reviewer, receipt-pair and environment comparisons. The exact scope remains `scripts/containment_evidence_preflight.py`, `tests/unit/test_containment_evidence_preflight.py`, and this verification document.

Actual local results with pinned CPython 3.14.6 and unchanged `uv.lock`:

- Tests-only RED on original source: **36 failed, 27 passed**, reproducing false structural positives and callback execution with spoofing/raising objects and string subclasses.
- GREEN after repair: **63 focused tests passed**. All malformed comparison controls refuse with zero callbacks, genuine complete A01-A11 claims remain structurally reviewable without authority, wrong plain policy values retain their refusal diagnostics, and replay leaves the input unchanged.
- **409 additional probes passed:** 243 root plain-string combinations match the original results and exact reasons; 132 hostile object/subclass controls across every A01-A11 case refuse without callbacks; 34 ordinary case controls preserve their exact original results. These are synthetic API checks, not host confinement probes.
- Repository Ruff lint and format checks passed on 564 files; strict `mypy src tests` passed on 472 files. Source distribution and wheel built successfully.
- Git whitespace/scope and both local Markdown-link checks passed. All 15 original fixture/test functions are unchanged by AST comparison; interpreter pins, lockfile, package metadata and shared guard bytes remain unchanged.
- The unchanged ordinary production AST profile accepts the actual final script. Four parsed-only socket, environment-read, subprocess and dynamic-evaluation injections refuse; none of the injected operations was executed. Public schema, helpers, imports and declared contract constants remain unchanged by AST inspection.
- One focused inventory probe failed at `tests/integration/test_m1e_compatibility.py:976`, solely because `scripts/containment_evidence_preflight.py` is absent from `INERT_SOURCE_PATHS`. The shared guard remains unchanged.

This exact script requires separately scoped inventory and actual scanner-dispatch membership. No new capability exception is needed, and #552-#556 requests are not silently expanded to cover this path. Preserve unknown-path negatives, pins and the separate #502 -> #487 / #394 gates. The full local suite was not rerun against the known inventory failure. Earlier [canonical run 39540047283](https://github.com/KanujVerma/drift/actions/runs/39540047283) failed at the original head and does not qualify this repair. Fresh canonical CI and independent acceptance remain pending.

On the exact published head, reproduce focused and static checks with:

```bash
uv run python -m pytest tests/unit/test_containment_evidence_preflight.py -q
uv run ruff check scripts/containment_evidence_preflight.py tests/unit/test_containment_evidence_preflight.py
uv run ruff format --check scripts/containment_evidence_preflight.py tests/unit/test_containment_evidence_preflight.py
uv run mypy src tests
uv build
git diff --check
```

Follow [AGENTS.md](../../../../AGENTS.md) and the [canonical workflow](../../agent-workflow.md), with full `uv run pytest` after accepted guard integration is composed. Automatic hosted CI remains enabled. Independent reviewers still examine A01-A11 evidence provenance, actual enforcer identity, environment scope and custody. Additional **inert host probes only after separately approved scope** must prove direct and alternate-entry enforcement at the principal level, including symlinks, child tooling, plugins and egress, paired with allowed positive controls. No host, network, worker, sandbox or credential probes were run here.

**Never** treat a code check, self-reported denial, broken environment or documentation review as an accepted sandbox or authorization to trade, launch an experimental worker, access holdouts or publish to main. This issue changes no original producer document, current kernel, account, source, policy, authorization, pin or protected tests. Matthew/#397 have final producer and independent evidence review responsibilities before any integration.
