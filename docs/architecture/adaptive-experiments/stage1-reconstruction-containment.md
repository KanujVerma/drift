# Stage 1 historical reconstruction containment

The current reconstruction accepts caller-supplied receipt mappings and does
not authenticate them against original account, RESULT, allocation or research
producer records. It also does not authenticate the study's independent role
acceptances. Until those interfaces are connected and independently verified,
reconstruction reports are `RECONSTRUCTION_FAILED`, have zero verified sessions,
and classify the study as `UNAVAILABLE`. A report's numerical fields are
untrusted diagnostic arithmetic, not historical NAV or economic evidence.

The reconstruction CLI requires an explicitly supplied incremental operating
cost or attributable cost. Missing costs are not assumed to be zero or another
number. A missing primary mean block length is not replaced by the 21-session
sensitivity. The present diagnostic calculation does not establish a valid
primary uncertainty interval, even if a caller supplies a block length.

Synthetic fixtures exercise arithmetic and tamper detection without becoming
original producer receipts. [Issue #600](https://github.com/KanujVerma/drift/issues/600)
tracks the full repair: authenticate original account, RESULT, research and
acceptance evidence; use the locked automatic block-length procedure and its
diagnostics; and independently verify the resulting study. Producer decisions
in [#507](https://github.com/KanujVerma/drift/issues/507) and
[#508](https://github.com/KanujVerma/drift/issues/508) remain separate. This
containment does not qualify data, complete G4, establish a result, or authorize
trading.
