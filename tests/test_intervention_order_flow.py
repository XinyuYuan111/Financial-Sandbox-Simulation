from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from sandbox.agents.llm_gateway import LLMGateway
from sandbox.contracts.intervention import DirectorPlanCandidate, InterventionPlanDraftInput, InterventionStage
from sandbox.contracts.scenario import ScenarioDraft
from sandbox.control.initialization import Initializer
from sandbox.control.run_manager import RunManager
from sandbox.store.archive import ArchiveService
from sandbox.store.sqlite import SQLiteStore
from sandbox.world.state import SimulationWorld


def impact_stage(impact_milli: int, *, stage_id: str = "stage-impact") -> InterventionStage:
    return InterventionStage.model_validate({
        "stage_id": stage_id,
        "effective_sim_time_us": 0,
        "background_order_flow_impact_milli": impact_milli,
        "effects": [{
            "effect_id": f"{stage_id}-announcement",
            "effect_type": "publish_information",
            "source_id": "scenario_director",
            "channel": "OfficialAnnouncement",
            "content": "A market-moving announcement was released.",
            "target_ids": [],
            "depends_on_state_effect_ids": [],
            "private_source_refs": [],
        }],
    })


class InterventionOrderFlowContractTests(unittest.TestCase):
    def test_impact_is_signed_bounded_and_defaults_to_neutral(self) -> None:
        neutral = impact_stage(0).model_dump(mode="json")
        self.assertEqual(neutral["background_order_flow_impact_milli"], 0)
        self.assertEqual(impact_stage(-1_000).background_order_flow_impact_milli, -1_000)
        self.assertEqual(impact_stage(1_000).background_order_flow_impact_milli, 1_000)

        for invalid in (-1_001, 1_001):
            with self.subTest(invalid=invalid), self.assertRaises(PydanticValidationError):
                impact_stage(invalid)

        legacy = impact_stage(0).model_dump(mode="json")
        legacy.pop("background_order_flow_impact_milli")
        self.assertEqual(InterventionStage.model_validate(legacy).background_order_flow_impact_milli, 0)

    def test_ai_candidate_must_explicitly_assess_every_stage(self) -> None:
        stage = impact_stage(0).model_dump(mode="json")
        stage.pop("background_order_flow_impact_milli")
        with self.assertRaises(PydanticValidationError):
            DirectorPlanCandidate.model_validate({"stages": [stage]})


class InterventionOrderFlowRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = SQLiteStore(self.root / "sandbox.db")
        self.manager = RunManager(
            self.store,
            Initializer({}, LLMGateway({})),
            ArchiveService(self.store, "0.2.0"),
            "0.2.0",
        )
        scenario = self.manager.create_scenario(ScenarioDraft(seed=1))
        resolved = asyncio.run(self.manager.resolve_scenario(str(scenario["scenario_id"])))
        run = self.manager.create_run(str(scenario["scenario_id"]), resolved.resolution_hash)
        self.run_id = str(run["run_id"])
        self.branch_id = str(run["branches"][0]["branch_id"])

    def tearDown(self) -> None:
        self.manager.close()
        self.store.close()
        self.temp.cleanup()

    def _apply_directly(self, impact_milli: int) -> SimulationWorld:
        world = self.manager._world(self.branch_id)
        result = world.apply_intervention_stage(
            impact_stage(impact_milli),
            plan_id=f"plan-{impact_milli}",
            branch_id=self.branch_id,
            world_version=0,
        )
        self.assertTrue(any(event.event_type == "BackgroundOrderFlowImpactApplied" for event in result.events))
        return result.world

    def test_signed_impact_changes_direction_with_identical_rng_draws(self) -> None:
        bullish = self._apply_directly(1_000)
        bearish = self._apply_directly(-1_000)

        # Extreme impact deliberately retains 10% contra-flow noise. Advance both
        # identical named streams to a draw that lies between the two thresholds.
        while True:
            probe = bullish.clone()
            side_value, _ = probe.rng.random("background-order-flow.side")
            if 100 <= int(side_value * 1_000) < 900:
                break
            bullish.rng.random("background-order-flow.side")
            bearish.rng.random("background-order-flow.side")

        bullish_action = self.manager._next_background_action(bullish, self.branch_id, 0)
        bearish_action = self.manager._next_background_action(bearish, self.branch_id, 0)
        self.assertIsNotNone(bullish_action)
        self.assertIsNotNone(bearish_action)
        bullish_sample = bullish.background_market_sector["pending_order_flow_sample"]
        bearish_sample = bearish.background_market_sector["pending_order_flow_sample"]

        self.assertEqual(bullish_sample["side_draw_index"], bearish_sample["side_draw_index"])
        self.assertEqual(bullish_sample["side_sample_milli"], bearish_sample["side_sample_milli"])
        self.assertEqual(bullish_sample["side"], "buy")
        self.assertEqual(bearish_sample["side"], "sell")
        self.assertEqual(bullish_sample["net_impact_milli"], 1_000)
        self.assertEqual(bearish_sample["net_impact_milli"], -1_000)
        self.assertEqual(bullish_sample["effective_buy_probability_milli"], 900)
        self.assertEqual(bearish_sample["effective_buy_probability_milli"], 100)
        self.assertGreater(bullish_sample["quantity_multiplier_milli"], 1_000)
        self.assertGreater(bearish_sample["quantity_multiplier_milli"], 1_000)
        self.assertTrue(bullish_sample["active_impact_sources"])
        self.assertTrue(bearish_sample["active_impact_sources"])

    def test_impact_decays_linearly_and_expires_after_thirty_minutes(self) -> None:
        world = self._apply_directly(1_000)
        world.sim_time_us = 15_000_000
        midpoint, midpoint_sources = self.manager._background_order_flow_impact(world)
        self.assertEqual(midpoint, 500)
        self.assertEqual(len(midpoint_sources), 1)

        world.sim_time_us = 30_000_000
        expired, expired_sources = self.manager._background_order_flow_impact(world)
        self.assertEqual(expired, 0)
        self.assertEqual(expired_sources, [])
        self.assertEqual(world.background_market_sector["active_intervention_impacts"], [])

    def test_concurrent_impacts_add_then_clamp(self) -> None:
        world = self._apply_directly(800)
        second = world.apply_intervention_stage(
            impact_stage(700, stage_id="stage-second-impact"),
            plan_id="plan-second-impact",
            branch_id=self.branch_id,
            world_version=0,
        ).world

        net, sources = self.manager._background_order_flow_impact(second)
        self.assertEqual(net, 1_000)
        self.assertEqual(len(sources), 2)

        second.sim_time_us = 15_000_000
        midpoint, _ = self.manager._background_order_flow_impact(second)
        self.assertEqual(midpoint, 750)

    def test_apply_persists_source_and_checkpoint_fork_inherits_it(self) -> None:
        self.manager.command(self.branch_id, "impact-start", "start")
        self.manager.command(self.branch_id, "impact-pause", "pause")
        current_time = self.manager._world(self.branch_id).sim_time_us
        stage = impact_stage(750).model_copy(update={"effective_sim_time_us": current_time})
        draft = InterventionPlanDraftInput(
            user_intent="Inject strongly bullish news",
            stages=[stage],
        )
        created = self.manager.create_intervention_plan(self.branch_id, "impact-draft", draft)
        confirmed = self.manager.confirm_intervention_plan(
            self.branch_id,
            str(created["plan_id"]),
            "impact-confirm",
        )
        self.assertEqual(confirmed["status"], "completed")

        persisted = self.manager._world(self.branch_id).background_market_sector
        serialized = json.dumps(persisted, sort_keys=True)
        self.assertIn(str(created["plan_id"]), serialized)
        self.assertIn(stage.stage_id, serialized)
        activation = next(
            event
            for event in self.manager.events.list_events(self.branch_id, limit=10_000)
            if event.event_type == "BackgroundOrderFlowImpactApplied"
        )
        self.assertEqual(activation.payload["signed_impact_milli"], 750)
        self.assertEqual(
            activation.payload["expires_sim_time_us"] - activation.payload["applied_sim_time_us"],
            30_000_000,
        )

        self.manager.command(self.branch_id, "impact-resume", "start")
        self.manager._runner_cancel[self.branch_id].set()
        sampled_events = []
        for _ in range(32):
            sampled_events = [
                event
                for event in self.manager.events.list_events(self.branch_id, limit=10_000)
                if event.event_type == "BackgroundOrderFlowSampled"
            ]
            if sampled_events:
                break
            self.assertTrue(self.manager._advance_background_once(self.branch_id))
        self.assertTrue(sampled_events)
        sampled = sampled_events[-1]
        self.assertIn("net_impact_milli", sampled.payload)
        self.assertIn("effective_buy_probability_milli", sampled.payload)
        self.assertIn("quantity_multiplier_milli", sampled.payload)
        self.assertTrue(any(
            source["impact_id"] == activation.payload["impact_id"]
            for source in sampled.payload["active_impact_sources"]
        ))
        self.manager.command(self.branch_id, "impact-repause", "pause")

        saved = self.manager.command(self.branch_id, "impact-save", "save")
        child = self.manager.fork(self.branch_id, str(saved["checkpoint_id"]), "impact-fork")
        child_id = str(child["branch_id"])
        self.assertEqual(
            self.manager._world(child_id).background_market_sector,
            self.manager._world(self.branch_id).background_market_sector,
        )

    def test_bullish_and_bearish_forks_create_divergent_background_flow(self) -> None:
        self.manager.command(self.branch_id, "fork-base-start", "start")
        self.manager.command(self.branch_id, "fork-base-pause", "pause")
        saved = self.manager.command(self.branch_id, "fork-base-save", "save")
        bullish_id = str(self.manager.fork(
            self.branch_id, str(saved["checkpoint_id"]), "fork-bullish-impact",
        )["branch_id"])
        bearish_id = str(self.manager.fork(
            self.branch_id, str(saved["checkpoint_id"]), "fork-bearish-impact",
        )["branch_id"])

        for branch_id, impact, label in (
            (bullish_id, 1_000, "bullish"),
            (bearish_id, -1_000, "bearish"),
        ):
            self.manager.command(branch_id, f"prepare-{label}", "start")
            self.manager.command(branch_id, f"prepare-pause-{label}", "pause")
            sim_time = self.manager._world(branch_id).sim_time_us
            stage = impact_stage(impact, stage_id=f"stage-{label}").model_copy(
                update={"effective_sim_time_us": sim_time},
            )
            created = self.manager.create_intervention_plan(
                branch_id,
                f"draft-{label}",
                InterventionPlanDraftInput(user_intent=label, stages=[stage]),
            )
            self.manager.confirm_intervention_plan(
                branch_id, str(created["plan_id"]), f"confirm-{label}",
            )
            initial_sequence = int(
                self.manager._world(branch_id).background_market_sector.get("policy_sequence", 0)
            )
            self.manager.command(branch_id, f"start-{label}", "start")
            self.manager._runner_cancel[branch_id].set()
            for _ in range(512):
                if int(self.manager._world(branch_id).background_market_sector.get("policy_sequence", 0)) >= initial_sequence + 24:
                    break
                self.assertTrue(self.manager._advance_background_once(branch_id))
            self.manager.command(branch_id, f"pause-{label}", "pause")

        def flow_samples(branch_id: str) -> list[dict[str, object]]:
            return [
                event.payload
                for event in self.manager.events.list_events(branch_id, limit=10_000)
                if event.event_type == "BackgroundOrderFlowSampled"
                and int(event.payload.get("net_impact_milli", 0)) != 0
            ]

        bullish_samples = flow_samples(bullish_id)
        bearish_samples = flow_samples(bearish_id)
        self.assertTrue(bullish_samples)
        self.assertTrue(bearish_samples)
        self.assertGreater(
            sum(sample["side"] == "buy" for sample in bullish_samples),
            sum(sample["side"] == "buy" for sample in bearish_samples),
        )
        self.assertGreater(
            sum(sample["side"] == "sell" for sample in bearish_samples),
            sum(sample["side"] == "sell" for sample in bullish_samples),
        )

        bullish_trades = self.manager.branch_projection(bullish_id)["market"]["trades"]
        bearish_trades = self.manager.branch_projection(bearish_id)["market"]["trades"]
        bullish_prices = [
            int(trade["price"])
            for trade in bullish_trades
            if {trade["buyer_id"], trade["seller_id"]} == {"background", "background_order_flow"}
        ]
        bearish_prices = [
            int(trade["price"])
            for trade in bearish_trades
            if {trade["buyer_id"], trade["seller_id"]} == {"background", "background_order_flow"}
        ]
        self.assertTrue(bullish_prices)
        self.assertTrue(bearish_prices)
        self.assertGreater(bullish_prices[-1], bearish_prices[-1])


if __name__ == "__main__":
    unittest.main()
