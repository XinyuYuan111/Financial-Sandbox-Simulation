from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from sandbox.contracts.agent import AgentDefinition, AgentRuntimeState, DecisionRationale
from sandbox.contracts.observation import ObservationPacket
from sandbox.contracts.planning import (
    CommunicationDirective,
    CompareCondition,
    Constraint,
    EmissionPolicy,
    Goal,
    PlanningRequest,
    PlanningResultCandidate,
    QuoteDirective,
    StrategyPlan,
    TradeDirective,
)
from sandbox.core.rng import NamedRandomStreams
from sandbox.core.errors import ConflictError, ValidationError
from sandbox.core.ids import deterministic_id
from sandbox.core.time import SIMULATION_PLAN_HORIZON_US
from sandbox.agents.reactive import align_price, evaluate_condition, market_reference


DEMO_ACTIVITY_POLICY_ID = "demo-agent-activity.v0.1"
DEMO_NOOP_FALLBACK_PROBABILITY_MILLI = 500


def _draw_milli(seed: int, namespace: str, *parts: object) -> int:
    streams = NamedRandomStreams(seed)
    value, _ = streams.random(":".join([namespace, *(str(part) for part in parts)]))
    return min(999, int(value * 1_000))


def _available_quantities(
    observation: ObservationPacket,
    *,
    risk_tolerance_milli: int,
) -> tuple[int, int]:
    account = observation.account_snapshot
    if account is None:
        return 0, 0
    market = observation.market_view
    base = account.balances.get(market.base_asset)
    quote = account.balances.get(market.quote_asset)
    reference = market_reference(observation)
    tick = market.price_tick
    worst_buy = align_price(reference * 10_500 // 10_000, tick, round_up=True)
    # A 10% reserve buffer covers the contract's maximum configured taker fee.
    buy_capacity = 0 if quote is None else quote.free * 10_000 // max(1, worst_buy * 11_000)
    sell_capacity = 0 if base is None else base.free
    participation_milli = max(25, min(200, risk_tolerance_milli // 5))
    buy_quantity = buy_capacity * participation_milli // 1_000
    sell_quantity = sell_capacity * participation_milli // 1_000
    return (
        max(1, buy_quantity) if buy_capacity > 0 else 0,
        max(1, sell_quantity) if sell_capacity > 0 else 0,
    )


def _observed_market_signal(
    definition: AgentDefinition,
    observation: ObservationPacket,
) -> tuple[Literal["buy", "sell"] | None, list[str]]:
    trust_milli = max(0, 1_000 - definition.base_persona.skepticism_milli)
    net_signal = 0
    evidence_ids: list[str] = []
    for item in observation.information_items[:8]:
        if item.source_id == definition.agent_id or item.signal_direction in {None, "neutral"}:
            continue
        confidence = item.signal_confidence_milli or 0
        weight = confidence * trust_milli // 1_000
        net_signal += weight if item.signal_direction == "bullish" else -weight
        evidence_ids.append(item.information_id)
    if abs(net_signal) < 100:
        return None, evidence_ids
    return ("buy" if net_signal > 0 else "sell"), evidence_ids


def activity_candidate(
    *,
    definition: AgentDefinition,
    observation: ObservationPacket,
    request: PlanningRequest,
    seed: int,
    fallback: bool = False,
) -> PlanningResultCandidate:
    capabilities = set(definition.capability_set)
    role_tags = set(definition.role_tags)
    persona = definition.base_persona
    reference = market_reference(observation)
    observed_side, signal_evidence_ids = _observed_market_signal(definition, observation)
    buy_quantity, sell_quantity = _available_quantities(
        observation,
        risk_tolerance_milli=persona.risk_tolerance_milli,
    )
    family_draw = _draw_milli(seed, DEMO_ACTIVITY_POLICY_ID, definition.agent_id, request.based_on_strategy_revision, "family")
    side_draw = _draw_milli(seed, DEMO_ACTIVITY_POLICY_ID, definition.agent_id, request.based_on_strategy_revision, "side")
    message_draw = _draw_milli(seed, DEMO_ACTIVITY_POLICY_ID, definition.agent_id, request.based_on_strategy_revision, "message")
    directives = []
    goal_key = "preserve_capital"

    is_information_role = "information_participant" in role_tags
    is_issuer = "asset_issuer" in role_tags
    should_communicate = (
        "information.publish" in capabilities
        and (
            is_information_role
            or (is_issuer and request.based_on_strategy_revision % 2 == 0)
            or ("market.trade" not in capabilities)
            or family_draw < persona.communication_propensity_milli
        )
    )
    if should_communicate:
        signal_direction = "bullish" if side_draw < 500 else "bearish"
        signal_confidence = 550 + family_draw * 300 // 1_000
        messages = {
            "bullish": (
                f"{definition.display_name} market view: buying pressure may strengthen near {reference}.",
                f"{definition.display_name} order-flow note: demand appears firmer around {reference}.",
                f"{definition.display_name} participant opinion: upside pressure is building near {reference}.",
            ),
            "bearish": (
                f"{definition.display_name} market view: selling pressure may strengthen near {reference}.",
                f"{definition.display_name} order-flow note: supply appears heavier around {reference}.",
                f"{definition.display_name} participant opinion: downside pressure is building near {reference}.",
            ),
        }[signal_direction]
        directives.append(CommunicationDirective(
            directive_key="publish_market_view",
            channel="PublicFeed",
            message_payload=messages[message_draw * len(messages) // 1_000],
            signal_direction=signal_direction,
            signal_confidence_milli=signal_confidence,
            emission=EmissionPolicy(mode="once", max_emissions=1),
        ))
        goal_key = "share_market_information"
    elif "market.quote" in capabilities and "market.trade" in capabilities and buy_quantity and sell_quantity:
        directives.append(QuoteDirective(
            directive_key="maintain_two_sided_liquidity",
            side="both",
            target_spread_bps=max(20, 120 - persona.risk_tolerance_milli // 10),
            max_quantity_per_side=min(buy_quantity, sell_quantity),
            refresh_interval_us=5_000_000,
            emission=EmissionPolicy(mode="once", max_emissions=1),
        ))
        goal_key = "provide_liquidity"
    elif "market.trade" in capabilities and (buy_quantity or sell_quantity):
        side = observed_side or ("buy" if side_draw < persona.trend_bias_milli else "sell")
        if side == "buy" and not buy_quantity:
            side = "sell"
        elif side == "sell" and not sell_quantity:
            side = "buy"
        quantity = buy_quantity if side == "buy" else sell_quantity
        protected = (
            "capital_holder" in role_tags
            or (
                persona.risk_tolerance_milli >= 650
                and request.based_on_strategy_revision % 2 == 1
            )
        )
        directives.append(TradeDirective(
            directive_key="participate_in_market",
            side=side,
            style="protected_market" if protected else "passive",
            max_quantity=quantity,
            price_offset_bps=0 if protected else (-20 if side == "buy" else 20),
            emission=EmissionPolicy(mode="once", max_emissions=1),
        ))
        goal_key = "seek_risk_adjusted_return"
    elif "information.publish" in capabilities:
        directives.append(CommunicationDirective(
            directive_key="publish_market_view",
            channel="PublicFeed",
            message_payload=f"{definition.display_name} market view: monitoring visible liquidity around {reference}.",
            emission=EmissionPolicy(mode="once", max_emissions=1),
        ))
        goal_key = "share_market_information"

    source = "no-op fallback" if fallback else "local rule planner"
    risk_flags = [DEMO_ACTIVITY_POLICY_ID]
    if fallback:
        risk_flags.append("no_op_fallback")
    return PlanningResultCandidate(
        based_on_strategy_revision=request.based_on_strategy_revision,
        valid_for_us=SIMULATION_PLAN_HORIZON_US,
        goals=[Goal(goal_key=goal_key, priority=80)] if directives else [],
        activation_preconditions=[],
        constraints=[Constraint(kind="allowed_action_count", amount=2)] if directives else [],
        directives=directives,
        replan_conditions=(
            [CompareCondition(path="observation.has_information_tag", op="eq", value=True)]
            if "market.trade" in capabilities
            else []
        ),
        rationale=DecisionRationale(
            goal_summary=(
                "Participate through a bounded, capability-safe demo directive."
                if directives
                else "Preserve capital because no capability-safe demo directive is available."
            ),
            evidence_ids=[observation.observation_id, *signal_evidence_ids],
            strategy_revision=request.based_on_strategy_revision,
            risk_flags=risk_flags,
            uncertainty_milli=350 if directives else 700,
            stated_reason=f"The {source} used the saved observation, Persona, capabilities, and free balances.",
        ),
    )


def sample_noop_fallback(
    *,
    definition: AgentDefinition,
    observation: ObservationPacket,
    request: PlanningRequest,
    seed: int,
    force: bool = False,
) -> tuple[PlanningResultCandidate | None, int]:
    sample_milli = _draw_milli(
        seed,
        f"{DEMO_ACTIVITY_POLICY_ID}.no-op-fallback",
        definition.agent_id,
        request.based_on_strategy_revision,
    )
    if not force and sample_milli >= DEMO_NOOP_FALLBACK_PROBABILITY_MILLI:
        return None, sample_milli
    candidate = activity_candidate(
        definition=definition,
        observation=observation,
        request=request,
        seed=seed,
        fallback=True,
    )
    return (candidate if candidate.directives else None), sample_milli


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
    seed: int = 0

    async def plan(
        self,
        *,
        definition: AgentDefinition,
        observation: ObservationPacket,
        state: AgentRuntimeState,
        request: PlanningRequest,
    ) -> PlanningResultCandidate:
        return activity_candidate(
            definition=definition,
            observation=observation,
            request=request,
            seed=self.seed,
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
    reference = market_reference(observation)
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
