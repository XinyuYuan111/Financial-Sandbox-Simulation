from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from sandbox.contracts.intervention import DirectorAccessScope, InterventionPlanDraftInput, PrivateStateRef


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    resolution_hash: str = Field(min_length=8, max_length=256)


class InterpretAgentConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_intent: str = Field(min_length=1, max_length=4_000)
    provider: Literal["openai", "deepseek"] = "openai"


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_command_id: str = Field(min_length=1, max_length=256)
    command_type: Literal["start", "pause", "stop", "step_fixture", "run_for", "save"]
    payload: dict[str, Any] = Field(default_factory=dict)


class ForkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checkpoint_id: str
    client_command_id: str = Field(min_length=1, max_length=256)


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str


class DraftInterventionPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_command_id: str = Field(min_length=1, max_length=256)
    draft: InterventionPlanDraftInput


class InterventionPlanCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_command_id: str = Field(min_length=1, max_length=256)


class InterpretInterventionPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_command_id: str = Field(min_length=1, max_length=256)
    user_intent: str = Field(min_length=1, max_length=4_000)
    requested_effective_time_us: int = Field(ge=0)
    provider: Literal["openai", "deepseek"] = "openai"
    access_scope: DirectorAccessScope = Field(default_factory=DirectorAccessScope)
    private_read_refs: list[PrivateStateRef] = Field(default_factory=list, max_length=2_048)
