"""M2 adversarial acceptance: a split view's anchor stamps belong to its date.

Issue 147, owner ruling option C, part B (the M2 closure guard). Issue 140
bound a realized record's UTC stamps to its local date in the realized clock
builder only. A split-normalized decision view's anchor session need not be a
clock session (``EvaluationInputBundleV1._validate_session_coherence``), and
M1d reads the anchor's stamps without binding them to the date
(``normalization._anchor_basis``), so the issue 140 guard never read the
anchor's record. The issue 147 probe moved the 2026-11-27 anchor record's
stamps a day later, over a realized clock of genuine records: the 2026-11-25
bar anchored on 2026-11-27 materialized at 50 instead of 100, its 2:1 split
applied a session early, and the bundle built and verified. Moved a day
earlier, the split was dropped (100 instead of 50).

Both bundle boundaries now hold every split-normalized decision view's anchor
to the issue 140 check: the anchor's selected realized record, both stamps,
or the opening evidence normalization used, its open. This is an interim M2
guard. M1d's recorded mapping provenance, and split views outside a bundle,
stay uncorrected until the canonical M1d fix, issue 151.
"""

# ruff: noqa: E402

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import cache
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

import action_session_test_support
import observation_test_support
import pytest
import session_test_support
from observation_test_support import NormalizationHarness
from session_test_support import session_dataset
from test_assertions import exact_boundary
from test_evaluator_clock import (
    RealizedStamps,
    _in_session_dst_schedules,
    _restamping,
    _utc,
    in_session_dst_timezone_bytes,
    restamped_corpus_queries,
)

from drift.datasets.hashing import assertion_version_payload
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.assertions import TemporalIntervalClaimV1
from drift.domain.evaluator_bundles import EvaluationInputBundleV1
from drift.domain.evaluator_clock import SessionClockV1
from drift.domain.normalization import (
    AnchorOpeningEvidenceV1,
    DerivedObservationViewV1,
    NormalizationDerivationV1,
    NormalizationQueryV1,
    NormalizationResultV1,
    ObservationDecisionReferenceV1,
    derived_view_output_hash,
)
from drift.domain.observation_query import ObservationOutcomeQueryV1
from drift.domain.sessions import RealizedSessionVersionV1
from drift.errors import DriftError
from drift.evaluator.bundles import (
    AnchorSessionLocalDateError,
    _require_anchor_stamps_on_local_date,
    assemble_evaluation_input_bundle,
    build_evaluation_input_bundle,
    replay_decision_views,
    verify_evaluation_input_bundle,
)
from drift.evaluator.clock import build_realized_session_clock
from drift.markets.normalization import normalize_observation
from drift.markets.observation_selection import select_observation_records
from drift.markets.observation_validation import M1dResolutionContext
from drift.serialization.canonical import canonical_json, content_hash

NOV25 = date(2026, 11, 25)
NOV26 = date(2026, 11, 26)
NOV27 = date(2026, 11, 27)
NOV28 = date(2026, 11, 28)
NOV30 = date(2026, 11, 30)
DEC1 = date(2026, 12, 1)

#: The security of every view here: the normalization corpus's `uid(21)`.
SECURITY = "019b8240-0000-7000-8000-000000000021"

#: The 2:1 split's trading-basis transition, after the 2026-11-27 early close
#: (18:00Z) or before that session's open (14:30Z), as in the issue 147 probe.
AFTER_CLOSE = "2026-11-27T18:05:00Z"
BEFORE_OPEN = "2026-11-27T14:00:00Z"

#: The decision cutoffs: the probe's, the 2026-11-30 close, and one after every
#: record of a moved 2026-11-30 anchor is published (five minutes after its
#: moved close, at the latest 04:35Z on 2026-12-01).
NOV30_CLOSE = datetime(2026, 11, 30, 21, 0, tzinfo=UTC)
DEC1_CUTOFF = datetime(2026, 12, 1, 5, 0, tzinfo=UTC)

INTERVAL = TemporalIntervalClaimV1(
    schema_version="1", start=exact_boundary("2026-11-01T00:00:00Z"), end=None
)


@dataclass(frozen=True)
class Corpus:
    """The genuine prior-open normalization corpus, with chosen evidence moved.

    ``stamps`` moves realized records as the issue 140 tests move them (each
    one's availability follows its moved close), ``dst`` puts the venue on the
    in-session DST corpus of those tests (2026-11-30 opens at UTC-5 and closes
    at UTC-4), and ``opening`` replaces the 2026-11-30 record with the
    opening-only record and companion of the Task 6 anchor-opening corpus, its
    companion's actual open at that instant. Every other byte is genuine.
    """

    stamps: RealizedStamps = ()
    basis: str = AFTER_CLOSE
    dst: bool = False
    opening: datetime | None = None


@dataclass(frozen=True)
class AnchorCase:
    """One decision view over a corpus, and the realized clock it rides."""

    harness: NormalizationHarness
    query: NormalizationQueryV1
    reference: ObservationDecisionReferenceV1
    session_queries: tuple[ObservationOutcomeQueryV1, ...]
    clock: SessionClockV1

    @property
    def context(self) -> M1dResolutionContext:
        context: M1dResolutionContext = self.harness.context
        return context

    @property
    def requests(
        self,
    ) -> tuple[tuple[ObservationDecisionReferenceV1, NormalizationQueryV1], ...]:
        return ((self.reference, self.query),)

    def build(self) -> EvaluationInputBundleV1:
        return build_evaluation_input_bundle(
            evaluation_interval=INTERVAL,
            session_clock=self.clock,
            context=self.context,
            session_queries=self.session_queries,
            decision_requests=self.requests,
        )

    def unguarded(self) -> EvaluationInputBundleV1:
        """The bundle the builder made before issue 147, over exact replay."""
        return assemble_evaluation_input_bundle(
            evaluation_interval=INTERVAL,
            session_clock=self.clock,
            authentic_decision_views=replay_decision_views(self.requests, self.context),
        )

    def verify(self, bundle: EvaluationInputBundleV1) -> None:
        verify_evaluation_input_bundle(
            bundle=bundle,
            context=self.context,
            session_queries=self.session_queries,
            decision_requests=self.requests,
        )


def _moving_opening(
    actual_open: datetime,
) -> Callable[..., M1dResolutionContext]:
    """Wrap the anchor-opening corpus builder to move its companion's open.

    The companion keeps every other field, the record cites the moved
    companion in its place and is resealed, and the realized dataset is
    rebuilt from it, exactly as the wrapped builder builds its own.
    """
    original = observation_test_support._with_anchor_opening_case

    def moved(context: M1dResolutionContext, case: Any) -> M1dResolutionContext:
        changed = original(context, case)
        dataset = next(
            item
            for item in changed.session_datasets
            if item.manifest.dataset_role.name == "realized_session"
        )
        records = tuple(
            item
            for item in dataset.records
            if isinstance(item, RealizedSessionVersionV1)
        )
        (anchor,) = (item for item in records if item.session_key.local_date == NOV30)
        support = dict(changed.supporting_artifacts)
        (digest,) = (
            item
            for item in anchor.source_evidence_hashes
            if b'"anchor_session_opening"' in support[item].data
        )
        companion = AnchorOpeningEvidenceV1.model_validate_json(support[digest].data)
        data = canonical_json(companion.model_copy(update={"actual_open": actual_open}))
        moved_digest = sha256(data).hexdigest()
        support[moved_digest] = VerifiedArtifactBytes(
            data=data, byte_size=len(data), content_hash=moved_digest
        )
        revision = anchor.revision.model_copy(update={"payload_hash": "0" * 64})
        values = dict(anchor) | {
            "revision": revision,
            "source_evidence_hashes": tuple(
                sorted(
                    moved_digest if item == digest else item
                    for item in anchor.source_evidence_hashes
                )
            ),
        }
        provisional = RealizedSessionVersionV1.model_construct(**values)
        values["revision"] = revision.model_copy(
            update={
                "payload_hash": content_hash(assertion_version_payload(provisional))
            }
        )
        record = RealizedSessionVersionV1.model_validate(values)
        rebuilt = session_dataset(
            "realized_session",
            tuple(record if item is anchor else item for item in records),
            support,
        )
        return replace(
            changed,
            session_datasets=tuple(
                rebuilt if item is dataset else item
                for item in changed.session_datasets
            ),
            supporting_artifacts=support,
        )

    return moved


@cache
def anchor_case(
    corpus: Corpus,
    *,
    anchor: date | None,
    cutoff: datetime = NOV30_CLOSE,
) -> AnchorCase:
    """The 2026-11-25 bar as a decision view at ``cutoff`` over ``corpus``.

    Anchored on ``anchor`` it is split normalized, and without one it is
    source basis. The realized clock is the genuine 2026-11-25 session alone,
    so the issue 140 clock guard passes and no anchor is a clock session. Cached
    because each case is only read.
    """
    text = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            action_session_test_support, "_realized_session", _restamping(corpus.stamps)
        )
        if corpus.dst:
            patch.setattr(
                session_test_support, "timezone_bytes", in_session_dst_timezone_bytes
            )
            patch.setattr(
                action_session_test_support,
                "schedule_record",
                _in_session_dst_schedules(session_test_support.schedule_record),
            )
        if corpus.opening is not None:
            patch.setattr(
                observation_test_support,
                "_with_anchor_opening_case",
                _moving_opening(corpus.opening),
            )
        harness = NormalizationHarness(
            include_prior_open=True,
            outer_kind="decision",
            source_session_date=NOV25,
            basis=corpus.basis,
            anchor_opening_case="completed" if corpus.opening is None else "matching",
            economic_through=text,
            economic_coverage_boundary=text,
        )
    mode: Literal["source_basis", "split_normalized"] = (
        "source_basis" if anchor is None else "split_normalized"
    )
    base = harness.normalization_query(mode, anchor_date=anchor)
    observation = base.observation.model_copy(
        update={
            "decision_time": cutoff,
            "knowledge_cutoff": cutoff,
            "effective_cutoff": cutoff,
        }
    )
    query = NormalizationQueryV1.model_validate(
        base.model_dump() | {"observation": observation.model_dump()}
    )
    result = harness.normalize(query)
    assert result.classification == "materialized", result.reasons
    assert isinstance(result.reference, ObservationDecisionReferenceV1)
    session_queries = restamped_corpus_queries(harness, NOV25)
    clock = build_realized_session_clock(session_queries, harness.context)
    return AnchorCase(
        harness=harness,
        query=query,
        reference=result.reference,
        session_queries=session_queries,
        clock=clock,
    )


def _close(view: DerivedObservationViewV1) -> Decimal | None:
    return next(
        item.quantized_value for item in view.fields if item.field_name == "close"
    )


def _anchor_record(case: AnchorCase) -> RealizedSessionVersionV1:
    """The realized record the anchor query selects, as normalization reads it."""
    anchor = case.query.anchor_session
    assert anchor is not None
    dependent = case.query.observation.model_copy(
        update={"session_date": anchor.local_date}
    )
    selected = select_observation_records(dependent, "realized_session", case.context)
    (record,) = selected.records
    assert isinstance(record, RealizedSessionVersionV1)
    return record


def anchor_refusal(
    anchor: str, evidence: str, boundary: str, stamp: str, local: str
) -> str:
    """The issue 147 refusal of one anchor stamp, as an anchored pattern."""
    return (
        "^"
        + re.escape(
            f"split-normalized decision view of security {SECURITY} anchored on "
            f"XNYS {anchor}: the anchor's {evidence} actual {boundary} {stamp} "
            f"falls on venue local date {local}, not its session date (issue 147)"
        )
        + "$"
    )


#: The 2026-11-27 anchor record, stamped a day late or a day early (the issue
#: 147 probe's two cases), and with one stamp moved across local midnight.
LATER = ((NOV27, _utc(NOV28, 14, 30), _utc(NOV28, 18)),)
EARLIER = ((NOV27, _utc(NOV26, 14, 30), _utc(NOV26, 18)),)
#: 04:00Z is 23:00 the evening before at the venue's UTC-5.
OPEN_THE_EVENING_BEFORE = ((NOV27, _utc(NOV27, 4), _utc(NOV27, 18)),)
#: 05:30Z on 2026-11-28 is 00:30 the next morning at UTC-5.
CLOSE_THE_NEXT_MORNING = ((NOV27, _utc(NOV27, 14, 30), _utc(NOV28, 5, 30)),)
#: 01:00Z on 2026-11-28 is 20:00 on 2026-11-27 at UTC-5: the next UTC date,
#: but the anchor's own local date.
CLOSE_PAST_UTC_MIDNIGHT = ((NOV27, _utc(NOV27, 14, 30), _utc(NOV28, 1)),)
#: The in-session DST corpus's two cases (see ``test_evaluator_clock``): each
#: stamp is on the session date at the other boundary's offset only.
DST_CLOSE = ((NOV30, _utc(NOV30, 14, 30), _utc(DEC1, 4, 30)),)
DST_OPEN = ((NOV30, _utc(NOV30, 4, 30), _utc(NOV30, 21)),)


@dataclass(frozen=True)
class Refused:
    """A misdated anchor, the refusal it earns and the view it materializes.

    ``genuine`` is the close the same view has over the genuine corpus, and
    ``moved`` the close M1d materializes with the anchor misdated.
    """

    corpus: Corpus
    anchor: date
    cutoff: datetime
    refusal: tuple[str, str, str, str, str]
    moved: str
    genuine: str


REFUSED: dict[str, Refused] = {
    "a-day-later-applies-the-split-a-session-early": Refused(
        Corpus(stamps=LATER),
        NOV27,
        NOV30_CLOSE,
        (
            "2026-11-27",
            "realized session",
            "open",
            "2026-11-28T14:30:00+00:00",
            "2026-11-28",
        ),
        moved="50.00",
        genuine="100.00",
    ),
    "a-day-earlier-drops-the-split": Refused(
        Corpus(stamps=EARLIER, basis=BEFORE_OPEN),
        NOV27,
        NOV30_CLOSE,
        (
            "2026-11-27",
            "realized session",
            "open",
            "2026-11-26T14:30:00+00:00",
            "2026-11-26",
        ),
        moved="100.00",
        genuine="50.00",
    ),
    "only-the-open-on-the-evening-before": Refused(
        Corpus(stamps=OPEN_THE_EVENING_BEFORE),
        NOV27,
        NOV30_CLOSE,
        (
            "2026-11-27",
            "realized session",
            "open",
            "2026-11-27T04:00:00+00:00",
            "2026-11-26",
        ),
        moved="100.00",
        genuine="100.00",
    ),
    "only-the-close-after-local-midnight": Refused(
        Corpus(stamps=CLOSE_THE_NEXT_MORNING, basis=BEFORE_OPEN),
        NOV27,
        NOV30_CLOSE,
        (
            "2026-11-27",
            "realized session",
            "close",
            "2026-11-28T05:30:00+00:00",
            "2026-11-28",
        ),
        moved="50.00",
        genuine="50.00",
    ),
    "the-close-read-at-its-own-utc-4": Refused(
        Corpus(stamps=DST_CLOSE, dst=True),
        NOV30,
        DEC1_CUTOFF,
        (
            "2026-11-30",
            "realized session",
            "close",
            "2026-12-01T04:30:00+00:00",
            "2026-12-01",
        ),
        moved="50.00",
        genuine="50.00",
    ),
    "the-open-read-at-its-own-utc-5": Refused(
        Corpus(stamps=DST_OPEN, dst=True),
        NOV30,
        DEC1_CUTOFF,
        (
            "2026-11-30",
            "realized session",
            "open",
            "2026-11-30T04:30:00+00:00",
            "2026-11-29",
        ),
        moved="50.00",
        genuine="50.00",
    ),
    "the-opening-evidence-on-the-evening-before": Refused(
        Corpus(basis=BEFORE_OPEN, opening=_utc(NOV30, 4)),
        NOV30,
        NOV30_CLOSE,
        (
            "2026-11-30",
            "opening evidence",
            "open",
            "2026-11-30T04:00:00+00:00",
            "2026-11-29",
        ),
        moved="50.00",
        genuine="50.00",
    ),
}


#: The anchor-opening corpus with its companion at the genuine 14:30Z open.
GENUINE_OPENING = Corpus(basis=BEFORE_OPEN, opening=_utc(NOV30, 14, 30))


def _genuine_of(case: Refused) -> Corpus:
    """The same corpus with nothing moved (the opening at its genuine 14:30Z)."""
    return Corpus(
        basis=case.corpus.basis,
        dst=case.corpus.dst,
        opening=None if case.corpus.opening is None else GENUINE_OPENING.opening,
    )


@pytest.mark.parametrize("name", REFUSED)
def test_a_misdated_anchor_materializes_a_view_the_unguarded_bundle_carries(
    name: str,
) -> None:
    """The cases are live: M1d materializes each misdated view, and replays it.

    The anchor is no clock session, so the issue 140 clock guard never reads
    its record, and the bundle the builder made before issue 147 carries the
    view. In the probe's two cases the factor is wrong: 50 for a genuine 100
    (the split applied a session early), and 100 for a genuine 50 (the split
    dropped).
    """
    refused = REFUSED[name]
    case = anchor_case(refused.corpus, anchor=refused.anchor, cutoff=refused.cutoff)
    genuine = anchor_case(
        _genuine_of(refused), anchor=refused.anchor, cutoff=refused.cutoff
    )
    _anchor_date, evidence, boundary, stamp, _local = refused.refusal

    bundle = case.unguarded()
    (view,) = bundle.authentic_decision_views
    (genuine_view,) = genuine.unguarded().authentic_decision_views

    assert view.basis_mode == "split_normalized"
    assert str(view.security_id) == SECURITY
    assert view.anchor_session is not None
    assert view.anchor_session.local_date == refused.anchor
    assert view.anchor_session not in {
        session.session_key for session in bundle.session_clock.sessions
    }
    assert _close(view) == Decimal(refused.moved)
    assert _close(genuine_view) == Decimal(refused.genuine)
    if evidence == "realized session":
        record = _anchor_record(case)
        moved = record.actual_open if boundary == "open" else record.actual_close
        assert moved is not None and moved.isoformat() == stamp
    else:
        assert refused.corpus.opening is not None
        assert refused.corpus.opening.isoformat() == stamp


@pytest.mark.parametrize("name", REFUSED)
def test_build_refuses_a_view_whose_anchor_stamp_is_off_its_local_date(
    name: str,
) -> None:
    """Issue 147: the builder reads each anchor stamp at its own offset.

    The completed anchor record's open and close are each checked, and so is
    the open of the opening evidence normalization used. Across the in-session
    DST transition each moved stamp is on the anchor's date at the other
    boundary's offset only.
    """
    refused = REFUSED[name]
    case = anchor_case(refused.corpus, anchor=refused.anchor, cutoff=refused.cutoff)

    with pytest.raises(
        AnchorSessionLocalDateError, match=anchor_refusal(*refused.refusal)
    ) as raised:
        case.build()

    assert type(raised.value) is AnchorSessionLocalDateError
    assert isinstance(raised.value, ValueError)
    assert isinstance(raised.value, DriftError)


@pytest.mark.parametrize("name", REFUSED)
def test_verify_refuses_a_bundle_carrying_such_a_view(name: str) -> None:
    """Issue 147: the view replays exactly, and verification still refuses it.

    The bundle is the one the builder made before issue 147, over exact
    replay, so the refusal is the anchor guard's and no replay mismatch.
    """
    refused = REFUSED[name]
    case = anchor_case(refused.corpus, anchor=refused.anchor, cutoff=refused.cutoff)
    bundle = case.unguarded()

    with pytest.raises(
        AnchorSessionLocalDateError, match=anchor_refusal(*refused.refusal)
    ) as raised:
        case.verify(bundle)

    assert type(raised.value) is AnchorSessionLocalDateError


#: Controls: genuine anchors, a completed record and an opening companion, in
#: the probe's two split positions and across the in-session DST transition,
#: and an anchor close past UTC midnight on its own local date.
GENUINE: dict[str, tuple[Corpus, date, datetime, str]] = {
    "the-probe-split-after-the-close": (Corpus(), NOV27, NOV30_CLOSE, "100.00"),
    "the-probe-split-before-the-open": (
        Corpus(basis=BEFORE_OPEN),
        NOV27,
        NOV30_CLOSE,
        "50.00",
    ),
    "an-opening-companion": (GENUINE_OPENING, NOV30, NOV30_CLOSE, "50.00"),
    "the-in-session-dst-transition": (Corpus(dst=True), NOV30, DEC1_CUTOFF, "50.00"),
    "a-close-past-utc-midnight-on-its-local-date": (
        Corpus(stamps=CLOSE_PAST_UTC_MIDNIGHT, basis=BEFORE_OPEN),
        NOV27,
        NOV30_CLOSE,
        "50.00",
    ),
}


@pytest.mark.parametrize("name", GENUINE)
def test_genuine_split_views_build_and_verify_byte_identically(name: str) -> None:
    """Control: the guard only refuses, so a genuine bundle is unchanged.

    Each built bundle equals, byte for byte, the bundle the builder made
    before issue 147, and verifies.
    """
    corpus, anchor, cutoff, close = GENUINE[name]
    case = anchor_case(corpus, anchor=anchor, cutoff=cutoff)

    bundle = case.build()

    unguarded = case.unguarded()
    assert bundle == unguarded
    assert canonical_json(bundle) == canonical_json(unguarded)
    assert bundle.bundle_hash == unguarded.bundle_hash
    (view,) = bundle.authentic_decision_views
    assert view.basis_mode == "split_normalized"
    assert _close(view) == Decimal(close)
    case.verify(bundle)


def test_a_source_basis_view_is_untouched_by_the_anchor_guard() -> None:
    """Control: a source-basis view has no anchor, so nothing is re-read.

    Over the corpus whose 2026-11-27 record is stamped a day late, the
    source-basis view of the 2026-11-25 bar builds and verifies unchanged.
    """
    case = anchor_case(Corpus(stamps=LATER), anchor=None)

    bundle = case.build()

    assert bundle == case.unguarded()
    (view,) = bundle.authentic_decision_views
    assert view.basis_mode == "source_basis"
    assert view.anchor_session is None
    assert _close(view) is None
    case.verify(bundle)


def test_a_misdated_record_that_anchors_no_view_is_untouched() -> None:
    """Control, and the guard's scope: only the anchor's own evidence is read.

    With the 2026-11-27 record stamped a day late, the view anchored on the
    genuine 2026-11-30 record builds and verifies, at its genuine 50. The
    misdated record lies strictly between source and anchor, so M1d records a
    false mapping for it without changing the factor, and that provenance is
    the canonical M1d fix's to correct (issue 151), not this guard's.
    """
    case = anchor_case(Corpus(stamps=LATER), anchor=NOV30, cutoff=DEC1_CUTOFF)
    (moved,) = (
        record
        for dataset in case.context.session_datasets
        if dataset.manifest.dataset_role.name == "realized_session"
        for record in dataset.records
        if isinstance(record, RealizedSessionVersionV1)
        and record.session_key.local_date == NOV27
    )
    assert moved.actual_open == _utc(NOV28, 14, 30)

    bundle = case.build()

    assert bundle == case.unguarded()
    (view,) = bundle.authentic_decision_views
    assert view.anchor_session is not None
    assert view.anchor_session.local_date == NOV30
    assert _close(view) == Decimal("50.00")
    case.verify(bundle)


def test_a_split_labelled_view_without_an_anchor_is_refused() -> None:
    """Fail closed: a split-normalized view is read only through its anchor.

    M1d refuses a split-normalized query without an anchor, so no replay at
    either boundary produces this view; the guard itself refuses it rather
    than pass it unread.
    """
    (view,) = anchor_case(Corpus(), anchor=None).unguarded().authentic_decision_views
    draft = DerivedObservationViewV1.model_construct(
        **(dict(view) | {"basis_mode": "split_normalized"})
    )
    relabelled = DerivedObservationViewV1.model_validate(
        dict(draft) | {"output_hash": derived_view_output_hash(draft)}
    )

    with pytest.raises(
        AnchorSessionLocalDateError,
        match=(
            "^"
            + re.escape(
                f"split-normalized decision view of security {SECURITY} carries "
                "no anchor session (issue 147)"
            )
            + "$"
        ),
    ):
        _require_anchor_stamps_on_local_date(
            (relabelled,), anchor_case(Corpus(), anchor=None).context
        )


def _without_opening(result: NormalizationResultV1) -> NormalizationResultV1:
    """The fresh normalization with its opening evidence no longer cited.

    Both forgeries are constructed past validation, since the lineage the
    result's own contract checks is exactly what they break.
    """
    assert result.derivation is not None
    support = anchor_case(GENUINE_OPENING, anchor=NOV30).context.supporting_artifacts
    cited = tuple(
        digest
        for digest in result.derivation.artifact_hashes
        if digest not in support
        or b'"anchor_session_opening"' not in support[digest].data
    )
    assert len(cited) == len(result.derivation.artifact_hashes) - 1
    derivation = NormalizationDerivationV1.model_construct(
        **(dict(result.derivation) | {"artifact_hashes": cited})
    )
    return NormalizationResultV1.model_construct(
        **(dict(result) | {"derivation": derivation})
    )


def _another_view(result: NormalizationResultV1) -> NormalizationResultV1:
    """The fresh normalization answering with some other view."""
    other = anchor_case(Corpus(), anchor=NOV27).unguarded()
    (view,) = other.authentic_decision_views
    assert view != result.view
    return NormalizationResultV1.model_construct(**(dict(result) | {"view": view}))


@pytest.mark.parametrize(
    "forge", [_without_opening, _another_view], ids=["uncited", "not-replayed"]
)
def test_an_anchor_open_that_cannot_be_located_is_refused(
    forge: Callable[[NormalizationResultV1], NormalizationResultV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed: the opening evidence read is the one normalization used.

    With no completed anchor record, the guard reads the opening evidence the
    view's fresh derivation cites, and only from a normalization that replays
    the view itself. Were the fresh normalization to cite none, or to answer
    another view, the anchor open is unlocated, and the view is refused.
    """
    case = anchor_case(GENUINE_OPENING, anchor=NOV30)
    monkeypatch.setattr(
        "drift.evaluator.bundles.normalize_observation",
        lambda query, context: forge(normalize_observation(query, context)),
    )

    with pytest.raises(
        AnchorSessionLocalDateError,
        match=(
            "^"
            + re.escape(
                f"split-normalized decision view of security {SECURITY} anchored "
                "on XNYS 2026-11-30: the anchor's open is neither one completed "
                "realized session nor one opening evidence its derivation cites "
                "(issue 147)"
            )
            + "$"
        ),
    ):
        case.build()
