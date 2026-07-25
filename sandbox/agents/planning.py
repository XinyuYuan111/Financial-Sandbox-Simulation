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
DEMO_ACTIVITY_EMISSION_INTERVAL_US = 5_000_000
DEMO_ACTIVITY_MAX_EMISSIONS = 2
DEMO_COMMUNICATION_INTERVAL_US = 2_000_000
DEMO_COMMUNICATION_MAX_EMISSIONS = 6
# An empty LLM plan is a useful signal that the provider declined to act, not a
# reason for the market to become inert. Keep the sample explicit and bounded.
DEMO_NOOP_FALLBACK_PROBABILITY_MILLI = 750


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
    state: AgentRuntimeState,
) -> tuple[Literal["buy", "sell"] | None, list[str], list[str]]:
    trust_milli = max(0, 1_000 - definition.base_persona.skepticism_milli)
    net_signal = 0
    evidence_ids: list[str] = []
    belief_ids: list[str] = []
    for item in observation.information_items[:8]:
        if item.source_id == definition.agent_id or item.signal_direction in {None, "neutral"}:
            continue
        confidence = item.signal_confidence_milli or 0
        weight = confidence * trust_milli // 1_000
        net_signal += weight if item.signal_direction == "bullish" else -weight
        evidence_ids.append(item.information_id)
    # Beliefs are only used when their supporting memory remains accessible. Do
    # not infer a direction from free-form text; only structured market_signal
    # beliefs can affect the sampled side.
    accessible_memory_ids = {
        entry.memory_id
        for entry in state.memory_entries
        if entry.accessible
    }
    for belief in state.beliefs:
        if belief.predicate != "market_signal" or belief.value not in {"bullish", "bearish"}:
            continue
        if not set(belief.evidence_memory_ids).issubset(accessible_memory_ids):
            continue
        weight = belief.confidence_milli * trust_milli // 1_000
        net_signal += weight if belief.value == "bullish" else -weight
        belief_ids.append(belief.belief_id)
    if abs(net_signal) < 100:
        return None, evidence_ids, belief_ids
    return ("buy" if net_signal > 0 else "sell"), evidence_ids, belief_ids


def _visible_peer_ids(definition: AgentDefinition, observation: ObservationPacket) -> list[str]:
    market = observation.market_view
    candidates = {
        *(order.agent_id for order in [*market.bids, *market.asks]),
        *(trade.buyer_id for trade in market.trades),
        *(trade.seller_id for trade in market.trades),
        *(item.source_id for item in observation.information_items),
    }
    return sorted(
        agent_id
        for agent_id in candidates
        if agent_id != definition.agent_id and not agent_id.startswith("background")
    )


def _communication_directive(
    *,
    definition: AgentDefinition,
    observation: ObservationPacket,
    state: AgentRuntimeState,
    seed: int,
    strategy_revision: int,
    force: bool = False,
    allow_withhold: bool = True,
) -> tuple[CommunicationDirective | None, list[str]]:
    capabilities = set(definition.capability_set)
    if "information.publish" not in capabilities:
        return None, []

    role_tags = set(definition.role_tags)
    persona = definition.base_persona
    family_draw = _draw_milli(seed, DEMO_ACTIVITY_POLICY_ID, definition.agent_id, strategy_revision, "family")
    should_communicate = (
        force
        or "information_participant" in role_tags
        or ("asset_issuer" in role_tags and strategy_revision % 2 == 0)
        or "market.trade" not in capabilities
        or family_draw < min(950, persona.communication_propensity_milli + 250)
    )
    if not should_communicate:
        return None, []

    observed_side, _, _ = _observed_market_signal(definition, observation, state)
    side_draw = _draw_milli(seed, DEMO_ACTIVITY_POLICY_ID, definition.agent_id, strategy_revision, "side")
    message_draw = _draw_milli(seed, DEMO_ACTIVITY_POLICY_ID, definition.agent_id, strategy_revision, "message")
    disclosure_draw = _draw_milli(seed, DEMO_ACTIVITY_POLICY_ID, definition.agent_id, strategy_revision, "disclosure")
    intent_draw = _draw_milli(seed, DEMO_ACTIVITY_POLICY_ID, definition.agent_id, strategy_revision, "intent")
    private_assessment = (
        "bullish" if observed_side == "buy" else
        "bearish" if observed_side == "sell" else
        "bullish" if side_draw < persona.trend_bias_milli else "bearish"
    )
    signal_confidence = 550 + family_draw * 300 // 1_000
    peers = _visible_peer_ids(definition, observation)
    withhold_threshold = max(
        50,
        min(300, (1_000 - persona.communication_propensity_milli) // 4 + persona.skepticism_milli // 8),
    )
    if allow_withhold and disclosure_draw < withhold_threshold:
        return CommunicationDirective(
            directive_key="withhold_market_view",
            channel="PublicFeed",
            communication_mode="withhold",
            private_assessment_direction=private_assessment,
            emission=EmissionPolicy(
                mode="periodic",
                interval_us=DEMO_COMMUNICATION_INTERVAL_US,
                max_emissions=DEMO_COMMUNICATION_MAX_EMISSIONS,
            ),
        ), ["communication_withheld"]

    selective = bool(peers) and disclosure_draw < withhold_threshold + 250
    deceptive = intent_draw < max(75, persona.risk_tolerance_milli // 4)
    signal_direction = (
        "bearish" if private_assessment == "bullish" else "bullish"
    ) if deceptive else private_assessment
    channel: Literal["PublicFeed", "PrivateChannel"] = "PrivateChannel" if selective else "PublicFeed"
    targets = [peers[message_draw * len(peers) // 1_000]] if selective else []
    reference = market_reference(observation)
    messages = {
        "bullish": (
            f"{definition.display_name} 观察到 {reference} 附近的买盘可能增强，短期更偏向上行。",
            f"{definition.display_name} 认为 {reference} 附近的需求正在转强。",
            f"{definition.display_name} 判断当前订单流在 {reference} 附近呈现向上压力。",
        ),
        "bearish": (
            f"{definition.display_name} 观察到 {reference} 附近的卖盘可能增强，短期更偏向下行。",
            f"{definition.display_name} 认为 {reference} 附近的供给正在转强。",
            f"{definition.display_name} 判断当前订单流在 {reference} 附近呈现向下压力。",
        ),
    }[signal_direction]
    directive_key = "host_share_market_view" if force else "share_market_view"
    flags = ["selective_disclosure"] if selective else []
    if deceptive:
        flags.append("strategic_deception")
    return CommunicationDirective(
        directive_key=directive_key,
        channel=channel,
        message_payload=messages[message_draw * len(messages) // 1_000],
        target_ids=targets,
        signal_direction=signal_direction,
        signal_confidence_milli=signal_confidence,
        claim_intent="strategic_deception" if deceptive else "sincere",
        private_assessment_direction=private_assessment,
        emission=EmissionPolicy(
            mode="periodic",
            interval_us=DEMO_COMMUNICATION_INTERVAL_US,
            max_emissions=DEMO_COMMUNICATION_MAX_EMISSIONS,
        ),
    ), flags


def ensure_communication_directive(
    candidate: PlanningResultCandidate,
    *,
    definition: AgentDefinition,
    observation: ObservationPacket,
    state: AgentRuntimeState,
    seed: int,
) -> PlanningResultCandidate:
    """Add the independent communication lane when an active plan omitted it."""
    if (
        not candidate.directives
        or len(candidate.directives) >= 32
        or any(isinstance(directive, CommunicationDirective) for directive in candidate.directives)
    ):
        return candidate
    directive, communication_flags = _communication_directive(
        definition=definition,
        observation=observation,
        state=state,
        seed=seed,
        strategy_revision=candidate.based_on_strategy_revision,
        force=True,
        allow_withhold=False,
    )
    if directive is None:
        return candidate

    used_keys = {item.directive_key for item in candidate.directives}
    if directive.directive_key in used_keys:
        directive = directive.model_copy(update={"directive_key": "host_periodic_market_view"})
    goals = list(candidate.goals)
    if len(goals) < 16 and not any(goal.goal_key == "share_market_information" for goal in goals):
        goals.append(Goal(goal_key="share_market_information", priority=60))
    constraints = [
        constraint.model_copy(update={"amount": constraint.amount + directive.emission.max_emissions})
        if constraint.kind == "allowed_action_count"
        else constraint
        for constraint in candidate.constraints
    ]
    risk_flags = list(dict.fromkeys([
        *candidate.rationale.risk_flags,
        "communication_policy_enriched",
        *communication_flags,
    ]))
    stated_reason = candidate.rationale.stated_reason.rstrip()
    rationale = candidate.rationale.model_copy(update={
        "risk_flags": risk_flags,
        "stated_reason": (
            f"{stated_reason} The host added the Agent's independent, bounded communication policy."
        ).strip(),
    })
    return candidate.model_copy(update={
        "goals": goals,
        "constraints": constraints,
        "directives": [*candidate.directives, directive],
        "rationale": rationale,
    })


def activity_candidate(
    *,
    definition: AgentDefinition,
    observation: ObservationPacket,
    request: PlanningRequest,
    seed: int,
    state: AgentRuntimeState,
    fallback: bool = False,
) -> PlanningResultCandidate:
    capabilities = set(definition.capability_set)
    role_tags = set(definition.role_tags)
    persona = definition.base_persona
    reference = market_reference(observation)
    observed_side, signal_evidence_ids, signal_belief_ids = _observed_market_signal(definition, observation, state)
    buy_quantity, sell_quantity = _available_quantities(
        observation,
        risk_tolerance_milli=persona.risk_tolerance_milli,
    )
    side_draw = _draw_milli(seed, DEMO_ACTIVITY_POLICY_ID, definition.agent_id, request.based_on_strategy_revision, "side")
    directives = []
    goal_keys: list[str] = []
    communication_flags: list[str] = []

    communication, sampled_flags = _communication_directive(
        definition=definition,
        observation=observation,
        state=state,
        seed=seed,
        strategy_revision=request.based_on_strategy_revision,
    )
    if communication is not None:
        directives.append(communication)
        communication_flags.extend(sampled_flags)
        goal_keys.append("share_market_information")
    if "market.quote" in capabilities and "market.trade" in capabilities and buy_quantity and sell_quantity:
        directives.append(QuoteDirective(
            directive_key="maintain_two_sided_liquidity",
            side="both",
            target_spread_bps=max(20, 120 - persona.risk_tolerance_milli // 10),
            max_quantity_per_side=min(buy_quantity, sell_quantity),
            refresh_interval_us=5_000_000,
            emission=EmissionPolicy(
                mode="periodic",
                interval_us=DEMO_ACTIVITY_EMISSION_INTERVAL_US,
                max_emissions=DEMO_ACTIVITY_MAX_EMISSIONS,
            ),
        ))
        goal_keys.append("provide_liquidity")
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
            emission=EmissionPolicy(
                mode="periodic",
                interval_us=DEMO_ACTIVITY_EMISSION_INTERVAL_US,
                max_emissions=DEMO_ACTIVITY_MAX_EMISSIONS,
            ),
        ))
        goal_keys.append("seek_risk_adjusted_return")

    source = "no-op fallback" if fallback else "local rule planner"
    risk_flags = [DEMO_ACTIVITY_POLICY_ID, *communication_flags]
    if fallback:
        risk_flags.extend(["no_op_fallback", "activity_sampled"])
        if observed_side is None and "market.trade" in capabilities:
            risk_flags.append("exploratory_direction_sample")
        elif observed_side is not None:
            risk_flags.append("evidence_directed_action")
    reason = (
        f"The {source} used the saved observation, accessible memory/beliefs, Persona, "
        "capabilities, and free balances."
    )
    if fallback:
        if observed_side is None:
            reason += " No structured directional signal was available; the side is an explicitly bounded exploratory sample."
        else:
            reason += f" A {observed_side} direction was supported by structured observation or belief evidence."
    planned_action_count = sum(
        0 if isinstance(directive, CommunicationDirective) and directive.communication_mode == "withhold"
        else directive.emission.max_emissions * (2 if isinstance(directive, QuoteDirective) and directive.side == "both" else 1)
        for directive in directives
    )
    return PlanningResultCandidate(
        based_on_strategy_revision=request.based_on_strategy_revision,
        valid_for_us=SIMULATION_PLAN_HORIZON_US,
        goals=[Goal(goal_key=goal_key, priority=max(50, 80 - index * 10)) for index, goal_key in enumerate(goal_keys)],
        activation_preconditions=[],
        constraints=[Constraint(kind="allowed_action_count", amount=planned_action_count)] if directives else [],
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
            belief_ids=signal_belief_ids,
            strategy_revision=request.based_on_strategy_revision,
            risk_flags=risk_flags,
            uncertainty_milli=350 if directives else 700,
            stated_reason=reason,
        ),
    )


def sample_noop_fallback(
    *,
    definition: AgentDefinition,
    observation: ObservationPacket,
    request: PlanningRequest,
    seed: int,
    state: AgentRuntimeState,
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
        state=state,
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
            state=state,
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
