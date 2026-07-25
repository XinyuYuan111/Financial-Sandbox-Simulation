from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sandbox.contracts.agent import ActionReceipt, DecisionTrigger


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BalanceView(StrictFrozenModel):
    free: int = Field(ge=0)
    locked: int = Field(ge=0)


class OrderView(StrictFrozenModel):
    order_id: str
    agent_id: str
    side: Literal["buy", "sell"]
    order_type: Literal["limit", "protected_market"]
    price: int | None = Field(default=None, ge=1)
    worst_price: int | None = Field(default=None, ge=1)
    quantity: int = Field(ge=1)
    remaining: int = Field(ge=0)
    status: str
    submitted_seq: int = Field(ge=1)
    locked_amount: int = Field(default=0, ge=0)


class TradeView(StrictFrozenModel):
    trade_id: str
    buy_order_id: str
    sell_order_id: str
    buyer_id: str
    seller_id: str
    quantity: int = Field(ge=1)
    price: int = Field(ge=1)
    buyer_fee: int = Field(ge=0)
    seller_fee: int = Field(ge=0)


class MarketObservation(StrictFrozenModel):
    market_id: str
    base_asset: str = "TOKEN"
    quote_asset: str = "USDX"
    price_tick: int = Field(default=1, ge=1)
    bids: list[OrderView] = Field(default_factory=list)
    asks: list[OrderView] = Field(default_factory=list)
    last_trade: TradeView | None = None
    trades: list[TradeView] = Field(default_factory=list)


class ObservedInformation(StrictFrozenModel):
    information_id: str
    source_id: str
    channel: str
    rendered_content: str = Field(max_length=4_000)
    sim_time_us: int = Field(ge=0)
    delivered_sim_time_us: int | None = Field(default=None, ge=0)
    viewed_sim_time_us: int | None = Field(default=None, ge=0)
    expires_sim_time_us: int | None = Field(default=None, ge=0)
    target_ids: list[str] = Field(default_factory=list)
    visibility: Literal["public", "agent_private"]
    signal_direction: Literal["bullish", "bearish", "neutral"] | None = None
    signal_confidence_milli: int | None = Field(default=None, ge=0, le=1_000)
    derived_from_info_id: str | None = None
    intervention_plan_id: str | None = None
    intervention_stage_id: str | None = None
    effect_id: str | None = None


class AgentAccountSnapshot(StrictFrozenModel):
    agent_id: str
    portfolio_revision: int = Field(ge=0)
    balances: dict[str, BalanceView] = Field(default_factory=dict)
    wallet_permissions: dict[str, list[Literal["observe", "transact"]]] = Field(default_factory=dict)
    accessible_wallet_balances: dict[str, dict[str, BalanceView]] = Field(default_factory=dict)
    positions: dict[str, int] = Field(default_factory=dict)
    open_orders: list[OrderView] = Field(default_factory=list)
    pending_action_ids: list[str] = Field(default_factory=list)
    reservation_ids: list[str] = Field(default_factory=list)
    risk_refs: list[str] = Field(default_factory=list)


class AttentionDecision(StrictFrozenModel):
    policy: str
    selected: int = Field(ge=0)
    dropped: int = Field(default=0, ge=0)
    reason_code: str = "within_capacity"


class ObservationPacket(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    observation_id: str
    agent_id: str
    branch_id: str
    sim_time_us: int = Field(ge=0)
    world_version: int = Field(ge=0)
    decision_triggers: list[DecisionTrigger] = Field(default_factory=list, max_length=32)
    market_view: MarketObservation
    account_snapshot: AgentAccountSnapshot | None = None
    # Kept as a compatibility projection for observation.v0.2 archives and clients.
    portfolio_view: dict[str, object] = Field(default_factory=dict)
    information_items: list[ObservedInformation] = Field(default_factory=list)
    private_messages: list[ObservedInformation] = Field(default_factory=list)
    action_receipts: list[ActionReceipt] = Field(default_factory=list)
    chain_view: dict[str, object] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    observation_delays: dict[str, int] = Field(default_factory=dict)
    provenance: list[str] = Field(default_factory=list)
    attention_decisions: list[AttentionDecision] = Field(default_factory=list)
    schema_version: Literal["observation.v0.2", "observation.v0.3"] = "observation.v0.3"
