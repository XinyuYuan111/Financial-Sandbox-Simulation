from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    agent_id: str
    display_name: str
    strategy: Literal["rule", "replay", "background"]
    role_tags: list[str] = Field(default_factory=list)
    funding_profile: str
    capabilities: list[str] = Field(default_factory=lambda: ["market.trade", "information.read"])
    token_balance: int = Field(ge=0)
    usdx_balance: int = Field(ge=0)


class MarketConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    market_id: str = "TOKEN-USDX"
    base_asset: str = "TOKEN"
    quote_asset: str = "USDX"
    base_scale: int = Field(default=1, ge=1)
    quote_scale: int = Field(default=1, ge=1)
    price_tick: int = Field(default=1, ge=1)
    maker_fee_bps: int = Field(default=5, ge=0, le=1_000)
    taker_fee_bps: int = Field(default=10, ge=0, le=1_000)
    initial_mid_price: int = Field(default=100, ge=1)


class ScenarioDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(default="Framework Alpha fixture", min_length=1, max_length=128)
    mode: Literal["test_fixture", "live"] = "test_fixture"
    seed: int = 20260723
    chain_id: str | None = None
    target_token: str = "TOKEN"
    llm_provider: str | None = None
    preset_version: Literal["framework-alpha.default.v0.2"] = "framework-alpha.default.v0.2"
    market: MarketConfig = Field(default_factory=MarketConfig)
    agents: list[AgentConfig] | None = None

    @model_validator(mode="after")
    def validate_live_inputs(self) -> "ScenarioDraft":
        if self.mode == "live" and (not self.chain_id or not self.llm_provider):
            raise ValueError("live mode requires chain_id and llm_provider")
        return self


class ResolvedInitialState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    scenario_id: str
    name: str
    mode: Literal["test_fixture", "live"]
    seed: int
    preset_version: str
    provider_report: dict[str, object]
    chain_snapshot: dict[str, object]
    market: MarketConfig
    agents: list[AgentConfig]
    total_supply: dict[str, int]
    warnings: list[str] = Field(default_factory=list)
    schema_version: Literal["resolved-initial-state.v0.2"] = "resolved-initial-state.v0.2"
