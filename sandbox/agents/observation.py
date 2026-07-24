from __future__ import annotations

from copy import deepcopy
from typing import Protocol

from sandbox.contracts.agent import DecisionTrigger
from sandbox.contracts.observation import AgentAccountSnapshot, ObservationPacket
from sandbox.core.ids import new_id


class ObservationService:
    def build(
        self,
        world: "WorldProjection",
        agent_id: str,
        branch_id: str,
        world_version: int,
        *,
        decision_triggers: list[DecisionTrigger] | None = None,
    ) -> ObservationPacket:
        definition = world.agent_definitions.get(agent_id)
        runtime_state = world.agent_runtime_states.get(agent_id)
        capacity = definition.attention_profile.information_capacity if definition is not None else 20
        if runtime_state is not None:
            capacity = min(capacity, runtime_state.attention_budget_state.items_remaining)
        viewed_ids = set(runtime_state.viewed_information_ids) if runtime_state is not None else set()
        minimum_salience = definition.attention_profile.minimum_salience if definition is not None else 0
        candidates: list[dict[str, object]] = []
        for raw in world.information_items:
            if str(raw.get("information_id")) in viewed_ids or int(raw.get("salience", 50)) < minimum_salience:
                continue
            delivery_times = raw.get("delivery_times_us", {})
            if not isinstance(delivery_times, dict) or agent_id not in delivery_times:
                continue
            delivered_at = int(delivery_times[agent_id])
            expires_at = int(raw.get("expires_sim_time_us", delivered_at + 86_400_000_000))
            if delivered_at > world.sim_time_us or expires_at < world.sim_time_us:
                continue
            item = {
                key: deepcopy(value)
                for key, value in raw.items()
                if key not in {"delivery_times_us", "salience"}
            }
            item["delivered_sim_time_us"] = delivered_at
            item["viewed_sim_time_us"] = world.sim_time_us
            item["expires_sim_time_us"] = expires_at
            item["_salience"] = int(raw.get("salience", 50))
            candidates.append(item)
        candidates.sort(key=lambda item: (-int(item["_salience"]), -int(item["sim_time_us"]), str(item["information_id"])))
        selected = candidates[:capacity]
        visible = [{key: value for key, value in item.items() if key != "_salience"} for item in selected]
        portfolio = world.portfolio_projection(agent_id)
        wallet_access = world.wallet_access_projection(agent_id)
        receipts = [receipt for receipt in world.action_receipts if receipt.agent_id == agent_id]
        return ObservationPacket(
            observation_id=new_id("obs"),
            agent_id=agent_id,
            branch_id=branch_id,
            sim_time_us=world.sim_time_us,
            world_version=world_version,
            decision_triggers=decision_triggers or [],
            market_view=world.market_projection(),
            account_snapshot=AgentAccountSnapshot(
                agent_id=agent_id,
                portfolio_revision=world_version,
                balances=portfolio["balances"],
                wallet_permissions=wallet_access["permissions"],
                accessible_wallet_balances=wallet_access["balances"],
                positions={asset: int(values["free"]) + int(values["locked"]) for asset, values in portfolio["balances"].items()},
                open_orders=portfolio["open_orders"],
                pending_action_ids=list(world.pending_action_ids(agent_id)),
                reservation_ids=list(world.reservation_ids(agent_id)),
                risk_refs=[],
            ),
            portfolio_view=portfolio,
            information_items=visible,
            private_messages=[item for item in visible if item.get("visibility") == "agent_private"],
            action_receipts=receipts[-20:],
            chain_view=world.chain_snapshot,
            provenance=[str(item.get("information_id")) for item in visible],
            attention_decisions=[{
                "policy": "salience-then-recency",
                "selected": len(visible),
                "dropped": max(0, len(candidates) - len(visible)),
                "reason_code": "within_capacity" if len(candidates) <= capacity else "capacity_exhausted",
            }],
        )


class WorldProjection(Protocol):
    sim_time_us: int
    information_items: list[dict[str, object]]
    chain_snapshot: dict[str, object]
    action_receipts: list[object]
    agent_definitions: dict[str, object]
    agent_runtime_states: dict[str, object]

    def market_projection(self) -> dict[str, object]: ...
    def portfolio_projection(self, agent_id: str) -> dict[str, object]: ...
    def wallet_access_projection(self, agent_id: str) -> dict[str, object]: ...
    def pending_action_ids(self, agent_id: str) -> list[str]: ...
    def reservation_ids(self, agent_id: str) -> list[str]: ...
