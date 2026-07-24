from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sandbox.contracts.agent import (
    AgentDefinition,
    AttentionProfile,
    BasePersona,
    CognitiveProfile,
    LatencyProfile,
)
from sandbox.contracts.scenario import AgentConfig, BackgroundMarketSector
from sandbox.core.rng import NamedRandomStreams


PRESET_COUNTS: dict[str, dict[str, int]] = {
    "smoke": {"ordinary": 1, "capital": 1, "liquidity": 1, "information": 1},
    "compact": {"ordinary": 14, "capital": 2, "liquidity": 2, "issuer": 1, "information": 1},
    "standard": {"ordinary": 180, "capital": 8, "liquidity": 6, "issuer": 1, "information": 5},
}

PROFILE_SHARES = {
    "ordinary": 75_000,
    "capital": 500_000,
    "liquidity": 300_000,
    "issuer": 100_000,
    "information": 25_000,
}


@dataclass(frozen=True, slots=True)
class PopulationResult:
    definitions: list[AgentDefinition]
    allocations: list[AgentConfig]
    background: BackgroundMarketSector
    preview: dict[str, object]


def _draw_milli(streams: NamedRandomStreams, name: str, minimum: int, maximum: int) -> int:
    value, _ = streams.random(name)
    return minimum + int(value * (maximum - minimum + 1))


def _largest_remainder(total: int, weights: list[int]) -> list[int]:
    if not weights:
        return []
    denominator = sum(weights)
    base = [(total * weight) // denominator for weight in weights]
    remainder = total - sum(base)
    order = sorted(
        range(len(weights)),
        key=lambda index: (-((total * weights[index]) % denominator), index),
    )
    for index in order[:remainder]:
        base[index] += 1
    return base


def _ranked_weights(seed: int, profile: str, count: int) -> list[int]:
    ranked = list(range(count))
    ranked.sort(
        key=lambda index: hashlib.sha256(f"{seed}:initialization.assets:{profile}:{index}".encode()).digest()
    )
    weights_by_rank = [max(1, 1_000_000 // ((rank + 3) ** 2)) for rank in range(count)]
    weights = [0] * count
    for rank, index in enumerate(ranked):
        weights[index] = weights_by_rank[rank]
    return weights


def _allocate_by_profile(total: int, profiles: list[str], seed: int, asset: str) -> list[int]:
    present = list(dict.fromkeys(profiles))
    profile_totals = _largest_remainder(total, [PROFILE_SHARES[profile] for profile in present])
    totals_by_profile = dict(zip(present, profile_totals, strict=True))
    output = [0] * len(profiles)
    for profile in present:
        indexes = [index for index, item in enumerate(profiles) if item == profile]
        weights = _ranked_weights(seed, f"{asset}:{profile}", len(indexes))
        values = _largest_remainder(totals_by_profile[profile], weights)
        for index, value in zip(indexes, values, strict=True):
            output[index] = value
    return output


def generate_population(
    *,
    seed: int,
    preset: str,
    total_token: int,
    total_usdx: int,
    planner_kind: str,
) -> PopulationResult:
    counts = PRESET_COUNTS.get(preset)
    if counts is None:
        raise ValueError(f"unknown population preset '{preset}'")
    streams = NamedRandomStreams(seed)
    profiles = [profile for profile, count in counts.items() for _ in range(count)]
    explicit_token = total_token * 700_000 // 1_000_000
    explicit_usdx = total_usdx * 700_000 // 1_000_000
    token_values = _allocate_by_profile(explicit_token, profiles, seed, "token")
    usdx_values = _allocate_by_profile(explicit_usdx, profiles, seed, "usdx")

    definitions: list[AgentDefinition] = []
    allocations: list[AgentConfig] = []
    for index, profile in enumerate(profiles, start=1):
        agent_id = f"agent_{index:04d}"
        role_tags = [profile]
        capabilities = ["market.trade", "information.read"]
        if profile == "liquidity":
            capabilities.append("market.quote")
        if profile in {"information", "issuer"}:
            capabilities.append("information.publish")
        persona = BasePersona(
            template_id="seeded_market_participant",
            private_goals=["preserve_capital", "pursue_risk_adjusted_return"],
            risk_tolerance_milli=_draw_milli(streams, f"agent.{agent_id}.persona", 250, 850),
            time_horizon=("short", "medium", "long")[index % 3],
            loss_aversion_milli=_draw_milli(streams, f"agent.{agent_id}.persona", 250, 900),
            trend_bias_milli=_draw_milli(streams, f"agent.{agent_id}.persona", 100, 900),
            skepticism_milli=_draw_milli(streams, f"agent.{agent_id}.persona", 100, 900),
            communication_propensity_milli=_draw_milli(streams, f"agent.{agent_id}.persona", 50, 850),
            bounded_notes="Seeded independent participant.",
        )
        definition = AgentDefinition(
            agent_id=agent_id,
            display_name=f"Market Participant {index:03d}",
            public_identity=f"Independent {profile} participant",
            role_tags=role_tags,
            funding_profile=profile,  # type: ignore[arg-type]
            capability_set=capabilities,
            base_persona=persona,
            planner_profile_id=f"{planner_kind}.default.v0.1",
            cognitive_profile=CognitiveProfile(
                context_capacity=6_000 + _draw_milli(streams, f"agent.{agent_id}.cognition", 0, 4_000),
                memory_search_limit=3 + _draw_milli(streams, f"agent.{agent_id}.cognition", 0, 3),
            ),
            attention_profile=AttentionProfile(
                information_capacity=12 + _draw_milli(streams, f"agent.{agent_id}.attention", 0, 16),
                minimum_salience=_draw_milli(streams, f"agent.{agent_id}.attention", 0, 30),
            ),
            latency_profile=LatencyProfile(
                planning_latency_us=500_000 + _draw_milli(streams, f"agent.{agent_id}.latency", 0, 2_000_000),
                action_latency_us=100_000 + _draw_milli(streams, f"agent.{agent_id}.latency", 0, 900_000),
            ),
        )
        definitions.append(definition)
        allocations.append(
            AgentConfig(
                agent_id=agent_id,
                display_name=definition.display_name,
                strategy=planner_kind,  # type: ignore[arg-type]
                role_tags=role_tags,
                funding_profile=profile,
                capabilities=capabilities,
                token_balance=token_values[index - 1],
                usdx_balance=usdx_values[index - 1],
            )
        )

    background = BackgroundMarketSector(
        token_balance=total_token - explicit_token,
        usdx_balance=total_usdx - explicit_usdx,
        participation_policy_id="background.seeded.v0.1",
    )
    preview = {
        "preset": preset,
        "seed": seed,
        "agent_count": len(definitions),
        "funding_profile_counts": counts,
        "active_capital_ppm": {"explicit_agents": 700_000, "background": 300_000},
        "assets": {
            "explicit_token": explicit_token,
            "explicit_usdx": explicit_usdx,
            "background_token": background.token_balance,
            "background_usdx": background.usdx_balance,
            "token_conserved": sum(token_values) + background.token_balance == total_token,
            "usdx_conserved": sum(usdx_values) + background.usdx_balance == total_usdx,
        },
        "named_rng_streams": sorted(streams.snapshot()),
    }
    return PopulationResult(definitions, allocations, background, preview)
