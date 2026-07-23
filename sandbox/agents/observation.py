from __future__ import annotations

from typing import Protocol

from sandbox.contracts.observation import ObservationPacket
from sandbox.core.ids import new_id


class ObservationService:
    def build(self, world: "WorldProjection", agent_id: str, branch_id: str, world_version: int) -> ObservationPacket:
        visible = [item for item in world.information_items if item.get("visibility") == "public" or agent_id in item.get("target_ids", [])]
        return ObservationPacket(
            observation_id=new_id("obs"),
            agent_id=agent_id,
            branch_id=branch_id,
            sim_time_us=world.sim_time_us,
            world_version=world_version,
            market_view=world.market_projection(),
            portfolio_view=world.portfolio_projection(agent_id),
            information_items=visible[-20:],
            private_messages=[item for item in visible if item.get("visibility") == "agent_private"],
            chain_view=world.chain_snapshot,
            provenance=[str(item.get("information_id")) for item in visible[-20:]],
            attention_decisions=[{"policy": "latest-within-capacity", "selected": len(visible[-20:])}],
        )


class WorldProjection(Protocol):
    sim_time_us: int
    information_items: list[dict[str, object]]
    chain_snapshot: dict[str, object]

    def market_projection(self) -> dict[str, object]: ...
    def portfolio_projection(self, agent_id: str) -> dict[str, object]: ...

