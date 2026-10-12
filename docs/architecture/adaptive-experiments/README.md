# Adaptive experiments: start here

This is Drift's agreed product and research direction, not a claim that the
adaptive system is implemented or operationally authorized.

Read in this order:
1. [Decisions and rationale](decisions.md): the 17 user-approved decisions.
2. [System design](design.md): boundaries, evidence rules, and experiment design.
3. [Delivery plan](delivery-plan.md): independently testable increments.
4. [External reuse](reuse-evaluation.md): source-backed patterns, not installed dependencies.
5. [Workstreams](../workstreams.md): ownership and producer-contract routing.
6. [Agent workflow](../agent-workflow.md): Resume, claims, Checkpoint, and Handoff.

GitHub Issues, native dependencies, and PRs own the live queue. Do not infer
readiness from this page. Implementation truth is the actual code, schemas,
tests, and Git history. The bootstrap activation issue must be completed
before newly created implementation issues can become READY.

A zero-context agent must read its assigned issue and the linked accepted
contracts. It must not infer undocumented interfaces from this overview.

The product MVP uses bounded strategy selection and adaptation. Later
AI-generated strategies reuse the same evaluation boundary after separate
validation. Three human workstreams are not permission to implement the
conditional M9 multi-agent trading architecture.
