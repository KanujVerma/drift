"""Admission gatekeeper validating M1e evidence against promotion admission."""

from drift.domain.evaluator_lanes import PromotionEvaluationAdmissionV1
from drift.domain.qualification import (
    AcquisitionState,
    ConsumerPurpose,
    ExecutionReachability,
    M1eCompletionKind,
    M1eCompletionRecordV1,
    PilotProfileSetV1,
    PilotStage,
    PurposeQualificationReportV1,
    QualificationDimension,
    QualificationProfileV1,
    QualificationStatus,
    qualification_profile_hash,
)
from drift.domain.qualification_adapters import (
    QualifiedSourceHandoffV1,
    qualified_source_handoff_hash,
)
from drift.serialization.canonical import content_hash


def validate_m1e_promotion_evidence(
    *,
    admission: PromotionEvaluationAdmissionV1,
    profile_set: PilotProfileSetV1,
    completion: M1eCompletionRecordV1,
    decision_profile: QualificationProfileV1,
    audit_profile: QualificationProfileV1,
    decision_report: PurposeQualificationReportV1,
    audit_report: PurposeQualificationReportV1,
    decision_handoff: QualifiedSourceHandoffV1,
    audit_handoff: QualifiedSourceHandoffV1,
) -> None:
    """Validate M1e qualification evidence against a promotion admission record.

    Ensures that promotion evaluation is admitted only when backed by an authentic,
    positive M1e completion record, valid profiles in the profile set, passing critical
    dimensions, shared snapshot identity, and valid qualified source handoffs.
    """
    if admission.lane != "promotion":
        raise ValueError("admission lane must be promotion")

    # 1. Positive completion record
    if completion.completion_kind != M1eCompletionKind.COMPLETED_POSITIVE:
        raise ValueError("promotion admission requires positive M1e completion")

    actual_comp_hash = content_hash(completion)
    if actual_comp_hash != admission.m1e_completion_record_hash:
        raise ValueError(
            "completion record hash mismatch: "
            f"expected {admission.m1e_completion_record_hash}, "
            f"got {actual_comp_hash}"
        )

    # 2. Profile set hash integrity
    actual_prof_set_hash = content_hash(profile_set)
    if actual_prof_set_hash != admission.m1e_profile_set_hash:
        raise ValueError(
            f"profile set hash mismatch: expected {admission.m1e_profile_set_hash}, "
            f"got {actual_prof_set_hash}"
        )

    if completion.profile_set_hash != admission.m1e_profile_set_hash:
        raise ValueError(
            "completion profile set hash mismatch: "
            f"expected {admission.m1e_profile_set_hash}, "
            f"got {completion.profile_set_hash}"
        )

    # 3. Decision and audit profiles
    if decision_profile.purpose != ConsumerPurpose.HISTORICAL_DECISION_INPUT:
        raise ValueError("decision profile must have historical_decision_input purpose")
    if audit_profile.purpose != ConsumerPurpose.RETROSPECTIVE_AUDIT:
        raise ValueError("audit profile must have retrospective_audit purpose")

    if decision_profile not in profile_set.profiles:
        raise ValueError("decision profile is not a member of bound profile set")
    if audit_profile not in profile_set.profiles:
        raise ValueError("audit profile is not a member of bound profile set")

    dec_prof_hash = qualification_profile_hash(decision_profile)
    audit_prof_hash = qualification_profile_hash(audit_profile)

    # 4. Purpose stage states in completion record: exactly one state per purpose
    if len({ps.purpose for ps in completion.purpose_states}) != len(
        completion.purpose_states
    ):
        raise ValueError("completion contains duplicate purpose states")
    purpose_states = {ps.purpose: ps for ps in completion.purpose_states}

    if ConsumerPurpose.HISTORICAL_DECISION_INPUT not in purpose_states:
        raise ValueError(
            "missing historical_decision_input purpose state in completion"
        )
    if ConsumerPurpose.RETROSPECTIVE_AUDIT not in purpose_states:
        raise ValueError("missing retrospective_audit purpose state in completion")

    dec_state = purpose_states[ConsumerPurpose.HISTORICAL_DECISION_INPUT]
    audit_state = purpose_states[ConsumerPurpose.RETROSPECTIVE_AUDIT]

    for purpose, state, expected_prof_hash in (
        (ConsumerPurpose.HISTORICAL_DECISION_INPUT, dec_state, dec_prof_hash),
        (ConsumerPurpose.RETROSPECTIVE_AUDIT, audit_state, audit_prof_hash),
    ):
        if state.stage != PilotStage.COMPLETED_POSITIVE:
            raise ValueError(f"purpose state for {purpose} is not COMPLETED_POSITIVE")
        if state.terminal_blocker is not None:
            raise ValueError(
                f"purpose state for {purpose} has terminal blocker: "
                f"{state.terminal_blocker}"
            )
        if state.profile_hash != expected_prof_hash:
            raise ValueError(
                f"purpose state profile hash mismatch for {purpose}: "
                f"expected {expected_prof_hash}, got {state.profile_hash}"
            )

    # 5. Purpose reports in completion record: exactly one report per purpose
    if len({pr.purpose for pr in completion.purpose_reports}) != len(
        completion.purpose_reports
    ):
        raise ValueError("completion contains duplicate purpose reports")
    reports_by_purpose = {pr.purpose: pr for pr in completion.purpose_reports}
    if ConsumerPurpose.HISTORICAL_DECISION_INPUT not in reports_by_purpose:
        raise ValueError(
            "missing historical_decision_input purpose report in completion"
        )
    if ConsumerPurpose.RETROSPECTIVE_AUDIT not in reports_by_purpose:
        raise ValueError("missing retrospective_audit purpose report in completion")

    comp_dec_report = reports_by_purpose[ConsumerPurpose.HISTORICAL_DECISION_INPUT]
    comp_audit_report = reports_by_purpose[ConsumerPurpose.RETROSPECTIVE_AUDIT]

    if content_hash(comp_dec_report) != content_hash(decision_report):
        raise ValueError("decision report does not match completion purpose report")
    if content_hash(comp_audit_report) != content_hash(audit_report):
        raise ValueError("audit report does not match completion purpose report")

    # Validate reports and their dimensions
    for purpose, report, profile in (
        (
            ConsumerPurpose.HISTORICAL_DECISION_INPUT,
            decision_report,
            decision_profile,
        ),
        (ConsumerPurpose.RETROSPECTIVE_AUDIT, audit_report, audit_profile),
    ):
        if report.purpose != purpose:
            raise ValueError(
                f"report purpose mismatch: expected {purpose}, got {report.purpose}"
            )
        prof_hash = qualification_profile_hash(profile)
        if report.target.profile_hash != prof_hash:
            raise ValueError(f"report target profile hash mismatch for {purpose}")

        results_by_dim = {r.dimension: r for r in report.results}
        if len(report.results) != len(results_by_dim):
            raise ValueError(
                f"report for {purpose} contains duplicate dimension results"
            )
        if set(results_by_dim) != set(QualificationDimension):
            raise ValueError(
                f"report for {purpose} does not carry the exact 12 dimension set"
            )

        for crit_dim in profile.critical_dimensions:
            dim_res = results_by_dim.get(crit_dim)
            if dim_res is None:
                raise ValueError(
                    f"critical dimension {crit_dim} missing from report for {purpose}"
                )
            if dim_res.reachability != ExecutionReachability.REACHED:
                raise ValueError(f"critical dimension {crit_dim} was not REACHED")
            if dim_res.status != QualificationStatus.PASS:
                raise ValueError(f"critical dimension {crit_dim} did not PASS")
            if not dim_res.admitted_purpose:
                raise ValueError(
                    f"critical dimension {crit_dim} was not admitted for {purpose}"
                )

    # 6. Snapshot-bound targets sharing one identical source snapshot
    for purpose, report in (
        (ConsumerPurpose.HISTORICAL_DECISION_INPUT, decision_report),
        (ConsumerPurpose.RETROSPECTIVE_AUDIT, audit_report),
    ):
        if report.target.acquisition_state is not AcquisitionState.SNAPSHOT_BOUND:
            raise ValueError(f"report target for {purpose} is not snapshot-bound")
        if report.target.snapshot_hash is None:
            raise ValueError(f"report target for {purpose} has no snapshot hash")
    if decision_report.target.snapshot_hash != audit_report.target.snapshot_hash:
        raise ValueError(
            "decision and audit reports do not share identical snapshot hash"
        )

    # 7. Qualified source handoffs: authentic self-hash, then admission binding
    if qualified_source_handoff_hash(decision_handoff) != (
        decision_handoff.handoff_hash
    ):
        raise ValueError(
            "inconsistent decision handoff hash: recomputed "
            f"{qualified_source_handoff_hash(decision_handoff)}, "
            f"declared {decision_handoff.handoff_hash}"
        )
    if qualified_source_handoff_hash(audit_handoff) != audit_handoff.handoff_hash:
        raise ValueError(
            "inconsistent audit handoff hash: recomputed "
            f"{qualified_source_handoff_hash(audit_handoff)}, "
            f"declared {audit_handoff.handoff_hash}"
        )
    if admission.decision_handoff_hash != decision_handoff.handoff_hash:
        raise ValueError(
            "decision handoff hash mismatch: "
            f"expected {admission.decision_handoff_hash}, "
            f"got {decision_handoff.handoff_hash}"
        )
    if admission.audit_handoff_hash != audit_handoff.handoff_hash:
        raise ValueError(
            "audit handoff hash mismatch: "
            f"expected {admission.audit_handoff_hash}, "
            f"got {audit_handoff.handoff_hash}"
        )

    for purpose, handoff, report, profile in (
        (
            ConsumerPurpose.HISTORICAL_DECISION_INPUT,
            decision_handoff,
            decision_report,
            decision_profile,
        ),
        (
            ConsumerPurpose.RETROSPECTIVE_AUDIT,
            audit_handoff,
            audit_report,
            audit_profile,
        ),
    ):
        if handoff.purpose != purpose:
            raise ValueError(
                f"handoff purpose mismatch: expected {purpose}, got {handoff.purpose}"
            )
        prof_hash = qualification_profile_hash(profile)
        if handoff.profile_hash != prof_hash:
            raise ValueError(f"handoff profile hash mismatch for {purpose}")
        rep_hash = content_hash(report)
        if handoff.report_hash != rep_hash:
            raise ValueError(f"handoff report hash mismatch for {purpose}")
        target_hash = content_hash(report.target)
        if handoff.target_hash != target_hash:
            raise ValueError(f"handoff target hash mismatch for {purpose}")
        if handoff.snapshot_hash != report.target.snapshot_hash:
            raise ValueError(f"handoff snapshot hash mismatch for {purpose}")
        if handoff.environment_closure_hash is None:
            raise ValueError(
                f"handoff for {purpose} has missing environment closure hash"
            )
        if handoff.replay_authorization_hash is None:
            raise ValueError(
                f"handoff for {purpose} has missing replay authorization hash"
            )

    # 8. Shared snapshot check across handoffs
    if decision_handoff.snapshot_hash != audit_handoff.snapshot_hash:
        raise ValueError(
            "decision and audit handoffs do not share identical snapshot hash"
        )
