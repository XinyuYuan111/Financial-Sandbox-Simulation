from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sandbox.core.errors import ValidationError


class ProviderAdapter(Protocol):
    name: str

    async def preflight(self) -> dict[str, object]: ...

    async def plan(self, request: dict[str, object]) -> dict[str, object]: ...


@dataclass(slots=True)
class LLMGateway:
    adapters: dict[str, ProviderAdapter]

    async def preflight(self, provider_name: str) -> dict[str, object]:
        adapter = self.adapters.get(provider_name)
        if adapter is None:
            raise ValidationError(f"LLM provider '{provider_name}' is not configured")
        report = await adapter.preflight()
        if not report.get("ok"):
            raise ValidationError(f"LLM provider preflight failed: {report.get('message', 'unknown error')}")
        return report

