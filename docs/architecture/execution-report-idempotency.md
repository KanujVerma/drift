# Execution report delivery idempotency

Issue [#631](https://github.com/KanujVerma/drift/issues/631) repairs the
duplicate-report persistence failures reproduced by
[#568](https://github.com/KanujVerma/drift/issues/568). The broker-neutral router
now uses the existing immutable report identity for all report-producing routes:
submission, original-intent recovery, local risk refusal, cancellation and status.

## Behavior

- A new report for the requested intent is appended through the existing journal.
- An identical report already retained anywhere in the journal is returned from
  storage without another insert, even if a different report arrived later.
- Reusing a report ID with different canonical payload raises
  `RouterExecutionError`. A matching claimed hash alone is insufficient.
- A report for a different requested intent raises `RouterExecutionError` before
  report retention. The earlier intent reservation, if any, remains retained.
- If another connection inserts between the read and insert, the router reads
  the stored report and applies the same exact comparison. A collision without
  the matching report or another persistence failure still propagates.

For example, canceling a mock order that already filled returns the original
FILLED report. Previously the router tried to append it again and raised a
uniqueness error. It now returns the retained fill without another report row,
fill or fee. Ordinary cancellation of an unfilled order continues to work.

The SQLite journal itself remains strict and append-only: direct duplicate
inserts still fail. No row, V1 payload, enum, profile, hash, schema, fixture,
interpreter or dependency pin is rewritten. New report IDs are distinct evidence
records even when their cumulative quantities happen to match.

## Limits

This is report-delivery idempotency, not exactly-once financial settlement or
broker authentication. A valid hash cannot establish the report's origin.
Identical reports do not advance journal arrival order. A status call can return
an older adapter report; this change does not select a monotonic current-status
projection or resolve conflicting lifecycle evidence.

The adapter may already have performed an action before returning an invalid
report or before persistence fails. A refusal does not roll that action back,
prove non-execution or authorize a resend. Durable UNKNOWN observations,
account-wide holds, sender fencing, atomic settlement, explicit resumption and
consumer migration remain the broader work in
[#411](https://github.com/KanujVerma/drift/issues/411).

## Regression coverage

The new actual-router suite covers cancellation after a fill and journal reopen;
nonconsecutive duplicate delivery; changed payload with either recomputed or
unchanged claimed hash; wrong-intent responses through submit, recovery, cancel
and status; a controlled insertion interleaving through separate SQLite
connections; conflicting concurrent identity; unrelated persistence failures;
and a fill notification reentering the router before submission returns.

Tests assert retained report counts/content and exact mock cash, positions and
fees where financial effects occur. The controlled interleaving is not a proof
of concurrent dispatch, broker recovery or settlement. All adapters are offline
mocks. Exact revision and executed test/CI results are recorded on #631 and its
linked PR.
