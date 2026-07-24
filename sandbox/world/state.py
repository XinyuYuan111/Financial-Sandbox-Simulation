from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from sandbox.agents.entities import AgentState
from sandbox.agents.observation import ObservationService
from sandbox.contracts.agent import ActionReceipt, AgentDefinition, AgentRuntimeState, DecisionTrigger
from sandbox.contracts.action import ActionContract
from sandbox.contracts.event import EventDraft
from sandbox.contracts.intervention import (
    CreateRelationshipEffect,
    CreateWorldEntityEffect,
    InterventionStage,
    PublishInformationEffect,
    SetAccountFreezeEffect,
    SetMarketStatusEffect,
    SetWalletAccessEffect,
    TransferAssetEffect,
)
from sandbox.contracts.observation import ObservationPacket
from sandbox.contracts.planning import PlanningRequest, StrategyPlan
from sandbox.contracts.scenario import ResolvedInitialState
from sandbox.core.errors import MissingCausalStateError, ValidationError
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
    receipts: list[ActionReceipt]


@dataclass(slots=True)
class InterventionResult:
    world: "SimulationWorld"
    events: list[EventDraft]
    observations: list[ObservationPacket]


class SimulationWorld:
    def __init__(self) -> None:
        self.sim_time_us = 0
        self.market: dict[str, Any] = {}
        self.agents: dict[str, AgentState] = {}
        self.agent_definitions: dict[str, AgentDefinition] = {}
        self.agent_runtime_states: dict[str, AgentRuntimeState] = {}
        self.background_market_sector: dict[str, object] = {"sector_id": "background", "token_balance": 0, "usdx_balance": 0}
        self.ledger = Ledger()
        self.clob = CLOB()
        self.information_items: list[dict[str, object]] = []
        self.chain_snapshot: dict[str, object] = {}
        self.rng = NamedRandomStreams(0)
        self.fixture_step = 0
        self.latest_observation_ids: dict[str, str] = {}
        self.action_receipts: list[ActionReceipt] = []
        self.pending_actions: dict[str, dict[str, object]] = {}
        self.action_reservations: dict[str, dict[str, object]] = {}
        self.planning_requests: dict[str, PlanningRequest] = {}
        self.strategy_plans: dict[str, StrategyPlan] = {}
        self.world_revision = 0
        self.world_entities: dict[str, dict[str, object]] = {}
        self.relationships: dict[str, dict[str, object]] = {}
        self.wallet_access: dict[str, dict[str, list[str]]] = {}
        self.frozen_accounts: set[str] = set()
        self.deferred_observation_ids: list[str] = []

    @classmethod
    def from_resolved(cls, resolved: ResolvedInitialState) -> "SimulationWorld":
        world = cls()
        world.market = resolved.market.model_dump(mode="json")
        world.market["status"] = "active"
        world.world_entities[resolved.market.market_id] = {
            "entity_id": resolved.market.market_id,
            "entity_type": "market",
            "display_name": resolved.market.market_id,
            "created_sim_time_us": 0,
        }
        world.chain_snapshot = deepcopy(resolved.chain_snapshot)
        world.rng = NamedRandomStreams(resolved.seed)
        definitions = {definition.agent_id: definition for definition in resolved.agent_definitions}
        for config in resolved.agents:
            if config.strategy == "background":
                continue
            world.agents[config.agent_id] = AgentState(
                agent_id=config.agent_id,
                display_name=config.display_name,
                strategy=config.strategy,
                role_tags=config.role_tags,
                funding_profile=config.funding_profile,
                capabilities=config.capabilities,
            )
            world.world_entities[config.agent_id] = {
                "entity_id": config.agent_id,
                "entity_type": "agent",
                "display_name": config.display_name,
                "created_sim_time_us": 0,
            }
            world.ledger.credit(config.agent_id, resolved.market.base_asset, config.token_balance, reason="initial_mint")
            world.ledger.credit(config.agent_id, resolved.market.quote_asset, config.usdx_balance, reason="initial_mint")
            definition = definitions.get(config.agent_id)
            if definition is not None:
                world.agent_definitions[config.agent_id] = definition
                world.agent_runtime_states[config.agent_id] = AgentRuntimeState(
                    agent_id=config.agent_id,
                    cognitive_budget_state={
                        "window_started_sim_time_us": 0,
                        "plans_remaining": definition.cognitive_profile.max_plans_per_window,
                        "plans_reserved": 0,
                        "searches_remaining": definition.cognitive_profile.memory_search_limit,
                    },
                    attention_budget_state={
                        "window_started_sim_time_us": 0,
                        "items_remaining": definition.attention_profile.information_capacity,
                    },
                )
        background = resolved.background_market_sector
        world.background_market_sector = background.model_dump(mode="json")
        world.world_entities[background.sector_id] = {
            "entity_id": background.sector_id,
            "entity_type": "background_market_sector",
            "display_name": background.sector_id,
            "created_sim_time_us": 0,
        }
        world.ledger.credit(background.sector_id, resolved.market.base_asset, background.token_balance, reason="initial_mint")
        world.ledger.credit(background.sector_id, resolved.market.quote_asset, background.usdx_balance, reason="initial_mint")
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
        world.agent_definitions = {item["agent_id"]: AgentDefinition.model_validate(item) for item in value.get("agent_definitions", [])}
        world.agent_runtime_states = {item["agent_id"]: AgentRuntimeState.model_validate(item) for item in value.get("agent_runtime_states", [])}
        world.background_market_sector = deepcopy(value.get("background_market_sector", {"sector_id": "background", "token_balance": 0, "usdx_balance": 0}))
        world.ledger = Ledger(value["ledger"]["balances"])
        world.ledger.postings = deepcopy(value["ledger"].get("postings", []))
        world.clob = CLOB(value["clob"]["orders"], value["clob"]["trades"])
        world.clob.sequence = int(value["clob"].get("sequence", world.clob.sequence))
        world.information_items = deepcopy(value.get("information_items", []))
        world.chain_snapshot = deepcopy(value.get("chain_snapshot", {}))
        world.rng = NamedRandomStreams(int(value["root_seed"]), deepcopy(value.get("rng_streams", {})))
        world.fixture_step = int(value.get("fixture_step", 0))
        world.latest_observation_ids = deepcopy(value.get("latest_observation_ids", {}))
        world.action_receipts = [ActionReceipt.model_validate(item) for item in value.get("action_receipts", [])]
        world.pending_actions = deepcopy(value.get("pending_actions", {}))
        world.action_reservations = deepcopy(value.get("action_reservations", {}))
        world.planning_requests = {item["request_id"]: PlanningRequest.model_validate(item) for item in value.get("planning_requests", [])}
        world.strategy_plans = {item["plan_id"]: StrategyPlan.model_validate(item) for item in value.get("strategy_plans", [])}
        world.world_revision = int(value.get("world_revision", 0))
        world.world_entities = deepcopy(value.get("world_entities", {}))
        world.relationships = deepcopy(value.get("relationships", {}))
        world.wallet_access = deepcopy(value.get("wallet_access", {}))
        world.frozen_accounts = set(value.get("frozen_accounts", []))
        world.deferred_observation_ids = list(value.get("deferred_observation_ids", []))
        return world

    def clone(self) -> "SimulationWorld":
        return self.from_json(self.to_json())

    def apply_action(
        self,
        action: ActionContract,
        *,
        world_version: int,
        proposal_id: str | None = None,
        decision_id: str | None = None,
    ) -> ActionResult:
        world = self.clone()
        if action.branch_id == "":
            raise ValidationError("branch_id is required")
        agent = world.agents.get(action.agent_id)
        background_id = str(world.background_market_sector.get("sector_id", "background"))
        if agent is None and action.agent_id != background_id:
            raise ValidationError("unknown agent")
        capabilities = agent.capabilities if agent is not None else ["market.trade", "information.read"]
        if action.expected_execution_time_us < action.submitted_sim_time_us:
            raise ValidationError("action execution time cannot precede submission")
        if action.expected_execution_time_us > action.submitted_sim_time_us + action.validity_window_us:
            raise ValidationError("action expires before its expected execution time")
        world.sim_time_us = max(world.sim_time_us, action.expected_execution_time_us)
        accepted = world._event(action, "ActionAccepted", {"action_type": action.action_type}, priority=70, visibility="participants")
        events = [accepted.model_copy(update={"sim_time_us": action.submitted_sim_time_us})]
        token_before = world.ledger.total(world.market["base_asset"])
        quote_before = world.ledger.total(world.market["quote_asset"])
        if action.action_type in {"SubmitLimitOrder", "SubmitProtectedMarketOrder", "CancelOrder", "ReplaceOrder"}:
            if "market.trade" not in capabilities:
                raise ValidationError("agent does not have market.trade capability")
            if world.market.get("status", "active") != "active":
                raise ValidationError("market is halted")
            if action.agent_id in world.frozen_accounts:
                raise ValidationError("agent account is frozen")
            events.extend(world._apply_market_action(action))
        elif action.action_type == "PublishInformation":
            if "information.publish" not in capabilities:
                raise ValidationError("agent does not have information.publish capability")
            events.extend(world._apply_information_action(action))
        if world.ledger.total(world.market["base_asset"]) != token_before or world.ledger.total(world.market["quote_asset"]) != quote_before:
            raise ValidationError("asset conservation invariant failed")
        receipt = ActionReceipt(
            receipt_id=new_id("receipt"),
            action_id=action.action_id,
            proposal_id=proposal_id,
            decision_id=decision_id,
            agent_id=action.agent_id,
            branch_id=action.branch_id,
            outcome="executed",
            reason_code="world_execution_succeeded",
            submitted_sim_time_us=action.submitted_sim_time_us,
            scheduled_sim_time_us=action.expected_execution_time_us,
            resolved_sim_time_us=world.sim_time_us,
            authoritative_event_ids=[],
            result_state_refs={"portfolio_revision": world_version + len(events)},
        )
        world.action_receipts.append(receipt)
        if action.action_type == "PublishInformation" and world.information_items[-1].get("visibility") == "agent_private":
            recipients = sorted(set([action.agent_id, *list(world.information_items[-1].get("target_ids", []))]) & set(world.agents))
        else:
            recipients = sorted(world.agents)
        triggers_by_agent: dict[str, list[DecisionTrigger]] = {}
        for recipient in recipients:
            trigger_type = "information" if action.action_type == "PublishInformation" else "market_change"
            triggers_by_agent[recipient] = [DecisionTrigger(
                type=trigger_type,
                semantic_key=f"{trigger_type}:{action.action_id}",
                source_event_ids=[],
                severity=50,
                first_sim_time_us=world.sim_time_us,
                last_sim_time_us=world.sim_time_us,
            )]
        if action.agent_id in world.agents:
            triggers_by_agent.setdefault(action.agent_id, []).append(DecisionTrigger(
                type="own_action_outcome",
                semantic_key=f"receipt:{action.action_id}",
                source_event_ids=[],
                severity=60,
                first_sim_time_us=world.sim_time_us,
                last_sim_time_us=world.sim_time_us,
            ))
        observations = world.create_observations(
            action.branch_id,
            world_version + len(events),
            recipient_ids=recipients,
            triggers_by_agent=triggers_by_agent,
        )
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
        return ActionResult(world, events, observations, [receipt])

    def apply_intervention_stage(
        self,
        stage: InterventionStage,
        *,
        branch_id: str,
        plan_id: str,
        world_version: int,
        defer_observations: bool = True,
    ) -> InterventionResult:
        if stage.status != "pending":
            raise ValidationError("only pending intervention stages can be applied")
        if stage.effective_sim_time_us != self.sim_time_us:
            raise ValidationError("current-time intervention stage must match branch sim_time_us")
        world = self.clone()
        events: list[EventDraft] = []
        affected_agents: set[str] = set()
        triggers_by_agent: dict[str, list[DecisionTrigger]] = {}
        state_effects = [effect for effect in stage.effects if not isinstance(effect, PublishInformationEffect)]
        information_effects = [effect for effect in stage.effects if isinstance(effect, PublishInformationEffect)]
        for effect in state_effects:
            effect_events, recipients = world._apply_state_intervention_effect(effect, plan_id, stage.stage_id)
            events.extend(effect_events)
            affected_agents.update(recipients)
        for effect in information_effects:
            if effect.source_id in world.agents:
                raise ValidationError("information intervention cannot impersonate an Agent source")
            if effect.source_id != "scenario_director" and not world._entity_exists(effect.source_id):
                raise MissingCausalStateError(f"information source '{effect.source_id}' does not exist")
            missing_targets = sorted(set(effect.target_ids) - set(world.agents))
            if missing_targets:
                raise MissingCausalStateError(f"information target Agents do not exist: {', '.join(missing_targets)}")
            item = publish_information(
                source_id=effect.source_id,
                channel=effect.channel,
                content=effect.content,
                sim_time_us=world.sim_time_us,
                target_ids=effect.target_ids,
            )
            item["intervention_plan_id"] = plan_id
            item["intervention_stage_id"] = stage.stage_id
            item["effect_id"] = effect.effect_id
            world.information_items.append(item)
            visibility = "agent_private" if item["visibility"] == "agent_private" else "public"
            events.append(world._intervention_event(
                plan_id, stage.stage_id, effect.effect_id, "InformationPublished", item,
                priority=40, visibility=visibility, phase="published",
            ))
            recipients = list(item["target_ids"]) if item["visibility"] == "agent_private" else sorted(world.agents)
            for target in recipients:
                delivery_type = "PrivateMessageDelivered" if item["visibility"] == "agent_private" else "InformationDelivered"
                events.append(world._intervention_event(
                    plan_id, stage.stage_id, effect.effect_id, delivery_type,
                    {"information_id": item["information_id"], "target_id": target},
                    priority=41, visibility="agent_private" if visibility == "agent_private" else "participants",
                    phase=f"delivered:{target}", target_ids=[target],
                ))
                if target in world.agents:
                    affected_agents.add(target)
                    trigger_type = "private_message" if visibility == "agent_private" else "information"
                    triggers_by_agent.setdefault(target, []).append(DecisionTrigger(
                        type=trigger_type,
                        semantic_key=f"intervention_information:{effect.effect_id}",
                        source_event_ids=[],
                        severity=70,
                        first_sim_time_us=world.sim_time_us,
                        last_sim_time_us=world.sim_time_us,
                    ))
        for agent_id in affected_agents:
            if agent_id not in triggers_by_agent:
                triggers_by_agent[agent_id] = [DecisionTrigger(
                    type="risk",
                    semantic_key=f"intervention_state:{stage.stage_id}",
                    source_event_ids=[],
                    severity=80,
                    first_sim_time_us=world.sim_time_us,
                    last_sim_time_us=world.sim_time_us,
                )]
        world.world_revision += 1
        observations = world.create_observations(
            branch_id,
            world_version + len(events) + 1,
            recipient_ids=sorted(affected_agents),
            triggers_by_agent=triggers_by_agent,
        ) if affected_agents else []
        if defer_observations:
            world.deferred_observation_ids.extend(observation.observation_id for observation in observations)
        events.extend(
            world._intervention_event(
                plan_id, stage.stage_id, "observation", "ObservationCreated",
                {"agent_id": observation.agent_id, "observation_id": observation.observation_id},
                priority=50, visibility="agent_private", phase=f"observation:{observation.agent_id}",
                target_ids=[observation.agent_id], observation_id=observation.observation_id,
            )
            for observation in observations
        )
        return InterventionResult(world=world, events=events, observations=observations)

    def _apply_state_intervention_effect(
        self,
        effect: object,
        plan_id: str,
        stage_id: str,
    ) -> tuple[list[EventDraft], set[str]]:
        recipients: set[str] = set()
        if isinstance(effect, CreateWorldEntityEffect):
            if self._entity_exists(effect.entity_id):
                raise ValidationError(f"world entity '{effect.entity_id}' already exists")
            self.world_entities[effect.entity_id] = {
                "entity_id": effect.entity_id,
                "entity_type": effect.entity_type,
                "display_name": effect.display_name,
                "created_sim_time_us": self.sim_time_us,
            }
            if effect.entity_type == "wallet":
                self.ledger.open_account(
                    effect.entity_id,
                    [str(self.market["base_asset"]), str(self.market["quote_asset"])],
                    reason="intervention_entity_created",
                )
            event_type = "WorldEntityCreated"
            payload = dict(self.world_entities[effect.entity_id])
        elif isinstance(effect, CreateRelationshipEffect):
            if effect.relationship_id in self.relationships:
                raise ValidationError(f"relationship '{effect.relationship_id}' already exists")
            if not self._entity_exists(effect.source_entity_id) or not self._entity_exists(effect.target_entity_id):
                raise MissingCausalStateError("relationship endpoints must exist before the stage")
            self.relationships[effect.relationship_id] = effect.model_dump(mode="json")
            event_type = "WorldRelationshipCreated"
            payload = dict(self.relationships[effect.relationship_id])
            recipients.update({effect.source_entity_id, effect.target_entity_id} & set(self.agents))
        elif isinstance(effect, TransferAssetEffect):
            missing = [relationship_id for relationship_id in effect.required_relationship_ids if relationship_id not in self.relationships]
            if missing:
                raise MissingCausalStateError(f"required relationships do not exist: {', '.join(missing)}")
            if not self.ledger.has_account(effect.from_owner_id, effect.asset) or not self.ledger.has_account(effect.to_owner_id, effect.asset):
                raise MissingCausalStateError("asset transfer requires existing ledger accounts")
            if effect.from_owner_id in self.frozen_accounts:
                raise ValidationError("source account is frozen")
            self.ledger.transfer_free(
                effect.from_owner_id,
                effect.to_owner_id,
                effect.asset,
                effect.amount,
                reason=f"intervention:{effect.reason_code}",
            )
            event_type = "ExternalAssetTransferred"
            payload = effect.model_dump(mode="json")
            recipients.update({effect.from_owner_id, effect.to_owner_id} & set(self.agents))
        elif isinstance(effect, SetMarketStatusEffect):
            if effect.market_id != self.market.get("market_id"):
                raise MissingCausalStateError(f"market '{effect.market_id}' does not exist")
            self.market["status"] = effect.status
            event_type = "MarketStatusChanged"
            payload = effect.model_dump(mode="json")
            recipients.update(self.agents)
        elif isinstance(effect, SetAccountFreezeEffect):
            if not self.ledger.has_owner(effect.owner_id):
                raise MissingCausalStateError(f"account owner '{effect.owner_id}' does not exist")
            if effect.frozen:
                self.frozen_accounts.add(effect.owner_id)
                canceled_order_ids: list[str] = []
                for order in list(self.clob.orders.values()):
                    if order.agent_id == effect.owner_id and order.status in {"open", "partially_filled"}:
                        self.clob.cancel(
                            order.order_id,
                            effect.owner_id,
                            self.ledger,
                            base_asset=str(self.market["base_asset"]),
                            quote_asset=str(self.market["quote_asset"]),
                        )
                        canceled_order_ids.append(order.order_id)
            else:
                self.frozen_accounts.discard(effect.owner_id)
                canceled_order_ids = []
            event_type = "AccountFreezeChanged"
            payload = {**effect.model_dump(mode="json"), "canceled_order_ids": canceled_order_ids}
            recipients.update({effect.owner_id} & set(self.agents))
        elif isinstance(effect, SetWalletAccessEffect):
            if not self.ledger.has_owner(effect.wallet_owner_id):
                raise MissingCausalStateError(f"wallet owner '{effect.wallet_owner_id}' does not exist")
            if effect.grantee_agent_id not in self.agents:
                raise MissingCausalStateError(f"Agent '{effect.grantee_agent_id}' does not exist")
            grants = self.wallet_access.setdefault(effect.wallet_owner_id, {})
            if effect.permissions:
                grants[effect.grantee_agent_id] = list(effect.permissions)
            else:
                grants.pop(effect.grantee_agent_id, None)
            event_type = "WalletAccessChanged"
            payload = effect.model_dump(mode="json")
            recipients.add(effect.grantee_agent_id)
            recipients.update({effect.wallet_owner_id} & set(self.agents))
        else:
            raise ValidationError("unsupported state intervention effect")
        return [self._intervention_event(
            plan_id, stage_id, effect.effect_id, event_type, payload,
            priority=20, visibility="analyst_only", phase=effect.effect_id,
        )], recipients

    def _entity_exists(self, entity_id: str) -> bool:
        return entity_id in self.world_entities or self.ledger.has_owner(entity_id)

    def _intervention_event(
        self,
        plan_id: str,
        stage_id: str,
        effect_id: str,
        event_type: str,
        payload: dict[str, object],
        *,
        priority: int,
        visibility: str,
        phase: str,
        target_ids: list[str] | None = None,
        observation_id: str | None = None,
    ) -> EventDraft:
        return EventDraft(
            sim_time_us=self.sim_time_us,
            priority=priority,
            tie_break_key=f"intervention:{plan_id}:{stage_id}:{phase}",
            event_type=event_type,
            source_id="scenario_director",
            target_ids=target_ids or [],
            payload={**payload, "intervention_plan_id": plan_id, "intervention_stage_id": stage_id, "effect_id": effect_id},
            observation_id=observation_id,
            correlation_id=plan_id,
            visibility=visibility,
        )

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

    def create_observations(
        self,
        branch_id: str,
        world_version: int,
        *,
        recipient_ids: list[str] | None = None,
        triggers_by_agent: dict[str, list[DecisionTrigger]] | None = None,
    ) -> list[ObservationPacket]:
        service = ObservationService()
        recipients = sorted(set(recipient_ids if recipient_ids is not None else self.agents) & set(self.agents))
        triggers_by_agent = triggers_by_agent or {
            agent_id: [DecisionTrigger(
                type="initial_observation",
                semantic_key="initial_observation",
                source_event_ids=[],
                severity=100,
                first_sim_time_us=self.sim_time_us,
                last_sim_time_us=self.sim_time_us,
            )]
            for agent_id in recipients
        }
        observations = [
            service.build(
                self,
                agent_id,
                branch_id,
                world_version,
                decision_triggers=triggers_by_agent.get(agent_id, []),
            )
            for agent_id in recipients
        ]
        self.latest_observation_ids.update({item.agent_id: item.observation_id for item in observations})
        return observations

    def pending_action_ids(self, agent_id: str) -> list[str]:
        return sorted(action_id for action_id, value in self.pending_actions.items() if value.get("agent_id") == agent_id)

    def reservation_ids(self, agent_id: str) -> list[str]:
        return sorted(reservation_id for reservation_id, value in self.action_reservations.items() if value.get("agent_id") == agent_id)

    def portfolio_projection(self, agent_id: str) -> dict[str, object]:
        balances = self.ledger.to_json()["balances"].get(agent_id, {})
        open_orders = [order for order in self.clob.to_json()["orders"] if order["agent_id"] == agent_id and order["status"] in {"open", "partially_filled"}]
        return {"agent_id": agent_id, "balances": balances, "open_orders": open_orders}

    def wallet_access_projection(self, agent_id: str) -> dict[str, object]:
        permissions: dict[str, list[str]] = {}
        balances: dict[str, dict[str, object]] = {}
        ledger_balances = self.ledger.to_json()["balances"]
        for wallet_owner_id, grants in self.wallet_access.items():
            granted = list(grants.get(agent_id, []))
            if not granted:
                continue
            permissions[wallet_owner_id] = granted
            if "observe" in granted:
                balances[wallet_owner_id] = deepcopy(ledger_balances.get(wallet_owner_id, {}))
        return {"permissions": permissions, "balances": balances}

    def market_projection(self) -> dict[str, object]:
        orders = self.clob.to_json()["orders"]
        bids = sorted([item for item in orders if item["side"] == "buy" and item["status"] in {"open", "partially_filled"}], key=lambda item: (-int(item["price"] or 0), int(item["submitted_seq"])))
        asks = sorted([item for item in orders if item["side"] == "sell" and item["status"] in {"open", "partially_filled"}], key=lambda item: (int(item["price"] or 0), int(item["submitted_seq"])))
        last_trade = self.clob.to_json()["trades"][-1] if self.clob.trades else None
        return {"market_id": self.market["market_id"], "bids": bids[:20], "asks": asks[:20], "last_trade": last_trade, "trades": self.clob.to_json()["trades"][-100:]}

    def agent_projection(self, agent_id: str) -> dict[str, object]:
        agent = self.agents[agent_id]
        definition = self.agent_definitions.get(agent_id)
        state = self.agent_runtime_states.get(agent_id)
        return {
            "agent_id": agent.agent_id,
            "display_name": agent.display_name,
            "strategy": agent.strategy,
            "role_tags": agent.role_tags,
            "funding_profile": agent.funding_profile,
            "capabilities": agent.capabilities,
            "planner_profile_id": definition.planner_profile_id if definition else agent.strategy,
            "agent_revision": state.agent_revision if state else 0,
            "active_strategy_revision": state.active_strategy_revision if state else 0,
            "planning_request_id": state.planning_request_id if state else None,
            "portfolio": self.portfolio_projection(agent.agent_id),
        }

    def projection(self, branch_id: str, state_version: int, status: str) -> dict[str, object]:
        return {
            "branch_id": branch_id,
            "cursor": state_version,
            "status": status,
            "sim_time_us": self.sim_time_us,
            "market": self.market_projection(),
            "agents": [self.agent_projection(agent_id) for agent_id in self.agents],
            "information": self.information_items[-100:],
            "fixture_step": self.fixture_step,
            "world_revision": self.world_revision,
            "market_status": self.market.get("status", "active"),
            "deferred_observation_count": len(self.deferred_observation_ids),
        }

    def to_json(self) -> dict[str, object]:
        return {
            "sim_time_us": self.sim_time_us,
            "market": deepcopy(self.market),
            "agents": [agent.model_dump(mode="json") for agent in self.agents.values()],
            "agent_definitions": [definition.model_dump(mode="json") for definition in self.agent_definitions.values()],
            "agent_runtime_states": [state.model_dump(mode="json") for state in self.agent_runtime_states.values()],
            "background_market_sector": deepcopy(self.background_market_sector),
            "ledger": self.ledger.to_json(),
            "clob": self.clob.to_json(),
            "information_items": deepcopy(self.information_items),
            "chain_snapshot": deepcopy(self.chain_snapshot),
            "root_seed": self.rng.root_seed,
            "rng_streams": self.rng.snapshot(),
            "fixture_step": self.fixture_step,
            "latest_observation_ids": deepcopy(self.latest_observation_ids),
            "action_receipts": [receipt.model_dump(mode="json") for receipt in self.action_receipts],
            "pending_actions": deepcopy(self.pending_actions),
            "action_reservations": deepcopy(self.action_reservations),
            "planning_requests": [request.model_dump(mode="json") for request in self.planning_requests.values()],
            "strategy_plans": [plan.model_dump(mode="json") for plan in self.strategy_plans.values()],
            "world_revision": self.world_revision,
            "world_entities": deepcopy(self.world_entities),
            "relationships": deepcopy(self.relationships),
            "wallet_access": deepcopy(self.wallet_access),
            "frozen_accounts": sorted(self.frozen_accounts),
            "deferred_observation_ids": list(self.deferred_observation_ids),
        }
