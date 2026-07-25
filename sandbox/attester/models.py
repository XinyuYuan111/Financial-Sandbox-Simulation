from __future__ import annotations

from pydantic import BaseModel
from typing import Literal


class AttestationRequest(BaseModel):
    """Request to record a simulation attestation on-chain."""
    run_id: str
    branch_id: str
    sim_time_us: int
    agent_count: int
    world_state_hash: str  # SHA256 hex (64 chars)
    final_event_hash: str
    completion_reason: str


class AttestationResult(BaseModel):
    """Result of an on-chain attestation attempt."""
    run_id: str
    branch_id: str
    tx_hash: str
    block_number: int
    status: Literal["pending", "confirmed", "failed"]
    error_message: str | None = None
