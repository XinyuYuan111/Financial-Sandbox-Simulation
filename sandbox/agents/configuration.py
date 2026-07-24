from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sandbox.contracts.agent import (
    AgentDefinition,
    AttentionProfile,
    BasePersona,
    CognitiveProfile,
    LatencyProfile,
)
from sandbox.contracts.agent_configuration import (
    AgentConfigurationDraft,
    AgentConfigurationInterpretationCandidate,
    ConfigurationProvenance,
    ParticipantArchetypeId,
    RandomizableAgentField,
)
from sandbox.core.errors import ValidationError
from sandbox.core.rng import NamedRandomStreams


CAPABILITY_REGISTRY = frozenset({
    "market.trade",
    "market.quote",
    "information.read",
    "information.publish",
})

RANDOM_FIELDS: tuple[RandomizableAgentField, ...] = (
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
)

DEFAULTS: dict[str, Any] = {
    "base_persona.private_goals": ["preserve_capital", "pursue_risk_adjusted_return"],
    "base_persona.risk_tolerance_milli": 500,
    "base_persona.time_horizon": "medium",
    "base_persona.loss_aversion_milli": 600,
    "base_persona.trend_bias_milli": 500,
    "base_persona.skepticism_milli": 500,
    "base_persona.communication_propensity_milli": 400,
    "base_persona.bounded_notes": "",
    "cognitive_profile.max_plans_per_window": 2,
    "cognitive_profile.planning_window_us": 300_000_000,
    "cognitive_profile.context_capacity": 8_000,
    "cognitive_profile.memory_search_limit": 5,
    "attention_profile.information_capacity": 20,
    "attention_profile.minimum_salience": 10,
    "latency_profile.planning_latency_us": 1_000_000,
    "latency_profile.action_latency_us": 1_000_000,
}

ARCHETYPE_TEMPLATES: dict[ParticipantArchetypeId, dict[str, Any]] = {
    "ordinary_participant": {
        "label": "普通参与者",
        "role_tags": ["market_participant"],
        "capability_set": ["market.trade", "information.read"],
        "persona": {
            "risk_tolerance_milli": 450,
            "time_horizon": "medium",
            "loss_aversion_milli": 650,
            "trend_bias_milli": 500,
            "skepticism_milli": 500,
            "communication_propensity_milli": 350,
        },
    },
    "capital_holder": {
        "label": "资本型持有者",
        "role_tags": ["capital_holder"],
        "capability_set": ["market.trade", "information.read"],
        "persona": {
            "risk_tolerance_milli": 600,
            "time_horizon": "long",
            "loss_aversion_milli": 550,
            "trend_bias_milli": 450,
            "skepticism_milli": 550,
            "communication_propensity_milli": 250,
        },
    },
    "liquidity_provider": {
        "label": "流动性提供者",
        "role_tags": ["liquidity_provider"],
        "capability_set": ["market.trade", "market.quote", "information.read"],
        "persona": {
            "risk_tolerance_milli": 550,
            "time_horizon": "short",
            "loss_aversion_milli": 500,
            "trend_bias_milli": 350,
            "skepticism_milli": 600,
            "communication_propensity_milli": 300,
        },
    },
    "asset_issuer": {
        "label": "资产发行方",
        "role_tags": ["asset_issuer"],
        "capability_set": ["market.trade", "information.read", "information.publish"],
        "persona": {
            "risk_tolerance_milli": 500,
            "time_horizon": "long",
            "loss_aversion_milli": 500,
            "trend_bias_milli": 500,
            "skepticism_milli": 400,
            "communication_propensity_milli": 700,
        },
    },
    "information_participant": {
        "label": "信息参与者",
        "role_tags": ["information_participant"],
        "capability_set": ["information.read", "information.publish"],
        "persona": {
            "risk_tolerance_milli": 400,
            "time_horizon": "medium",
            "loss_aversion_milli": 600,
            "trend_bias_milli": 400,
            "skepticism_milli": 750,
            "communication_propensity_milli": 750,
        },
    },
}


@dataclass(frozen=True, slots=True)
class CompiledAgentDraft:
    definition: AgentDefinition
    strategy: str
    token_amount: int | None
    usdx_amount: int | None
    portfolio_provenance: dict[str, ConfigurationProvenance]
    input_mode: str
    archetype_ids: tuple[str, ...]
    ambiguities: tuple[str, ...]


def archetype_catalog() -> list[dict[str, object]]:
    return [
        {
            "archetype_id": archetype_id,
            "label": template["label"],
            "suggested_role_tags": template["role_tags"],
            "suggested_capabilities": template["capability_set"],
            "suggested_persona": template["persona"],
            "schema_version": "participant-archetype.v0.1",
        }
        for archetype_id, template in ARCHETYPE_TEMPLATES.items()
    ]


def _draw(streams: NamedRandomStreams, stream_name: str, minimum: int, maximum: int) -> int:
    value, _ = streams.random(stream_name)
    return minimum + int(value * (maximum - minimum + 1))


def _random_value(path: RandomizableAgentField, streams: NamedRandomStreams, draft_id: str) -> Any:
    stream = f"agent-configuration.{draft_id}.{path}"
    ranges: dict[str, tuple[int, int]] = {
        "base_persona.risk_tolerance_milli": (200, 850),
        "base_persona.loss_aversion_milli": (250, 900),
        "base_persona.trend_bias_milli": (100, 900),
        "base_persona.skepticism_milli": (100, 900),
        "base_persona.communication_propensity_milli": (50, 850),
        "cognitive_profile.context_capacity": (6_000, 10_000),
        "cognitive_profile.memory_search_limit": (3, 7),
        "attention_profile.information_capacity": (12, 28),
        "attention_profile.minimum_salience": (0, 30),
        "latency_profile.planning_latency_us": (500_000, 2_500_000),
        "latency_profile.action_latency_us": (100_000, 1_000_000),
    }
    if path == "base_persona.time_horizon":
        return ("short", "medium", "long")[_draw(streams, stream, 0, 2)]
    minimum, maximum = ranges[path]
    return _draw(streams, stream, minimum, maximum)


def _archetype_persona(archetype_ids: list[ParticipantArchetypeId]) -> dict[str, Any]:
    if not archetype_ids:
        return {}
    persona_values = [ARCHETYPE_TEMPLATES[item]["persona"] for item in archetype_ids]
    output: dict[str, Any] = {}
    for field in persona_values[0]:
        values = [item[field] for item in persona_values]
        if field == "time_horizon":
            rank = {"short": 0, "medium": 1, "long": 2}
            output[field] = ("short", "medium", "long")[round(sum(rank[value] for value in values) / len(values))]
        else:
            output[field] = sum(int(value) for value in values) // len(values)
    return output


def _provided_fields(draft: AgentConfigurationDraft) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for prefix, value in (
        ("base_persona", draft.base_persona),
        ("cognitive_profile", draft.cognitive_profile),
        ("attention_profile", draft.attention_profile),
        ("latency_profile", draft.latency_profile),
    ):
        for field, field_value in value.model_dump(exclude_none=True).items():
            output[f"{prefix}.{field}"] = field_value
    return output


def _provenance(
    draft: AgentConfigurationDraft,
    path: str,
    *,
    fallback: str,
    source_ref: str | None = None,
    seed: int | None = None,
) -> ConfigurationProvenance:
    existing = draft.provenance.get(path)
    if existing is not None:
        return existing
    return ConfigurationProvenance(
        source=fallback,  # type: ignore[arg-type]
        source_ref=source_ref,
        distribution_version="agent-field-distribution.v0.1" if fallback == "random" else None,
        seed=seed if fallback == "random" else None,
        user_confirmed=fallback == "user",
    )


def compile_agent_configuration(
    draft: AgentConfigurationDraft,
    *,
    seed: int,
    ordinal: int,
    planner_kind: str,
) -> CompiledAgentDraft:
    suggestion_ids = {item.suggestion_id for item in draft.suggestions}
    disposed = set(draft.accepted_suggestion_ids) | set(draft.declined_suggestion_ids)
    pending = sorted(suggestion_ids - disposed)
    if pending:
        raise ValidationError(f"Agent configuration has unconfirmed suggestions: {', '.join(pending)}")

    accepted = [item for item in draft.suggestions if item.suggestion_id in draft.accepted_suggestion_ids]
    archetype_ids = list(draft.archetype_ids)
    for suggestion in accepted:
        if suggestion.kind == "archetype":
            if suggestion.value not in ARCHETYPE_TEMPLATES:
                raise ValidationError(f"unknown Participant Archetype '{suggestion.value}'")
            if suggestion.value not in archetype_ids:
                archetype_ids.append(suggestion.value)  # type: ignore[arg-type]

    role_tags = list(dict.fromkeys(
        tag
        for archetype_id in archetype_ids
        for tag in ARCHETYPE_TEMPLATES[archetype_id]["role_tags"]
    ))
    capabilities = list(dict.fromkeys(
        capability
        for archetype_id in archetype_ids
        for capability in ARCHETYPE_TEMPLATES[archetype_id]["capability_set"]
    ))
    for suggestion in accepted:
        if suggestion.kind == "role_tag" and suggestion.value not in role_tags:
            role_tags.append(suggestion.value)
        if suggestion.kind == "capability" and suggestion.value not in capabilities:
            capabilities.append(suggestion.value)
    if draft.role_tags is not None:
        role_tags = list(dict.fromkeys(draft.role_tags))
    if draft.capability_set is not None:
        capabilities = list(dict.fromkeys(draft.capability_set))
    if not role_tags:
        role_tags = ["market_participant"]
    if not capabilities:
        capabilities = ["market.trade", "information.read"]
    unknown_capabilities = sorted(set(capabilities) - CAPABILITY_REGISTRY)
    if unknown_capabilities:
        raise ValidationError(f"unregistered Agent capabilities: {', '.join(unknown_capabilities)}")

    values = dict(DEFAULTS)
    provenance: dict[str, ConfigurationProvenance] = {
        path: ConfigurationProvenance(source="default", source_ref="agent-defaults.v0.1")
        for path in values
    }
    archetype_persona = _archetype_persona(archetype_ids)
    for field, value in archetype_persona.items():
        path = f"base_persona.{field}"
        values[path] = value
        provenance[path] = ConfigurationProvenance(
            source="archetype",
            source_ref="+".join(archetype_ids),
        )

    random_fields = set(draft.random_fields)
    if draft.input_mode == "random" and not random_fields:
        random_fields = set(RANDOM_FIELDS)
    streams = NamedRandomStreams(seed)
    for path in sorted(random_fields):
        values[path] = _random_value(path, streams, draft.draft_id)  # type: ignore[arg-type]
        provenance[path] = _provenance(draft, path, fallback="random", seed=seed)

    for path, value in _provided_fields(draft).items():
        values[path] = value
        provenance[path] = _provenance(draft, path, fallback="user")

    identity_source = "user" if draft.display_name is not None else "default"
    agent_id = draft.agent_id or f"agent_{ordinal:04d}"
    display_name = draft.display_name or f"Market Participant {ordinal:03d}"
    public_identity = draft.public_identity if draft.public_identity is not None else "Independent synthetic market participant"
    strategy = draft.strategy or planner_kind
    planner_profile_id = draft.planner_profile_id or f"{strategy}.default.v0.1"
    provenance.update({
        "agent_id": _provenance(draft, "agent_id", fallback="user" if draft.agent_id is not None else "default"),
        "display_name": _provenance(draft, "display_name", fallback=identity_source),
        "public_identity": _provenance(draft, "public_identity", fallback="user" if draft.public_identity is not None else "default"),
        "role_tags": _provenance(
            draft,
            "role_tags",
            fallback="user" if draft.role_tags is not None else ("archetype" if archetype_ids else "default"),
            source_ref="+".join(archetype_ids) or "agent-defaults.v0.1",
        ),
        "capability_set": _provenance(
            draft,
            "capability_set",
            fallback="user" if draft.capability_set is not None else ("archetype" if archetype_ids else "default"),
            source_ref="+".join(archetype_ids) or "agent-defaults.v0.1",
        ),
        "archetype_ids": _provenance(
            draft,
            "archetype_ids",
            fallback="user" if draft.archetype_ids else ("llm_interpreted" if any(item.kind == "archetype" for item in accepted) else "default"),
            source_ref="+".join(archetype_ids) or "agent-defaults.v0.1",
        ),
        "strategy": _provenance(draft, "strategy", fallback="user" if draft.strategy is not None else "default"),
        "planner_profile_id": _provenance(draft, "planner_profile_id", fallback="user" if draft.planner_profile_id is not None else "default"),
    })
    if any(item.kind == "archetype" for item in accepted):
        provenance = {
            path: item.model_copy(update={"user_confirmed": True}) if item.source == "archetype" else item
            for path, item in provenance.items()
        }
    for suggestion in accepted:
        if suggestion.kind in {"role_tag", "capability"}:
            path = "role_tags" if suggestion.kind == "role_tag" else "capability_set"
            provenance[path] = ConfigurationProvenance(
                source="llm_interpreted",
                source_ref=suggestion.suggestion_id,
                user_confirmed=True,
            )

    definition = AgentDefinition(
        agent_id=agent_id,
        display_name=display_name,
        public_identity=public_identity,
        role_tags=role_tags,
        capability_set=capabilities,
        base_persona=BasePersona(
            template_id="compiled-agent.v0.1",
            private_goals=values["base_persona.private_goals"],
            risk_tolerance_milli=values["base_persona.risk_tolerance_milli"],
            time_horizon=values["base_persona.time_horizon"],
            loss_aversion_milli=values["base_persona.loss_aversion_milli"],
            trend_bias_milli=values["base_persona.trend_bias_milli"],
            skepticism_milli=values["base_persona.skepticism_milli"],
            communication_propensity_milli=values["base_persona.communication_propensity_milli"],
            bounded_notes=values["base_persona.bounded_notes"],
        ),
        planner_profile_id=planner_profile_id,
        cognitive_profile=CognitiveProfile(
            max_plans_per_window=values["cognitive_profile.max_plans_per_window"],
            planning_window_us=values["cognitive_profile.planning_window_us"],
            context_capacity=values["cognitive_profile.context_capacity"],
            memory_search_limit=values["cognitive_profile.memory_search_limit"],
        ),
        attention_profile=AttentionProfile(
            information_capacity=values["attention_profile.information_capacity"],
            minimum_salience=values["attention_profile.minimum_salience"],
        ),
        latency_profile=LatencyProfile(
            planning_latency_us=values["latency_profile.planning_latency_us"],
            action_latency_us=values["latency_profile.action_latency_us"],
        ),
        configuration_provenance=provenance,
    )
    portfolio_provenance = {
        path: _provenance(draft, path, fallback="user")
        for path, value in (
            ("portfolio.token_amount", draft.portfolio.token_amount),
            ("portfolio.usdx_amount", draft.portfolio.usdx_amount),
        )
        if value is not None
    }
    return CompiledAgentDraft(
        definition=definition,
        strategy=strategy,
        token_amount=draft.portfolio.token_amount,
        usdx_amount=draft.portfolio.usdx_amount,
        portfolio_provenance=portfolio_provenance,
        input_mode=draft.input_mode,
        archetype_ids=tuple(archetype_ids),
        ambiguities=tuple(draft.ambiguities),
    )


def draft_from_interpretation(
    candidate: AgentConfigurationInterpretationCandidate,
    *,
    draft_id: str,
    request_id: str,
) -> AgentConfigurationDraft:
    allowed_source_paths = {
        "display_name",
        "public_identity",
        "portfolio.token_amount",
        "portfolio.usdx_amount",
        *{f"base_persona.{field}" for field in type(candidate.base_persona).model_fields},
    }
    unknown_paths = sorted(set(candidate.field_sources) - allowed_source_paths)
    if unknown_paths:
        raise ValidationError(f"Agent interpreter returned forbidden field paths: {', '.join(unknown_paths)}")
    present_paths = {
        path
        for path, value in {
            "display_name": candidate.display_name,
            "public_identity": candidate.public_identity,
            "portfolio.token_amount": candidate.explicit_token_amount,
            "portfolio.usdx_amount": candidate.explicit_usdx_amount,
            **{
                f"base_persona.{field}": value
                for field, value in candidate.base_persona.model_dump().items()
            },
        }.items()
        if value is not None
    }
    missing_sources = sorted(present_paths - set(candidate.field_sources))
    if missing_sources:
        raise ValidationError(f"Agent interpreter omitted field provenance: {', '.join(missing_sources)}")
    for suggestion in candidate.suggestions:
        if suggestion.kind == "archetype" and suggestion.value not in ARCHETYPE_TEMPLATES:
            raise ValidationError(f"Agent interpreter suggested unknown archetype '{suggestion.value}'")
        if suggestion.kind == "capability" and suggestion.value not in CAPABILITY_REGISTRY:
            raise ValidationError(f"Agent interpreter suggested unregistered capability '{suggestion.value}'")
    provenance = {
        path: ConfigurationProvenance(
            source=source,
            source_ref="natural-language-interpreter.v0.1",
            interpreter_request_id=request_id,
            user_confirmed=source == "user",
        )
        for path, source in candidate.field_sources.items()
    }
    return AgentConfigurationDraft(
        draft_id=draft_id,
        input_mode="natural_language",
        display_name=candidate.display_name,
        public_identity=candidate.public_identity,
        base_persona=candidate.base_persona,
        portfolio={
            "token_amount": candidate.explicit_token_amount,
            "usdx_amount": candidate.explicit_usdx_amount,
        },
        provenance=provenance,
        suggestions=candidate.suggestions,
        ambiguities=candidate.ambiguities,
    )
