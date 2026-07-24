from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Callable, Protocol

from sandbox.contracts.planning import LLMRecord, PlanningProviderRequest, PlanningResultCandidate
from sandbox.core.errors import ValidationError


RecordCallback = Callable[[LLMRecord], None]


class ProviderAdapter(Protocol):
    name: str

    async def preflight(self) -> dict[str, object]: ...

    async def create_plan(
        self,
        request: PlanningProviderRequest,
        *,
        record_raw: RecordCallback | None = None,
    ) -> PlanningResultCandidate: ...


@dataclass(slots=True)
class LLMGateway:
    adapters: dict[str, ProviderAdapter]
    max_in_flight: int = 4
    _semaphore: asyncio.Semaphore | None = field(default=None, init=False, repr=False)

    def _pool(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_in_flight)
        return self._semaphore

    def profiles(self) -> list[dict[str, object]]:
        output = []
        for name, adapter in sorted(self.adapters.items()):
            profile = getattr(adapter, "profile", None)
            output.append(profile.model_dump(mode="json") if profile is not None else {"provider": name})
        return output

    async def preflight(self, provider_name: str) -> dict[str, object]:
        adapter = self.adapters.get(provider_name)
        if adapter is None:
            raise ValidationError(f"LLM provider '{provider_name}' is not configured")
        report = await adapter.preflight()
        if not report.get("ok"):
            raise ValidationError(f"LLM provider preflight failed: {report.get('message', 'unknown error')}")
        return report

    async def plan(
        self,
        provider_name: str,
        request: PlanningProviderRequest,
        *,
        record_raw: RecordCallback | None = None,
    ) -> PlanningResultCandidate:
        adapter = self.adapters.get(provider_name)
        if adapter is None:
            raise ValidationError(f"LLM provider '{provider_name}' is not configured")
        async with self._pool():
            return await adapter.create_plan(request, record_raw=record_raw)
