from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sandbox.agents.configuration import CompiledAgentDraft, compile_agent_configuration
from sandbox.contracts.agent import AgentDefinition
from sandbox.contracts.agent_configuration import AgentConfigurationDraft
from sandbox.contracts.scenario import (
    AgentConfig,
    BackgroundMarketSector,
    HolderDistribution,
    PortfolioSynthesisConfig,
)
from sandbox.core.errors import ValidationError


PRESET_COUNTS: dict[str, dict[str, int]] = {
    "smoke": {
        "ordinary_participant": 1,
        "capital_holder": 1,
        "liquidity_provider": 1,
        "information_participant": 1,
    },
    "compact": {
        "ordinary_participant": 14,
        "capital_holder": 2,
        "liquidity_provider": 2,
        "asset_issuer": 1,
        "information_participant": 1,
    },
    "standard": {
        "ordinary_participant": 180,
        "capital_holder": 8,
        "liquidity_provider": 6,
        "asset_issuer": 1,
        "information_participant": 5,
    },
}


@dataclass(frozen=True, slots=True)
class PopulationResult:
    definitions: list[AgentDefinition]
    allocations: list[AgentConfig]
    background: BackgroundMarketSector
    preview: dict[str, object]


def _largest_remainder(total: int, weights: list[int]) -> list[int]:
    if not weights:
        if total:
            raise ValidationError("cannot allocate a positive amount to an empty population")
        return []
    denominator = sum(weights)
    if denominator <= 0:
        raise ValidationError("allocation weights must contain a positive value")
    base = [(total * weight) // denominator for weight in weights]
    remainder = total - sum(base)
    order = sorted(
        range(len(weights)),
        key=lambda index: (-((total * weights[index]) % denominator), index),
    )
    for index in order[:remainder]:
        base[index] += 1
    return base


def _stable_fraction(seed: int, namespace: str, agent_id: str) -> int:
    digest = hashlib.sha256(f"{seed}:{namespace}:{agent_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % 1_000_000


def _holder_weight(seed: int, agent_id: str, distribution: HolderDistribution) -> int:
    draw = _stable_fraction(seed, "portfolio-synthesis.v0.1", agent_id)
    if draw < 500_000:
        base = distribution.p25_balance
    elif draw < 750_000:
        base = distribution.p50_balance
    elif draw < 900_000:
        base = distribution.p75_balance
    elif draw < 980_000:
        base = distribution.p90_balance
    else:
        base = distribution.p99_balance
    concentration_boost = 1_000 + (
        distribution.top_10_concentration_milli
        * _stable_fraction(seed, "portfolio-concentration.v0.1", agent_id)
        // 1_000_000
    )
    return max(1, base * concentration_boost // 1_000)


def _independent_composition_weight(seed: int, agent_id: str) -> int:
    draw = _stable_fraction(seed, "portfolio-composition.v0.1", agent_id)
    return max(1, 100_000 + draw)


def _preset_archetypes(preset: str, count: int | None) -> list[str]:
    configured = PRESET_COUNTS.get(preset)
    if configured is None:
        raise ValidationError(f"unknown population preset '{preset}'")
    default_count = sum(configured.values())
    target = count or default_count
    if target == default_count:
        return [archetype for archetype, quantity in configured.items() for _ in range(quantity)]
    archetypes = list(configured)
    normalized = _largest_remainder(target, [configured[item] for item in archetypes])
    return [archetype for archetype, quantity in zip(archetypes, normalized, strict=True) for _ in range(quantity)]


def preset_configuration_drafts(
    *,
    preset: str,
    agent_count: int | None,
    planner_kind: str,
) -> list[AgentConfigurationDraft]:
    archetypes = _preset_archetypes(preset, agent_count)
    return [
        AgentConfigurationDraft(
            draft_id=f"preset-{index:04d}",
            input_mode="random",
            agent_id=f"agent_{index:04d}",
            display_name=f"Market Participant {index:03d}",
            archetype_ids=[archetype],
        )
        for index, archetype in enumerate(archetypes, start=1)
    ]


def _allocate_with_manual_overrides(
    *,
    total: int,
    weights: list[int],
    manual: list[int | None],
    field_name: str,
) -> list[int]:
    manual_total = sum(value or 0 for value in manual)
    if manual_total > total:
        raise ValidationError(f"manual {field_name} amounts exceed the explicit allocation budget")
    output = [value or 0 for value in manual]
    remaining_indexes = [index for index, value in enumerate(manual) if value is None]
    remaining = total - manual_total
    if not remaining_indexes:
        if remaining:
            raise ValidationError(f"fully manual {field_name} amounts must equal the explicit allocation budget")
        return output
    distributed = _largest_remainder(remaining, [weights[index] for index in remaining_indexes])
    for index, value in zip(remaining_indexes, distributed, strict=True):
        output[index] = value
    return output


def generate_population(
    *,
    seed: int,
    preset: str,
    agent_count: int | None,
    eligible_active_supply: int,
    covered_eligible_supply: int,
    total_token_supply: int,
    active_usdx_supply: int,
    holder_distribution: HolderDistribution,
    portfolio: PortfolioSynthesisConfig,
    planner_kind: str,
    drafts: list[AgentConfigurationDraft] | None = None,
) -> PopulationResult:
    source_drafts = drafts or preset_configuration_drafts(
        preset=preset,
        agent_count=agent_count,
        planner_kind=planner_kind,
    )
    if not source_drafts:
        raise ValidationError("at least one explicit Agent is required")
    compiled: list[CompiledAgentDraft] = [
        compile_agent_configuration(
            draft,
            seed=seed,
            ordinal=index,
            planner_kind=planner_kind,
        )
        for index, draft in enumerate(source_drafts, start=1)
    ]
    definitions = [item.definition for item in compiled]
    agent_ids = [item.agent_id for item in definitions]
    if len(agent_ids) != len(set(agent_ids)):
        raise ValidationError("compiled agent_id values must be unique")

    other_token = sum(account.token_amount for account in portfolio.other_explicit_accounts)
    other_usdx = sum(account.usdx_amount for account in portfolio.other_explicit_accounts)
    available_token = eligible_active_supply - other_token
    available_usdx = active_usdx_supply - other_usdx
    if available_token < 0:
        raise ValidationError("other explicit Token accounts exceed Eligible Active Supply")
    if available_usdx < 0:
        raise ValidationError("other explicit USDx accounts exceed active USDx supply")

    holder_weights = [_holder_weight(seed, agent_id, holder_distribution) for agent_id in agent_ids]
    raw_sample_total = sum(holder_weights)
    sampled_budget = min(raw_sample_total, covered_eligible_supply, available_token)
    manual_token = [item.token_amount for item in compiled]
    manual_token_total = sum(value or 0 for value in manual_token)
    if manual_token_total > available_token:
        raise ValidationError("manual Agent Token amounts exceed Eligible Active Supply")

    if all(value is not None for value in manual_token):
        explicit_token_budget = manual_token_total
        token_values = [int(value) for value in manual_token if value is not None]
    elif portfolio.token_distribution == "manual":
        if any(value is None for value in manual_token):
            raise ValidationError("manual Token allocation requires an amount for every Agent")
        explicit_token_budget = manual_token_total
        token_values = [int(value) for value in manual_token if value is not None]
    else:
        explicit_token_budget = portfolio.explicit_token_budget if portfolio.explicit_token_budget is not None else sampled_budget
        explicit_token_budget = max(explicit_token_budget, manual_token_total)
        if explicit_token_budget > available_token:
            raise ValidationError("explicit Agent Token budget exceeds Eligible Active Supply")
        weights = [1] * len(compiled) if portfolio.token_distribution == "equal" else holder_weights
        token_values = _allocate_with_manual_overrides(
            total=explicit_token_budget,
            weights=weights,
            manual=manual_token,
            field_name="Token",
        )

    token_weight_ppm = _largest_remainder(1_000_000, [max(1, value) for value in token_values])
    independent_weight_ppm = _largest_remainder(
        1_000_000,
        [_independent_composition_weight(seed, agent_id) for agent_id in agent_ids],
    )
    correlation = portfolio.token_usdx_correlation_milli
    composition_weights = [
        max(1, correlation * token_weight + (1_000 - correlation) * independent_weight)
        for token_weight, independent_weight in zip(token_weight_ppm, independent_weight_ppm, strict=True)
    ]
    default_explicit_usdx = (
        active_usdx_supply * explicit_token_budget // eligible_active_supply
        if eligible_active_supply
        else 0
    )
    manual_usdx = [item.usdx_amount for item in compiled]
    manual_usdx_total = sum(value or 0 for value in manual_usdx)
    if manual_usdx_total > available_usdx:
        raise ValidationError("manual Agent USDx amounts exceed active USDx supply")
    explicit_usdx_budget = (
        manual_usdx_total
        if all(value is not None for value in manual_usdx)
        else max(default_explicit_usdx, manual_usdx_total)
    )
    if explicit_usdx_budget > available_usdx:
        explicit_usdx_budget = available_usdx
    usdx_values = _allocate_with_manual_overrides(
        total=explicit_usdx_budget,
        weights=composition_weights,
        manual=manual_usdx,
        field_name="USDx",
    )

    allocations = [
        AgentConfig(
            agent_id=item.definition.agent_id,
            display_name=item.definition.display_name,
            strategy=item.strategy,  # type: ignore[arg-type]
            role_tags=item.definition.role_tags,
            capabilities=item.definition.capability_set,
            token_balance=token,
            usdx_balance=usdx,
            configuration_provenance={
                **item.portfolio_provenance,
                "portfolio.token_balance": item.portfolio_provenance.get(
                    "portfolio.token_amount",
                    item.definition.configuration_provenance["agent_id"].model_copy(update={
                        "source": "random" if item.input_mode == "random" else "default",
                        "source_ref": portfolio.synthesis_distribution_version,
                        "distribution_version": portfolio.synthesis_distribution_version,
                        "seed": seed,
                    }),
                ),
                "portfolio.usdx_balance": item.portfolio_provenance.get(
                    "portfolio.usdx_amount",
                    item.definition.configuration_provenance["agent_id"].model_copy(update={
                        "source": "random" if item.input_mode == "random" else "default",
                        "source_ref": portfolio.composition_distribution_version,
                        "distribution_version": portfolio.composition_distribution_version,
                        "seed": seed,
                    }),
                ),
            },
        )
        for item, token, usdx in zip(compiled, token_values, usdx_values, strict=True)
    ]

    background = BackgroundMarketSector(
        token_balance=available_token - sum(token_values),
        usdx_balance=available_usdx - sum(usdx_values),
        enabled=True,
        two_sided_ready=(available_token - sum(token_values) > 0 and available_usdx - sum(usdx_values) > 0),
        participation_policy_id="background.seeded.v0.1",
    )
    if not background.two_sided_ready:
        raise ValidationError("background market requires positive residual Token and USDx balances")

    sorted_token = sorted(token_values, reverse=True)
    sorted_usdx = sorted(usdx_values, reverse=True)
    preview = {
        "preset": preset if drafts is None else "custom-drafts",
        "seed": seed,
        "agent_count": len(definitions),
        "archetype_counts": {
            archetype: sum(archetype in item.archetype_ids for item in compiled)
            for archetype in sorted({archetype for item in compiled for archetype in item.archetype_ids})
        },
        "assets": {
            "token_total_before": total_token_supply,
            "eligible_active_token_supply": eligible_active_supply,
            "covered_eligible_token_supply": covered_eligible_supply,
            "inactive_token_supply": total_token_supply - eligible_active_supply,
            "explicit_agent_token": sum(token_values),
            "other_explicit_token": other_token,
            "background_token": background.token_balance,
            "active_usdx_supply": active_usdx_supply,
            "explicit_agent_usdx": sum(usdx_values),
            "other_explicit_usdx": other_usdx,
            "background_usdx": background.usdx_balance,
            "token_total_after": sum(token_values) + other_token + background.token_balance + total_token_supply - eligible_active_supply,
            "usdx_total_before": active_usdx_supply,
            "usdx_total_after": sum(usdx_values) + other_usdx + background.usdx_balance,
            "token_conserved": sum(token_values) + other_token + background.token_balance + total_token_supply - eligible_active_supply == total_token_supply,
            "usdx_conserved": sum(usdx_values) + other_usdx + background.usdx_balance == active_usdx_supply,
            "background_derivation": "eligible_or_active_supply_minus_explicit_accounts",
        },
        "portfolio_distribution": {
            "synthesis_version": portfolio.synthesis_distribution_version,
            "composition_version": portfolio.composition_distribution_version,
            "holder_distribution_version": holder_distribution.distribution_version,
            "token_distribution": portfolio.token_distribution,
            "token_usdx_correlation_milli": portfolio.token_usdx_correlation_milli,
            "raw_sample_total": raw_sample_total,
            "sample_scaled": raw_sample_total > sampled_budget,
            "manual_token_overrides": sum(value is not None for value in manual_token),
            "manual_usdx_overrides": sum(value is not None for value in manual_usdx),
            "token_min": min(token_values),
            "token_max": max(token_values),
            "usdx_min": min(usdx_values),
            "usdx_max": max(usdx_values),
            "token_top_5": sorted_token[:5],
            "usdx_top_5": sorted_usdx[:5],
            "seed": seed,
        },
        "background": {
            "enabled": background.enabled,
            "two_sided_ready": background.two_sided_ready,
        },
        "configuration": {
            "compiler_version": "agent-configuration-compiler.v0.1",
            "input_modes": sorted({item.input_mode for item in compiled}),
            "ambiguities": [ambiguity for item in compiled for ambiguity in item.ambiguities],
        },
    }
    return PopulationResult(definitions, allocations, background, preview)
