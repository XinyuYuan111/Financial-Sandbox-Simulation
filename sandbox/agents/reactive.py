from __future__ import annotations

from dataclasses import dataclass, field

from sandbox.contracts.agent import ActionProposal, AgentDefinition, AgentRuntimeState, DirectiveExecutionCursor
from sandbox.contracts.observation import ObservationPacket
from sandbox.contracts.planning import (
    AllOfCondition,
    AnyOfCondition,
    CancelDirective,
    CommunicationDirective,
    CompareCondition,
    ConditionExpr,
    Directive,
    NotCondition,
    QuoteDirective,
    StrategyPlan,
    TradeDirective,
)
from sandbox.core.ids import deterministic_id


@dataclass(frozen=True, slots=True)
class ReactiveResult:
    action_proposals: list[ActionProposal]
    cursors: dict[str, DirectiveExecutionCursor]
    communication_records: list[dict[str, object]] = field(default_factory=list)


def market_reference(observation: ObservationPacket) -> int:
    if observation.market_view.last_trade is not None:
        return observation.market_view.last_trade.price
    best_bid = observation.market_view.bids[0].price if observation.market_view.bids else None
    best_ask = observation.market_view.asks[0].price if observation.market_view.asks else None
    if best_bid is not None and best_ask is not None:
        return max(1, (best_bid + best_ask) // 2)
    return best_bid or best_ask or 100


def align_price(raw_price: int, price_tick: int, *, round_up: bool) -> int:
    if round_up:
        return max(price_tick, ((raw_price + price_tick - 1) // price_tick) * price_tick)
    return max(price_tick, (raw_price // price_tick) * price_tick)


def _condition_value(path: str, observation: ObservationPacket, state: AgentRuntimeState) -> int | str | bool:
    market = observation.market_view
    account = observation.account_snapshot
    if path == "market.last_price_tick":
        return market_reference(observation)
    if path == "market.spread_bps":
        if not market.bids or not market.asks or market.bids[0].price is None or market.asks[0].price is None:
            return 0
        midpoint = max(1, (market.bids[0].price + market.asks[0].price) // 2)
        return (market.asks[0].price - market.bids[0].price) * 10_000 // midpoint
    if path == "market.recent_volume":
        return sum(trade.quantity for trade in market.trades)
    if path in {"account.free_base", "account.position_base"}:
        if account is None or not account.balances:
            return 0
        first = next(iter(account.balances.values()))
        return first.free if path == "account.free_base" else first.free + first.locked
    if path == "account.free_quote":
        if account is None or not account.balances:
            return 0
        return list(account.balances.values())[-1].free
    if path == "belief.confidence_milli":
        return max((belief.confidence_milli for belief in state.beliefs), default=0)
    if path == "observation.has_information_tag":
        return bool(observation.information_items)
    if path == "own_action_outcome.code":
        return observation.action_receipts[-1].reason_code if observation.action_receipts else "none"
    if path == "sim_time_us":
        return observation.sim_time_us
    raise ValueError(f"unsupported condition path '{path}'")


def evaluate_condition(condition: ConditionExpr, observation: ObservationPacket, state: AgentRuntimeState) -> bool:
    if isinstance(condition, CompareCondition):
        left = _condition_value(condition.path, observation, state)
        right = condition.value
        if condition.op == "contains":
            return str(right) in str(left)
        if type(left) is not type(right) and not (isinstance(left, int) and isinstance(right, int)):
            return condition.op == "neq"
        return {
            "lt": lambda: left < right,
            "lte": lambda: left <= right,
            "eq": lambda: left == right,
            "neq": lambda: left != right,
            "gte": lambda: left >= right,
            "gt": lambda: left > right,
        }[condition.op]()
    if isinstance(condition, AllOfCondition):
        return all(evaluate_condition(item, observation, state) for item in condition.conditions)
    if isinstance(condition, AnyOfCondition):
        return any(evaluate_condition(item, observation, state) for item in condition.conditions)
    if isinstance(condition, NotCondition):
        return not evaluate_condition(condition.condition, observation, state)
    raise ValueError("unknown condition type")


def _eligible(directive: Directive, cursor: DirectiveExecutionCursor, guard: bool, sim_time_us: int) -> bool:
    emission = directive.emission
    if not guard or cursor.emission_count >= emission.max_emissions:
        return False
    if emission.mode == "once":
        return cursor.emission_count == 0
    if emission.mode == "on_guard_transition":
        return cursor.previous_guard is not True
    if emission.mode in {"periodic", "while_guarded"}:
        return cursor.next_eligible_sim_time_us is None or sim_time_us >= cursor.next_eligible_sim_time_us
    return False


def _next_time(directive: Directive, now: int) -> int | None:
    if directive.emission.mode == "periodic":
        assert directive.emission.interval_us is not None
        return now + directive.emission.interval_us
    if directive.emission.mode == "while_guarded":
        assert directive.emission.cooldown_us is not None
        return now + directive.emission.cooldown_us
    return None


class DeclarativeMarketController:
    def react(
        self,
        *,
        definition: AgentDefinition,
        state: AgentRuntimeState,
        observation: ObservationPacket,
        plan: StrategyPlan | None,
    ) -> ReactiveResult:
        if plan is None or not (plan.valid_from_sim_time_us <= observation.sim_time_us < plan.valid_until_sim_time_us):
            return ReactiveResult([], dict(state.directive_cursors))
        proposals: list[ActionProposal] = []
        communication_records: list[dict[str, object]] = []
        cursors = dict(state.directive_cursors)
        for directive in plan.directives:
            cursor_key = f"{plan.strategy_revision}:{directive.directive_key}"
            cursor = cursors.get(cursor_key) or DirectiveExecutionCursor(
                plan_revision=plan.strategy_revision,
                directive_id=directive.directive_key,
            )
            guard = directive.guard is None or evaluate_condition(directive.guard, observation, state)
            emitted_action_ids = list(cursor.action_ids)
            emitted_count = 0
            if _eligible(directive, cursor, guard, observation.sim_time_us):
                generated = self._proposals_for_directive(definition, observation, plan, directive)
                proposals.extend(generated)
                emitted_action_ids.extend(item.proposal_id for item in generated)
                emitted_count = len(generated)
                if isinstance(directive, CommunicationDirective) and directive.communication_mode == "withhold":
                    emitted_count = 1
                    communication_records.append({
                        "directive_key": directive.directive_key,
                        "channel": directive.channel,
                        "communication_mode": directive.communication_mode,
                        "private_assessment_direction": directive.private_assessment_direction,
                        "strategy_revision": plan.strategy_revision,
                    })
            cursors[cursor_key] = cursor.model_copy(update={
                "last_observation_id": observation.observation_id,
                "previous_guard": guard,
                "emission_count": cursor.emission_count + (1 if emitted_count else 0),
                "last_eligible_sim_time_us": observation.sim_time_us if emitted_count else cursor.last_eligible_sim_time_us,
                "next_eligible_sim_time_us": _next_time(directive, observation.sim_time_us) if emitted_count else cursor.next_eligible_sim_time_us,
                "action_ids": emitted_action_ids,
            })
        return ReactiveResult(proposals, cursors, communication_records)

    def _proposals_for_directive(
        self,
        definition: AgentDefinition,
        observation: ObservationPacket,
        plan: StrategyPlan,
        directive: Directive,
    ) -> list[ActionProposal]:
        latency = definition.latency_profile.action_latency_us
        expected = observation.sim_time_us + latency
        common = {
            "expected_execution_time_us": expected,
            "validity_window_us": max(latency + 1_000_000, 1_000_000),
            "required_capabilities": ["market.trade"],
        }
        if isinstance(directive, TradeDirective):
            reference = market_reference(observation)
            tick = observation.market_view.price_tick
            if directive.style == "protected_market":
                raw_worst_price = reference * (10_500 if directive.side == "buy" else 9_500) // 10_000
                payload = {
                    "side": directive.side,
                    "quantity": directive.max_quantity,
                    "worst_price": align_price(raw_worst_price, tick, round_up=directive.side == "buy"),
                }
                action_type = "SubmitProtectedMarketOrder"
            else:
                raw_price = reference * (10_000 + directive.price_offset_bps) // 10_000
                payload = {
                    "side": directive.side,
                    "quantity": directive.max_quantity,
                    "price": align_price(raw_price, tick, round_up=directive.side == "buy"),
                }
                action_type = "SubmitLimitOrder"
            return [ActionProposal(
                proposal_id=deterministic_id("proposal", plan.plan_id, directive.directive_key, observation.observation_id, 0),
                action_type=action_type,
                payload=payload,
                **common,
            )]
        if isinstance(directive, QuoteDirective):
            reference = market_reference(observation)
            tick = observation.market_view.price_tick
            sides = [directive.side] if directive.side != "both" else ["buy", "sell"]
            output: list[ActionProposal] = []
            for index, side in enumerate(sides):
                offset = directive.target_spread_bps // 2
                raw_price = reference * (10_000 - offset if side == "buy" else 10_000 + offset) // 10_000
                price = align_price(raw_price, tick, round_up=side == "sell")
                output.append(ActionProposal(
                    proposal_id=deterministic_id("proposal", plan.plan_id, directive.directive_key, observation.observation_id, index),
                    action_type="SubmitLimitOrder",
                    payload={"side": side, "quantity": directive.max_quantity_per_side, "price": price},
                    **common,
                ))
            return output
        if isinstance(directive, CancelDirective):
            orders = observation.account_snapshot.open_orders if observation.account_snapshot else []
            selected = [order for order in orders if (directive.order_id is None or order.order_id == directive.order_id) and (directive.side is None or order.side == directive.side)]
            return [ActionProposal(
                proposal_id=deterministic_id("proposal", plan.plan_id, directive.directive_key, observation.observation_id, index),
                action_type="CancelOrder",
                payload={"order_id": order.order_id},
                **common,
            ) for index, order in enumerate(selected)]
        if isinstance(directive, CommunicationDirective):
            if directive.communication_mode == "withhold":
                return []
            payload = {
                "channel": directive.channel,
                "content": directive.message_payload,
                "target_ids": directive.target_ids,
                "claim_intent": directive.claim_intent,
                "private_assessment_direction": directive.private_assessment_direction,
            }
            if directive.signal_direction is not None:
                payload["signal_direction"] = directive.signal_direction
                payload["signal_confidence_milli"] = directive.signal_confidence_milli
            if directive.derived_from_info_id is not None:
                payload["derived_from_info_id"] = directive.derived_from_info_id
            return [ActionProposal(
                proposal_id=deterministic_id("proposal", plan.plan_id, directive.directive_key, observation.observation_id, 0),
                action_type="PublishInformation",
                payload=payload,
                expected_execution_time_us=expected,
                validity_window_us=max(latency + 1_000_000, 1_000_000),
                required_capabilities=["information.publish" if directive.channel != "PrivateChannel" else "information.publish"],
            )]
        raise ValueError("unknown directive type")
