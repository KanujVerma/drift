# Execution journal validation before storage

Issue [#637](https://github.com/KanujVerma/drift/issues/637) makes the existing
V1 readers' validation rules apply before a journal write. Previously, a caller
could bypass frozen-model construction checks and submit changed fields with an
old hash. The journal committed those bytes and then rejected them on readback,
leaving an unreadable row in append-only storage.

## Write contract

`record_intent` and `record_execution_report` serialize the supplied model with
the existing `canonical_json` function, then validate those exact bytes using
`OrderIntentV1.model_validate_json` or `ExecutionReportV1.model_validate_json`.
This occurs before the SQLite transaction begins. Indexed columns are obtained
from the validated model. The original valid serialized bytes are stored as-is.

The existing V1 field, semantic, schema-version and content-hash rules determine
acceptance. Invalid inputs raise the existing validation errors. The writer does
not generate a replacement hash, silently repair fields, or convert invalid
input into a broker rejection. A valid record retains its original payload,
hash, sequence behavior and subsequent strict readback behavior.

No table, index, trigger, wire profile, version, hash algorithm or prior row is
changed. Duplicate IDs and hashes remain strict journal errors. Identical report
redelivery is handled separately by the router, not by weakening journal
uniqueness. Existing append-only UPDATE/DELETE guards remain active.

## Evidence and limits

The regression tests use deliberately forged in-memory models, with positive
controls for ordinary records. They verify rejection before any SQL statement,
unchanged database contents, mutation count and sequence state, later insertion
of the valid identity, exact canonical byte/hash preservation and cold readback.
Duplicate and append-only enforcement are also checked.

This protects content integrity at the normal journal API boundary. It does not
authenticate a caller or broker, prove account/intent authority, stop privileged
direct database writes, or prove the economic truth of a validly hashed claim.
It also does not implement durable execution attempts, UNKNOWN holds, atomic
financial settlement or permission to trade.

Already-corrupted historical rows remain subject to strict read failure. This
change does not rewrite or delete them; recovery requires its own authorized
procedure preserving the original evidence. A validation error after an adapter
has acted likewise does not prove nonexecution or authorize resubmission.
