from __future__ import annotations

import unittest

from sandbox.agents.population import generate_population


class PopulationTests(unittest.TestCase):
    def test_seeded_populations_are_stable_and_conserve_assets(self) -> None:
        expected_counts = {"smoke": 4, "compact": 20, "standard": 200}
        for preset, expected_count in expected_counts.items():
            first = generate_population(
                seed=20260724,
                preset=preset,
                total_token=1_000_000,
                total_usdx=100_000_000,
                planner_kind="openai",
            )
            second = generate_population(
                seed=20260724,
                preset=preset,
                total_token=1_000_000,
                total_usdx=100_000_000,
                planner_kind="openai",
            )
            self.assertEqual(first, second)
            self.assertEqual(len(first.definitions), expected_count)
            self.assertNotIn("background", {item.agent_id for item in first.definitions})
            self.assertEqual(sum(item.token_balance for item in first.allocations) + first.background.token_balance, 1_000_000)
            self.assertEqual(sum(item.usdx_balance for item in first.allocations) + first.background.usdx_balance, 100_000_000)
            self.assertTrue(all(isinstance(item.token_balance, int) and isinstance(item.usdx_balance, int) for item in first.allocations))


if __name__ == "__main__":
    unittest.main()
