from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PrivateAccessCategory = Literal[
    "persona",
    "memory",
    "belief",
    "private_messages",
    "planner_prompt",
    "provider_response",
]


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PrivateAccessGrant(StrictFrozenModel):
    category: PrivateAccessCategory
    target_ids: list[str] = Field(min_length=1, max_length=64)
    purpose: str = Field(min_length=1, max_length=500)


class PrivateStateRef(StrictFrozenModel):
    category: PrivateAccessCategory
    target_id: str = Field(min_length=1, max_length=256)


class DirectorAccessScope(StrictFrozenModel):
    private_grants: list[PrivateAccessGrant] = Field(default_factory=list, max_length=32)


class DirectorAccessRecord(StrictFrozenModel):
    category: PrivateAccessCategory
    target_id: str = Field(min_length=1, max_length=256)
    state_revision: int = Field(ge=0)
    source_ref: str = Field(min_length=1, max_length=512)


class PublishInformationEffect(StrictFrozenModel):
    effect_id: str = Field(min_length=1, max_length=256)
    effect_type: Literal["publish_information"] = "publish_information"
    source_id: str = Field(default="scenario_director", min_length=1, max_length=256)
    channel: Literal["PublicFeed", "OfficialAnnouncement", "TradingTerminal", "PrivateChannel"]
    content: str = Field(min_length=1, max_length=4_000)
    target_ids: list[str] = Field(default_factory=list, max_length=1_000)
    depends_on_state_effect_ids: list[str] = Field(default_factory=list, max_length=32)
    private_source_refs: list[PrivateStateRef] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def validate_delivery(self) -> "PublishInformationEffect":
        if self.channel == "PrivateChannel" and not self.target_ids:
            raise ValueError("private information requires target_ids")
        if self.channel != "PrivateChannel" and self.target_ids:
            raise ValueError("public information channels cannot declare target_ids")
        return self


class TransferAssetEffect(StrictFrozenModel):
    effect_id: str = Field(min_length=1, max_length=256)
    effect_type: Literal["transfer_asset"] = "transfer_asset"
    from_owner_id: str = Field(min_length=1, max_length=256)
    to_owner_id: str = Field(min_length=1, max_length=256)
    asset: str = Field(min_length=1, max_length=64)
    amount: int = Field(ge=1)
    reason_code: str = Field(min_length=1, max_length=128)
    required_relationship_ids: list[str] = Field(default_factory=list, max_length=32)


class SetMarketStatusEffect(StrictFrozenModel):
    effect_id: str = Field(min_length=1, max_length=256)
    effect_type: Literal["set_market_status"] = "set_market_status"
    market_id: str = Field(min_length=1, max_length=256)
    status: Literal["active", "halted"]
    reason_code: str = Field(min_length=1, max_length=128)


class SetAccountFreezeEffect(StrictFrozenModel):
    effect_id: str = Field(min_length=1, max_length=256)
    effect_type: Literal["set_account_freeze"] = "set_account_freeze"
    owner_id: str = Field(min_length=1, max_length=256)
    frozen: bool
    reason_code: str = Field(min_length=1, max_length=128)


class SetWalletAccessEffect(StrictFrozenModel):
    effect_id: str = Field(min_length=1, max_length=256)
    effect_type: Literal["set_wallet_access"] = "set_wallet_access"
    wallet_owner_id: str = Field(min_length=1, max_length=256)
    grantee_agent_id: str = Field(min_length=1, max_length=256)
    permissions: list[Literal["observe", "transact"]] = Field(default_factory=list, max_length=2)
    reason_code: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_permissions(self) -> "SetWalletAccessEffect":
        if len(self.permissions) != len(set(self.permissions)):
            raise ValueError("wallet permissions must be unique")
        return self


class CreateWorldEntityEffect(StrictFrozenModel):
    effect_id: str = Field(min_length=1, max_length=256)
    effect_type: Literal["create_world_entity"] = "create_world_entity"
    entity_id: str = Field(min_length=1, max_length=256)
    entity_type: Literal["institution", "venue", "wallet"]
    display_name: str = Field(min_length=1, max_length=256)


class CreateRelationshipEffect(StrictFrozenModel):
    effect_id: str = Field(min_length=1, max_length=256)
    effect_type: Literal["create_relationship"] = "create_relationship"
    relationship_id: str = Field(min_length=1, max_length=256)
    relationship_type: Literal["wallet_control", "custody", "exposure"]
    source_entity_id: str = Field(min_length=1, max_length=256)
    target_entity_id: str = Field(min_length=1, max_length=256)
    asset: str | None = Field(default=None, max_length=64)
    amount: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_exposure(self) -> "CreateRelationshipEffect":
        if self.relationship_type == "exposure" and (self.asset is None or self.amount is None):
            raise ValueError("exposure relationships require asset and amount")
        if self.relationship_type != "exposure" and (self.asset is not None or self.amount is not None):
            raise ValueError("only exposure relationships accept asset and amount")
        return self


InterventionEffect = Annotated[
    PublishInformationEffect
    | TransferAssetEffect
    | SetMarketStatusEffect
    | SetAccountFreezeEffect
    | SetWalletAccessEffect
    | CreateWorldEntityEffect
    | CreateRelationshipEffect,
    Field(discriminator="effect_type"),
]


class InterventionStage(StrictFrozenModel):
    stage_id: str = Field(min_length=1, max_length=256)
    effective_sim_time_us: int = Field(ge=0)
    effects: list[InterventionEffect] = Field(min_length=1, max_length=64)
    status: Literal["pending", "applied", "failed", "canceled"] = "pending"
    failure_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_effect_dependencies(self) -> "InterventionStage":
        effect_ids = [effect.effect_id for effect in self.effects]
        if len(effect_ids) != len(set(effect_ids)):
            raise ValueError("effect_id must be unique within a stage")
        state_effect_ids = {
            effect.effect_id
            for effect in self.effects
            if not isinstance(effect, PublishInformationEffect)
        }
        for effect in self.effects:
            if isinstance(effect, PublishInformationEffect):
                missing = set(effect.depends_on_state_effect_ids) - state_effect_ids
                if missing:
                    raise ValueError("information dependencies must reference state effects in the same stage")
        if self.status == "failed" and not self.failure_reason:
            raise ValueError("failed stages require failure_reason")
        if self.status != "failed" and self.failure_reason is not None:
            raise ValueError("failure_reason is only valid for failed stages")
        return self


class EffectPreview(StrictFrozenModel):
    effect_id: str
    effect_type: str
    target_refs: list[str] = Field(default_factory=list, max_length=64)
    summary: str = Field(max_length=500)
    warnings: list[str] = Field(default_factory=list, max_length=16)


class DirectorRecord(StrictFrozenModel):
    director_kind: Literal["typed_control_plane.v0.1", "openai.v0.1", "deepseek.v0.1"] = "typed_control_plane.v0.1"
    submitted_intent: str = Field(min_length=1, max_length=4_000)
    typed_output: list[dict[str, object]] = Field(default_factory=list, max_length=32)
    provider: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=256)
    context_hash: str | None = Field(default=None, max_length=256)
    call_ids: list[str] = Field(default_factory=list, max_length=16)
    rationale: str = Field(default="", max_length=1_000)


class InterventionPlanDraftInput(StrictFrozenModel):
    user_intent: str = Field(min_length=1, max_length=4_000)
    access_scope: DirectorAccessScope = Field(default_factory=DirectorAccessScope)
    private_read_refs: list[PrivateStateRef] = Field(default_factory=list, max_length=2_048)
    stages: list[InterventionStage] = Field(min_length=1, max_length=32)


class DirectorProviderRequest(StrictFrozenModel):
    request_id: str
    branch_id: str
    context_hash: str
    user_intent: str = Field(min_length=1, max_length=4_000)
    current_sim_time_us: int = Field(ge=0)
    requested_effective_time_us: int = Field(ge=0)
    world_context: dict[str, object]
    private_context: dict[str, object] = Field(default_factory=dict)
    allowed_effect_types: list[str] = Field(min_length=1, max_length=32)
    schema_version: Literal["director-provider-request.v0.1"] = "director-provider-request.v0.1"


class DirectorPlanCandidate(StrictFrozenModel):
    stages: list[InterventionStage] = Field(min_length=1, max_length=32)
    rationale: str = Field(default="", max_length=1_000)
    schema_version: Literal["director-plan-candidate.v0.1"] = "director-plan-candidate.v0.1"


class InterventionPlan(StrictFrozenModel):
    plan_id: str
    branch_id: str
    created_command_id: str
    created_branch_seq: int = Field(ge=0)
    base_world_revision: int = Field(ge=0)
    plan_revision: int = Field(default=1, ge=1)
    status: Literal["draft", "confirmed", "rejected", "canceled", "completed", "failed"] = "draft"
    access_scope: DirectorAccessScope = Field(default_factory=DirectorAccessScope)
    actual_private_reads: list[DirectorAccessRecord] = Field(default_factory=list, max_length=2_048)
    director_record: DirectorRecord
    stages: list[InterventionStage] = Field(min_length=1, max_length=32)
    preview: list[EffectPreview] = Field(default_factory=list, max_length=2_048)
    confirmed_command_id: str | None = None
    terminal_command_id: str | None = None
    schema_version: Literal["intervention-plan.v0.1"] = "intervention-plan.v0.1"

    @model_validator(mode="after")
    def validate_plan(self) -> "InterventionPlan":
        stage_ids = [stage.stage_id for stage in self.stages]
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError("stage_id must be unique within a plan")
        times = [stage.effective_sim_time_us for stage in self.stages]
        if times != sorted(times):
            raise ValueError("intervention stages must be ordered by effective_sim_time_us")
        all_effect_ids = [effect.effect_id for stage in self.stages for effect in stage.effects]
        if len(all_effect_ids) != len(set(all_effect_ids)):
            raise ValueError("effect_id must be unique within a plan")
        read_refs = {(record.category, record.target_id) for record in self.actual_private_reads}
        for stage in self.stages:
            for effect in stage.effects:
                if isinstance(effect, PublishInformationEffect):
                    for private_ref in effect.private_source_refs:
                        if (private_ref.category, private_ref.target_id) not in read_refs:
                            raise ValueError("private disclosure requires a matching recorded Director read")
        return self
