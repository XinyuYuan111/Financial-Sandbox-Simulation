from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError as PydanticValidationError

from sandbox.agents.configuration import compile_agent_configuration
from sandbox.agents.llm_gateway import LLMGateway
from sandbox.agents.population import generate_population
from sandbox.contracts.agent import AgentDefinition, AgentRuntimeState
from sandbox.contracts.agent_configuration import AgentConfigurationDraft, ConfigurationProvenance
from sandbox.contracts.scenario import (
    AgentConfig,
    BackgroundMarketSector,
    HolderSnapshot,
    ResolvedInitialState,
    ScenarioDraft,
)
from sandbox.core.errors import ValidationError


class HolderDataProvider(Protocol):
    name: str

    async def preflight(self, chain_id: str, target_token: str) -> dict[str, object]: ...

    async def load_finalized_snapshot(self, chain_id: str, target_token: str) -> dict[str, object]: ...


SUPPORTED_CHAIN_CATALOG: tuple[dict[str, str], ...] = (
    {"chain_id": "ethereum", "label": "Ethereum"},
    {"chain_id": "solana", "label": "Solana"},
    {"chain_id": "injective", "label": "Injective L1"},
)


def chain_catalog(configured_chain_ids: set[str]) -> list[dict[str, object]]:
    return [
        {
            **chain,
            "holder_source_configured": chain["chain_id"] in configured_chain_ids,
        }
        for chain in SUPPORTED_CHAIN_CATALOG
    ]


def synthetic_smoke_snapshot(*, seed: int, target_token: str) -> HolderSnapshot:
    """Build a deterministic, conserved holder snapshot for LLM smoke runs."""
    digest = hashlib.sha256(f"synthetic-smoke.v0.1:{seed}:{target_token}".encode()).digest()
    total_supply = 5_000_000 + int.from_bytes(digest[0:8], "big") % 95_000_001
    eligible_ratio_milli = 700 + digest[8] % 251
    coverage_ratio_milli = 650 + digest[9] % 301
    eligible_active_supply = total_supply * eligible_ratio_milli // 1_000
    inactive_supply = total_supply - eligible_active_supply
    locked_supply = inactive_supply * (450 + digest[10] % 151) // 1_000
    protocol_supply = (inactive_supply - locked_supply) * (300 + digest[11] % 201) // 1_000
    burned_supply = inactive_supply - locked_supply - protocol_supply
    covered_eligible_supply = max(
        1,
        eligible_active_supply * coverage_ratio_milli // 1_000,
    )
    active_holder_count = 5_000 + int.from_bytes(digest[12:16], "big") % 45_001
    average_balance = max(1, eligible_active_supply // active_holder_count)
    snapshot_hash = hashlib.sha256(
        f"{seed}:{target_token}:{total_supply}:{eligible_active_supply}".encode()
    ).hexdigest()
    return HolderSnapshot(
        provider="synthetic-holder-snapshot",
        chain_id="synthetic-smoke",
        target_token=target_token,
        block_height=1 + int.from_bytes(digest[16:24], "big") % 1_000_000_000,
        block_hash=f"synthetic:{snapshot_hash}",
        finalized=True,
        coverage_ratio_milli=coverage_ratio_milli,
        total_supply=total_supply,
        eligible_active_supply=eligible_active_supply,
        covered_eligible_supply=covered_eligible_supply,
        source_buckets=[
            {
                "bucket_id": "synthetic-eligible-active",
                "category": "eligible_active",
                "amount": eligible_active_supply,
                "eligible_for_active_market": True,
            },
            {
                "bucket_id": "synthetic-locked",
                "category": "locked",
                "amount": locked_supply,
                "eligible_for_active_market": False,
            },
            {
                "bucket_id": "synthetic-protocol",
                "category": "protocol",
                "amount": protocol_supply,
                "eligible_for_active_market": False,
            },
            {
                "bucket_id": "synthetic-burned",
                "category": "burned",
                "amount": burned_supply,
                "eligible_for_active_market": False,
            },
        ],
        holder_distribution={
            "active_holder_count": active_holder_count,
            "p25_balance": max(1, average_balance // 4),
            "p50_balance": average_balance,
            "p75_balance": average_balance * 3,
            "p90_balance": average_balance * 10,
            "p99_balance": average_balance * 50,
            "top_10_concentration_milli": 350 + digest[24] % 451,
        },
        content_hash=f"sha256:{snapshot_hash}",
        source_name="deterministic synthetic LLM smoke input",
        mode="synthetic-smoke",
    )


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
            snapshot = HolderSnapshot.model_validate(self._load())
        except (OSError, UnicodeError, json.JSONDecodeError, PydanticValidationError, ValidationError) as error:
            return {"ok": False, "provider": self.name, "message": str(error)}
        if chain_id != self.chain_id or snapshot.chain_id != chain_id:
            return {"ok": False, "provider": self.name, "message": "snapshot chain_id does not match the requested chain"}
        if snapshot.target_token.casefold() != target_token.casefold():
            return {"ok": False, "provider": self.name, "message": "snapshot target_token does not match the request"}
        return {
            "ok": True,
            "provider": self.name,
            "chain_id": chain_id,
            "target_token": target_token,
            "block_height": snapshot.block_height,
            "block_hash": snapshot.block_hash,
            "coverage_ratio_milli": snapshot.coverage_ratio_milli,
            "eligible_active_supply": snapshot.eligible_active_supply,
            "content_hash": snapshot.content_hash,
        }

    async def load_finalized_snapshot(self, chain_id: str, target_token: str) -> dict[str, object]:
        report = await self.preflight(chain_id, target_token)
        if not report.get("ok"):
            raise ValidationError(f"holder snapshot preflight failed: {report.get('message', 'unknown error')}")
        return self._load()


def fixture_agents() -> list[AgentConfig]:
    preset_path = Path(__file__).resolve().parents[2] / "fixtures" / "presets" / "framework-alpha.default.v0.3.json"
    preset = json.loads(preset_path.read_text(encoding="utf-8"))
    return [AgentConfig.model_validate(agent) for agent in preset["agents"]]


def definition_from_config(config: AgentConfig, *, seed: int) -> AgentDefinition:
    compiled = compile_agent_configuration(
        AgentConfigurationDraft(
            draft_id=f"resolved-{config.agent_id}",
            input_mode="preset",
            agent_id=config.agent_id,
            display_name=config.display_name,
            strategy=config.strategy,
            role_tags=config.role_tags,
            capability_set=config.capabilities,
            portfolio={"token_amount": config.token_balance, "usdx_amount": config.usdx_balance},
            provenance={
                "agent_id": ConfigurationProvenance(source="user", source_ref="resolved-agent-config", user_confirmed=True),
                "display_name": ConfigurationProvenance(source="user", source_ref="resolved-agent-config", user_confirmed=True),
                "role_tags": ConfigurationProvenance(source="user", source_ref="resolved-agent-config", user_confirmed=True),
                "capability_set": ConfigurationProvenance(source="user", source_ref="resolved-agent-config", user_confirmed=True),
            },
        ),
        seed=seed,
        ordinal=1,
        planner_kind=config.strategy,
    )
    return compiled.definition


def _explicit_preview(
    *,
    draft: ScenarioDraft,
    snapshot: HolderSnapshot,
    agents: list[AgentConfig],
    definitions: list[AgentDefinition],
    background: BackgroundMarketSector,
    active_usdx_supply: int,
) -> dict[str, object]:
    explicit_token = sum(agent.token_balance for agent in agents)
    explicit_usdx = sum(agent.usdx_balance for agent in agents)
    other_token = sum(account.token_amount for account in draft.portfolio.other_explicit_accounts)
    other_usdx = sum(account.usdx_amount for account in draft.portfolio.other_explicit_accounts)
    return {
        "preset": "fixture" if draft.agents is None and draft.population.preset == "fixture" else "resolved-agents",
        "seed": draft.seed,
        "agent_count": len(definitions),
        "archetype_counts": {},
        "assets": {
            "token_total_before": snapshot.total_supply,
            "eligible_active_token_supply": snapshot.eligible_active_supply,
            "covered_eligible_token_supply": snapshot.covered_eligible_supply,
            "inactive_token_supply": snapshot.total_supply - snapshot.eligible_active_supply,
            "explicit_agent_token": explicit_token,
            "other_explicit_token": other_token,
            "background_token": background.token_balance,
            "token_total_after": explicit_token + other_token + background.token_balance + snapshot.total_supply - snapshot.eligible_active_supply,
            "active_usdx_supply": active_usdx_supply,
            "explicit_agent_usdx": explicit_usdx,
            "other_explicit_usdx": other_usdx,
            "background_usdx": background.usdx_balance,
            "usdx_total_before": active_usdx_supply,
            "usdx_total_after": explicit_usdx + other_usdx + background.usdx_balance,
            "token_conserved": explicit_token + other_token + background.token_balance + snapshot.total_supply - snapshot.eligible_active_supply == snapshot.total_supply,
            "usdx_conserved": explicit_usdx + other_usdx + background.usdx_balance == active_usdx_supply,
            "background_derivation": "eligible_or_active_supply_minus_explicit_accounts",
        },
        "portfolio_distribution": {
            "synthesis_version": draft.portfolio.synthesis_distribution_version,
            "composition_version": draft.portfolio.composition_distribution_version,
            "token_distribution": "manual-resolved",
            "token_usdx_correlation_milli": draft.portfolio.token_usdx_correlation_milli,
            "manual_token_overrides": len(agents),
            "manual_usdx_overrides": len(agents),
            "token_min": min(agent.token_balance for agent in agents),
            "token_max": max(agent.token_balance for agent in agents),
            "usdx_min": min(agent.usdx_balance for agent in agents),
            "usdx_max": max(agent.usdx_balance for agent in agents),
            "token_top_5": sorted((agent.token_balance for agent in agents), reverse=True)[:5],
            "usdx_top_5": sorted((agent.usdx_balance for agent in agents), reverse=True)[:5],
            "seed": draft.seed,
        },
        "background": {"enabled": background.enabled, "two_sided_ready": background.two_sided_ready},
        "configuration": {
            "compiler_version": "agent-configuration-compiler.v0.1",
            "input_modes": ["preset"],
            "ambiguities": [],
        },
    }


@dataclass(slots=True)
class Initializer:
    holder_providers: dict[str, HolderDataProvider]
    llm_gateway: LLMGateway

    async def resolve(self, scenario_id: str, draft: ScenarioDraft) -> ResolvedInitialState:
        input_agents = draft.agents if draft.agents is not None else (
            fixture_agents() if draft.population.preset == "fixture" and draft.agent_configuration_drafts is None else []
        )
        if len({agent.agent_id for agent in input_agents}) != len(input_agents):
            raise ValidationError("agent_id values must be unique")

        if draft.mode == "test_fixture":
            snapshot_path = Path(__file__).resolve().parents[2] / "fixtures" / "holder_snapshots" / "framework-alpha.fixture.v0.3.json"
            raw_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            raw_snapshot["target_token"] = draft.target_token
            snapshot = HolderSnapshot.model_validate(raw_snapshot)
            provider_report: dict[str, object] = {
                "mode": "fixture",
                "provider": snapshot.provider,
                "ok": True,
                "coverage_ratio_milli": snapshot.coverage_ratio_milli,
                "eligible_active_supply": snapshot.eligible_active_supply,
            }
            warnings = ["Explicit test fixture mode: no live chain or LLM provider was used."]
            llm_report: dict[str, object] = {"ok": True, "provider": "fixture", "model": "deterministic", "mode": "fixture"}
        elif draft.mode == "live_llm_smoke":
            assert draft.llm_provider is not None
            snapshot = synthetic_smoke_snapshot(seed=draft.seed, target_token=draft.target_token)
            llm_report = await self.llm_gateway.preflight(draft.llm_provider)
            provider_report = {
                "mode": "live_llm_smoke",
                "provider": snapshot.provider,
                "ok": True,
                "synthetic": True,
                "total_supply": snapshot.total_supply,
                "eligible_active_supply": snapshot.eligible_active_supply,
            }
            warnings = [
                "LLM smoke mode uses deterministic synthetic Token and USDx supplies; no live holder data was used."
            ]
        else:
            assert draft.chain_id is not None and draft.llm_provider is not None
            provider = self.holder_providers.get(draft.chain_id)
            if provider is None:
                raise ValidationError(
                    f"holder provider for chain '{draft.chain_id}' is not configured; "
                    "set SANDBOX_HOLDER_CHAIN_ID and SANDBOX_HOLDER_SNAPSHOT_PATH"
                )
            provider_report = await provider.preflight(draft.chain_id, draft.target_token)
            if not provider_report.get("ok"):
                raise ValidationError(f"holder provider preflight failed: {provider_report.get('message', 'unknown error')}")
            llm_report = await self.llm_gateway.preflight(draft.llm_provider)
            snapshot = HolderSnapshot.model_validate(
                await provider.load_finalized_snapshot(draft.chain_id, draft.target_token)
            )
            warnings = []

        active_usdx_supply = (
            snapshot.eligible_active_supply
            * draft.market.initial_mid_price
            * draft.portfolio.quote_coverage_ratio_ppm
            // 1_000_000
        )
        if active_usdx_supply <= 0:
            raise ValidationError("Quote Coverage Ratio produces no active USDx supply")
        other_token = sum(account.token_amount for account in draft.portfolio.other_explicit_accounts)
        other_usdx = sum(account.usdx_amount for account in draft.portfolio.other_explicit_accounts)

        if input_agents:
            agents = list(input_agents)
            token_assigned = sum(agent.token_balance for agent in agents)
            usdx_assigned = sum(agent.usdx_balance for agent in agents)
            if token_assigned + other_token > snapshot.eligible_active_supply:
                raise ValidationError("explicit Agent Token balances exceed Eligible Active Supply")
            if usdx_assigned + other_usdx > active_usdx_supply:
                raise ValidationError("explicit Agent USDx balances exceed active USDx supply")
            if draft.agent_definitions is not None:
                definitions = list(draft.agent_definitions)
                definition_ids = [definition.agent_id for definition in definitions]
                if len(definition_ids) != len(set(definition_ids)):
                    raise ValidationError("agent definition ids must be unique")
                configurations = {agent.agent_id: agent for agent in agents}
                if set(definition_ids) != set(configurations):
                    raise ValidationError("agent_definitions must match the explicit agents exactly")
                for definition in definitions:
                    config = configurations[definition.agent_id]
                    if (
                        definition.display_name != config.display_name
                        or definition.role_tags != config.role_tags
                        or definition.capability_set != config.capabilities
                    ):
                        raise ValidationError(f"AgentDefinition conflicts with AgentConfig for '{definition.agent_id}'")
            else:
                definitions = [definition_from_config(agent, seed=draft.seed) for agent in agents]
            background = BackgroundMarketSector(
                token_balance=snapshot.eligible_active_supply - token_assigned - other_token,
                usdx_balance=active_usdx_supply - usdx_assigned - other_usdx,
                enabled=True,
                two_sided_ready=(
                    snapshot.eligible_active_supply - token_assigned - other_token > 0
                    and active_usdx_supply - usdx_assigned - other_usdx > 0
                ),
            )
            if not background.two_sided_ready:
                raise ValidationError("background market requires positive residual Token and USDx balances")
            preview = _explicit_preview(
                draft=draft,
                snapshot=snapshot,
                agents=agents,
                definitions=definitions,
                background=background,
                active_usdx_supply=active_usdx_supply,
            )
        else:
            preset = draft.population.preset
            if draft.mode == "live_llm_smoke":
                preset = "smoke"
            elif draft.mode == "live" and preset == "fixture":
                preset = "standard"
            generated = generate_population(
                seed=draft.seed,
                preset=preset,
                agent_count=draft.population.agent_count,
                eligible_active_supply=snapshot.eligible_active_supply,
                covered_eligible_supply=snapshot.covered_eligible_supply,
                total_token_supply=snapshot.total_supply,
                active_usdx_supply=active_usdx_supply,
                holder_distribution=snapshot.holder_distribution,
                portfolio=draft.portfolio,
                planner_kind=draft.llm_provider or "rule",
                drafts=list(draft.agent_configuration_drafts) if draft.agent_configuration_drafts is not None else None,
            )
            agents = generated.allocations
            definitions = generated.definitions
            background = generated.background
            preview = generated.preview

        preview = {
            **preview,
            "source_buckets": [bucket.model_dump(mode="json") for bucket in snapshot.source_buckets],
            "market": {
                "initial_mid_price": draft.market.initial_mid_price,
                "quote_coverage_ratio_ppm": draft.portfolio.quote_coverage_ratio_ppm,
                "active_usdx_supply": active_usdx_supply,
                "price_tick": draft.market.price_tick,
                "target_spread_bps": background.target_spread_bps,
                "impact_target_bps": background.impact_target_bps,
                "quote_levels": background.quote_levels,
                "background_participation_policy_id": background.participation_policy_id,
            },
        }
        provider_report = {**provider_report, "llm": llm_report}
        initial_states = list(draft.initial_agent_states or [])
        if initial_states:
            state_ids = [state.agent_id for state in initial_states]
            definition_ids = {definition.agent_id for definition in definitions}
            if len(state_ids) != len(set(state_ids)) or not set(state_ids).issubset(definition_ids):
                raise ValidationError("initial_agent_states must be unique and belong to configured Agents")

        agent_ids = {agent.agent_id for agent in agents}
        source_account_ids = {
            f"source:{bucket.bucket_id}"
            for bucket in snapshot.source_buckets
            if not bucket.eligible_for_active_market
        }
        reserved_account_ids = {
            background.sector_id,
            background.flow_account_id,
            "fee_account",
            "genesis_asset_pool",
            *source_account_ids,
        }
        other_account_ids = {account.account_id for account in draft.portfolio.other_explicit_accounts}
        collisions = sorted(
            (agent_ids & reserved_account_ids)
            | (other_account_ids & reserved_account_ids)
            | (other_account_ids & agent_ids)
        )
        if collisions:
            raise ValidationError(f"initial account ids collide with reserved or Agent accounts: {', '.join(collisions)}")
        if draft.target_token == draft.market.quote_asset:
            raise ValidationError("target Token and quote asset must be distinct")

        unresolved = ResolvedInitialState(
            scenario_id=scenario_id,
            name=draft.name,
            mode=draft.mode,
            seed=draft.seed,
            preset_version=draft.preset_version,
            provider_report=provider_report,
            chain_snapshot=snapshot,
            market=draft.market.model_copy(update={"base_asset": draft.target_token}),
            portfolio=draft.portfolio,
            agents=agents,
            agent_definitions=definitions,
            initial_agent_states=initial_states,
            other_explicit_accounts=draft.portfolio.other_explicit_accounts,
            background_market_sector=background,
            total_supply={draft.target_token: snapshot.total_supply, draft.market.quote_asset: active_usdx_supply},
            preview=preview,
            warnings=warnings,
            resolution_hash="unresolved",
        )
        canonical = json.dumps(
            unresolved.model_dump(mode="json", exclude={"resolution_hash"}),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return unresolved.model_copy(update={"resolution_hash": "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()})
