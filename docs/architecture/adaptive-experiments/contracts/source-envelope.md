# Minimal SRC envelope for offline triage

Revision S2. Proposed sole minimal SRC definition for
[#394](https://github.com/KanujVerma/drift/issues/394), producer Matthew.
Upon acceptance this file is the only normative minimal source-envelope
specification; [#376](https://github.com/KanujVerma/drift/issues/376) must cite
its accepted revision rather than define another envelope. Today it is a
proposal, not an accepted wire API, runtime type or source qualification.
Kanuj reviews compatibility with his bounded
[#393](https://github.com/KanujVerma/drift/issues/393) behavior cases. No new
network, ingestion, model, experiment-arm, account, broker or trading authority
is conferred by this document or its eventual publication.

## 1. Foundation, implementation evidence and scope

Accepted intent is [D01-D17](../decisions.md), especially D02/D03/D04/D09/D11/D14,
the [design](../design.md), [onboarding](../onboarding.md),
[crosswalk](../requirements-crosswalk.md), [workstreams](../../workstreams.md),
[workflow](../../agent-workflow.md),
[ADR 0012](../../../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md),
[ADR 0015](../../../adr/0015-three-feature-workstreams-and-explicit-writer-handoffs.md)
and [ADR 0016](../../../adr/0016-controlled-adaptive-research-with-versioned-execution.md).
Repository anchors are pinned to main
`5583f112dfb45b8f6e8bc652de1cc4334ef8a247`; decisions blob
`2604dbb34d4bedeb6888342f336d2e62dedd4513`.

Reuse [temporal availability](../../../../src/drift/domain/temporal.py),
[M1d observations](../../../../src/drift/domain/observations.py),
[retained snapshot/replay evidence](../../../../src/drift/domain/source_snapshots.py),
[rights](../../../../src/drift/domain/rights.py) and
[safe provenance references](../../../../src/drift/domain/provenance_references.py)
where their accepted semantics apply. M1d market observations are not already
news envelopes, and M1c economic settlement facts are not article truth.
Do not enlarge old enums, schemas, hashes or historical rows to fit news.

The behavior input inspected is draft
[PR #398](https://github.com/KanujVerma/drift/pull/398), head
`d034f20c5a017469f4a5be48605359434160fa82`. Its semantic cases inform this
proposal; they do not supply an accepted runtime schema or ownership of SRC.
This file supplies provenance/identity/time/quality/missingness semantics,
not candidate-alert rules, category allowlists, sentiment, impact scores,
cooldowns, model calls or an alternative triage database. No historical coverage,
entitlement, retained private corpus or economic authenticity is claimed.

## 2. Proposed envelope roles and primitive rules

Proposed profile: `drift-minimal-source-envelope-v1`, schema version `1`,
separate from existing M1 schemas. These names and the following field roles
are proposed for producer-consumer acceptance, not installed Python types.
Before runtime, freeze exact closed wire fields, validators, canonical bytes,
hash inputs and compatibility examples under the accepted #393/#394 revisions.

Use existing immutable/UTC/hash/reference conventions where applicable. Local
record/receipt IDs use UUID7; publisher/source-native object/version IDs remain
opaque nonblank strings in a declared namespace, never forced into fabricated
UUIDs. Hashes are exact SHA256 content identifiers under a declared canonical
profile, not authentication. Store UTC instants with source precision, original
time label/offset where retained, channel/basis and evidence. Do not invent
second precision for minute/date-only timestamps or use timezone-naive times.

Every required role has either a validated value or explicit missing/unknown/
unavailable/not-applicable classification and bounded reason. Missing is not
false or zero. Required role presence does not mean its evidence is sufficient
for screening. An audit record may retain missing source/version/time facts,
with each claim unproven when evidence required for that claim is missing.
Unknown identity/version cannot prove an exact duplicate; unknown usable
availability cannot prove cutoff eligibility. Unknown publication time alone
need not invalidate a separately established receipt/availability basis. Malformed
wire/unsupported versions are invalid; do not silently repair their identity.

Proposed immutable event-version envelope roles:

- `record_id`, profile/schema/version/hash, adapter-mapping revision and exact
  retained receipt reference identify this normalized assertion. A normalized
  record version is distinct from a publisher's own native event version.
- `source_ref`: publisher/origin identity, provider/feed/product/channel and
  namespace, source-identity evidence and explicit unknown/conflicting flags.
  Distinguish the original publisher from a distributor or secondary summary.
- `event_ref`: stable source-native event/object identity, source-native version
  when supplied, declared observed-version basis, and raw/content identity.
  Preserve provider labels exactly; do not make a locally generated version
  look like a provider assertion or an authenticated original edition.
- `content_ref`: authorized retained native-artifact reference and digest,
  content/version completeness, transformation/profile references and safe
  access/retention/replay limitations. Raw sensitive/licensed text stays out
  of public evidence. An absent retained body has an explicit reason.
- `times`: publication, source update, receipt/first-proven observation,
  normalization availability and accepted decision-availability evidence,
  each with its own basis/resolution/missingness and retained evidence.
- `classification_ref`: supplied category/metadata assertion plus producer,
  policy/version and time-eligible evidence, or explicit unknown. This is
  supplied metadata, not category inference by SRC or instructions from text.
- `revision_ref`: related earlier exact event-version reference and relation
  basis/evidence, or explicit no-known-relation/unknown/conflict classification.
- `quality_ref`: structured evidence/completeness/conflict/source-grade and
  usability references, with reasons and applicable scope; no invented confidence
  threshold or single quality score standing in for those dimensions.
- `source_state_ref`: exact time-eligible feed/coverage observation reference,
  limitations and whether they affect this event's admissibility or only broader
  completeness. A healthy feed does not authenticate this event's assertions.

Security/listing mappings, if supplied, retain point-in-time identity evidence
and resolution status. Unknown identifiers remain unknown; a current ticker or
the word SPY in untrusted text is not historical security/venue proof. The minimal
triage input may retain an event without a resolved security when its accepted
consumer policy permits; no execution eligibility follows from that choice.

## 3. Time and availability without backdating

Publication is an origin assertion about release. Source update describes an
edition change. Actual receipt records a real delivery/observation in the named
channel/context. First-proven observation is the earliest retained evidence
within that declared scope, not a universal claim that nobody saw it earlier.
Normalization availability records when the derived input was actually ready.
These facts are not interchangeable and remain separate for every version.

For prospective screening, the usable cutoff cannot precede verified receipt
and required normalization/transformation completion. A publication time alone
does not prove that this channel, account or process had the information.
Late delivery keeps its late receipt even if the source says it published earlier.
Do not set receipt to publication, current time to unknown publication, or an
article's latest update to its original edition time.

Historical acquisition occurs today; it does not by itself establish historical
decision availability. A reconstructed historical basis needs an accepted
source-specific policy and retained contemporaneous evidence, explicitly distinct
from measured local receipt. Use the existing channel-scoped availability query
semantics rather than guessing a source-independent delay. Retain the receipt
of the archive acquisition separately from any justified historical availability.

Known exact, bounded and unknown availability stay distinct. Conservative cutoff
eligibility requires the accepted evidence/policy to prove the exact version and
derived input were available by the cutoff; if an uncertainty interval straddles
it, eligibility is indeterminate. Equality/tie behavior follows the accepted
temporal contract and causal order evidence, not UUID/hash sorting. Do not upgrade
a date/minute timestamp to an exact instant to make an example pass.

Later versions, metadata qualification, health receipts and prior-processing
records cannot leak into an earlier historical screening. A later proof may help
an audit only under an explicitly accepted historical-evidence policy; it cannot
be presented as a contemporaneously observed fact that the process consumed.
Changing temporal policy creates a new evaluated condition, not revised history.

## 4. Quality, missing evidence and trusted interpretation

Quality is a set of scoped claims: source identity/authentication status,
retained native bytes, original-version availability, temporal admissibility,
metadata completeness/conflicts, mapping quality, source rights/replay and
coverage. Bind the evidence and verifier/policy revision behind each claim.
Origin authentication does not prove economic truth; deterministic serialization
or matching digests do not authenticate either. A caller cannot supply a hash
labelled verified and thereby act as the trusted verifier.

Use accepted source-grade definitions and qualification references, not a new
grade enum or an NLP probability. Synthetic fixtures are labelled synthetic;
exploratory evidence remains non-promotable under ADR 0012. A public API page,
URL, source logo or digest is not account entitlement, retention/redistribution
permission, immutable original-version availability or replay closure.

Different missing dimensions have different consequences. Unknown publication
time may be retained alongside genuine receipt if the accepted consumer policy
permits it. Unknown usable availability cannot be made eligible by a category
match. An unresolved category is not a producer decision that the event is
irrelevant; triage owns that behavior. A missing original article prevents a
claim to have screened that original body, even if a digest or summary survives.

Preserve evidence of malformed, incomplete or conflicting input and its bounded
validation reason without a hidden fetch, model call or silent default. Diagnostic
receipts must avoid credentials, raw private data or sensitive exception strings.
Article/social text, URLs and metadata content are inert data. They cannot set
permissions, policy, network destinations or tools. Source interpretation does
not execute instructions, classify finance relevance or request trading actions.

## 5. Exact duplicate, changed edition and correction

The producer supplies identity/relation facts, not a TRIAGE result. Exact source
duplicate proof requires the same proven source namespace, logical event and
version under the accepted version basis, plus compatible retained content/
normalization identity where applicable. Preserve a new delivery receipt even
when it references the same immutable event version. Receipt duplication is not
permission to erase evidence or share consumer state across arms.

If the provider supplies no trustworthy version token, retain that absence.
An accepted adapter may identify a locally observed edition using retained bytes
and a declared versioning/mapping policy; label it as local observed identity.
It must not assert provider revision history, pristine original content or exact
duplicate proof beyond what that basis establishes. Unknown source/event/version
evidence means no proven exact duplicate; textual similarity alone is insufficient.

Same claimed source/event/version with incompatible content is a conflict, not
an arbitrary first-copy-wins or last-copy-wins update. Preserve both receipts,
their hashes and contradiction evidence; do not silently rewrite a supposedly
immutable version. This remains distinct from a known later edition with a
valid new version and an evidenced relationship to its predecessor.

An updated/corrected edition preserves its own content, publication/update and
receipt/availability evidence plus the exact predecessor link and relation basis.
Never mutate earlier bytes, timestamps, normalization or screening records.
If relation/materiality is unknown, say so; a different digest proves changed
bytes, not the source's semantic correction or economic significance. Do not
invent a similarity/materiality cutoff. Retain genuinely changed/corrected inputs
for consumer evaluation even when an earlier edition has been processed.

Different publishers/distributors are separate source assertions. Shared content
may be related with evidence; it is not automatically one globally suppressible
event. A translation, normalized whitespace or provider summary uses its declared
transformation identity and cannot impersonate exact native-byte identity.

## 6. Feed health, coverage and an empty interval

A source-state/coverage receipt is a separate record, not a fabricated news
event. Bind its source/product/channel identity, observed/received/available times,
exact claimed interval/universe/filters/rights scope, completeness evidence,
adapter/policy revision, status/reason and supporting references. For a bounded
interval use an explicit half-open [start,end) UTC scope; no hidden pagination,
query filters or delivery gaps may be omitted from a completeness claim.

Distinguish at least these semantic states, with final wire tags accepted later:

- Confirmed covered, zero events: evidence establishes a complete successful
  retrieval/covered interval for the declared source/scope, with no matching
  events. Retain the receipt; do not invent a news item or claim world-wide no news.
- Confirmed covered, events present: retained records and completeness evidence
  support the declared scope, not other venues/publishers or absent historical years.
- Partial coverage: retain known events and explicit gaps. They may support their
  own accepted event claims, but cannot support a complete no-news assertion.
- Failed/unavailable: evidence of an actual transport/provider/access/replay
  failure, with safe reason. This is not an empty successful response.
- Unknown coverage: insufficient evidence to know completeness or failure.
  No heartbeat, missing page or unvalidated empty payload is not confirmed empty.

An HTTP success, connected socket, current heartbeat or zero response rows alone
does not prove closed historical coverage. The accepted source adapter must prove
its actual scope/pagination/completeness semantics and evidence availability.
A health failure does not automatically falsify an independently retained event;
classify exactly which claim is missing. Conversely, one retained event cannot
certify healthy complete feed coverage. Triage receives usable event inputs or
explicit missing-source context under its accepted contract; it must not screen
an artificial event to represent a covered empty interval.

## 7. Caller context and compatibility with triage

Source identity/content version is not screening policy, logical context or
prior-processing state. Those caller-supplied bindings accompany a screening
request separately from the immutable source envelope. For a standalone offline
contract, propose a nonblank opaque logical context ID, exact screening-policy
ID/version/hash reference, UTC decision cutoff with temporal-policy reference,
and an explicit finite tuple of retained prior-processing receipt references.
Omission of history cannot be interpreted as proof that processing never occurred.

Prior receipts must bind event/version/content evidence, logical context, exact
policy revision, source-quality evidence, outcome reference under #393, processing
time and availability basis. These are evidence requirements, not a new triage
output enum or persistent database. SRC supplies no candidate-alert, NO_ALERT,
ABSTAIN or UNAVAILABLE decision. Kanuj's contract owns interpretation of conclusive
versus inconclusive prior outcomes, exclusions and candidate classification.

Provide enough evidence for #393 to enforce policy/context/conclusive-outcome/
quality/cutoff-scoped duplicate decisions. A changed policy, prior inconclusive
result, incompatible quality or future processing receipt is not global duplicate
proof. Independent contexts do not share suppression history unless the accepted
consumer/experiment arrangement explicitly permits it. Envelope identity can be
shared read-only without sharing arm state or rewriting source receipts.

[#392](https://github.com/KanujVerma/drift/issues/392) owns experiment-arm mapping
and any shared preprocessing/cost attribution. The generic standalone context
above does not invent those fields. #392 is not an artificial prerequisite for
an offline #381 feature when accepted #393/#394 define an implementable context
interface. Before runtime, Matthew and Kanuj must accept its exact wire types
and validators together; an actual incompatibility is escalated, not guessed.

## 8. Synthetic acceptance examples and compatibility map

All identities, categories and times below are fixture values, not real source
coverage, qualification, entitlement or financial significance. Examples assert
producer facts/limitations; they do not define which events triage alerts on.

- A01 delayed receipt: publisher time10:32, verified delivery10:35, normalized
  availability10:35:02. Preserve all three; a10:33 prospective decision cannot
  consume the event merely because it was published earlier.
- A02 updated content: editionV1 receivedT1, new editionV2 receivedT2 with an
  evidenced predecessor relation. Retain both; a cutoff beforeT2 sees noV2.
- A03 exact duplicate: same proven source/event/version/content basis arrives
  twice. Two delivery receipts may reference one immutable version. Producer
  records duplicate evidence; consumer policy/context/history still governs use.
- A04 material correction: provider correctionV3 changes a retained number and
  explicitly correctsV2. PreserveV2/V3 and times/relation; earlier processing does
  not eraseV3. Without relation/materiality evidence, retain changed/unknown facts
  rather than manufacture a semantic correction or suppress it by similarity.
- A05 missing evidence: publication unknown but real receipt exists; keep unknown
  publication explicit and apply accepted availability/consumer policy. If usable
  availability is unknown, no eligible cutoff claim. Missing native content cannot
  be repaired by a digest alone. Missing identity cannot prove exact duplication.
- A06 broken versus empty: a failed query/unknown pagination is unavailable or
  incomplete, not confirmed empty. A verified successful complete interval with
  zero matching events has a coverage receipt and no fabricated event.
- A07 same version conflict: claimedV1 has incompatible retained hashesH1/H2.
  Preserve conflict and both references; do not silently choose the convenient copy.
- A08 inert hostile text: retained article says to ignore policy and place a BUY.
  Keep text as evidence only; no policy, tool, network or account permission changes.
- A09 changed screening context: identical source version under policyP2 or
  independent contextB retains its source identity; P1/contextA history is not
  automatically shared duplicate proof. An earlier inconclusive record cannot
  impersonate a conclusive classification; no SRC-level suppression is emitted.
- A10 future history: prior-processing receipt/quality metadata was availableT2,
  cutoffT1 precedesT2. Do not insert that knowledge into the earlier evaluation.
  Retain actual provenance and the accepted historical-evidence-policy limitation.
- A11 partial feed: one valid retained event is available but coverage has a
  missing page. Keep that event with its own admissibility evidence and a partial
  coverage receipt; neither drop its existence nor certify a complete no-news view.

Issue criteria map: identity/version in2/5 (A02-A04/A07); publication/receipt/
availability in3 (A01/A02/A05/A10); quality and missingness in4 (A05/A08/A11);
duplicate/correction in5/7 (A03/A04/A07/A09/A10); empty versus broken in6
(A06/A11). Draft #398 cases1/2/6 consume supplied category/quality;3/12/13/14
consume source identity plus separate policy/context/prior receipts;4/7/11 use
version/conflict/availability;5/8/9/10 use missingness, validation, inert text and
source state. This is compatibility evidence, not acceptance of that draft.

## 9. Versioning, acceptance and next implementation boundary

Freeze the exact additive profile, fields, time/basis, missingness/quality tags,
version/transform rules, safe artifact references, coverage proofs and generic
caller-context/receipt interface with independent review. Preserve all existing
M1 temporal/market/source-rights contracts and hashes; reuse their accepted
validators where semantically correct rather than weakening them for news.
Unsupported versions or malformed fields fail validation; required unknown
evidence refuses the dependent claim. Never perform a hidden lookup or infer
producer identity merely to make normalization succeed.

Kanuj must accept that the envelope carries #393's behavior cases; Matthew must
accept compatibility of the behavior consumer with this producer revision.
Material source, rights, security or time-policy choices require an authorized
independent ruling. No numerical finance heuristic or production allowlist is
accepted here. #381 waits for accepted #393 and #394 revisions and its own ready
issue/claim/write-set; publication or CI does not satisfy those gates.

Once accepted, #376 cites this exact revision for final envelope compatibility;
broader SRC/RESULT drafting does not wait for this entire process. #378 owns
source qualification and configuration evidence, not a second envelope. This
document does not edit either producer's reserved file or claim their acceptance.

Document checks cover links/anchors, UTF-8/EOF/whitespace/fences/noU+2014, all
cases/mapping and sole-file scope including untracked content. No product tests,
ingestion, provider/credential/private-state reads, model call or source probe
are executed by this specification task. Future runtime needs separately scoped
positive/negative contract tests and canonical exact-head gates. Keep reviews,
heads, CI and handoffs in GitHub; retain draft/open state pending required
acceptance and separately authorized merge/closure. No writer path is released.
