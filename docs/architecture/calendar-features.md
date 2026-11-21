# Point-in-time calendar features

Issue [#662](https://github.com/KanujVerma/drift/issues/662). Status: first
slice. Offline only, exploratory lane only
([ADR 0012](../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md)).
It changes nothing under `src/drift/evaluator/`, sources no data and opens no
connection. Every record it produces carries `evidence_lane="exploratory"`
and none of it is promotion-grade evidence.

This is the producer side for exposure-timing and calendar-tilt baselines: a
pure, deterministic function from a session schedule and as-of knowledge to
typed, hashed calendar features per session.

## What it adds

| Module | Role |
|---|---|
| [`src/drift/domain/calendar_features.py`](../../src/drift/domain/calendar_features.py) | Request, event record, feature values, per-session record, feature set, settlement table, hashes, seals, `CalendarFeatureInputError` |
| [`src/drift/markets/calendar_features.py`](../../src/drift/markets/calendar_features.py) | `compute_calendar_features` |

Both files are registered by exact path in
`tests/integration/test_m1e_compatibility.py`, so the source-capability guard
scans the real files. Neither imports `drift.evaluator`, an adapter, a
transport module or a process module.

## Inputs

```python
compute_calendar_features(
    schedule,             # ScheduledSessionVersionV1 rows, every version
    requests,             # CalendarFeatureRequestV1(session_key, as_of)
    *,
    channel,              # AvailabilityChannelV1 the knowledge clock reads
    availability_policy,  # AvailabilityPolicyV1, as in M1b selection
    retained_evidence=None,  # raw evidence behind rule-derived availability
    events=(),            # CalendarEventRecordV1, optional
    event_kinds=(),       # the event kinds to report, declared up front
) -> CalendarFeatureSetV1
```

The schedule is the same `ScheduledSessionVersionV1` row type DRIFT already
validates in M1d, not a parallel calendar. The rows must come from one source
and one venue. Each session date has at most one logical row; a correction, a
late closure or a withdrawal is a later version of that row's revision chain.

The function does not authenticate rows. A closed row materialized from
closed-world coverage is indistinguishable here from one a provider printed,
so a caller holding an M1d context should run
`verify_closed_world_session_coverage` on it before passing its rows. Hash
consistency is not origin authentication.

## Cutoff semantics

Each request carries its own `as_of`: the caller's knowledge cutoff for that
session. The features of session `t` depend only on schedule rows and event
records known **strictly before** `t`'s `as_of`. The cutoff is a parameter,
not a constant, because the right instant depends on the consumer:

- For a strategy that decides at a session close and executes at the next
  open, the features of the execution session `t` should be computed as of
  the decision instant, the close of the session before `t`.
- For features of the decision session itself, use the decision instant.

Rules that hold for every call:

- `as_of` must be timezone-aware. A naive datetime is refused when the request
  is built.
- Requests must be in strictly increasing session-date order, and their
  cutoffs must not decrease.
- Nothing here knows when a session opens, so nothing checks `as_of` against
  the session's own boundaries. A cutoff after the session is accepted and
  gives features as of that later instant; choosing it is the caller's
  decision.

## How schedule knowledge is read

A row is known for a request when M1b assertion selection
(`drift.datasets.assertions.select_assertion_version`) on the requested
channel and policy selects it. Selection is evaluated one microsecond before
`as_of`, the resolution of a Python datetime, which makes "available by the
cutoff" strictly "available before the cutoff". Corrections, withdrawals,
INDETERMINATE availability windows and rule-derived evidence follow M1b
unchanged.

Each date then has one status as of the cutoff:

| Known row state | Status |
|---|---|
| `regular` or `early_close` | open |
| `closed` | closed |
| `unknown`, withdrawn, not yet known, INDETERMINATE, or no row | unknown |

An unknown date never counts as closed. A weekend needs an explicit closed
row like any other date; closed-world coverage materializes exactly such rows.

## Features

| Feature | Definition | INDETERMINATE when |
|---|---|---|
| `session_status` | Status of `t` itself | never (it is the status) |
| `month_ordinal_from_start` | 1 plus the open dates from the 1st to the day before `t` | any of those dates is unknown, or `t` is not known open |
| `month_ordinal_from_end` | 1 plus the open dates from the day after `t` to month end | any of those dates is unknown, or `t` is not known open |
| `sessions_remaining_in_month` | `month_ordinal_from_end` minus 1 | same as `month_ordinal_from_end` |
| `third_friday`, `is_third_friday` | The calendar third Friday of `t`'s month | never |
| `monthly_expiration_session` | The third Friday if open, else the latest earlier open date | a date walked over is unknown |
| `is_monthly_expiration_session` | `t` is that session | `t` is not known open, or the expiration session is INDETERMINATE |
| `settlement_cycle` | `n` of `T+n` for trade date `t` | see the settlement table below |
| per event kind: `on_session` | a visible event falls on `t` | never |
| per event kind: `previous_event_date`, `next_event_date` | nearest visible event dates strictly before and after `t` | no such visible event |
| per event kind: `sessions_until_next_event` | open dates after `t` up to and including the next visible event date | no next visible event, a date in between is unknown, or `t` is not known open |

An INDETERMINATE feature carries a reason code and, for
`schedule_status_unknown`, the first blocking date. It never carries a guessed
default. The session-relative features (ordinals, sessions remaining, the
expiration flag and `sessions_until_next_event`) are INDETERMINATE with
`session_not_known_open` whenever `t` is not known open; the date-level
features are computed regardless.

`schedule_record_hashes` and `event_record_hashes` name exactly the schedule
rows and event revisions the features were read from. Every one of them was
known strictly before `as_of`.

## Monthly options expiration

Rule used: Cboe Exchange Rule 1.1, definition of "Expiration Date" (rulebook
updated as of November 16, 2026): unless defined otherwise, the expiration
date is the third Friday of the expiration month, or, if that Friday is a day
on which the listing exchange is not open for business, the preceding day on
which it is open. Source:
[Cboe Exchange rulebook](https://cdn.cboe.com/resources/regulation/rule_book/C1_Exchange_Rule_Book.pdf),
text extracted and read directly for this slice.

Worked example: Good Friday, 2025-04-18, was the third Friday of April 2025
and a closure, so the expiration session is Thursday 2025-04-17. MIAX's
Good Friday 2025 notice states that its options markets were closed on
2025-04-18 and that expiration for that week moved to 2025-04-17
([MIAX alert](https://www.miaxglobal.com/alert/2025/04/07/miax-exchange-group-holiday-schedule-good-friday-2025)).
The unit tests hold this vector.

Two limits:

- The rule speaks of the options exchange's business days. This module walks
  the supplied venue schedule (for example XNYS) as a proxy. The two agree for
  the closures tested here; a day on which the equity venue is open and the
  options exchange is closed, or the reverse, would make them disagree.
- Before 2015-02-01 the OCC expiration date of standard monthly options was
  the Saturday after the third Friday; SR-OCC-2013-04 (SEC Release No.
  34-69772, [Federal Register 2013-14793](https://www.govinfo.gov/content/pkg/FR-2013-06-21/html/2013-14793.htm))
  moved it to the third Friday for series expiring after 2015-02-01. The
  feature here is the last session on or before the third Friday. That this
  was also the last trading session before 2015 is (inferred) and was not
  verified against a pre-2015 rule text.

## Settlement-cycle table

`US_REGULAR_WAY_SETTLEMENT_TABLE_V1` is a closed, versioned, self-hashed
table keyed by trade date, for venues XASE, XNAS and XNYS. It is the
regular-way standard for most broker-dealer transactions under SEC Rule
15c6-1 and, before it, the self-regulatory organizations' rules. It does not
cover securities a rule exempts and does not compute settlement dates, which
follow a settlement-holiday calendar this module does not hold.

| Row | Trade dates | Cycle | Announced on | Source |
|---|---|---|---|---|
| `t5-sro-regular-way` | 1993-10-06 to 1995-05-31 | T+5 | 1993-10-06 | SEC Release No. 34-33023 (1993-10-06) adopting Rule 15c6-1 replaced the T+5 standard; [NASD NtM 93-77](https://www.finra.org/rules-guidance/notices/93-77) |
| `t5-before-conversion` | 1995-06-01 to 1995-06-04 | T+5 | 1995-04-01 | Release No. 34-34952 (1994-11-09, 59 FR 59137) moved the effective date from 1995-06-01 to 1995-06-07; [NASD NtM 95-26](https://www.finra.org/rules-guidance/notices/95-26) settles 1995-06-02 trades on 1995-06-09 |
| `t4-conversion` | 1995-06-05 to 1995-06-06 | T+4 | 1995-04-01 | NtM 95-26: both days settle in four business days (two double settlement days) |
| `t3-rule-15c6-1` | 1995-06-07 to 2017-09-04 | T+3 | 1995-04-01 | NtM 95-26: 1995-06-07 is the first T+3 trade date |
| `t2-rule-15c6-1` | 2017-09-05 to 2024-05-27 | T+2 | 2017-03-22 | SEC Release No. 34-80295, [press release 2017-68](https://www.sec.gov/newsroom/press-releases/2017-68-0), compliance date 2017-09-05 ([Federal Register 2017-06037](https://www.govinfo.gov/content/pkg/FR-2017-03-29/pdf/2017-06037.pdf)) |
| `t1-rule-15c6-1` | 2024-05-28 onward | T+1 | 2023-02-15 | SEC Release No. 34-96930, [release page](https://www.sec.gov/rules-regulations/2023/02/34-96930), compliance date 2024-05-28 ([SEC T+1 FAQ](https://www.sec.gov/exams/educationhelpguidesfaqs/t1-faq)) |

How the table answers, and when it does not:

- **Before 1993-10-06**: INDETERMINATE (`settlement_before_table`). T+5 was
  the standard well before then, but no source found dates the NYSE's move to
  T+5. NtM 93-77 says the American Stock Exchange reached T+5 in 1968 and the
  NYSE "gradually moved" there. The table starts at the earliest date a
  verified source describes T+5 as the standard.
- **After 2026-11-20** (`verified_through`, the date the table was checked):
  INDETERMINATE (`settlement_after_verified_range`). A later change would need
  a new table version, not a guess that T+1 continues.
- **Before a row is known**: a row counts as known only from 00:00 UTC two
  days after its announcement date, which is after the end of that date in
  every US time zone; a cutoff not later than that gives INDETERMINATE
  (`settlement_row_not_known_at_cutoff`). Announcement dates are conservative:
  where an earlier document exists (Release No. 34-34952 for the T+3 start),
  the later directly verified notice is used.
- The 1995 T+5 period is split at 1995-06-01 because the 1993 release first
  set that date as the start of T+3. A cutoff before the 1995 notice cannot see
  the T+5 answer for 1995-06-01 to 1995-06-04, which the 1993 release had
  assigned to T+3.
- **Outside XASE, XNAS, XNYS**: INDETERMINATE
  (`settlement_venue_outside_table`).

## Known-in-advance events

An optional registry of caller-supplied `CalendarEventRecordV1` records, for
example scheduled FOMC meetings. Each record has an `event_id`, a `revision`
numbered from 0, an `event_kind`, a `status` (`scheduled` or `cancelled`), an
`event_date` and a `published_at`. The latest revision of an event published
strictly before `as_of` decides it; a `cancelled` latest revision hides the
event. Records of a kind not declared in `event_kinds` are refused, so the
features reported never depend on which records exist after the cutoff.

`published_at` is whatever the caller states. It must be a conservative upper
bound of first publication; nothing here can check it. "No visible event"
means none was known by the cutoff, not that none happened.

## Refusals

Inconsistent input is refused with `CalendarFeatureInputError` and its code
(`CALENDAR_FEATURE_INPUT_CODES`), whether or not the inconsistency is known
before any cutoff. Nothing is computed from it. Refused: an empty schedule or
request list; rows of two sources or two venues; a duplicate row or record
version; two logical rows for one date; a revision chain that moves its date
or fails M1b chain checks (branching, cycles, backward availability,
non-increasing sequence); a forged row that does not revalidate; date or
datetime subclasses; requests out of order or with a decreasing cutoff; a
request for another venue; event revisions that are duplicated, have gaps,
change kind or are not published strictly after the revision they replace;
an undeclared or malformed event kind.

Consistent knowledge that is not established strictly before a cutoff is not
refused. It makes the dependent features INDETERMINATE.

## What this does not prove

- **Historical as-known features need historical knowledge times.** A row's
  knowledge time is its availability evidence on the chosen channel. Rows
  whose only evidence is a 2026 acquisition are not known before 2026, so
  features for earlier sessions computed as of their own decision times are
  INDETERMINATE. That is correct behavior, not a defect. Usable historical
  features need schedule rows whose availability evidences the original
  publication of each calendar entry, which is a data-sourcing question
  outside this slice. Computing every session as of one later audit instant
  is possible (one cutoff for every request) but is current interpretation,
  not point-in-time evidence, and the output cannot tell the two apart.
- The NYSE dates in the tests are real closures; every availability instant
  in the tests is synthetic. No real schedule data was used.
- The 2025-01-09 National Day of Mourning closure used in the adversarial
  tests was announced by the NYSE on 2024-12-30 (per search results; the ICE
  press release itself was not fetched).
- A passing feature set is exploratory development evidence about supplied
  inputs. It is not a source qualification and grants nothing.

## Tests

- `tests/unit/test_calendar_features.py`: hand-computed month positions for
  December 2024 (early close), January 2025 (with and without the 2025-01-09
  closure) and April 2025 (Good Friday); third Fridays; expiration on an open
  third Friday, on Good Friday 2025, across consecutive closures and into an
  unknown date; settlement on and either side of every table boundary, outside
  the table and before announcement; strict-cutoff, bounded-availability,
  other-channel and withdrawal knowledge; event visibility, rescheduling and
  cancellation; every refusal code; record tamper checks; pinned hashes.
- `tests/adversarial/test_calendar_features_causality.py`: 30 random
  (session, cutoff) pairs over randomly revised histories where truncating all
  later knowledge, or revising every row and event after the cutoff and adding
  rows for new dates, leaves every session's features byte-identical; the
  late-announced closure changes exactly the January 2025 trading sessions
  (every one of them has a cutoff after the announcement) and nothing whose
  cutoff precedes it or whose features never read 2025-01-09, such as the
  2024-12-31 session; refusals that hold whatever the cutoff; forged
  feature sets; stability across input order, UTC offsets and JSON round trip.
