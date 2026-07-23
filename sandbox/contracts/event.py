from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Stable identifier hash for the immutable event.v0.2 contract namespace.
EVENT_SCHEMA_HASH = "sha256:58e4932603526789bcbfbe4ac4b740e21116680787c204e159f2c074c8cb6977"


class EventDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    sim_time_us: int = Field(ge=0)
    priority: int = Field(ge=0, le=100)
    tie_break_key: str = Field(min_length=1, max_length=256)
    event_type: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=256)
    target_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    parent_event_ids: list[str] = Field(default_factory=list)
    observation_id: str | None = None
    action_id: str | None = None
    correlation_id: str | None = None
    visibility: Literal["public", "participants", "agent_private", "analyst_only"] = "public"
    rng_stream: str | None = None
    rng_draw_index: int | None = Field(default=None, ge=0)


class EventEnvelope(EventDraft):
    event_id: str
    run_id: str
    branch_id: str
    branch_seq: int = Field(ge=1)
    schema_version: Literal["event.v0.2"] = "event.v0.2"
    schema_hash: str = EVENT_SCHEMA_HASH
    prev_event_hash: str
    event_hash: str
