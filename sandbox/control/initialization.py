from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sandbox.agents.llm_gateway import LLMGateway
from sandbox.agents.population import generate_population
from sandbox.contracts.agent import AgentDefinition, BasePersona
from sandbox.contracts.scenario import AgentConfig, BackgroundMarketSector, ResolvedInitialState, ScenarioDraft
from sandbox.core.errors import ValidationError


class HolderDataProvider(Protocol):
    name: str

    async def preflight(self, chain_id: str, target_token: str) -> dict[str, object]: ...

    async def load_finalized_snapshot(self, chain_id: str, target_token: str) -> dict[str, object]: ...


def fixture_agents() -> list[AgentConfig]:
    preset_path = Path(__file__).resolve().parents[2] / "fixtures" / "presets" / "framework-alpha.default.v0.2.json"
    preset = json.loads(preset_path.read_text(encoding="utf-8"))
    return [AgentConfig.model_validate(agent) for agent in preset["agents"]]


def definition_from_config(config: AgentConfig, *, seed: int) -> AgentDefinition:
    bias = sum(f"{seed}:{config.agent_id}".encode()) % 401
    return AgentDefinition(
        agent_id=config.agent_id,
        display_name=config.display_name,
        public_identity=f"Fixture {config.funding_profile} participant",
        role_tags=config.role_tags,
        funding_profile=config.funding_profile,  # type: ignore[arg-type]
        capability_set=config.capabilities,
        base_persona=BasePersona(
            template_id="fixture_participant",
            private_goals=["follow_declared_strategy"],
            risk_tolerance_milli=300 + bias,
            time_horizon="medium",
            loss_aversion_milli=700 - bias,
            trend_bias_milli=300 + bias,
            skepticism_milli=700 - bias,
            communication_propensity_milli=300 + bias,
            bounded_notes="Deterministic fixture persona.",
        ),
        planner_profile_id=f"{config.strategy}.default.v0.1",
    )


@dataclass(slots=True)
class Initializer:
    holder_providers: dict[str, HolderDataProvider]
    llm_gateway: LLMGateway

    async def resolve(self, scenario_id: str, draft: ScenarioDraft) -> ResolvedInitialState:
        input_agents = draft.agents or (fixture_agents() if draft.population.preset == "fixture" else [])
        if len({agent.agent_id for agent in input_agents}) != len(input_agents):
            raise ValidationError("agent_id values must be unique")
        if draft.mode == "test_fixture":
            snapshot_path = Path(__file__).resolve().parents[2] / "fixtures" / "holder_snapshots" / "framework-alpha.fixture.v0.2.json"
            fixture_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            provider_report = {"mode": "fixture", "provider": fixture_snapshot["provider"], "ok": True, "coverage_ratio_milli": fixture_snapshot["coverage_ratio_milli"]}
            chain_snapshot = {**fixture_snapshot, "target_token": draft.target_token}
            warnings = ["Explicit test fixture mode: no live chain or LLM provider was used."]
            llm_report: dict[str, object] = {"ok": True, "provider": "fixture", "model": "deterministic", "mode": "fixture"}
        elif draft.mode == "live_llm_smoke":
            assert draft.llm_provider is not None
            snapshot_path = Path(__file__).resolve().parents[2] / "fixtures" / "holder_snapshots" / "framework-alpha.fixture.v0.2.json"
            fixture_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            chain_snapshot = {**fixture_snapshot, "target_token": draft.target_token, "mode": "synthetic-smoke"}
            llm_report = await self.llm_gateway.preflight(draft.llm_provider)
            provider_report = {"mode": "live_llm_smoke", "provider": "synthetic-holder-snapshot", "ok": True}
            warnings = ["OpenAI smoke mode uses a synthetic market and does not use live chain holder data."]
        else:
            assert draft.chain_id is not None and draft.llm_provider is not None
            provider = self.holder_providers.get(draft.chain_id)
            if provider is None:
                raise ValidationError(f"holder provider for chain '{draft.chain_id}' is not configured")
            provider_report = await provider.preflight(draft.chain_id, draft.target_token)
            if not provider_report.get("ok"):
                raise ValidationError(f"holder provider preflight failed: {provider_report.get('message', 'unknown error')}")
            llm_report = await self.llm_gateway.preflight(draft.llm_provider)
            chain_snapshot = await provider.load_finalized_snapshot(draft.chain_id, draft.target_token)
            if not chain_snapshot.get("finalized"):
                raise ValidationError("holder provider did not return a finalized block")
            warnings = []
        explicit_inputs = [agent for agent in input_agents if agent.strategy != "background"]
        legacy_background = next((agent for agent in input_agents if agent.strategy == "background"), None)
        token_assigned = sum(agent.token_balance for agent in explicit_inputs) + (legacy_background.token_balance if legacy_background else 0)
        usdx_assigned = sum(agent.usdx_balance for agent in explicit_inputs) + (legacy_background.usdx_balance if legacy_background else 0)
        total_token = max(int(chain_snapshot.get("total_supply", 1_000_000)), token_assigned)
        total_usdx = max(100_000_000, usdx_assigned)

        preset = draft.population.preset
        if draft.mode == "live_llm_smoke":
            preset = "smoke"
        elif draft.mode == "live" and preset == "fixture":
            preset = "standard"
        if explicit_inputs:
            agents = explicit_inputs
            definitions = [definition_from_config(agent, seed=draft.seed) for agent in agents]
            background = BackgroundMarketSector(
                token_balance=legacy_background.token_balance if legacy_background else total_token - sum(agent.token_balance for agent in agents),
                usdx_balance=legacy_background.usdx_balance if legacy_background else total_usdx - sum(agent.usdx_balance for agent in agents),
            )
            preview = {
                "preset": "fixture" if legacy_background else "custom",
                "seed": draft.seed,
                "agent_count": len(definitions),
                "funding_profile_counts": {profile: sum(item.funding_profile == profile for item in agents) for profile in sorted({item.funding_profile for item in agents})},
                "assets": {
                    "explicit_token": sum(item.token_balance for item in agents),
                    "explicit_usdx": sum(item.usdx_balance for item in agents),
                    "background_token": background.token_balance,
                    "background_usdx": background.usdx_balance,
                },
            }
        else:
            generated = generate_population(
                seed=draft.seed,
                preset=preset,
                total_token=total_token,
                total_usdx=total_usdx,
                planner_kind="openai" if draft.mode != "test_fixture" else "rule",
            )
            agents = generated.allocations
            definitions = generated.definitions
            background = generated.background
            preview = generated.preview
        provider_report = {**provider_report, "llm": llm_report}
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
            agent_definitions=definitions,
            background_market_sector=background,
            total_supply={draft.target_token: total_token, draft.market.quote_asset: total_usdx},
            preview=preview,
            warnings=warnings,
        )
