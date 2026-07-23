from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ActionContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    action_id: str
    agent_id: str
    branch_id: str
    submitted_sim_time_us: int = Field(ge=0)
    action_type: Literal["SubmitLimitOrder", "SubmitProtectedMarketOrder", "CancelOrder", "ReplaceOrder", "PublishInformation"]
    payload: dict[str, Any]
    expected_execution_time_us: int = Field(ge=0)
    validity_window_us: int = Field(ge=0)
    parent_observation_id: str | None = None
    client_command_id: str = Field(min_length=1, max_length=256)
    schema_version: Literal["action.v0.2"] = "action.v0.2"
