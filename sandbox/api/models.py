from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_command_id: str = Field(min_length=1, max_length=256)
    command_type: Literal["start", "pause", "step_fixture", "run_for", "save"]
    payload: dict[str, Any] = Field(default_factory=dict)


class ForkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checkpoint_id: str
    client_command_id: str = Field(min_length=1, max_length=256)


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
