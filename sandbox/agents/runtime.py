from __future__ import annotations

from dataclasses import dataclass

from sandbox.agents.planning import PlanningCoordinator
from sandbox.agents.reactive import DeclarativeMarketController, evaluate_condition
from sandbox.contracts.agent import (
    AgentDecision,
    AgentDefinition,
    AgentRuntimeState,
    BeliefProposal,
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
        belief_proposals = []
        information_by_id = {item.information_id: item for item in observation.information_items}
        for memory_proposal in memory_proposals:
            if not memory_proposal.source_ids:
                continue
            source_id = memory_proposal.source_ids[0]
            item = information_by_id.get(source_id)
            if item is None:
                continue
            memory_id = deterministic_id("memory", decision_id, memory_proposal.proposal_id)
            confidence = max(
                50,
                min(
                    950,
                    1_000 - definition.base_persona.skepticism_milli
                    + (150 if item.visibility == "agent_private" else 0),
                ),
            )
            belief_proposals.append(BeliefProposal(
                proposal_id=deterministic_id("proposal", observation.observation_id, "belief", source_id),
                depends_on=[memory_proposal.proposal_id],
                subject=item.source_id,
                predicate="reported_information",
                value=item.rendered_content,
                confidence_milli=confidence,
                evidence_memory_ids=[memory_id],
                stated_reason="Confidence is derived from the Agent's private skepticism and delivery context.",
            ))
        active_plan_is_current = (
            active_plan is not None
            and active_plan.valid_from_sim_time_us <= observation.sim_time_us < active_plan.valid_until_sim_time_us
        )
        replan_due = False
        if active_plan is not None:
            replan_due = not active_plan_is_current or any(
                evaluate_condition(condition, observation, state)
                for condition in active_plan.replan_conditions
            )
        # An expired plan must stop producing directives and reopen the planning
        # gate. Replanning conditions have the same boundary semantics.
        plan_for_controller = activate_plan or (active_plan if active_plan_is_current and not replan_due else None)
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
        proposal_ids.extend(item.proposal_id for item in belief_proposals)
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
            belief_proposals=belief_proposals,
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
        beliefs = list(state.beliefs)
        observed_sources = set(observation.provenance) | {receipt.action_id for receipt in observation.action_receipts}
        accepted_ids: set[str] = set()
        for proposal in decision.memory_proposals:
            if proposal.kind == "write" and proposal.source_ids and set(proposal.source_ids).issubset(observed_sources):
                memory_id = deterministic_id("memory", decision.decision_id, proposal.proposal_id)
                memory_entries.append(MemoryEntryState(
                    memory_id=memory_id,
                    summary=proposal.summary,
                    source_ids=proposal.source_ids,
                    confidence_milli=proposal.confidence_milli,
                    salience=proposal.salience,
                    created_sim_time_us=observation.sim_time_us,
                ))
                accepted_ids.add(proposal.proposal_id)
                results.append(ProposalResult(proposal_id=proposal.proposal_id, accepted=True, reason_code="accepted"))
            elif proposal.kind == "forget" and proposal.memory_id is not None:
                next_entries = [entry for entry in memory_entries if entry.memory_id != proposal.memory_id]
                if len(next_entries) != len(memory_entries):
                    memory_entries = next_entries
                    accepted_ids.add(proposal.proposal_id)
                    results.append(ProposalResult(proposal_id=proposal.proposal_id, accepted=True, reason_code="forgotten"))
                else:
                    results.append(ProposalResult(proposal_id=proposal.proposal_id, accepted=False, reason_code="memory_not_found"))
            else:
                results.append(ProposalResult(proposal_id=proposal.proposal_id, accepted=False, reason_code="invalid_memory_source"))
        memory_capacity = max(1, min(1_000, definition.cognitive_profile.context_capacity // 256))
        if len(memory_entries) > memory_capacity:
            memory_entries = sorted(
                memory_entries,
                key=lambda entry: (-entry.salience, -entry.created_sim_time_us, entry.memory_id),
            )[:memory_capacity]
        if memory_entries != list(state.memory_entries):
            revisions["memory"] += 1

        available_memory_ids = {entry.memory_id for entry in memory_entries}
        for proposal in decision.belief_proposals:
            dependencies_ok = set(proposal.depends_on).issubset(accepted_ids)
            evidence_ok = set(proposal.evidence_memory_ids).issubset(available_memory_ids)
            if not dependencies_ok or not evidence_ok:
                results.append(ProposalResult(proposal_id=proposal.proposal_id, accepted=False, reason_code="invalid_belief_evidence"))
                continue
            belief = BeliefState(
                belief_id=deterministic_id("belief", state.agent_id, proposal.subject, proposal.predicate),
                subject=proposal.subject,
                predicate=proposal.predicate,
                value=proposal.value,
                confidence_milli=proposal.confidence_milli,
                evidence_memory_ids=proposal.evidence_memory_ids,
                updated_sim_time_us=observation.sim_time_us,
                stated_reason=proposal.stated_reason,
            )
            beliefs = [
                existing for existing in beliefs
                if (existing.subject, existing.predicate) != (belief.subject, belief.predicate)
            ]
            beliefs.append(belief)
            accepted_ids.add(proposal.proposal_id)
            results.append(ProposalResult(
                proposal_id=proposal.proposal_id,
                accepted=True,
                reason_code="belief_revised",
                resulting_ref=belief.belief_id,
            ))
        if beliefs != list(state.beliefs):
            revisions["belief"] += 1

        request = None
        planning_request_id = state.planning_request_id
        budget = state.cognitive_budget_state
        budget_changes: list[BudgetChange] = []
        if observation.sim_time_us - budget.window_started_sim_time_us >= definition.cognitive_profile.planning_window_us:
            budget = budget.model_copy(update={
                "window_started_sim_time_us": observation.sim_time_us,
                "plans_remaining": definition.cognitive_profile.max_plans_per_window,
                "plans_reserved": 0,
                "searches_remaining": definition.cognitive_profile.memory_search_limit,
            })
            revisions["budget"] += 1
            budget_changes.append(BudgetChange(
                budget_kind="cognitive",
                operation="reset",
                delta=definition.cognitive_profile.max_plans_per_window,
                remaining=budget.plans_remaining,
                reason_code="planning_window_elapsed",
            ))
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
        attention_budget = state.attention_budget_state
        if observation.sim_time_us - attention_budget.window_started_sim_time_us >= definition.cognitive_profile.planning_window_us:
            attention_budget = attention_budget.model_copy(update={
                "window_started_sim_time_us": observation.sim_time_us,
                "items_remaining": definition.attention_profile.information_capacity,
            })
            revisions["attention"] += 1
            budget_changes.append(BudgetChange(
                budget_kind="attention",
                operation="reset",
                delta=definition.attention_profile.information_capacity,
                remaining=attention_budget.items_remaining,
                reason_code="attention_window_elapsed",
            ))
        viewed_count = len(observation.information_items)
        if viewed_count:
            attention_budget = attention_budget.model_copy(update={
                "items_remaining": max(0, attention_budget.items_remaining - viewed_count),
            })
            revisions["attention"] += 1
            budget_changes.append(BudgetChange(
                budget_kind="attention",
                operation="consume",
                delta=-viewed_count,
                remaining=attention_budget.items_remaining,
                reason_code="information_viewed",
            ))
        next_state = state.model_copy(update={
            "agent_revision": state.agent_revision + 1,
            "component_revisions": revisions,
            "active_plan_id": active_plan_id,
            "active_strategy_revision": active_revision,
            "planning_request_id": planning_request_id,
            "directive_cursors": cursors,
            "cognitive_budget_state": budget,
            "attention_budget_state": attention_budget,
            "memory_entries": memory_entries,
            "beliefs": beliefs,
            "viewed_information_ids": list(dict.fromkeys([
                *state.viewed_information_ids,
                *(item.information_id for item in observation.information_items),
            ]))[-10_000:],
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
