from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sandbox.contracts.agent import AgentDefinition, AgentRuntimeState
from sandbox.contracts.agent_configuration import AgentConfigurationDraft, ConfigurationProvenance


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    agent_id: str
    display_name: str
    strategy: Literal["rule", "replay", "openai", "deepseek"]
    role_tags: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(
        default_factory=lambda: ["market.trade", "information.read", "information.publish"]
    )
    token_balance: int = Field(ge=0)
    usdx_balance: int = Field(ge=0)
    configuration_provenance: dict[str, ConfigurationProvenance] = Field(default_factory=dict)

class TokenSourceBucket(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    bucket_id: str = Field(min_length=1, max_length=128)
    category: Literal["eligible_active", "locked", "burned", "protocol", "bridge", "custody_uncertain", "other"]
    amount: int = Field(ge=0)
    eligible_for_active_market: bool


class HolderDistribution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    distribution_version: Literal["holder-distribution.v0.1"] = "holder-distribution.v0.1"
    active_holder_count: int = Field(ge=1)
    p25_balance: int = Field(ge=0)
    p50_balance: int = Field(ge=0)
    p75_balance: int = Field(ge=0)
    p90_balance: int = Field(ge=0)
    p99_balance: int = Field(ge=0)
    top_10_concentration_milli: int = Field(ge=0, le=1_000)

    @model_validator(mode="after")
    def validate_quantiles(self) -> "HolderDistribution":
        values = [self.p25_balance, self.p50_balance, self.p75_balance, self.p90_balance, self.p99_balance]
        if values != sorted(values):
            raise ValueError("holder balance quantiles must be non-decreasing")
        return self


class HolderSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["holder-snapshot.v0.3"] = "holder-snapshot.v0.3"
    provider: str = Field(min_length=1, max_length=128)
    chain_id: str = Field(min_length=1, max_length=128)
    target_token: str = Field(min_length=1, max_length=128)
    block_height: int = Field(ge=0)
    block_hash: str = Field(min_length=1, max_length=256)
    finalized: Literal[True]
    coverage_ratio_milli: int = Field(gt=0, le=1_000)
    total_supply: int = Field(gt=0)
    eligible_active_supply: int = Field(gt=0)
    covered_eligible_supply: int = Field(gt=0)
    source_buckets: list[TokenSourceBucket] = Field(min_length=1, max_length=64)
    holder_distribution: HolderDistribution
    content_hash: str | None = Field(default=None, max_length=256)
    source_name: str | None = Field(default=None, max_length=256)
    retrieved_at: str | None = Field(default=None, max_length=128)
    mode: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_supply_classification(self) -> "HolderSnapshot":
        if len({bucket.bucket_id for bucket in self.source_buckets}) != len(self.source_buckets):
            raise ValueError("source bucket ids must be unique")
        if sum(bucket.amount for bucket in self.source_buckets) != self.total_supply:
            raise ValueError("source buckets must sum to total_supply")
        eligible = sum(bucket.amount for bucket in self.source_buckets if bucket.eligible_for_active_market)
        if eligible != self.eligible_active_supply:
            raise ValueError("eligible source buckets must sum to eligible_active_supply")
        if self.covered_eligible_supply > self.eligible_active_supply:
            raise ValueError("covered_eligible_supply cannot exceed eligible_active_supply")
        coverage_delta = abs(
            self.covered_eligible_supply * 1_000
            - self.eligible_active_supply * self.coverage_ratio_milli
        )
        if coverage_delta > self.eligible_active_supply:
            raise ValueError("covered_eligible_supply must match coverage_ratio_milli within one milli")
        return self


class ExplicitAssetAccount(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    account_id: str = Field(min_length=1, max_length=256)
    token_amount: int = Field(default=0, ge=0)
    usdx_amount: int = Field(default=0, ge=0)


class PortfolioSynthesisConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    token_distribution: Literal["long_tail", "equal", "manual"] = "long_tail"
    synthesis_distribution_version: Literal["portfolio-synthesis.v0.1"] = "portfolio-synthesis.v0.1"
    composition_distribution_version: Literal["portfolio-composition.v0.1"] = "portfolio-composition.v0.1"
    quote_coverage_ratio_ppm: int = Field(default=1_000_000, ge=1, le=10_000_000)
    token_usdx_correlation_milli: int = Field(default=350, ge=0, le=1_000)
    explicit_token_budget: int | None = Field(default=None, ge=0)
    other_explicit_accounts: list[ExplicitAssetAccount] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def validate_accounts(self) -> "PortfolioSynthesisConfig":
        if len({account.account_id for account in self.other_explicit_accounts}) != len(self.other_explicit_accounts):
            raise ValueError("other explicit account ids must be unique")
        if self.token_distribution == "manual" and self.explicit_token_budget is not None:
            raise ValueError("manual Token allocation is defined by per-Agent amounts, not an aggregate budget")
        return self


class BackgroundMarketSector(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    sector_id: str = "background"
    flow_account_id: str = "background_order_flow"
    token_balance: int = Field(default=0, ge=0)
    usdx_balance: int = Field(default=0, ge=0)
    enabled: bool = True
    two_sided_ready: bool = False
    participation_policy_id: str = "background.seeded.v0.2"
    target_spread_bps: int = Field(default=20, ge=0, le=10_000)
    impact_target_bps: int = Field(default=400, ge=1, le=10_000)
    quote_levels: int = Field(default=5, ge=1, le=20)
    quote_refresh_interval_us: int = Field(default=1_000_000, ge=1)
    quote_size_fraction_ppm: int = Field(default=100_000, ge=1, le=1_000_000)
    flow_inventory_fraction_ppm: int = Field(default=200_000, ge=1, le=500_000)
    taker_probability_milli: int = Field(default=300, ge=0, le=1_000)
    directional_limit_probability_milli: int = Field(default=250, ge=0, le=1_000)
    schema_version: Literal["background-market-sector.v0.1"] = "background-market-sector.v0.1"

    @model_validator(mode="after")
    def validate_order_flow_policy(self) -> "BackgroundMarketSector":
        if self.flow_account_id == self.sector_id:
            raise ValueError("background flow account must differ from the maker account")
        if self.taker_probability_milli + self.directional_limit_probability_milli > 1_000:
            raise ValueError("background order-flow probabilities cannot exceed 1000 milli")
        return self


class PopulationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    preset: Literal["fixture", "smoke", "compact", "standard"] = "fixture"
    agent_count: int | None = Field(default=None, ge=1, le=10_000)


class MarketConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    market_id: str = "TOKEN-USDX"
    base_asset: str = "TOKEN"
    quote_asset: str = "USDX"
    base_scale: int = Field(default=1, ge=1)
    quote_scale: int = Field(default=1, ge=1)
    price_tick: int = Field(default=10, ge=1)
    maker_fee_bps: int = Field(default=5, ge=0, le=1_000)
    taker_fee_bps: int = Field(default=10, ge=0, le=1_000)
    initial_mid_price: int = Field(default=10_000, ge=1)


class ScenarioDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(default="Framework Alpha fixture", min_length=1, max_length=128)
    mode: Literal["test_fixture", "live_llm_smoke", "live"] = "test_fixture"
    seed: int = 20260723
    chain_id: str | None = None
    target_token: str = "TOKEN"
    llm_provider: str | None = None
    preset_version: str = "framework-alpha.default.v0.3"
    population: PopulationConfig = Field(default_factory=PopulationConfig)
    market: MarketConfig = Field(default_factory=MarketConfig)
    portfolio: PortfolioSynthesisConfig = Field(default_factory=PortfolioSynthesisConfig)
    agents: list[AgentConfig] | None = None
    agent_definitions: list[AgentDefinition] | None = None
    agent_configuration_drafts: list[AgentConfigurationDraft] | None = None
    initial_agent_states: list[AgentRuntimeState] | None = None

    @model_validator(mode="after")
    def validate_live_inputs(self) -> "ScenarioDraft":
        if self.mode == "live" and (not self.chain_id or not self.llm_provider):
            raise ValueError("live mode requires chain_id and llm_provider")
        if self.mode == "live" and "target_token" not in self.__pydantic_fields_set__:
            raise ValueError("live mode requires an explicit target_token")
        if self.mode == "live_llm_smoke" and not self.llm_provider:
            raise ValueError("live_llm_smoke mode requires llm_provider")
        if self.agent_configuration_drafts is not None and (self.agents is not None or self.agent_definitions is not None):
            raise ValueError("agent_configuration_drafts cannot be combined with resolved Agent inputs")
        if self.agent_definitions is not None and self.agents is None:
            raise ValueError("agent_definitions require matching Agent allocations")
        return self


class ResolvedInitialState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    scenario_id: str
    name: str
    mode: Literal["test_fixture", "live_llm_smoke", "live"]
    seed: int
    preset_version: str
    provider_report: dict[str, object]
    chain_snapshot: HolderSnapshot
    market: MarketConfig
    portfolio: PortfolioSynthesisConfig
    agents: list[AgentConfig]
    agent_definitions: list[AgentDefinition] = Field(default_factory=list)
    initial_agent_states: list[AgentRuntimeState] = Field(default_factory=list)
    other_explicit_accounts: list[ExplicitAssetAccount] = Field(default_factory=list)
    background_market_sector: BackgroundMarketSector = Field(default_factory=BackgroundMarketSector)
    total_supply: dict[str, int]
    preview: dict[str, object] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    resolution_hash: str = Field(min_length=8, max_length=256)
    schema_version: Literal["resolved-initial-state.v0.3"] = "resolved-initial-state.v0.3"
