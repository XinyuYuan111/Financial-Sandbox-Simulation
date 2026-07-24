from __future__ import annotations

import re

from sandbox.contracts.intervention import (
    CreateRelationshipEffect,
    CreateWorldEntityEffect,
    DirectorAccessRecord,
    DirectorAccessScope,
    DirectorRecord,
    EffectPreview,
    InterventionPlan,
    InterventionPlanDraftInput,
    PrivateStateRef,
    PublishInformationEffect,
    SetAccountFreezeEffect,
    SetMarketStatusEffect,
    SetWalletAccessEffect,
    TransferAssetEffect,
)
from sandbox.core.errors import MissingCausalStateError, ValidationError
from sandbox.core.ids import deterministic_id
from sandbox.world.state import SimulationWorld


class ScenarioDirector:
    """Command-scoped, read-only interpreter for typed intervention drafts."""

    def draft(
        self,
        *,
        branch_id: str,
        created_command_id: str,
        branch_seq: int,
        world: SimulationWorld,
        request: InterventionPlanDraftInput,
    ) -> InterventionPlan:
        self.reject_secret_material(request)
        access_records = self.authorize_private_reads(
            world,
            request.access_scope,
            request.private_read_refs,
        )
        working = world.clone()
        previews: list[EffectPreview] = []
        for stage in request.stages:
            if stage.effective_sim_time_us < world.sim_time_us:
                raise ValidationError("intervention stages cannot target committed history")
            working.sim_time_us = stage.effective_sim_time_us
            result = working.apply_intervention_stage(
                stage,
                branch_id=branch_id,
                plan_id="preview",
                world_version=branch_seq,
            )
            working = result.world
            previews.extend(self._preview_effect(effect) for effect in stage.effects)
        plan_id = deterministic_id("intervention-plan", branch_id, created_command_id)
        return InterventionPlan(
            plan_id=plan_id,
            branch_id=branch_id,
            created_command_id=created_command_id,
            created_branch_seq=branch_seq,
            base_world_revision=world.world_revision,
            access_scope=request.access_scope,
            actual_private_reads=access_records,
            director_record=DirectorRecord(
                submitted_intent=request.user_intent,
                typed_output=[stage.model_dump(mode="json") for stage in request.stages],
            ),
            stages=request.stages,
            preview=previews,
        )

    @staticmethod
    def reject_secret_material(request: InterventionPlanDraftInput) -> None:
        ScenarioDirector.reject_secret_text(request.model_dump_json())

    @staticmethod
    def reject_secret_text(value: str) -> None:
        patterns = (
            r"\bsk-[A-Za-z0-9_-]{16,}",
            r"authorization\s*:\s*bearer\s+\S+",
            r"openai_api_key\s*[=:]",
            r"(?:private|secret)[_-]?key\s*[=:]\s*['\"]?[A-Za-z0-9+/=_-]{16,}",
        )
        if any(re.search(pattern, value, flags=re.IGNORECASE) for pattern in patterns):
            raise ValidationError("Director input contains prohibited runtime secret material")

    @staticmethod
    def authorize_private_reads(
        world: SimulationWorld,
        access_scope: DirectorAccessScope,
        private_read_refs: list[PrivateStateRef],
    ) -> list[DirectorAccessRecord]:
        grants = {
            (grant.category, target_id)
            for grant in access_scope.private_grants
            for target_id in grant.target_ids
        }
        records: list[DirectorAccessRecord] = []
        seen: set[tuple[str, str]] = set()
        for private_ref in private_read_refs:
            key = (private_ref.category, private_ref.target_id)
            if key in seen:
                continue
            if key not in grants:
                raise ValidationError(
                    f"Director private read is outside the command access scope: {private_ref.category}/{private_ref.target_id}"
                )
            if private_ref.target_id not in world.agents:
                raise MissingCausalStateError(f"Agent '{private_ref.target_id}' does not exist")
            state = world.agent_runtime_states.get(private_ref.target_id)
            if private_ref.category == "persona":
                if private_ref.target_id not in world.agent_definitions:
                    raise MissingCausalStateError(f"Agent persona '{private_ref.target_id}' does not exist")
                revision = state.agent_revision if state else 0
                source_ref = f"agent-definition:{private_ref.target_id}"
            elif private_ref.category in {"memory", "belief"}:
                if state is None:
                    raise MissingCausalStateError(f"Agent runtime state '{private_ref.target_id}' does not exist")
                revision = state.component_revisions[private_ref.category]
                source_ref = f"agent-runtime:{private_ref.target_id}:{private_ref.category}"
            elif private_ref.category == "private_messages":
                revision = world.world_revision
                source_ref = f"world-information:{private_ref.target_id}"
            else:
                raise ValidationError(
                    f"private access category '{private_ref.category}' is not available to the typed Director"
                )
            records.append(DirectorAccessRecord(
                category=private_ref.category,
                target_id=private_ref.target_id,
                state_revision=revision,
                source_ref=source_ref,
            ))
            seen.add(key)
        return records

    @staticmethod
    def provider_context(
        world: SimulationWorld,
        private_read_refs: list[PrivateStateRef],
    ) -> tuple[dict[str, object], dict[str, object]]:
        world_context = {
            "sim_time_us": world.sim_time_us,
            "world_revision": world.world_revision,
            "market": world.market_projection(),
            "market_status": world.market.get("status", "active"),
            "ledger_balances": world.ledger.to_json()["balances"],
            "order_book": world.clob.to_json(),
            "agents": [world.agent_projection(agent_id) for agent_id in sorted(world.agents)],
            "background_market_sector": world.background_market_sector,
            "public_information": [item for item in world.information_items[-100:] if item.get("visibility") == "public"],
            "world_entities": list(world.world_entities.values()),
            "relationships": list(world.relationships.values()),
            "wallet_access": world.wallet_access,
            "frozen_accounts": sorted(world.frozen_accounts),
            "pending_actions": world.pending_actions,
            "action_reservations": world.action_reservations,
            "chain_snapshot": world.chain_snapshot,
        }
        private_context: dict[str, object] = {}
        for private_ref in private_read_refs:
            agent_id = private_ref.target_id
            state = world.agent_runtime_states.get(agent_id)
            if private_ref.category == "persona":
                definition = world.agent_definitions.get(agent_id)
                private_context[f"persona:{agent_id}"] = definition.base_persona.model_dump(mode="json") if definition else None
            elif private_ref.category == "memory":
                private_context[f"memory:{agent_id}"] = [item.model_dump(mode="json") for item in state.memory_entries] if state else []
            elif private_ref.category == "belief":
                private_context[f"belief:{agent_id}"] = [item.model_dump(mode="json") for item in state.beliefs] if state else []
            elif private_ref.category == "private_messages":
                private_context[f"private_messages:{agent_id}"] = [
                    item for item in world.information_items[-100:]
                    if item.get("visibility") == "agent_private" and agent_id in item.get("target_ids", [])
                ]
        return world_context, private_context

    @staticmethod
    def _preview_effect(effect: object) -> EffectPreview:
        if isinstance(effect, PublishInformationEffect):
            targets = effect.target_ids or ["public"]
            summary = f"Publish via {effect.channel} to {len(targets)} audience target(s)"
        elif isinstance(effect, TransferAssetEffect):
            targets = [effect.from_owner_id, effect.to_owner_id]
            summary = f"Transfer {effect.amount} {effect.asset} between existing ledger owners"
        elif isinstance(effect, SetMarketStatusEffect):
            targets = [effect.market_id]
            summary = f"Set market status to {effect.status}"
        elif isinstance(effect, SetAccountFreezeEffect):
            targets = [effect.owner_id]
            summary = f"Set account frozen={effect.frozen}"
        elif isinstance(effect, SetWalletAccessEffect):
            targets = [effect.wallet_owner_id, effect.grantee_agent_id]
            summary = f"Set wallet permissions: {', '.join(effect.permissions) or 'none'}"
        elif isinstance(effect, CreateWorldEntityEffect):
            targets = [effect.entity_id]
            summary = f"Create {effect.entity_type} from the stage time forward"
        elif isinstance(effect, CreateRelationshipEffect):
            targets = [effect.source_entity_id, effect.target_entity_id]
            summary = f"Create {effect.relationship_type} relationship from the stage time forward"
        else:  # pragma: no cover - closed union protects this boundary
            raise ValidationError("unsupported intervention effect")
        return EffectPreview(
            effect_id=effect.effect_id,
            effect_type=effect.effect_type,
            target_refs=targets,
            summary=summary,
        )
