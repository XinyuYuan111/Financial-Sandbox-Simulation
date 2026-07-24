from __future__ import annotations

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
        visible = [item for item in world.information_items if item.get("visibility") == "public" or agent_id in item.get("target_ids", [])]
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
            information_items=visible[-20:],
            private_messages=[item for item in visible if item.get("visibility") == "agent_private"],
            action_receipts=receipts[-20:],
            chain_view=world.chain_snapshot,
            provenance=[str(item.get("information_id")) for item in visible[-20:]],
            attention_decisions=[{"policy": "latest-within-capacity", "selected": len(visible[-20:])}],
        )


class WorldProjection(Protocol):
    sim_time_us: int
    information_items: list[dict[str, object]]
    chain_snapshot: dict[str, object]
    action_receipts: list[object]

    def market_projection(self) -> dict[str, object]: ...
    def portfolio_projection(self, agent_id: str) -> dict[str, object]: ...
    def wallet_access_projection(self, agent_id: str) -> dict[str, object]: ...
    def pending_action_ids(self, agent_id: str) -> list[str]: ...
    def reservation_ids(self, agent_id: str) -> list[str]: ...
