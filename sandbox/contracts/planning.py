from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sandbox.contracts.agent import DecisionRationale, DirectiveExecutionCursor


ConditionPath = Literal[
    "market.last_price_tick",
    "market.spread_bps",
    "market.recent_volume",
    "account.free_base",
    "account.free_quote",
    "account.position_base",
    "belief.confidence_milli",
    "observation.has_information_tag",
    "own_action_outcome.code",
    "sim_time_us",
]
CompareOperator = Literal["lt", "lte", "eq", "neq", "gte", "gt", "contains"]


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CompareCondition(StrictFrozenModel):
    type: Literal["compare"] = "compare"
    path: ConditionPath
    op: CompareOperator
    value: int | str | bool


class AllOfCondition(StrictFrozenModel):
    type: Literal["all_of"] = "all_of"
    conditions: list["ConditionExpr"] = Field(min_length=1, max_length=16)


class AnyOfCondition(StrictFrozenModel):
    type: Literal["any_of"] = "any_of"
    conditions: list["ConditionExpr"] = Field(min_length=1, max_length=16)


class NotCondition(StrictFrozenModel):
    type: Literal["not"] = "not"
    condition: "ConditionExpr"


ConditionExpr: TypeAlias = Annotated[
    CompareCondition | AllOfCondition | AnyOfCondition | NotCondition,
    Field(discriminator="type"),
]


class EmissionPolicy(StrictFrozenModel):
    mode: Literal["once", "on_guard_transition", "periodic", "while_guarded"]
    max_emissions: int = Field(default=1, ge=1, le=10_000)
    interval_us: int | None = Field(default=None, ge=1)
    cooldown_us: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_timing(self) -> "EmissionPolicy":
        if self.mode == "periodic" and self.interval_us is None:
            raise ValueError("periodic emission requires interval_us")
        if self.mode == "while_guarded" and self.cooldown_us is None:
            raise ValueError("while_guarded emission requires cooldown_us")
        return self


class TradeDirective(StrictFrozenModel):
    type: Literal["trade"] = "trade"
    directive_key: str = Field(min_length=1, max_length=128)
    side: Literal["buy", "sell"]
    style: Literal["passive", "aggressive", "protected_market"]
    max_quantity: int = Field(ge=1)
    max_notional: int | None = Field(default=None, ge=1)
    price_offset_bps: int = Field(default=0, ge=-10_000, le=10_000)
    guard: ConditionExpr | None = None
    emission: EmissionPolicy


class QuoteDirective(StrictFrozenModel):
    type: Literal["quote"] = "quote"
    directive_key: str = Field(min_length=1, max_length=128)
    side: Literal["both", "buy", "sell"] = "both"
    target_spread_bps: int = Field(ge=0, le=10_000)
    max_quantity_per_side: int = Field(ge=1)
    inventory_target: int | None = None
    refresh_interval_us: int = Field(ge=1)
    guard: ConditionExpr | None = None
    emission: EmissionPolicy


class CancelDirective(StrictFrozenModel):
    type: Literal["cancel"] = "cancel"
    directive_key: str = Field(min_length=1, max_length=128)
    order_id: str | None = None
    side: Literal["buy", "sell"] | None = None
    plan_revision: int | None = Field(default=None, ge=1)
    guard: ConditionExpr | None = None
    emission: EmissionPolicy

    @model_validator(mode="after")
    def validate_selector(self) -> "CancelDirective":
        if self.order_id is None and self.side is None and self.plan_revision is None:
            raise ValueError("cancel directive requires a selector")
        return self


class CommunicationDirective(StrictFrozenModel):
    type: Literal["communication"] = "communication"
    directive_key: str = Field(min_length=1, max_length=128)
    channel: Literal["PublicFeed", "OfficialAnnouncement", "TradingTerminal", "PrivateChannel"]
    communication_mode: Literal["disclose", "withhold"] = "disclose"
    message_payload: str = Field(default="", max_length=4_000)
    target_ids: list[str] = Field(default_factory=list, max_length=64)
    signal_direction: Literal["bullish", "bearish", "neutral"] | None = None
    signal_confidence_milli: int | None = Field(default=None, ge=0, le=1_000)
    claim_intent: Literal["sincere", "strategic_deception"] = "sincere"
    private_assessment_direction: Literal["bullish", "bearish", "neutral"] | None = None
    derived_from_info_id: str | None = Field(default=None, min_length=1, max_length=256)
    guard: ConditionExpr | None = None
    emission: EmissionPolicy

    @model_validator(mode="after")
    def validate_targets(self) -> "CommunicationDirective":
        if self.communication_mode == "withhold":
            if self.target_ids:
                raise ValueError("withheld communication cannot declare recipients")
            if self.message_payload or self.signal_direction is not None or self.signal_confidence_milli is not None:
                raise ValueError("withheld communication cannot contain a released claim")
            if self.claim_intent != "sincere" or self.private_assessment_direction is None:
                raise ValueError("withheld communication requires only a private assessment")
            return self
        if not self.message_payload.strip():
            raise ValueError("disclosed communication requires a message")
        if self.channel == "PrivateChannel" and not self.target_ids:
            raise ValueError("private communication requires target_ids")
        if self.channel != "PrivateChannel" and self.target_ids:
            raise ValueError("public communication channels cannot declare target_ids")
        if (self.signal_direction is None) != (self.signal_confidence_milli is None):
            raise ValueError("communication signal direction and confidence must be supplied together")
        if self.claim_intent == "strategic_deception":
            if self.signal_direction is None or self.private_assessment_direction is None:
                raise ValueError("strategic deception requires a claimed and private direction")
            if self.signal_direction == self.private_assessment_direction:
                raise ValueError("strategic deception must contradict the private assessment")
        elif (
            self.signal_direction is not None
            and self.private_assessment_direction is not None
            and self.signal_direction != self.private_assessment_direction
        ):
            raise ValueError("a sincere claim cannot contradict the private assessment")
        return self


Directive: TypeAlias = Annotated[
    TradeDirective | QuoteDirective | CancelDirective | CommunicationDirective,
    Field(discriminator="type"),
]


class Goal(StrictFrozenModel):
    goal_key: str = Field(min_length=1, max_length=128)
    priority: int = Field(ge=0, le=100)


class Constraint(StrictFrozenModel):
    kind: Literal["max_order_notional", "max_position_base", "min_free_quote", "allowed_action_count"]
    amount: int = Field(ge=0)


class PlanningResultCandidate(StrictFrozenModel):
    based_on_strategy_revision: int = Field(ge=0)
    valid_for_us: int = Field(ge=1)
    goals: list[Goal] = Field(default_factory=list, max_length=16)
    activation_preconditions: list[ConditionExpr] = Field(default_factory=list, max_length=16)
    constraints: list[Constraint] = Field(default_factory=list, max_length=16)
    directives: list[Directive] = Field(default_factory=list, max_length=32)
    replan_conditions: list[ConditionExpr] = Field(default_factory=list, max_length=16)
    rationale: DecisionRationale
    schema_version: Literal["planning-result-candidate.v0.1"] = "planning-result-candidate.v0.1"


class StrategyPlan(StrictFrozenModel):
    plan_id: str
    agent_id: str
    strategy_revision: int = Field(ge=1)
    based_on_strategy_revision: int = Field(ge=0)
    source_observation_id: str
    planning_request_id: str
    valid_from_sim_time_us: int = Field(ge=0)
    valid_until_sim_time_us: int = Field(ge=0)
    goals: list[Goal] = Field(default_factory=list, max_length=16)
    activation_preconditions: list[ConditionExpr] = Field(default_factory=list, max_length=16)
    constraints: list[Constraint] = Field(default_factory=list, max_length=16)
    directives: list[Directive] = Field(default_factory=list, max_length=32)
    replan_conditions: list[ConditionExpr] = Field(default_factory=list, max_length=16)
    schema_version: Literal["strategy-plan.v0.1"] = "strategy-plan.v0.1"

    @model_validator(mode="after")
    def validate_validity(self) -> "StrategyPlan":
        if self.valid_until_sim_time_us <= self.valid_from_sim_time_us:
            raise ValueError("strategy plan validity must be positive")
        return self


PlanningState = Literal["Queued", "Running", "Ready", "Terminal"]
PlanningTerminalOutcome = Literal["applied", "rejected", "failed", "timed_out", "canceled"]


class PlanningRequest(StrictFrozenModel):
    request_id: str
    branch_id: str
    agent_id: str
    source_decision_id: str
    source_observation_id: str
    requested_sim_time_us: int = Field(ge=0)
    activation_time_us: int = Field(ge=0)
    planner_profile_id: str
    state: PlanningState = "Queued"
    terminal_outcome: PlanningTerminalOutcome | None = None
    based_on_strategy_revision: int = Field(ge=0)
    memory_revision: int = Field(ge=0)
    belief_revision: int = Field(ge=0)
    reason_keys: list[str] = Field(default_factory=list, max_length=16)
    cognitive_budget_reserved: int = Field(default=1, ge=0)
    result_plan_id: str | None = None
    error_code: str | None = None
    schema_version: Literal["planning-request.v0.1"] = "planning-request.v0.1"

    @model_validator(mode="after")
    def validate_lifecycle_shape(self) -> "PlanningRequest":
        if self.activation_time_us < self.requested_sim_time_us:
            raise ValueError("activation_time_us must not precede request time")
        if self.state == "Terminal" and self.terminal_outcome is None:
            raise ValueError("Terminal planning request requires terminal_outcome")
        if self.state != "Terminal" and self.terminal_outcome is not None:
            raise ValueError("terminal_outcome is only valid in Terminal state")
        return self


ALLOWED_PLANNING_TRANSITIONS: dict[PlanningState, set[PlanningState]] = {
    "Queued": {"Running", "Terminal"},
    "Running": {"Ready", "Terminal"},
    "Ready": {"Terminal"},
    "Terminal": set(),
}


def validate_planning_transition(current: PlanningRequest, next_request: PlanningRequest) -> None:
    if current.request_id != next_request.request_id:
        raise ValueError("planning transition must preserve request_id")
    if next_request.state not in ALLOWED_PLANNING_TRANSITIONS[current.state]:
        raise ValueError(f"invalid planning transition {current.state} -> {next_request.state}")


class ProviderProfile(StrictFrozenModel):
    provider: str
    model: str
    endpoint_class: Literal["responses", "chat_completions"] = "responses"
    timeout_seconds: int = Field(ge=1, le=600)
    max_retries: int = Field(ge=0, le=10)
    max_in_flight: int = Field(ge=1, le=1_000)
    max_output_tokens: int = Field(ge=1, le=100_000)
    key_present: bool


class ProviderReport(StrictFrozenModel):
    ok: bool
    provider: str
    model: str
    latency_ms: int = Field(ge=0)
    structured_output_ok: bool
    request_id: str | None = None
    quota_hint: str | None = None
    checked_at: str
    message: str | None = None


class PlanningProviderRequest(StrictFrozenModel):
    request_id: str
    agent_id: str
    context_hash: str
    based_on_strategy_revision: int = Field(default=0, ge=0)
    planner_instructions: str = Field(min_length=1, max_length=10_000)
    capabilities: list[str] = Field(default_factory=list, max_length=32)
    role_tags: list[str] = Field(default_factory=list, max_length=16)
    public_identity: str = Field(default="", max_length=500)
    persona: dict[str, object]
    observation: dict[str, object]
    cognition: dict[str, object]
    account_snapshot: dict[str, object]
    current_strategy: dict[str, object] | None = None
    max_tool_rounds: int = Field(default=0, ge=0, le=3)
    schema_version: Literal["planning-provider-request.v0.1"] = "planning-provider-request.v0.1"


class LLMRecord(StrictFrozenModel):
    call_id: str
    request_id: str
    agent_id: str
    attempt: int = Field(ge=1)
    provider: str
    model: str
    context_hash: str
    redacted_request: dict[str, object]
    raw_response: dict[str, object] | str | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    latency_ms: int = Field(ge=0)
    status: Literal["succeeded", "failed", "timed_out", "late_ignored"]
    error_code: str | None = None
    schema_version: Literal["llm-record.v0.1"] = "llm-record.v0.1"


AllOfCondition.model_rebuild()
AnyOfCondition.model_rebuild()
NotCondition.model_rebuild()


__all__ = [
    "ConditionExpr",
    "Directive",
    "DirectiveExecutionCursor",
    "PlanningRequest",
    "PlanningResultCandidate",
    "StrategyPlan",
    "validate_planning_transition",
]
