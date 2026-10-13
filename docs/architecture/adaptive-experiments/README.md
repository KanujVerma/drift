# Adaptive experiments: start here

This is Drift's agreed product and research direction, not a claim that the
adaptive system is implemented or operationally authorized.

Read in this order:
1. [Onboarding](onboarding.md): how a fresh agent finds its owner, scope and next task.
2. [Decisions and rationale](decisions.md): the 17 user-approved decisions and why.
3. [System design](design.md): boundaries, evidence rules, and experiment design.
4. [Requirements crosswalk](requirements-crosswalk.md): requirement, producer and issue lineage.
5. [Delivery plan](delivery-plan.md): independently testable increments.
6. [External reuse](reuse-evaluation.md): source-backed patterns, not installed dependencies.
7. [Workstreams](../workstreams.md): ownership and producer-contract routing.
8. [Agent workflow](../agent-workflow.md): Resume, claims, Checkpoint, and Handoff.

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
