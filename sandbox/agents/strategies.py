from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    action_type: str
    payload: dict[str, object]


class FixtureStrategies:
    """Deterministic actions used only by the explicit test fixture mode."""

    STEPS = (
        ("background", StrategyDecision("SubmitLimitOrder", {"side": "sell", "quantity": 1_000, "price": 102})),
        ("rule_alpha", StrategyDecision("SubmitLimitOrder", {"side": "buy", "quantity": 600, "price": 102})),
        ("background", StrategyDecision("SubmitLimitOrder", {"side": "buy", "quantity": 1_000, "price": 98})),
        ("rule_beta", StrategyDecision("SubmitLimitOrder", {"side": "sell", "quantity": 400, "price": 98})),
        ("replay_agent", StrategyDecision("SubmitLimitOrder", {"side": "buy", "quantity": 100, "price": 102})),
        ("replay_agent", StrategyDecision("PublishInformation", {"channel": "PublicFeed", "content": "Replay fixture: liquidity conditions changed."})),
    )

    @classmethod
    def at(cls, index: int) -> tuple[str, StrategyDecision] | None:
        return cls.STEPS[index] if 0 <= index < len(cls.STEPS) else None
