from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sandbox.contracts.agent import AgentDefinition, AgentRuntimeState, DecisionRationale
from sandbox.contracts.observation import ObservationPacket
from sandbox.contracts.planning import (
    CommunicationDirective,
    EmissionPolicy,
    PlanningRequest,
    PlanningResultCandidate,
    StrategyPlan,
    TradeDirective,
)
from sandbox.core.errors import ConflictError, ValidationError
from sandbox.core.ids import deterministic_id
from sandbox.core.time import SIMULATION_PLAN_HORIZON_US
from sandbox.agents.reactive import evaluate_condition


class StrategicPlanner(Protocol):
    async def plan(
        self,
        *,
        definition: AgentDefinition,
        observation: ObservationPacket,
        state: AgentRuntimeState,
        request: PlanningRequest,
    ) -> PlanningResultCandidate: ...


@dataclass(frozen=True, slots=True)
class RulePlanner:
    async def plan(
        self,
        *,
        definition: AgentDefinition,
        observation: ObservationPacket,
        state: AgentRuntimeState,
        request: PlanningRequest,
    ) -> PlanningResultCandidate:
        return PlanningResultCandidate(
            based_on_strategy_revision=state.active_strategy_revision,
            valid_for_us=SIMULATION_PLAN_HORIZON_US,
            goals=[],
            activation_preconditions=[],
            constraints=[],
            directives=[],
            replan_conditions=[],
            rationale=DecisionRationale(
                goal_summary="Preserve capital until a declared fixture or replay directive is available.",
                evidence_ids=[observation.observation_id],
                strategy_revision=state.active_strategy_revision,
                risk_flags=["hold_and_protect"],
                uncertainty_milli=700,
                stated_reason="No deterministic opportunity was configured for this planning request.",
            ),
        )


@dataclass(frozen=True, slots=True)
class ReplayPlanner:
    candidates: dict[str, PlanningResultCandidate]

    async def plan(
        self,
        *,
        definition: AgentDefinition,
        observation: ObservationPacket,
        state: AgentRuntimeState,
        request: PlanningRequest,
    ) -> PlanningResultCandidate:
        candidate = self.candidates.get(request.request_id)
        if candidate is None:
            raise ValidationError(f"no replay candidate for request '{request.request_id}'")
        return candidate


class PlanningCoordinator:
    def create_request(
        self,
        *,
        definition: AgentDefinition,
        state: AgentRuntimeState,
        observation: ObservationPacket,
        decision_id: str,
        reason_keys: list[str],
    ) -> PlanningRequest:
        if state.planning_request_id is not None:
            raise ConflictError("agent already has an open planning request", error_code="PLANNING_REQUEST_ALREADY_OPEN")
        return PlanningRequest(
            request_id=deterministic_id("request", observation.branch_id, definition.agent_id, decision_id),
            branch_id=observation.branch_id,
            agent_id=definition.agent_id,
            source_decision_id=decision_id,
            source_observation_id=observation.observation_id,
            requested_sim_time_us=observation.sim_time_us,
            activation_time_us=observation.sim_time_us + definition.latency_profile.planning_latency_us,
            planner_profile_id=definition.planner_profile_id,
            based_on_strategy_revision=state.active_strategy_revision,
            memory_revision=state.component_revisions.get("memory", 0),
            belief_revision=state.component_revisions.get("belief", 0),
            reason_keys=reason_keys,
        )

    def activate_candidate(
        self,
        *,
        definition: AgentDefinition,
        state: AgentRuntimeState,
        observation: ObservationPacket,
        request: PlanningRequest,
        candidate: PlanningResultCandidate,
    ) -> StrategyPlan:
        if request.agent_id != definition.agent_id or request.branch_id != observation.branch_id:
            raise ValidationError("planning request ownership mismatch")
        if request.state not in {"Ready", "Running"}:
            raise ValidationError("planning request is not ready for activation")
        if candidate.based_on_strategy_revision != state.active_strategy_revision:
            raise ValidationError("candidate is based on a stale strategy revision")
        if any(not evaluate_condition(condition, observation, state) for condition in candidate.activation_preconditions):
            raise ValidationError("candidate activation precondition is not satisfied")
        capabilities = set(definition.capability_set)
        for directive in candidate.directives:
            required = "market.trade"
            if directive.type == "quote":
                required = "market.quote"
            elif directive.type == "communication":
                required = "information.publish"
            if required not in capabilities:
                raise ValidationError(f"directive '{directive.type}' requires capability '{required}'")
        valid_from = max(observation.sim_time_us, request.activation_time_us)
        return StrategyPlan(
            plan_id=deterministic_id("plan", request.branch_id, request.agent_id, request.request_id, state.active_strategy_revision + 1),
            agent_id=request.agent_id,
            strategy_revision=state.active_strategy_revision + 1,
            based_on_strategy_revision=state.active_strategy_revision,
            source_observation_id=observation.observation_id,
            planning_request_id=request.request_id,
            valid_from_sim_time_us=valid_from,
            valid_until_sim_time_us=valid_from + candidate.valid_for_us,
            goals=candidate.goals,
            activation_preconditions=candidate.activation_preconditions,
            constraints=candidate.constraints,
            directives=candidate.directives,
            replan_conditions=candidate.replan_conditions,
        )


def fixture_candidate(
    *,
    action_type: str,
    payload: dict[str, object],
    observation: ObservationPacket,
    strategy_revision: int,
) -> PlanningResultCandidate:
    directives = []
    reference = 100
    if observation.market_view.last_trade is not None:
        reference = observation.market_view.last_trade.price
    elif observation.market_view.bids and observation.market_view.asks:
        bid = observation.market_view.bids[0].price or 1
        ask = observation.market_view.asks[0].price or bid
        reference = max(1, (bid + ask) // 2)
    elif observation.market_view.bids:
        reference = observation.market_view.bids[0].price or 100
    elif observation.market_view.asks:
        reference = observation.market_view.asks[0].price or 100
    if action_type in {"SubmitLimitOrder", "SubmitProtectedMarketOrder"}:
        side = str(payload["side"])
        quantity = int(payload["quantity"])
        if action_type == "SubmitLimitOrder":
            target = int(payload["price"])
            offset = (target * 10_000 + reference - 1) // reference - 10_000
            style = "passive"
        else:
            offset = 0
            style = "protected_market"
        directives.append(TradeDirective(
            directive_key="fixture_action",
            side=side,  # type: ignore[arg-type]
            style=style,  # type: ignore[arg-type]
            max_quantity=quantity,
            price_offset_bps=offset,
            emission=EmissionPolicy(mode="once", max_emissions=1),
        ))
    elif action_type == "PublishInformation":
        directives.append(CommunicationDirective(
            directive_key="fixture_information",
            channel=str(payload.get("channel", "PublicFeed")),  # type: ignore[arg-type]
            message_payload=str(payload.get("content", "")),
            target_ids=list(payload.get("target_ids", [])),
            emission=EmissionPolicy(mode="once", max_emissions=1),
        ))
    else:
        raise ValidationError(f"fixture planner does not support '{action_type}'")
    return PlanningResultCandidate(
        based_on_strategy_revision=strategy_revision,
        valid_for_us=SIMULATION_PLAN_HORIZON_US,
        goals=[],
        activation_preconditions=[],
        constraints=[],
        directives=directives,
        replan_conditions=[],
        rationale=DecisionRationale(
            goal_summary="Execute the deterministic fixture directive through the Agent pipeline.",
            evidence_ids=[observation.observation_id],
            strategy_revision=strategy_revision,
            uncertainty_milli=0,
            stated_reason="Fixture and replay planners provide a saved deterministic directive.",
        ),
    )
