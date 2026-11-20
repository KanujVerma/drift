# Stage 1 development calibration containment

Issue [#596](https://github.com/KanujVerma/drift/issues/596) and draft
[PR #597](https://github.com/KanujVerma/drift/pull/597) contain the unqualified
synthetic producer. This is a deliberate compatibility break for callers that
previously expected generated historical-calibration results.

## Public behavior

`execute_development_run` always raises
`DEVELOPMENT_CALIBRATION_UNQUALIFIED: synthetic inputs only`.
The `development-run` CLI returns 1 for a valid request reaching that refusal.
Neither creates a result or ledger, overwrites an existing output/ledger, updates
the host configuration file, nor mutates the supplied artifact/receipt stores or
allocated-account set. Invalid CLI inputs may fail earlier with input errors.

The synthetic return generator, single-pair simulator, and unreachable campaign
implementation are removed. There is no fixture flag or private simulation
fallback. Plan hashes, authority labels, session counts, and historical date
windows cannot make this entry point produce qualified data.

The configuration and result models, signature, error identifier, and existing
result-hash validation remain available for compatibility. Parsing an old result
or recomputing its hash is not evidence that its inputs came from a qualified
historical source. Existing artifacts require their own origin assessment.

## Explicit fixture coverage

The separate `calibrate` command ranks supplied attempt receipts. Its integration
test supplies nine visibly named FIXTURE receipts, verifies the expected winner
and full ranking proof under reversed input order, and requires no original
acceptance receipts. The incomplete-grid refusal remains tested.

Unit tests cover refusal across session-count choices, preservation of populated
caller state and existing ledger bytes, prohibited-window validation, and a
clearly labelled result-serialization fixture with hash and field tampering.
The serialization fixture does not claim nine original accounts were executed.
No test-only receipt is emitted by the disabled development runner.

## Remaining original-execution obligations

[#606](https://github.com/KanujVerma/drift/issues/606) must establish qualified
point-in-time inputs and nine independent adaptive accounts, causal decisions,
complete costs in the correct units, authoritative accounting, authentic receipt
readback, and safe repeat-run/shared-account/ledger refusal. Those behaviors are
unavailable here; removing their defective synthetic approximation does not
satisfy them. The former synthetic account-success and shared-account tests are
replaced by containment and ranking/serialization coverage, not represented as
validation of the future original-data runner.

No source qualification, scientific acceptance, profitable edge, broker access,
or trading permission follows from this correction. Exact-revision verification
and any remaining environment limitations belong in the PR checkpoint.
