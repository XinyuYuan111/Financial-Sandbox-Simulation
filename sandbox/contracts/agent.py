from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ComponentName = Literal["memory", "belief", "planning", "strategy", "cursor", "budget", "attention"]
ActionType = Literal[
    "SubmitLimitOrder",
    "SubmitProtectedMarketOrder",
    "CancelOrder",
    "ReplaceOrder",
    "PublishInformation",
]


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BasePersona(StrictFrozenModel):
    template_id: str = Field(min_length=1, max_length=128)
    template_version: Literal["persona.v0.1"] = "persona.v0.1"
    private_goals: list[str] = Field(default_factory=list, max_length=8)
    risk_tolerance_milli: int = Field(ge=0, le=1_000)
    time_horizon: Literal["short", "medium", "long"]
    loss_aversion_milli: int = Field(ge=0, le=1_000)
    trend_bias_milli: int = Field(ge=0, le=1_000)
    skepticism_milli: int = Field(ge=0, le=1_000)
    communication_propensity_milli: int = Field(ge=0, le=1_000)
    bounded_notes: str = Field(default="", max_length=500)


class CognitiveProfile(StrictFrozenModel):
    profile_id: str = "cognitive.default.v0.1"
    max_plans_per_window: int = Field(default=2, ge=0, le=100)
    planning_window_us: int = Field(default=300_000_000, ge=1)
    context_capacity: int = Field(default=8_000, ge=256, le=1_000_000)
    memory_search_limit: int = Field(default=5, ge=0, le=100)


class AttentionProfile(StrictFrozenModel):
    profile_id: str = "attention.default.v0.1"
    information_capacity: int = Field(default=20, ge=1, le=10_000)
    minimum_salience: int = Field(default=0, ge=0, le=100)


class LatencyProfile(StrictFrozenModel):
    profile_id: str = "latency.default.v0.1"
    planning_latency_us: int = Field(default=1_000_000, ge=0)
    action_latency_us: int = Field(default=1_000_000, ge=0)


class AgentDefinition(StrictFrozenModel):
    agent_id: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=128)
    public_identity: str = Field(default="", max_length=500)
    role_tags: list[str] = Field(default_factory=list, max_length=16)
    funding_profile: Literal["ordinary", "capital", "liquidity", "issuer", "information"]
    capability_set: list[str] = Field(default_factory=list, max_length=32)
    base_persona: BasePersona
    planner_profile_id: str = Field(min_length=1, max_length=128)
    controller_profile_id: str = Field(default="declarative_market.v0.1", min_length=1, max_length=128)
    cognitive_profile: CognitiveProfile = Field(default_factory=CognitiveProfile)
    attention_profile: AttentionProfile = Field(default_factory=AttentionProfile)
    latency_profile: LatencyProfile = Field(default_factory=LatencyProfile)
    schema_version: Literal["agent-definition.v0.1"] = "agent-definition.v0.1"


class CognitiveBudgetState(StrictFrozenModel):
    window_started_sim_time_us: int = Field(default=0, ge=0)
    plans_remaining: int = Field(default=2, ge=0)
    plans_reserved: int = Field(default=0, ge=0)
    searches_remaining: int = Field(default=5, ge=0)


class AttentionBudgetState(StrictFrozenModel):
    window_started_sim_time_us: int = Field(default=0, ge=0)
    items_remaining: int = Field(default=20, ge=0)


class MemoryEntryState(StrictFrozenModel):
    memory_id: str
    summary: str = Field(max_length=1_000)
    source_ids: list[str] = Field(default_factory=list, max_length=32)
    confidence_milli: int = Field(ge=0, le=1_000)
    salience: int = Field(ge=0, le=100)
    created_sim_time_us: int = Field(ge=0)
    accessible: bool = True


class BeliefState(StrictFrozenModel):
    belief_id: str
    subject: str
    predicate: str
    value: str
    confidence_milli: int = Field(ge=0, le=1_000)
    evidence_memory_ids: list[str] = Field(default_factory=list, max_length=32)
    updated_sim_time_us: int = Field(ge=0)
    stated_reason: str = Field(default="", max_length=500)


class ReplanTrigger(StrictFrozenModel):
    semantic_key: str = Field(min_length=1, max_length=128)
    count: int = Field(default=1, ge=1)
    first_sim_time_us: int = Field(ge=0)
    last_sim_time_us: int = Field(ge=0)
    source_event_ids: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def validate_time_order(self) -> "ReplanTrigger":
        if self.last_sim_time_us < self.first_sim_time_us:
            raise ValueError("last_sim_time_us must not precede first_sim_time_us")
        return self


class DecisionTrigger(StrictFrozenModel):
    type: Literal["initial_observation", "market_change", "information", "private_message", "own_action_outcome", "planning_result", "directive_wakeup", "risk"]
    semantic_key: str = Field(min_length=1, max_length=128)
    source_event_ids: list[str] = Field(default_factory=list, max_length=32)
    severity: int = Field(default=50, ge=0, le=100)
    first_sim_time_us: int = Field(ge=0)
    last_sim_time_us: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_time_order(self) -> "DecisionTrigger":
        if self.last_sim_time_us < self.first_sim_time_us:
            raise ValueError("last_sim_time_us must not precede first_sim_time_us")
        return self


class DirectiveExecutionCursor(StrictFrozenModel):
    plan_revision: int = Field(ge=1)
    directive_id: str = Field(min_length=1, max_length=256)
    last_observation_id: str | None = None
    previous_guard: bool | None = None
    emission_count: int = Field(default=0, ge=0)
    last_eligible_sim_time_us: int | None = Field(default=None, ge=0)
    next_eligible_sim_time_us: int | None = Field(default=None, ge=0)
    action_ids: list[str] = Field(default_factory=list, max_length=10_000)


class AgentRuntimeState(StrictFrozenModel):
    agent_id: str
    agent_revision: int = Field(default=0, ge=0)
    component_revisions: dict[ComponentName, int] = Field(
        default_factory=lambda: {
            "memory": 0,
            "belief": 0,
            "planning": 0,
            "strategy": 0,
            "cursor": 0,
            "budget": 0,
            "attention": 0,
        }
    )
    active_plan_id: str | None = None
    active_strategy_revision: int = Field(default=0, ge=0)
    planning_request_id: str | None = None
    trigger_accumulator: list[ReplanTrigger] = Field(default_factory=list, max_length=32)
    directive_cursors: dict[str, DirectiveExecutionCursor] = Field(default_factory=dict)
    cognitive_budget_state: CognitiveBudgetState = Field(default_factory=CognitiveBudgetState)
    attention_budget_state: AttentionBudgetState = Field(default_factory=AttentionBudgetState)
    memory_entries: list[MemoryEntryState] = Field(default_factory=list, max_length=1_000)
    beliefs: list[BeliefState] = Field(default_factory=list, max_length=1_000)
    processed_observation_ids: list[str] = Field(default_factory=list, max_length=10_000)
    schema_version: Literal["agent-runtime-state.v0.1"] = "agent-runtime-state.v0.1"


class ProposalBase(StrictFrozenModel):
    proposal_id: str = Field(min_length=1, max_length=256)
    depends_on: list[str] = Field(default_factory=list, max_length=32)


class MemoryProposal(ProposalBase):
    kind: Literal["write", "forget"]
    summary: str = Field(default="", max_length=1_000)
    source_ids: list[str] = Field(default_factory=list, max_length=32)
    confidence_milli: int = Field(default=500, ge=0, le=1_000)
    salience: int = Field(default=0, ge=0, le=100)
    memory_id: str | None = None


class BeliefProposal(ProposalBase):
    subject: str = Field(min_length=1, max_length=256)
    predicate: str = Field(min_length=1, max_length=128)
    value: str = Field(max_length=1_000)
    confidence_milli: int = Field(ge=0, le=1_000)
    evidence_memory_ids: list[str] = Field(default_factory=list, max_length=32)
    stated_reason: str = Field(default="", max_length=500)


class PlanningRequestProposal(ProposalBase):
    reason_keys: list[str] = Field(min_length=1, max_length=16)
    requested_planner_profile_id: str = Field(min_length=1, max_length=128)


class StrategyPlanProposal(ProposalBase):
    planning_request_id: str
    plan_id: str


class ActionProposal(ProposalBase):
    action_type: ActionType
    payload: dict[str, object]
    expected_execution_time_us: int = Field(ge=0)
    validity_window_us: int = Field(ge=0)
    priority: int = Field(default=50, ge=0, le=100)
    required_capabilities: list[str] = Field(default_factory=list, max_length=16)


class DecisionRationale(StrictFrozenModel):
    goal_summary: str = Field(default="", max_length=500)
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    belief_ids: list[str] = Field(default_factory=list, max_length=64)
    strategy_revision: int = Field(default=0, ge=0)
    risk_flags: list[str] = Field(default_factory=list, max_length=32)
    uncertainty_milli: int = Field(default=500, ge=0, le=1_000)
    proposal_ids: list[str] = Field(default_factory=list, max_length=128)
    stated_reason: str = Field(default="", max_length=1_000)


class AgentDecision(StrictFrozenModel):
    decision_id: str
    branch_id: str
    agent_id: str
    observation_id: str
    sim_time_us: int = Field(ge=0)
    decision_triggers: list[DecisionTrigger] = Field(default_factory=list, max_length=32)
    base_agent_revision: int = Field(ge=0)
    component_dependencies: dict[ComponentName, int] = Field(default_factory=dict)
    memory_proposals: list[MemoryProposal] = Field(default_factory=list, max_length=64)
    belief_proposals: list[BeliefProposal] = Field(default_factory=list, max_length=64)
    planning_request_proposal: PlanningRequestProposal | None = None
    strategy_plan_proposal: StrategyPlanProposal | None = None
    action_proposals: list[ActionProposal] = Field(default_factory=list, max_length=32)
    rationale: DecisionRationale = Field(default_factory=DecisionRationale)
    original_decision_id: str | None = None
    planning_request_id: str | None = None
    schema_version: Literal["agent-decision.v0.1"] = "agent-decision.v0.1"

    @model_validator(mode="after")
    def validate_proposal_dependencies(self) -> "AgentDecision":
        staged: list[tuple[int, ProposalBase]] = []
        staged.extend((0, proposal) for proposal in self.memory_proposals)
        staged.extend((1, proposal) for proposal in self.belief_proposals)
        if self.planning_request_proposal is not None:
            staged.append((2, self.planning_request_proposal))
        if self.strategy_plan_proposal is not None:
            staged.append((2, self.strategy_plan_proposal))
        staged.extend((3, proposal) for proposal in self.action_proposals)
        stage_by_id: dict[str, int] = {}
        for stage, proposal in staged:
            if proposal.proposal_id in stage_by_id:
                raise ValueError(f"duplicate proposal_id '{proposal.proposal_id}'")
            stage_by_id[proposal.proposal_id] = stage
        for stage, proposal in staged:
            for dependency in proposal.depends_on:
                dependency_stage = stage_by_id.get(dependency)
                if dependency_stage is None:
                    raise ValueError(f"unknown proposal dependency '{dependency}'")
                if dependency_stage >= stage:
                    raise ValueError("proposal dependencies must point to an earlier pipeline stage")
        return self


class ProposalResult(StrictFrozenModel):
    proposal_id: str
    accepted: bool
    reason_code: str = Field(min_length=1, max_length=128)
    depends_on: list[str] = Field(default_factory=list)
    resulting_ref: str | None = None


class BudgetChange(StrictFrozenModel):
    budget_kind: Literal["cognitive", "attention", "provider"]
    operation: Literal["reserve", "consume", "release", "reset", "modifier"]
    delta: int
    remaining: int = Field(ge=0)
    reason_code: str


class DecisionOutcome(StrictFrozenModel):
    decision_id: str
    accepted: bool
    proposal_results: list[ProposalResult] = Field(default_factory=list)
    resulting_agent_revision: int = Field(ge=0)
    resulting_component_revisions: dict[ComponentName, int] = Field(default_factory=dict)
    budget_changes: list[BudgetChange] = Field(default_factory=list)
    recorded_event_ids: list[str] = Field(default_factory=list)
    schema_version: Literal["decision-outcome.v0.1"] = "decision-outcome.v0.1"


class ActionReservation(StrictFrozenModel):
    reservation_id: str
    action_id: str
    agent_id: str
    asset_amounts: dict[str, int]
    created_sim_time_us: int = Field(ge=0)
    expires_sim_time_us: int = Field(ge=0)
    state: Literal["active", "consumed", "released"] = "active"


class PendingAction(StrictFrozenModel):
    action_id: str
    proposal_id: str
    decision_id: str | None = None
    agent_id: str
    expected_execution_time_us: int = Field(ge=0)
    validity_deadline_us: int = Field(ge=0)
    reservation_id: str | None = None
    strategy_revision_dependency: int | None = Field(default=None, ge=0)


class ActionReceipt(StrictFrozenModel):
    receipt_id: str
    action_id: str
    proposal_id: str | None = None
    decision_id: str | None = None
    agent_id: str
    branch_id: str
    outcome: Literal["accepted", "rejected", "queued", "executed", "partial", "failed", "expired", "canceled"]
    reason_code: str = Field(min_length=1, max_length=128)
    submitted_sim_time_us: int = Field(ge=0)
    scheduled_sim_time_us: int = Field(ge=0)
    resolved_sim_time_us: int = Field(ge=0)
    authoritative_event_ids: list[str] = Field(default_factory=list)
    result_state_refs: dict[str, int | str] = Field(default_factory=dict)
    schema_version: Literal["action-receipt.v0.1"] = "action-receipt.v0.1"

    @model_validator(mode="after")
    def validate_time_order(self) -> "ActionReceipt":
        if self.scheduled_sim_time_us < self.submitted_sim_time_us:
            raise ValueError("scheduled_sim_time_us must not precede submission")
        if self.resolved_sim_time_us < self.submitted_sim_time_us:
            raise ValueError("resolved_sim_time_us must not precede submission")
        return self
