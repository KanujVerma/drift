# Stage 1 development calibration containment (draft)

The existing development runner generates synthetic family returns but emits
ordinary calibration artifacts. Until a qualified original-data producer and
an explicitly separate, non-promotable fixture contract exist, the proposed
containment refuses the public runner before creating ledgers or artifacts.

This is a temporary refusal, not a historical calibration implementation.
It does not correct the runner's same-session lookahead, transaction-cost units,
or repeat-ledger behavior. Previously generated artifacts are not retroactively
validated or invalidated by this code change; consumers must assess their origin.

The current patch deliberately changes the public API and CLI behavior. Existing
positive tests still expect successful synthetic execution and fail. The change
is not ready to merge until an agreed compatibility boundary and equivalent
meaningful tests exist, the affected tests and canonical checks pass, and the
exact head is reviewed. No source rights, independent acceptance, profitability,
or trading permission follows from this containment.
