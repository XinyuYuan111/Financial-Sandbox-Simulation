from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ObservationPacket(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    observation_id: str
    agent_id: str
    branch_id: str
    sim_time_us: int = Field(ge=0)
    world_version: int = Field(ge=0)
    market_view: dict[str, Any] = Field(default_factory=dict)
    portfolio_view: dict[str, Any] = Field(default_factory=dict)
    information_items: list[dict[str, Any]] = Field(default_factory=list)
    private_messages: list[dict[str, Any]] = Field(default_factory=list)
    chain_view: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    observation_delays: dict[str, int] = Field(default_factory=dict)
    provenance: list[str] = Field(default_factory=list)
    attention_decisions: list[dict[str, Any]] = Field(default_factory=list)
    schema_version: Literal["observation.v0.2"] = "observation.v0.2"
