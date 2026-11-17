# Retained fill quantity consistency

Issue [#635](https://github.com/KanujVerma/drift/issues/635) extends the duplicate
report retention repair in [#631](https://github.com/KanujVerma/drift/issues/631).
The real-router diagnostics in [#568](https://github.com/KanujVerma/drift/issues/568)
showed an earlier acknowledgement arriving after a confirmed fill and becoming
the latest cached result. Five retained filled shares could therefore appear as
zero filled shares to a caller.

## Router behavior

Before returning a report, `BrokerNeutralExecutionRouter` reads the retained
history for that same intent. If any retained report has a greater cumulative
filled quantity than the candidate result, it raises `RouterExecutionError`
with a cumulative-quantity diagnostic. It does not select a replacement status,
subtract fills, manufacture a rejection, or infer that the order did not execute.

This check covers newly received reports, identical duplicate readback, cached
client-token and intent-ID retries, cancellation results, and journal fallback
when the adapter returns no report. A history read failure propagates; an
unreadable history is not an empty history. Different intents are compared
separately. Report timestamps do not override a greater retained quantity.

Valid new reports are retained before the consistency check. For example:

| Arrival | Retained history | Router outcome |
| --- | --- | --- |
| FILLED, cumulative 5 | FILLED/5 | Returns the fill |
| Earlier ACKNOWLEDGED, cumulative 0 | FILLED/5, ACKNOWLEDGED/0 | Refuses the lower result |
| Same acknowledgement again | Same two rows | Refuses without appending a duplicate |
| Cached same-intent retry after reopen | Same two rows | Refuses without another submission |

The journal itself remains an append-only arrival record. Its latest-row API
still returns the last retained observation, including the lower acknowledgement.
Consumers that read it directly must not treat it as a resolved current state.
Such consumer migration needs its own explicit implementation scope.

Equal or increasing cumulative quantities preserve existing router behavior,
including cancellation retaining a prior partial fill. Equal quantity alone
does not establish lifecycle ordering, cancellation success, measured fees,
broker origin, account binding or settlement completeness. No new status
precedence or correction/bust policy is introduced. An asserted downward
correction is unresolved by this interface and cannot erase historical evidence.

## Limits and recovery

This is a bounded existing-V1 consistency guard, not the proposed UNKNOWN
architecture in [#411](https://github.com/KanujVerma/drift/issues/411). Durable
attempts, account-wide holds, sender fencing, authenticated reconciliation,
atomic settlement and explicit resumption still need their accepted contracts
and implementation. Transport timeout mappings are unchanged.

A refusal may follow an actual fill or cancellation call. It is not permission
to resubmit with the same or a fresh intent ID. The check does not place an
account-wide hold or automatically retry, cancel, liquidate, reconcile or resume.
Returning a later nonregressing report is also not a hold-clearance decision.

The comparison uses the existing journal read snapshot. It is linear in the
number of reports for that intent, does not introduce another mutable projection,
and is not a cross-process lock or a guarantee about observations committed
after that read. Broader transaction and dispatch concurrency belong to #411.

Regression tests exercise lower NEW/ACKNOWLEDGED/partial/canceled/rejected
reports, timestamps on both sides of the fill, reentrant fill-before-ack delivery,
idempotent redelivery, all retained history, reopened cached paths, isolated
intents, nondecreasing positive controls and injected history read failures.
Mock cash and holdings remain unchanged by refusal and cached retry. The issue
and PR record exact validation results; this document does not claim live safety.
