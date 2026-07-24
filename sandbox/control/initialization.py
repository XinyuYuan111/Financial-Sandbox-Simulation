from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sandbox.agents.llm_gateway import LLMGateway
from sandbox.agents.population import generate_population
from sandbox.contracts.agent import AgentDefinition, AgentRuntimeState, BasePersona
from sandbox.contracts.scenario import AgentConfig, BackgroundMarketSector, ResolvedInitialState, ScenarioDraft
from sandbox.core.errors import ValidationError


class HolderDataProvider(Protocol):
    name: str

    async def preflight(self, chain_id: str, target_token: str) -> dict[str, object]: ...

    async def load_finalized_snapshot(self, chain_id: str, target_token: str) -> dict[str, object]: ...


@dataclass(slots=True)
class FinalizedSnapshotFileProvider:
    path: Path
    chain_id: str
    name: str = "finalized_snapshot_file"
    max_bytes: int = 16 * 1024 * 1024
    _cached_mtime_ns: int | None = None
    _cached_snapshot: dict[str, object] | None = None

    def _load(self) -> dict[str, object]:
        stat = self.path.stat()
        if stat.st_size > self.max_bytes:
            raise ValidationError("holder snapshot exceeds the 16 MiB limit")
        if self._cached_snapshot is not None and self._cached_mtime_ns == stat.st_mtime_ns:
            return dict(self._cached_snapshot)
        raw = self.path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValidationError("holder snapshot root must be an object")
        snapshot = dict(value)
        snapshot["provider"] = self.name
        snapshot["content_hash"] = "sha256:" + hashlib.sha256(raw).hexdigest()
        snapshot["source_name"] = self.path.name
        self._cached_mtime_ns = stat.st_mtime_ns
        self._cached_snapshot = snapshot
        return dict(snapshot)

    async def preflight(self, chain_id: str, target_token: str) -> dict[str, object]:
        try:
            snapshot = self._load()
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            return {"ok": False, "provider": self.name, "message": str(error)}
        if chain_id != self.chain_id or snapshot.get("chain_id") != chain_id:
            return {"ok": False, "provider": self.name, "message": "snapshot chain_id does not match the requested chain"}
        if str(snapshot.get("target_token", "")).casefold() != target_token.casefold():
            return {"ok": False, "provider": self.name, "message": "snapshot target_token does not match the request"}
        if snapshot.get("finalized") is not True or not snapshot.get("block_hash") or snapshot.get("block_height") is None:
            return {"ok": False, "provider": self.name, "message": "snapshot lacks a finalized block boundary"}
        if int(snapshot.get("coverage_ratio_milli", 0)) <= 0 or int(snapshot.get("total_supply", 0)) <= 0:
            return {"ok": False, "provider": self.name, "message": "snapshot requires positive coverage and total_supply"}
        return {
            "ok": True,
            "provider": self.name,
            "chain_id": chain_id,
            "target_token": target_token,
            "block_height": snapshot["block_height"],
            "block_hash": snapshot["block_hash"],
            "coverage_ratio_milli": snapshot["coverage_ratio_milli"],
            "content_hash": snapshot["content_hash"],
        }

    async def load_finalized_snapshot(self, chain_id: str, target_token: str) -> dict[str, object]:
        report = await self.preflight(chain_id, target_token)
        if not report.get("ok"):
            raise ValidationError(f"holder snapshot preflight failed: {report.get('message', 'unknown error')}")
        return self._load()


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
            if draft.agent_definitions is not None:
                configured_ids = {definition.agent_id for definition in draft.agent_definitions}
                agent_ids = {agent.agent_id for agent in agents}
                if configured_ids != agent_ids:
                    raise ValidationError("agent_definitions must match the explicit agents exactly")
                definitions = list(draft.agent_definitions)
            else:
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
        initial_states = list(draft.initial_agent_states or [])
        if initial_states:
            state_ids = {state.agent_id for state in initial_states}
            definition_ids = {definition.agent_id for definition in definitions}
            if len(state_ids) != len(initial_states) or not state_ids.issubset(definition_ids):
                raise ValidationError("initial_agent_states must be unique and belong to configured Agents")
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
            initial_agent_states=initial_states,
            background_market_sector=background,
            total_supply={draft.target_token: total_token, draft.market.quote_asset: total_usdx},
            preview=preview,
            warnings=warnings,
        )
