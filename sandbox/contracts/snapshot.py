from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    checkpoint_id: str
    run_id: str
    branch_id: str
    branch_seq: int = Field(ge=0)
    event_hash: str
    sim_time_us: int = Field(ge=0)
    state: dict[str, Any]
    control_state: dict[str, Any] = Field(default_factory=dict)
    runtime_version: str
    schema_version: Literal["checkpoint.v0.2"] = "checkpoint.v0.2"


class ArchiveManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["archive.v0.2"] = "archive.v0.2"
    runtime_version: str
    run_id: str
    root_branch_id: str
    included_branches: list[str]
    file_hashes: dict[str, str]
    complete: bool = True
