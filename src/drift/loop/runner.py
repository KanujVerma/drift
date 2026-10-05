"""Recursive R&D loop controller and execution runner (M8-3, Issue 235).

Orchestrates iterative research cycles across:
1. Historical memory context synthesis (M7);
2. Conditioned agent proposal generation (M7);
3. Deterministic gatekeeper validation (M7);
4. Simulation evaluation and scorecard calculation (M2/M3/M5);
5. Automated failure diagnosis and postmortem extraction (M6/M8);
6. Immutable M0 ledger sealing and memory refreshment;
7. Hard stop condition enforcement.
"""

from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from drift.agent.context import ResearchContextSynthesizer
from drift.agent.protocol import ResearchAgentProtocol
from drift.agent.validator import ProposalValidator
from drift.domain.common import UTCDateTime
from drift.domain.research_agent import ResearchAgentRole
from drift.domain.research_loop import (
    IterationStatus,
    LoopTerminationReason,
    ResearchIterationRecordV1,
    ResearchLoopConfigV1,
    ResearchLoopSummaryV1,
    build_research_iteration_record,
    build_research_loop_summary,
)
from drift.domain.research_memory import (
    ParameterSearchSpaceV1,
    TrialOutcome,
    build_research_trial_record,
)
from drift.loop.diagnosis import (
    build_automatic_failure_postmortem,
    diagnose_trial_outcome,
)
from drift.loop.evaluator_adapter import TrialEvaluatorProtocol
from drift.memory.archive import ResearchMemoryArchive
from drift.memory.recorder import (
    ResearchMemoryRecorder,
    deterministic_memory_uuid7,
)


class ResearchLoopRunner:
    """Autonomous recursive controller for iterative quantitative R&D."""

    def __init__(
        self,
        *,
        config: ResearchLoopConfigV1,
        synthesizer: ResearchContextSynthesizer,
        agent: ResearchAgentProtocol,
        validator: ProposalValidator,
        evaluator: TrialEvaluatorProtocol,
        recorder: ResearchMemoryRecorder,
        archive: ResearchMemoryArchive,
        search_spaces: Mapping[str, ParameterSearchSpaceV1] | None = None,
    ) -> None:
        self.config = config
        self.synthesizer = synthesizer
        self.agent = agent
        self.validator = validator
        self.evaluator = evaluator
        self.recorder = recorder
        self.archive = archive
        self.search_spaces = dict(search_spaces) if search_spaces else {}

    def run(
        self,
        start_time: UTCDateTime,
    ) -> tuple[ResearchLoopSummaryV1, tuple[ResearchIterationRecordV1, ...]]:
        """Execute recursive R&D cycles up to configured stop conditions."""
        consecutive_failures = 0
        accepted_count = 0
        rejected_count = 0
        validated_count = 0
        falsified_count = 0
        best_trial_id: UUID | None = None
        best_sharpe: Decimal | None = None
        iterations: list[ResearchIterationRecordV1] = []
        termination_reason = LoopTerminationReason.MAX_ITERATIONS_REACHED

        last_time = start_time

        for iter_idx in range(self.config.max_iterations):
            # Check consecutive failure circuit breaker
            if consecutive_failures >= self.config.max_consecutive_failures:
                termination_reason = LoopTerminationReason.MAX_CONSECUTIVE_FAILURES
                break

            step_time = start_time + timedelta(seconds=iter_idx * 60)
            completed_time = step_time + timedelta(seconds=30)
            last_time = completed_time

            # 1. Synthesize current context packet from research memory
            packet = self.synthesizer.synthesize_packet(
                agent_role=ResearchAgentRole.ALPHA_RESEARCHER,
                as_of_time=step_time,
                available_strategy_types=(self.config.target_strategy_type,),
            )

            # 2. Agent proposes hypothesis and experiment specification
            space = self.search_spaces.get(self.config.target_strategy_type)
            hyp_prop, exp_prop = self.agent.generate_proposal(
                context=packet,
                target_strategy_type=self.config.target_strategy_type,
                search_space=space,
            )

            # 3. Deterministic gatekeeper validation
            val_res = self.validator.validate_proposal(
                hypothesis=hyp_prop,
                experiment=exp_prop,
                as_of_time=step_time,
            )

            if not val_res.is_accepted:
                rejected_count += 1
                consecutive_failures += 1

                iter_rec = build_research_iteration_record(
                    iteration_id=deterministic_memory_uuid7(
                        f"iter:{self.config.loop_id}:{iter_idx}"
                    ),
                    loop_id=self.config.loop_id,
                    iteration_index=iter_idx,
                    status=IterationStatus.PROPOSAL_REJECTED,
                    validation_status=val_res.status,
                    hypothesis_proposal_id=hyp_prop.proposal_id,
                    experiment_proposal_id=exp_prop.experiment_proposal_id,
                    rejection_reasons=val_res.rejection_reasons,
                    started_at=step_time,
                    completed_at=completed_time,
                )
                iterations.append(iter_rec)
                continue

            accepted_count += 1

            # 4. Simulation evaluation
            metrics = self.evaluator.evaluate_experiment(exp_prop)

            # 5. Outcome diagnosis and root-cause analysis
            diag = diagnose_trial_outcome(
                hypothesis=hyp_prop,
                experiment=exp_prop,
                metrics=metrics,
            )

            trial_id = deterministic_memory_uuid7(
                f"trial:{self.config.loop_id}:{iter_idx}"
            )
            run_id = deterministic_memory_uuid7(f"run:{self.config.loop_id}:{iter_idx}")

            postmortem_id: UUID | None = None
            if diag.outcome == TrialOutcome.FAILED:
                falsified_count += 1
                consecutive_failures += 1

                pm = build_automatic_failure_postmortem(
                    diagnosis=diag,
                    experiment_id=exp_prop.experiment_proposal_id,
                    run_id=run_id,
                    trial_id=trial_id,
                    falsified_hypothesis_id=hyp_prop.proposal_id,
                    created_at=step_time,
                )
                self.recorder.record_postmortem(pm)
                postmortem_id = pm.postmortem_id
            else:
                validated_count += 1
                consecutive_failures = 0

                raw_s = metrics.get("annualized_sharpe", Decimal("0"))
                sharpe_val = Decimal(str(raw_s))
                if best_sharpe is None or sharpe_val > best_sharpe:
                    best_sharpe = sharpe_val
                    best_trial_id = trial_id

            # 6. Seal trial into M0 research memory ledger
            trial = build_research_trial_record(
                trial_id=trial_id,
                hypothesis_id=hyp_prop.proposal_id,
                experiment_id=exp_prop.experiment_proposal_id,
                run_id=run_id,
                strategy_type=self.config.target_strategy_type,
                parameters=(
                    dict(exp_prop.proposed_parameters)
                    if isinstance(exp_prop.proposed_parameters, Mapping)
                    else {}
                ),
                headline_metrics=dict(metrics),
                trial_outcome=diag.outcome,
                postmortem_id=postmortem_id,
                created_at=step_time,
            )
            self.recorder.record_trial(trial)
            self.archive.refresh()

            # 7. Record completed iteration
            iter_rec = build_research_iteration_record(
                iteration_id=deterministic_memory_uuid7(
                    f"iter:{self.config.loop_id}:{iter_idx}"
                ),
                loop_id=self.config.loop_id,
                iteration_index=iter_idx,
                status=IterationStatus.EVALUATION_COMPLETED,
                validation_status=val_res.status,
                hypothesis_proposal_id=hyp_prop.proposal_id,
                experiment_proposal_id=exp_prop.experiment_proposal_id,
                trial_outcome=diag.outcome,
                annualized_sharpe=Decimal(str(metrics.get("annualized_sharpe", "0"))),
                max_drawdown=Decimal(str(metrics.get("max_drawdown", "0"))),
                annualized_turnover=Decimal(
                    str(metrics.get("annualized_turnover", "0"))
                ),
                failure_category=diag.failure_category,
                postmortem_id=postmortem_id,
                started_at=step_time,
                completed_at=completed_time,
            )
            iterations.append(iter_rec)

            # 8. Check target performance achievement
            if (
                self.config.stop_on_target_met
                and self.config.target_annualized_sharpe is not None
                and best_sharpe is not None
                and best_sharpe >= self.config.target_annualized_sharpe
            ):
                termination_reason = LoopTerminationReason.TARGET_PERFORMANCE_MET
                break

        summary = build_research_loop_summary(
            loop_id=self.config.loop_id,
            config_hash=self.config.config_hash,
            termination_reason=termination_reason,
            total_iterations=accepted_count + rejected_count,
            accepted_proposals=accepted_count,
            rejected_proposals=rejected_count,
            validated_trials=validated_count,
            falsified_trials=falsified_count,
            started_at=start_time,
            completed_at=last_time,
            best_trial_id=best_trial_id,
            best_annualized_sharpe=best_sharpe,
            final_exhaustion_fraction=Decimal("0.0"),
        )

        return summary, tuple(iterations)
