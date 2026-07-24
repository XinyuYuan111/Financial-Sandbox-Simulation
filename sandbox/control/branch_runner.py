from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sandbox.control.run_manager import RunManager


@dataclass(slots=True)
class BranchRunner:
    manager: "RunManager"

    async def run_for(self, branch_id: str, *, max_requests: int = 1) -> dict[str, object]:
        return await self.manager._run_planning_requests(branch_id, max_requests=max_requests)
