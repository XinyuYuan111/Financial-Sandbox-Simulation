from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CognitiveProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_plans_per_window: int = Field(default=2, ge=0)
    context_capacity: int = Field(default=8_000, ge=256)
    memory_search_limit: int = Field(default=5, ge=0)
    information_capacity: int = Field(default=20, ge=1)


class AgentState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    display_name: str
    strategy: str
    role_tags: list[str]
    funding_profile: str
    capabilities: list[str]
    base_cognitive_profile: CognitiveProfile = Field(default_factory=CognitiveProfile)
    cognitive_budget_state: dict[str, int] = Field(default_factory=lambda: {"plans_remaining": 2, "searches_remaining": 5})

