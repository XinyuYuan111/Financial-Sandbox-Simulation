from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from sandbox.agents.entities import AgentState
from sandbox.agents.observation import ObservationService
from sandbox.contracts.action import ActionContract
from sandbox.contracts.event import EventDraft
from sandbox.contracts.observation import ObservationPacket
from sandbox.contracts.scenario import ResolvedInitialState
from sandbox.core.errors import ValidationError
from sandbox.core.ids import new_id
from sandbox.core.numeric import require_int
from sandbox.core.rng import NamedRandomStreams
from sandbox.world.information import publish_information
from sandbox.world.ledger import Ledger
from sandbox.world.market.clob import CLOB


@dataclass(slots=True)
class ActionResult:
    world: "SimulationWorld"
    events: list[EventDraft]
    observations: list[ObservationPacket]


class SimulationWorld:
    def __init__(self) -> None:
        self.sim_time_us = 0
        self.market: dict[str, Any] = {}
        self.agents: dict[str, AgentState] = {}
        self.ledger = Ledger()
        self.clob = CLOB()
        self.information_items: list[dict[str, object]] = []
        self.chain_snapshot: dict[str, object] = {}
        self.rng = NamedRandomStreams(0)
        self.fixture_step = 0
        self.latest_observation_ids: dict[str, str] = {}

    @classmethod
    def from_resolved(cls, resolved: ResolvedInitialState) -> "SimulationWorld":
        world = cls()
        world.market = resolved.market.model_dump(mode="json")
        world.chain_snapshot = deepcopy(resolved.chain_snapshot)
        world.rng = NamedRandomStreams(resolved.seed)
        for config in resolved.agents:
            world.agents[config.agent_id] = AgentState(
                agent_id=config.agent_id,
                display_name=config.display_name,
                strategy=config.strategy,
                role_tags=config.role_tags,
                funding_profile=config.funding_profile,
                capabilities=config.capabilities,
            )
            world.ledger.credit(config.agent_id, resolved.market.base_asset, config.token_balance, reason="initial_mint")
            world.ledger.credit(config.agent_id, resolved.market.quote_asset, config.usdx_balance, reason="initial_mint")
        token_remainder = resolved.total_supply[resolved.market.base_asset] - world.ledger.total(resolved.market.base_asset)
        usdx_remainder = resolved.total_supply[resolved.market.quote_asset] - world.ledger.total(resolved.market.quote_asset)
        world.ledger.credit("inactive_reserve", resolved.market.base_asset, token_remainder, reason="initial_mint")
        world.ledger.credit("inactive_reserve", resolved.market.quote_asset, usdx_remainder, reason="initial_mint")
        world.ledger.credit("fee_account", resolved.market.base_asset, 0, reason="account_opened")
        world.ledger.credit("fee_account", resolved.market.quote_asset, 0, reason="account_opened")
        return world

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "SimulationWorld":
        world = cls()
        world.sim_time_us = int(value["sim_time_us"])
        world.market = deepcopy(value["market"])
        world.agents = {item["agent_id"]: AgentState.model_validate(item) for item in value["agents"]}
        world.ledger = Ledger(value["ledger"]["balances"])
        world.ledger.postings = deepcopy(value["ledger"].get("postings", []))
        world.clob = CLOB(value["clob"]["orders"], value["clob"]["trades"])
        world.clob.sequence = int(value["clob"].get("sequence", world.clob.sequence))
        world.information_items = deepcopy(value.get("information_items", []))
        world.chain_snapshot = deepcopy(value.get("chain_snapshot", {}))
        world.rng = NamedRandomStreams(int(value["root_seed"]), deepcopy(value.get("rng_streams", {})))
        world.fixture_step = int(value.get("fixture_step", 0))
        world.latest_observation_ids = deepcopy(value.get("latest_observation_ids", {}))
        return world

    def clone(self) -> "SimulationWorld":
        return self.from_json(self.to_json())

    def apply_action(self, action: ActionContract, *, world_version: int) -> ActionResult:
        world = self.clone()
        if action.branch_id == "":
            raise ValidationError("branch_id is required")
        agent = world.agents.get(action.agent_id)
        if agent is None:
            raise ValidationError("unknown agent")
        if action.expected_execution_time_us > action.submitted_sim_time_us + action.validity_window_us:
            raise ValidationError("action expires before its expected execution time")
        world.sim_time_us = max(world.sim_time_us, action.expected_execution_time_us)
        accepted = world._event(action, "ActionAccepted", {"action_type": action.action_type}, priority=70, visibility="participants")
        events = [accepted.model_copy(update={"sim_time_us": action.submitted_sim_time_us})]
        token_before = world.ledger.total(world.market["base_asset"])
        quote_before = world.ledger.total(world.market["quote_asset"])
        if action.action_type in {"SubmitLimitOrder", "SubmitProtectedMarketOrder", "CancelOrder", "ReplaceOrder"}:
            if "market.trade" not in agent.capabilities:
                raise ValidationError("agent does not have market.trade capability")
            events.extend(world._apply_market_action(action))
        elif action.action_type == "PublishInformation":
            if "information.publish" not in agent.capabilities:
                raise ValidationError("agent does not have information.publish capability")
            events.extend(world._apply_information_action(action))
        if world.ledger.total(world.market["base_asset"]) != token_before or world.ledger.total(world.market["quote_asset"]) != quote_before:
            raise ValidationError("asset conservation invariant failed")
        observations = world.create_observations(action.branch_id, world_version + len(events))
        events.extend(
            world._event(action, "ObservationCreated", {"agent_id": observation.agent_id, "observation_id": observation.observation_id}, priority=50, visibility="agent_private", observation_id=observation.observation_id)
            for observation in observations
        )
        if action.action_type == "PublishInformation":
            information_id = str(world.information_items[-1]["information_id"])
            events.extend(
                world._event(action, "InformationViewed", {"information_id": information_id, "agent_id": observation.agent_id}, priority=55, visibility="agent_private", observation_id=observation.observation_id)
                for observation in observations
            )
        return ActionResult(world, events, observations)

    def rejection_event(self, action: ActionContract, message: str) -> EventDraft:
        return self._event(action, "ActionRejected", {"action_type": action.action_type, "reason": message}, priority=70, visibility="participants")

    def _apply_market_action(self, action: ActionContract) -> list[EventDraft]:
        payload = action.payload
        if action.action_type == "CancelOrder":
            order_id = str(payload.get("order_id", ""))
            order = self.clob.cancel(order_id, action.agent_id, self.ledger, base_asset=self.market["base_asset"], quote_asset=self.market["quote_asset"])
            return [self._event(action, "OrderCancelled", {"order_id": order.order_id, "remaining": order.remaining}, priority=20, phase="00-cancel")]
        replaced_order_id: str | None = None
        if action.action_type == "ReplaceOrder":
            replaced_order_id = str(payload.get("order_id", ""))
            previous = self.clob.orders.get(replaced_order_id)
            if previous is None or previous.agent_id != action.agent_id:
                raise ValidationError("order is not owned by agent")
            side = previous.side
            default_quantity = previous.remaining
            self.clob.cancel(replaced_order_id, action.agent_id, self.ledger, base_asset=self.market["base_asset"], quote_asset=self.market["quote_asset"])
            payload = {**payload, "side": side, "quantity": payload.get("quantity", default_quantity)}
        side = payload.get("side")
        if side not in {"buy", "sell"}:
            raise ValidationError("order side must be buy or sell")
        quantity = require_int(payload.get("quantity"), "payload.quantity", minimum=1)
        if action.action_type in {"SubmitLimitOrder", "ReplaceOrder"}:
            price = require_int(payload.get("price"), "payload.price", minimum=1)
            order_type: Literal["limit", "protected_market"] = "limit"
            worst_price = None
        else:
            price = None
            worst_price = require_int(payload.get("worst_price"), "payload.worst_price", minimum=1)
            order_type = "protected_market"
        order, trades = self.clob.submit(
            agent_id=action.agent_id,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=price,
            worst_price=worst_price,
            ledger=self.ledger,
            maker_fee_bps=self.market["maker_fee_bps"],
            taker_fee_bps=self.market["taker_fee_bps"],
            base_asset=self.market["base_asset"],
            quote_asset=self.market["quote_asset"],
        )
        submitted_type = "OrderReplaced" if replaced_order_id else "OrderSubmitted"
        order_payload: dict[str, object] = {"order_id": order.order_id, "agent_id": order.agent_id, "side": order.side, "order_type": order.order_type, "price": order.price, "quantity": order.quantity, "remaining": order.remaining, "status": order.status}
        if replaced_order_id:
            order_payload["replaced_order_id"] = replaced_order_id
        events = [self._event(action, submitted_type, order_payload, priority=20, phase="00-order")]
        for trade in trades:
            payload_trade = {"trade_id": trade.trade_id, "buy_order_id": trade.buy_order_id, "sell_order_id": trade.sell_order_id, "buyer_id": trade.buyer_id, "seller_id": trade.seller_id, "quantity": trade.quantity, "price": trade.price}
            events.append(self._event(action, "TradeMatched", payload_trade, priority=20, phase=f"01-match:{trade.trade_id}"))
            events.append(self._event(action, "TradeSettled", {**payload_trade, "buyer_fee": trade.buyer_fee, "seller_fee": trade.seller_fee}, priority=20, phase=f"02-settle:{trade.trade_id}"))
            events.append(self._event(action, "FeeCharged", {"trade_id": trade.trade_id, "buyer_fee": trade.buyer_fee, "seller_fee": trade.seller_fee, "asset": self.market["quote_asset"]}, priority=20, visibility="analyst_only", phase=f"03-fee:{trade.trade_id}"))
        return events

    def _apply_information_action(self, action: ActionContract) -> list[EventDraft]:
        item = publish_information(
            source_id=action.agent_id,
            channel=str(action.payload.get("channel", "PublicFeed")),
            content=str(action.payload.get("content", "")),
            sim_time_us=self.sim_time_us,
            target_ids=list(action.payload.get("target_ids", [])),
        )
        self.information_items.append(item)
        events = [self._event(action, "InformationPublished", item, priority=40, visibility="agent_private" if item["visibility"] == "agent_private" else "public", phase="00-published")]
        recipients = list(item["target_ids"]) if item["visibility"] == "agent_private" else sorted(self.agents)
        for target in recipients:
            delivery_type = "PrivateMessageDelivered" if item["visibility"] == "agent_private" else "InformationDelivered"
            events.append(self._event(action, delivery_type, {"information_id": item["information_id"], "target_id": target}, priority=40, visibility="agent_private" if item["visibility"] == "agent_private" else "participants", phase=f"01-delivered:{target}"))
        return events

    def _event(self, action: ActionContract, event_type: str, payload: dict[str, object], *, priority: int, visibility: str = "public", observation_id: str | None = None, phase: str | None = None) -> EventDraft:
        return EventDraft(
            sim_time_us=self.sim_time_us,
            priority=priority,
            tie_break_key=f"{action.agent_id}:{action.action_id}:{phase or event_type}",
            event_type=event_type,
            source_id=action.agent_id,
            target_ids=[action.agent_id],
            payload=payload,
            observation_id=observation_id,
            action_id=action.action_id,
            correlation_id=action.client_command_id,
            visibility=visibility,
        )

    def create_observations(self, branch_id: str, world_version: int) -> list[ObservationPacket]:
        service = ObservationService()
        observations = [service.build(self, agent_id, branch_id, world_version) for agent_id in sorted(self.agents)]
        self.latest_observation_ids.update({item.agent_id: item.observation_id for item in observations})
        return observations

    def portfolio_projection(self, agent_id: str) -> dict[str, object]:
        balances = self.ledger.to_json()["balances"].get(agent_id, {})
        open_orders = [order for order in self.clob.to_json()["orders"] if order["agent_id"] == agent_id and order["status"] in {"open", "partially_filled"}]
        return {"agent_id": agent_id, "balances": balances, "open_orders": open_orders}

    def market_projection(self) -> dict[str, object]:
        orders = self.clob.to_json()["orders"]
        bids = sorted([item for item in orders if item["side"] == "buy" and item["status"] in {"open", "partially_filled"}], key=lambda item: (-int(item["price"] or 0), int(item["submitted_seq"])))
        asks = sorted([item for item in orders if item["side"] == "sell" and item["status"] in {"open", "partially_filled"}], key=lambda item: (int(item["price"] or 0), int(item["submitted_seq"])))
        last_trade = self.clob.to_json()["trades"][-1] if self.clob.trades else None
        return {"market_id": self.market["market_id"], "bids": bids[:20], "asks": asks[:20], "last_trade": last_trade, "trades": self.clob.to_json()["trades"][-100:]}

    def projection(self, branch_id: str, state_version: int, status: str) -> dict[str, object]:
        return {
            "branch_id": branch_id,
            "cursor": state_version,
            "status": status,
            "sim_time_us": self.sim_time_us,
            "market": self.market_projection(),
            "agents": [{"agent_id": agent.agent_id, "display_name": agent.display_name, "strategy": agent.strategy, "role_tags": agent.role_tags, "portfolio": self.portfolio_projection(agent.agent_id)} for agent in self.agents.values()],
            "information": self.information_items[-100:],
            "fixture_step": self.fixture_step,
        }

    def to_json(self) -> dict[str, object]:
        return {
            "sim_time_us": self.sim_time_us,
            "market": deepcopy(self.market),
            "agents": [agent.model_dump(mode="json") for agent in self.agents.values()],
            "ledger": self.ledger.to_json(),
            "clob": self.clob.to_json(),
            "information_items": deepcopy(self.information_items),
            "chain_snapshot": deepcopy(self.chain_snapshot),
            "root_seed": self.rng.root_seed,
            "rng_streams": self.rng.snapshot(),
            "fixture_step": self.fixture_step,
            "latest_observation_ids": deepcopy(self.latest_observation_ids),
        }
