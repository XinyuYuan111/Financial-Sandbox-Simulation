from __future__ import annotations

from dataclasses import dataclass

from sandbox.agents.planning import PlanningCoordinator
from sandbox.agents.reactive import DeclarativeMarketController
from sandbox.contracts.agent import (
    AgentDecision,
    AgentDefinition,
    AgentRuntimeState,
    BeliefState,
    BudgetChange,
    DecisionOutcome,
    DecisionRationale,
    MemoryEntryState,
    MemoryProposal,
    PlanningRequestProposal,
    ProposalResult,
    StrategyPlanProposal,
)
from sandbox.contracts.event import EventDraft
from sandbox.contracts.observation import ObservationPacket
from sandbox.contracts.planning import PlanningRequest, StrategyPlan
from sandbox.core.errors import ValidationError
from sandbox.core.ids import deterministic_id


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    decision: AgentDecision
    outcome: DecisionOutcome
    state: AgentRuntimeState
    planning_request: PlanningRequest | None
    action_proposals: list
    events: list[EventDraft]


class DeterministicSalienceCognition:
    def propose(self, observation: ObservationPacket, state: AgentRuntimeState) -> list[MemoryProposal]:
        known_sources = {source for entry in state.memory_entries for source in entry.source_ids}
        proposals: list[MemoryProposal] = []
        for item in observation.information_items:
            if item.information_id in known_sources:
                continue
            proposals.append(MemoryProposal(
                proposal_id=deterministic_id("proposal", observation.observation_id, "memory", item.information_id),
                kind="write",
                summary=item.rendered_content,
                source_ids=[item.information_id],
                confidence_milli=500,
                salience=60 if item.visibility == "agent_private" else 40,
            ))
        return proposals[:8]


class AgentRuntime:
    def __init__(self) -> None:
        self.cognition = DeterministicSalienceCognition()
        self.controller = DeclarativeMarketController()
        self.planning = PlanningCoordinator()

    def decide(
        self,
        *,
        definition: AgentDefinition,
        state: AgentRuntimeState,
        observation: ObservationPacket,
        active_plan: StrategyPlan | None = None,
        activate_plan: StrategyPlan | None = None,
    ) -> RuntimeResult | None:
        if definition.agent_id != state.agent_id or observation.agent_id != state.agent_id:
            raise ValidationError("Agent Runtime ownership mismatch")
        if observation.observation_id in state.processed_observation_ids:
            return None
        decision_id = deterministic_id(
            "decision", observation.branch_id, state.agent_id, observation.observation_id, state.agent_revision
        )
        memory_proposals = self.cognition.propose(observation, state)
        plan_for_controller = activate_plan or active_plan
        reactive = self.controller.react(
            definition=definition,
            state=state,
            observation=observation,
            plan=plan_for_controller,
        )
        strategy_proposal = None
        if activate_plan is not None:
            strategy_proposal = StrategyPlanProposal(
                proposal_id=deterministic_id("proposal", decision_id, "strategy"),
                planning_request_id=activate_plan.planning_request_id,
                plan_id=activate_plan.plan_id,
            )
            reactive_actions = [
                proposal.model_copy(update={"depends_on": [strategy_proposal.proposal_id]})
                for proposal in reactive.action_proposals
            ]
        else:
            reactive_actions = reactive.action_proposals

        planning_proposal = None
        if plan_for_controller is None and state.planning_request_id is None and state.cognitive_budget_state.plans_remaining > 0:
            planning_proposal = PlanningRequestProposal(
                proposal_id=deterministic_id("proposal", decision_id, "planning"),
                depends_on=[item.proposal_id for item in memory_proposals],
                reason_keys=[trigger.semantic_key for trigger in observation.decision_triggers] or ["no_active_plan"],
                requested_planner_profile_id=definition.planner_profile_id,
            )
        proposal_ids = [item.proposal_id for item in memory_proposals]
        if planning_proposal is not None:
            proposal_ids.append(planning_proposal.proposal_id)
        if strategy_proposal is not None:
            proposal_ids.append(strategy_proposal.proposal_id)
        proposal_ids.extend(item.proposal_id for item in reactive_actions)
        decision = AgentDecision(
            decision_id=decision_id,
            branch_id=observation.branch_id,
            agent_id=state.agent_id,
            observation_id=observation.observation_id,
            sim_time_us=observation.sim_time_us,
            decision_triggers=observation.decision_triggers,
            base_agent_revision=state.agent_revision,
            component_dependencies={
                "memory": state.component_revisions["memory"],
                "belief": state.component_revisions["belief"],
                "strategy": state.component_revisions["strategy"],
                "budget": state.component_revisions["budget"],
            },
            memory_proposals=memory_proposals,
            planning_request_proposal=planning_proposal,
            strategy_plan_proposal=strategy_proposal,
            action_proposals=reactive_actions,
            rationale=DecisionRationale(
                goal_summary=(activate_plan and "Activate a validated plan and interpret its directives") or "Update cognition and request planning",
                evidence_ids=[observation.observation_id, *observation.provenance],
                strategy_revision=state.active_strategy_revision,
                risk_flags=[] if plan_for_controller else ["hold_and_protect"],
                uncertainty_milli=0 if activate_plan else 600,
                proposal_ids=proposal_ids,
                stated_reason="All proposals were produced by the fixed Agent Decision Pipeline.",
            ),
            planning_request_id=activate_plan.planning_request_id if activate_plan else state.planning_request_id,
        )
        return self._commit(definition, state, observation, decision, reactive.cursors, activate_plan)

    def _commit(
        self,
        definition: AgentDefinition,
        state: AgentRuntimeState,
        observation: ObservationPacket,
        decision: AgentDecision,
        cursors: dict,
        activate_plan: StrategyPlan | None,
    ) -> RuntimeResult:
        results: list[ProposalResult] = []
        revisions = dict(state.component_revisions)
        memory_entries = list(state.memory_entries)
        observed_sources = set(observation.provenance) | {receipt.action_id for receipt in observation.action_receipts}
        accepted_ids: set[str] = set()
        for proposal in decision.memory_proposals:
            if proposal.kind == "write" and proposal.source_ids and set(proposal.source_ids).issubset(observed_sources):
                memory_entries.append(MemoryEntryState(
                    memory_id=deterministic_id("memory", decision.decision_id, proposal.proposal_id),
                    summary=proposal.summary,
                    source_ids=proposal.source_ids,
                    confidence_milli=proposal.confidence_milli,
                    salience=proposal.salience,
                    created_sim_time_us=observation.sim_time_us,
                ))
                accepted_ids.add(proposal.proposal_id)
                results.append(ProposalResult(proposal_id=proposal.proposal_id, accepted=True, reason_code="accepted"))
            else:
                results.append(ProposalResult(proposal_id=proposal.proposal_id, accepted=False, reason_code="invalid_memory_source"))
        if memory_entries != list(state.memory_entries):
            revisions["memory"] += 1

        request = None
        planning_request_id = state.planning_request_id
        budget = state.cognitive_budget_state
        budget_changes: list[BudgetChange] = []
        if decision.planning_request_proposal is not None:
            proposal = decision.planning_request_proposal
            dependencies_ok = set(proposal.depends_on).issubset(accepted_ids)
            if dependencies_ok and planning_request_id is None and budget.plans_remaining > 0:
                request = self.planning.create_request(
                    definition=definition,
                    state=state,
                    observation=observation,
                    decision_id=decision.decision_id,
                    reason_keys=proposal.reason_keys,
                )
                planning_request_id = request.request_id
                budget = budget.model_copy(update={
                    "plans_remaining": budget.plans_remaining - 1,
                    "plans_reserved": budget.plans_reserved + 1,
                })
                revisions["planning"] += 1
                revisions["budget"] += 1
                accepted_ids.add(proposal.proposal_id)
                results.append(ProposalResult(proposal_id=proposal.proposal_id, accepted=True, reason_code="queued", resulting_ref=request.request_id))
                budget_changes.append(BudgetChange(budget_kind="cognitive", operation="reserve", delta=-1, remaining=budget.plans_remaining, reason_code="planning_request_queued"))
            else:
                results.append(ProposalResult(proposal_id=proposal.proposal_id, accepted=False, reason_code="planning_request_rejected"))

        active_plan_id = state.active_plan_id
        active_revision = state.active_strategy_revision
        if decision.strategy_plan_proposal is not None:
            proposal = decision.strategy_plan_proposal
            if activate_plan is not None and activate_plan.based_on_strategy_revision == state.active_strategy_revision:
                active_plan_id = activate_plan.plan_id
                active_revision = activate_plan.strategy_revision
                planning_request_id = None
                revisions["strategy"] += 1
                revisions["planning"] += 1
                accepted_ids.add(proposal.proposal_id)
                results.append(ProposalResult(proposal_id=proposal.proposal_id, accepted=True, reason_code="plan_activated", resulting_ref=activate_plan.plan_id))
            else:
                results.append(ProposalResult(proposal_id=proposal.proposal_id, accepted=False, reason_code="stale_strategy_revision"))

        accepted_actions = []
        capabilities = set(definition.capability_set)
        for proposal in decision.action_proposals:
            dependencies_ok = set(proposal.depends_on).issubset(accepted_ids)
            if dependencies_ok and set(proposal.required_capabilities).issubset(capabilities):
                accepted_ids.add(proposal.proposal_id)
                accepted_actions.append(proposal)
                results.append(ProposalResult(proposal_id=proposal.proposal_id, accepted=True, reason_code="world_admission_pending"))
            else:
                results.append(ProposalResult(proposal_id=proposal.proposal_id, accepted=False, reason_code="dependency_or_capability_rejected"))
        if cursors != dict(state.directive_cursors):
            revisions["cursor"] += 1
        next_state = state.model_copy(update={
            "agent_revision": state.agent_revision + 1,
            "component_revisions": revisions,
            "active_plan_id": active_plan_id,
            "active_strategy_revision": active_revision,
            "planning_request_id": planning_request_id,
            "directive_cursors": cursors,
            "cognitive_budget_state": budget,
            "memory_entries": memory_entries,
            "processed_observation_ids": [*state.processed_observation_ids, observation.observation_id],
        })
        outcome = DecisionOutcome(
            decision_id=decision.decision_id,
            accepted=True,
            proposal_results=results,
            resulting_agent_revision=next_state.agent_revision,
            resulting_component_revisions=revisions,
            budget_changes=budget_changes,
            recorded_event_ids=[],
        )
        events = [
            EventDraft(
                sim_time_us=observation.sim_time_us,
                priority=60,
                tie_break_key=f"agent:{definition.agent_id}:{decision.decision_id}:decision",
                event_type="AgentDecisionRecorded",
                source_id=definition.agent_id,
                target_ids=[definition.agent_id],
                payload={"decision_id": decision.decision_id, "observation_id": observation.observation_id, "proposal_count": len(results)},
                observation_id=observation.observation_id,
                visibility="agent_private",
            ),
            EventDraft(
                sim_time_us=observation.sim_time_us,
                priority=61,
                tie_break_key=f"agent:{definition.agent_id}:{decision.decision_id}:outcome",
                event_type="AgentDecisionOutcomeRecorded",
                source_id=definition.agent_id,
                target_ids=[definition.agent_id],
                payload={"decision_id": decision.decision_id, "agent_revision": next_state.agent_revision, "accepted_actions": len(accepted_actions)},
                observation_id=observation.observation_id,
                visibility="agent_private",
            ),
        ]
        if request is not None:
            events.append(EventDraft(
                sim_time_us=observation.sim_time_us,
                priority=62,
                tie_break_key=f"agent:{definition.agent_id}:{request.request_id}:queued",
                event_type="PlanningRequestStateChanged",
                source_id=definition.agent_id,
                target_ids=[definition.agent_id],
                payload={"request_id": request.request_id, "from": None, "to": "Queued", "activation_time_us": request.activation_time_us},
                observation_id=observation.observation_id,
                visibility="agent_private",
            ))
        if activate_plan is not None and active_plan_id == activate_plan.plan_id:
            events.append(EventDraft(
                sim_time_us=observation.sim_time_us,
                priority=62,
                tie_break_key=f"agent:{definition.agent_id}:{activate_plan.plan_id}:activated",
                event_type="StrategyPlanActivated",
                source_id=definition.agent_id,
                target_ids=[definition.agent_id],
                payload={"plan_id": activate_plan.plan_id, "revision": activate_plan.strategy_revision, "request_id": activate_plan.planning_request_id},
                observation_id=observation.observation_id,
                visibility="agent_private",
            ))
        return RuntimeResult(decision, outcome, next_state, request, accepted_actions, events)
