from __future__ import annotations

import unittest

from sandbox.agents.population import generate_population
from sandbox.contracts.scenario import HolderDistribution, PortfolioSynthesisConfig


class PopulationTests(unittest.TestCase):
    def test_seeded_populations_are_stable_and_conserve_assets(self) -> None:
        expected_counts = {"smoke": 4, "compact": 20, "standard": 200}
        holder_distribution = HolderDistribution(
            active_holder_count=10_000,
            p25_balance=100,
            p50_balance=500,
            p75_balance=2_000,
            p90_balance=10_000,
            p99_balance=50_000,
            top_10_concentration_milli=600,
        )
        for preset, expected_count in expected_counts.items():
            first = generate_population(
                seed=20260724,
                preset=preset,
                agent_count=None,
                eligible_active_supply=900_000,
                covered_eligible_supply=600_000,
                total_token_supply=1_000_000,
                active_usdx_supply=100_000_000,
                holder_distribution=holder_distribution,
                portfolio=PortfolioSynthesisConfig(),
                planner_kind="openai",
            )
            second = generate_population(
                seed=20260724,
                preset=preset,
                agent_count=None,
                eligible_active_supply=900_000,
                covered_eligible_supply=600_000,
                total_token_supply=1_000_000,
                active_usdx_supply=100_000_000,
                holder_distribution=holder_distribution,
                portfolio=PortfolioSynthesisConfig(),
                planner_kind="openai",
            )
            self.assertEqual(first, second)
            self.assertEqual(len(first.definitions), expected_count)
            self.assertNotIn("background", {item.agent_id for item in first.definitions})
            self.assertEqual(sum(item.token_balance for item in first.allocations) + first.background.token_balance, 900_000)
            self.assertEqual(sum(item.usdx_balance for item in first.allocations) + first.background.usdx_balance, 100_000_000)
            self.assertTrue(first.preview["assets"]["token_conserved"])
            self.assertTrue(first.preview["assets"]["usdx_conserved"])
            self.assertTrue(all(isinstance(item.token_balance, int) and isinstance(item.usdx_balance, int) for item in first.allocations))


if __name__ == "__main__":
    unittest.main()
