from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ConfigurationSource = Literal["default", "archetype", "random", "user", "llm_interpreted"]
AgentConfigurationInputMode = Literal["preset", "random", "natural_language", "detailed"]
ParticipantArchetypeId = Literal[
    "ordinary_participant",
    "capital_holder",
    "liquidity_provider",
    "asset_issuer",
    "information_participant",
]
RandomizableAgentField = Literal[
    "base_persona.risk_tolerance_milli",
    "base_persona.time_horizon",
    "base_persona.loss_aversion_milli",
    "base_persona.trend_bias_milli",
    "base_persona.skepticism_milli",
    "base_persona.communication_propensity_milli",
    "cognitive_profile.context_capacity",
    "cognitive_profile.memory_search_limit",
    "attention_profile.information_capacity",
    "attention_profile.minimum_salience",
    "latency_profile.planning_latency_us",
    "latency_profile.action_latency_us",
]


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ConfigurationProvenance(StrictFrozenModel):
    source: ConfigurationSource
    source_ref: str | None = Field(default=None, max_length=256)
    distribution_version: str | None = Field(default=None, max_length=128)
    seed: int | None = None
    interpreter_request_id: str | None = Field(default=None, max_length=256)
    user_confirmed: bool = False


class ConfigurationSuggestion(StrictFrozenModel):
    suggestion_id: str = Field(min_length=1, max_length=256)
    kind: Literal["archetype", "role_tag", "capability"]
    value: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=500)
    confidence_milli: int = Field(ge=0, le=1_000)
    ambiguity: str = Field(default="", max_length=500)


class BasePersonaDraft(StrictFrozenModel):
    private_goals: list[str] | None = Field(default=None, max_length=8)
    risk_tolerance_milli: int | None = Field(default=None, ge=0, le=1_000)
    time_horizon: Literal["short", "medium", "long"] | None = None
    loss_aversion_milli: int | None = Field(default=None, ge=0, le=1_000)
    trend_bias_milli: int | None = Field(default=None, ge=0, le=1_000)
    skepticism_milli: int | None = Field(default=None, ge=0, le=1_000)
    communication_propensity_milli: int | None = Field(default=None, ge=0, le=1_000)
    bounded_notes: str | None = Field(default=None, max_length=500)


class CognitiveProfileDraft(StrictFrozenModel):
    max_plans_per_window: int | None = Field(default=None, ge=0, le=100)
    planning_window_us: int | None = Field(default=None, ge=1)
    context_capacity: int | None = Field(default=None, ge=256, le=1_000_000)
    memory_search_limit: int | None = Field(default=None, ge=0, le=100)


class AttentionProfileDraft(StrictFrozenModel):
    information_capacity: int | None = Field(default=None, ge=1, le=10_000)
    minimum_salience: int | None = Field(default=None, ge=0, le=100)


class LatencyProfileDraft(StrictFrozenModel):
    planning_latency_us: int | None = Field(default=None, ge=0)
    action_latency_us: int | None = Field(default=None, ge=0)


class AgentPortfolioDraft(StrictFrozenModel):
    token_amount: int | None = Field(default=None, ge=0)
    usdx_amount: int | None = Field(default=None, ge=0)


class AgentConfigurationDraft(StrictFrozenModel):
    draft_id: str = Field(min_length=1, max_length=256)
    input_mode: AgentConfigurationInputMode
    agent_id: str | None = Field(default=None, min_length=1, max_length=256)
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    public_identity: str | None = Field(default=None, max_length=500)
    strategy: Literal["rule", "replay", "openai", "deepseek"] | None = None
    archetype_ids: list[ParticipantArchetypeId] = Field(default_factory=list, max_length=5)
    role_tags: list[str] | None = Field(default=None, max_length=16)
    capability_set: list[str] | None = Field(default=None, max_length=32)
    base_persona: BasePersonaDraft = Field(default_factory=BasePersonaDraft)
    cognitive_profile: CognitiveProfileDraft = Field(default_factory=CognitiveProfileDraft)
    attention_profile: AttentionProfileDraft = Field(default_factory=AttentionProfileDraft)
    latency_profile: LatencyProfileDraft = Field(default_factory=LatencyProfileDraft)
    planner_profile_id: str | None = Field(default=None, min_length=1, max_length=128)
    portfolio: AgentPortfolioDraft = Field(default_factory=AgentPortfolioDraft)
    random_fields: list[RandomizableAgentField] = Field(default_factory=list, max_length=32)
    provenance: dict[str, ConfigurationProvenance] = Field(default_factory=dict)
    suggestions: list[ConfigurationSuggestion] = Field(default_factory=list, max_length=32)
    accepted_suggestion_ids: list[str] = Field(default_factory=list, max_length=32)
    declined_suggestion_ids: list[str] = Field(default_factory=list, max_length=32)
    ambiguities: list[str] = Field(default_factory=list, max_length=32)
    schema_version: Literal["agent-configuration-draft.v0.1"] = "agent-configuration-draft.v0.1"

    @model_validator(mode="after")
    def validate_suggestion_disposition(self) -> "AgentConfigurationDraft":
        suggestion_ids = [item.suggestion_id for item in self.suggestions]
        if len(suggestion_ids) != len(set(suggestion_ids)):
            raise ValueError("suggestion_id values must be unique")
        accepted = set(self.accepted_suggestion_ids)
        declined = set(self.declined_suggestion_ids)
        if accepted & declined:
            raise ValueError("a suggestion cannot be both accepted and declined")
        if not (accepted | declined).issubset(suggestion_ids):
            raise ValueError("suggestion disposition references an unknown suggestion")
        if len(self.archetype_ids) != len(set(self.archetype_ids)):
            raise ValueError("archetype_ids must be unique")
        if len(self.random_fields) != len(set(self.random_fields)):
            raise ValueError("random_fields must be unique")
        return self


class AgentConfigurationProviderRequest(StrictFrozenModel):
    request_id: str
    context_hash: str = Field(min_length=8, max_length=256)
    user_intent: str = Field(min_length=1, max_length=4_000)
    allowed_archetypes: list[ParticipantArchetypeId] = Field(min_length=1, max_length=5)
    allowed_capabilities: list[str] = Field(min_length=1, max_length=32)
    allowed_persona_fields: list[str] = Field(min_length=1, max_length=32)
    schema_version: Literal["agent-configuration-provider-request.v0.1"] = "agent-configuration-provider-request.v0.1"


class AgentConfigurationInterpretationCandidate(StrictFrozenModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    public_identity: str | None = Field(default=None, max_length=500)
    base_persona: BasePersonaDraft = Field(default_factory=BasePersonaDraft)
    explicit_token_amount: int | None = Field(default=None, ge=0)
    explicit_usdx_amount: int | None = Field(default=None, ge=0)
    field_sources: dict[str, Literal["user", "llm_interpreted"]] = Field(default_factory=dict)
    suggestions: list[ConfigurationSuggestion] = Field(default_factory=list, max_length=32)
    ambiguities: list[str] = Field(default_factory=list, max_length=32)
    schema_version: Literal["agent-configuration-interpretation.v0.1"] = "agent-configuration-interpretation.v0.1"
