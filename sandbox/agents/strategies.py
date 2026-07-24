from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    action_type: str
    payload: dict[str, object]


class FixtureStrategies:
    """Deterministic actions used only by the explicit test fixture mode."""

    STEPS = (
        ("background", StrategyDecision("SubmitLimitOrder", {"side": "sell", "quantity": 1_000, "price_multiplier_bps": 10_010})),
        ("rule_alpha", StrategyDecision("SubmitLimitOrder", {"side": "buy", "quantity": 600, "price_multiplier_bps": 10_010})),
        ("background", StrategyDecision("SubmitLimitOrder", {"side": "buy", "quantity": 1_000, "price_multiplier_bps": 9_990})),
        ("rule_beta", StrategyDecision("SubmitLimitOrder", {"side": "sell", "quantity": 400, "price_multiplier_bps": 9_990})),
        ("replay_agent", StrategyDecision("SubmitLimitOrder", {"side": "buy", "quantity": 100, "price_multiplier_bps": 10_010})),
        ("replay_agent", StrategyDecision("PublishInformation", {"channel": "PublicFeed", "content": "Replay fixture: liquidity conditions changed."})),
    )

    @classmethod
    def at(cls, index: int, *, reference_price: int = 10_000, price_tick: int = 1) -> tuple[str, StrategyDecision] | None:
        if not 0 <= index < len(cls.STEPS):
            return None
        agent_id, decision = cls.STEPS[index]
        payload = dict(decision.payload)
        multiplier = payload.pop("price_multiplier_bps", None)
        if multiplier is not None:
            raw_price = reference_price * int(multiplier) // 10_000
            payload["price"] = max(price_tick, raw_price // price_tick * price_tick)
        return agent_id, StrategyDecision(decision.action_type, payload)
