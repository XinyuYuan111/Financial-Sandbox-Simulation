from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sandbox.agents.llm_gateway import LLMGateway
from sandbox.contracts.scenario import AgentConfig, ResolvedInitialState, ScenarioDraft
from sandbox.core.errors import ValidationError


class HolderDataProvider(Protocol):
    name: str

    async def preflight(self, chain_id: str, target_token: str) -> dict[str, object]: ...

    async def load_finalized_snapshot(self, chain_id: str, target_token: str) -> dict[str, object]: ...


def fixture_agents() -> list[AgentConfig]:
    preset_path = Path(__file__).resolve().parents[2] / "fixtures" / "presets" / "framework-alpha.default.v0.2.json"
    preset = json.loads(preset_path.read_text(encoding="utf-8"))
    return [AgentConfig.model_validate(agent) for agent in preset["agents"]]


@dataclass(slots=True)
class Initializer:
    holder_providers: dict[str, HolderDataProvider]
    llm_gateway: LLMGateway

    async def resolve(self, scenario_id: str, draft: ScenarioDraft) -> ResolvedInitialState:
        agents = draft.agents or fixture_agents()
        if len({agent.agent_id for agent in agents}) != len(agents):
            raise ValidationError("agent_id values must be unique")
        if draft.mode == "test_fixture":
            snapshot_path = Path(__file__).resolve().parents[2] / "fixtures" / "holder_snapshots" / "framework-alpha.fixture.v0.2.json"
            fixture_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            provider_report = {"mode": "fixture", "provider": fixture_snapshot["provider"], "ok": True, "coverage_ratio_milli": fixture_snapshot["coverage_ratio_milli"]}
            chain_snapshot = {**fixture_snapshot, "target_token": draft.target_token}
            warnings = ["Explicit test fixture mode: no live chain or LLM provider was used."]
        else:
            assert draft.chain_id is not None and draft.llm_provider is not None
            provider = self.holder_providers.get(draft.chain_id)
            if provider is None:
                raise ValidationError(f"holder provider for chain '{draft.chain_id}' is not configured")
            provider_report = await provider.preflight(draft.chain_id, draft.target_token)
            if not provider_report.get("ok"):
                raise ValidationError(f"holder provider preflight failed: {provider_report.get('message', 'unknown error')}")
            await self.llm_gateway.preflight(draft.llm_provider)
            chain_snapshot = await provider.load_finalized_snapshot(draft.chain_id, draft.target_token)
            if not chain_snapshot.get("finalized"):
                raise ValidationError("holder provider did not return a finalized block")
            warnings = []
        token_assigned = sum(agent.token_balance for agent in agents)
        usdx_assigned = sum(agent.usdx_balance for agent in agents)
        total_token = max(1_000_000, token_assigned)
        total_usdx = max(100_000_000, usdx_assigned)
        return ResolvedInitialState(
            scenario_id=scenario_id,
            name=draft.name,
            mode=draft.mode,
            seed=draft.seed,
            preset_version=draft.preset_version,
            provider_report=provider_report,
            chain_snapshot=chain_snapshot,
            market=draft.market.model_copy(update={"base_asset": draft.target_token}),
            agents=agents,
            total_supply={draft.target_token: total_token, draft.market.quote_asset: total_usdx},
            warnings=warnings,
        )
