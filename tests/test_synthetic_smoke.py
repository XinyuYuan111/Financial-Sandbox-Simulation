from __future__ import annotations

import unittest

from sandbox.agents.llm_gateway import LLMGateway
from sandbox.contracts.planning import ProviderProfile
from sandbox.contracts.scenario import ScenarioDraft
from sandbox.control.initialization import Initializer, synthetic_smoke_snapshot


class FakeDeepSeekAdapter:
    name = "deepseek"
    profile = ProviderProfile(
        provider="deepseek",
        model="deepseek-chat",
        endpoint_class="chat_completions",
        timeout_seconds=60,
        max_retries=1,
        max_in_flight=4,
        max_output_tokens=1_800,
        key_present=True,
    )

    async def preflight(self) -> dict[str, object]:
        return {
            "ok": True,
            "provider": "deepseek",
            "model": "deepseek-chat",
        }


class SyntheticSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_smoke_resolution_needs_no_holder_provider_and_conserves_assets(self) -> None:
        initializer = Initializer(
            holder_providers={},
            llm_gateway=LLMGateway({"deepseek": FakeDeepSeekAdapter()}),
        )
        draft = ScenarioDraft(
            mode="live_llm_smoke",
            llm_provider="deepseek",
            seed=20260724,
            target_token="SMOKE",
            population={"preset": "smoke", "agent_count": 4},
        )

        resolved = await initializer.resolve("scenario-synthetic", draft)

        self.assertEqual(resolved.chain_snapshot.provider, "synthetic-holder-snapshot")
        self.assertEqual(resolved.chain_snapshot.chain_id, "synthetic-smoke")
        self.assertTrue(resolved.provider_report["synthetic"])
        self.assertEqual(
            sum(bucket.amount for bucket in resolved.chain_snapshot.source_buckets),
            resolved.chain_snapshot.total_supply,
        )
        self.assertEqual(
            sum(agent.token_balance for agent in resolved.agents) + resolved.background_market_sector.token_balance,
            resolved.chain_snapshot.eligible_active_supply,
        )
        self.assertEqual(
            sum(agent.usdx_balance for agent in resolved.agents) + resolved.background_market_sector.usdx_balance,
            resolved.total_supply[resolved.market.quote_asset],
        )
        self.assertTrue(resolved.background_market_sector.two_sided_ready)
        self.assertTrue(all(agent.strategy == "deepseek" for agent in resolved.agents))
        self.assertTrue(all(definition.planner_profile_id.startswith("deepseek.") for definition in resolved.agent_definitions))

    async def test_synthetic_snapshot_is_seeded_and_reproducible(self) -> None:
        first = synthetic_smoke_snapshot(seed=7, target_token="TOKEN")
        repeated = synthetic_smoke_snapshot(seed=7, target_token="TOKEN")
        different = synthetic_smoke_snapshot(seed=8, target_token="TOKEN")

        self.assertEqual(first, repeated)
        self.assertNotEqual(first.content_hash, different.content_hash)
        self.assertNotEqual(first.total_supply, different.total_supply)


if __name__ == "__main__":
    unittest.main()
