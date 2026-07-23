from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class BranchState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    branch_id: str
    run_id: str
    parent_branch_id: str | None = None
    fork_checkpoint_id: str | None = None
    status: Literal["Created", "Initializing", "Ready", "Running", "Paused", "Quiescing", "Checkpointed", "Forking", "Completed", "Failed"]
    sim_time_us: int
    state_version: int
    last_event_hash: str

