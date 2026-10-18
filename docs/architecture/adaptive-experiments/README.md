# Adaptive experiments: start here

This is Drift's agreed product and research direction, not a claim that the
adaptive system is implemented or operationally authorized.

Read in this order:
1. [Onboarding](onboarding.md): how a fresh agent finds its owner, scope and next task.
2. [Broad product decisions](decisions.md): D01-D17, their rationale and long-term adaptive direction.
3. [Stage 1 strategy decisions](stage1-decisions.md): all S01-S38 user-approved controlled-study choices and rationale.
4. [Stage 1 implementation roadmap](stage1-roadmap.md): sequenced research, owners, synthetic integration and approval gates.
5. [System design](design.md): broader boundaries, evidence rules, and experiment design.
6. [Requirements crosswalk](requirements-crosswalk.md): established broad-product requirement and producer lineage.
7. [Delivery plan](delivery-plan.md): existing issue-driven independently testable increments.
8. [External reuse](reuse-evaluation.md): source-backed patterns, not installed dependencies.
9. [Workstreams](../workstreams.md): ownership and producer-contract routing.
10. [Agent workflow](../agent-workflow.md): Resume, claims, Checkpoint, and Handoff.

The earlier D01-D17 product decisions and the newer S01-S38 Stage 1 decisions
have **different numbering and scopes**. The first seventeen S decisions are
not the original D01-D17. Read both; do not overwrite or concatenate one
onto the other.

GitHub Issues, native dependencies, and PRs own the live queue. Do not infer
readiness from this page. Implementation truth is the actual code, schemas,
tests, and Git history. Each workstream has its own activation gate. Another person's unresolved login
does not by itself keep this workstream blocked. Implementation issues stay
blocked until their exact contract and activation gates are satisfied.

A zero-context agent must read its assigned issue and the linked accepted
contracts. It must not infer undocumented interfaces from this overview.

The product MVP uses bounded strategy selection and adaptation. Later
AI-generated strategies reuse the same evaluation boundary after separate
validation. Three human workstreams are not permission to implement the
conditional M9 multi-agent trading architecture. Four human owners are not
permission to run multiple runtime agents.
