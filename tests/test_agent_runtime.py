from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from sandbox.agents.llm_gateway import LLMGateway
from sandbox.agents.planning import (
    DEMO_ACTIVITY_EMISSION_INTERVAL_US,
    DEMO_ACTIVITY_MAX_EMISSIONS,
    DEMO_NOOP_FALLBACK_PROBABILITY_MILLI,
    RulePlanner,
)
from sandbox.agents.runtime import DEMO_ACTIVITY_REPLAN_COOLDOWN_US
from sandbox.agents.strategies import StrategyDecision
from sandbox.contracts.agent import DecisionRationale
from sandbox.contracts.action import ActionContract
from sandbox.contracts.scenario import ScenarioDraft
from sandbox.contracts.planning import LLMRecord, PlanningResultCandidate, ProviderProfile
from sandbox.contracts.observation import ObservationPacket, ObservedInformation
from sandbox.control.initialization import Initializer
from sandbox.control.run_manager import RunManager
from sandbox.core.ids import new_id
from sandbox.core.errors import ValidationError
from sandbox.store.archive import ArchiveService
from sandbox.store.sqlite import SQLiteStore


class FakePlanningAdapter:
    name = "openai"
    profile = ProviderProfile(
        provider="openai",
        model="fake-model",
        timeout_seconds=1,
        max_retries=0,
        max_in_flight=4,
        max_output_tokens=128,
        key_present=True,
    )

    async def preflight(self) -> dict[str, object]:
        return {"ok": True, "provider": "openai", "model": "fake-model"}

    async def create_plan(self, request, *, record_raw=None):
        if record_raw is not None:
            record_raw(LLMRecord(
                call_id=f"llm-{request.request_id}",
                request_id=request.request_id,
                agent_id=request.agent_id,
                attempt=1,
                provider="openai",
                model="fake-model",
                context_hash=request.context_hash,
                redacted_request={"request_id": request.request_id},
                raw_response={"candidate": "hold"},
                latency_ms=1,
                status="succeeded",
            ))
        return PlanningResultCandidate(
            based_on_strategy_revision=request.based_on_strategy_revision,
            valid_for_us=10_000_000,
            goals=[],
            activation_preconditions=[],
            constraints=[],
            directives=[],
            replan_conditions=[],
            rationale=DecisionRationale(goal_summary="Hold", uncertainty_milli=800, stated_reason="Smoke hold plan"),
        )


class SlowPlanningAdapter(FakePlanningAdapter):
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.requests = []

    async def create_plan(self, request, *, record_raw=None):
        self.requests.append(request)
        await asyncio.sleep(self.delay_seconds)
        return await super().create_plan(request, record_raw=record_raw)


class FailingPlanningAdapter(FakePlanningAdapter):
    async def create_plan(self, request, *, record_raw=None):
        raise ValidationError("provider returned truncated JSON")


class AgentRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(Path(self.temp.name) / "sandbox.db")
        self.manager = RunManager(
            self.store,
            Initializer({}, LLMGateway({})),
            ArchiveService(self.store, "0.2.0"),
            "0.2.0",
        )

    def tearDown(self) -> None:
        self.manager.close()
        self.store.close()
        self.temp.cleanup()

    def wait_for_information_view(self, branch_id: str, action_id: str, agent_id: str, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if any(
                event.action_id == action_id
                and event.event_type == "InformationViewed"
                and event.payload.get("agent_id") == agent_id
                for event in self.manager.events.list_events(branch_id, limit=10_000)
            ):
                return
            time.sleep(0.02)
        self.fail("the information was not viewed before the timeout")

    def create_running(self) -> tuple[str, str]:
        scenario = self.manager.create_scenario(ScenarioDraft())
        resolved = asyncio.run(self.manager.resolve_scenario(str(scenario["scenario_id"])))
        run = self.manager.create_run(str(scenario["scenario_id"]), resolved.resolution_hash)
        branch_id = str(run["branches"][0]["branch_id"])
        self.manager.command(branch_id, "start", "start")
        return str(run["run_id"]), branch_id

    def test_fixture_agent_uses_decision_plan_action_receipt_pipeline(self) -> None:
        _, branch_id = self.create_running()
        initial_decisions = self.store.connection.execute(
            "SELECT COUNT(*) count FROM agent_decisions WHERE branch_id=?", (branch_id,)
        ).fetchone()["count"]
        self.assertEqual(initial_decisions, 3)
        projected_agent = next(
            item for item in self.manager.branch_projection(branch_id)["agents"]
            if item["agent_id"] == "rule_alpha"
        )
        self.assertTrue(projected_agent["planning_request_id"])
        self.assertEqual(projected_agent["agent_revision"], 1)
        self.assertTrue(str(projected_agent["planner_profile_id"]).startswith("rule"))
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) count FROM agent_decisions WHERE branch_id=? AND agent_id='background'", (branch_id,)
            ).fetchone()["count"],
            0,
        )

        self.manager.command(branch_id, "background-step", "step_fixture")
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) count FROM agent_decisions WHERE branch_id=?", (branch_id,)
            ).fetchone()["count"],
            initial_decisions,
        )
        result = self.manager.command(branch_id, "agent-step", "step_fixture")
        self.assertTrue(result["accepted"])
        decision = self.store.connection.execute(
            "SELECT decision_id FROM agent_decisions WHERE branch_id=? AND agent_id='rule_alpha' ORDER BY sim_time_us DESC LIMIT 1",
            (branch_id,),
        ).fetchone()
        receipt = self.store.connection.execute(
            "SELECT receipt_json FROM action_receipts WHERE branch_id=? AND agent_id='rule_alpha' ORDER BY sim_time_us DESC LIMIT 1",
            (branch_id,),
        ).fetchone()
        self.assertIsNotNone(decision)
        self.assertIn(str(decision["decision_id"]), str(receipt["receipt_json"]))
        request = self.store.connection.execute(
            "SELECT state,terminal_outcome FROM planning_requests WHERE branch_id=? AND agent_id='rule_alpha'",
            (branch_id,),
        ).fetchone()
        self.assertEqual((request["state"], request["terminal_outcome"]), ("Terminal", "applied"))
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) count FROM strategy_plans WHERE branch_id=? AND agent_id='rule_alpha' AND active=1", (branch_id,)
            ).fetchone()["count"],
            1,
        )

    def test_private_information_only_wakes_source_and_target(self) -> None:
        _, branch_id = self.create_running()
        action = ActionContract(
            action_id=new_id("act"),
            agent_id="replay_agent",
            branch_id=branch_id,
            submitted_sim_time_us=0,
            action_type="PublishInformation",
            payload={
                "channel": "PrivateChannel",
                "content": "private: buying pressure is strengthening",
                "target_ids": ["rule_alpha"],
                "signal_direction": "bullish",
                "signal_confidence_milli": 900,
            },
            expected_execution_time_us=1,
            validity_window_us=10,
            parent_observation_id=None,
            client_command_id="private-message",
        )
        result = self.manager.submit_action(action)
        self.assertTrue(result["accepted"])
        self.assertIn(action.action_id, self.manager._world(branch_id).pending_actions)
        self.wait_for_information_view(branch_id, action.action_id, "rule_alpha")
        published = next(
            event for event in self.manager.events.list_events(branch_id, limit=10_000)
            if event.action_id == action.action_id and event.event_type == "InformationPublished"
        )
        information_id = str(published.payload["information_id"])
        observations = {
            agent: [
                item for item in self.manager.observations(branch_id, agent)
                if information_id in item["provenance"]
            ]
            for agent in ("rule_alpha", "rule_beta", "replay_agent")
        }
        self.assertEqual(len(observations["rule_alpha"]), 1)
        self.assertEqual(len(observations["replay_agent"]), 1)
        self.assertFalse(observations["rule_beta"])
        target_observation_id = observations["rule_alpha"][0]["observation_id"]
        self.assertEqual(
            sum(
                decision["decision"]["observation_id"] == target_observation_id
                for decision in self.manager.agent_decisions(branch_id, "rule_alpha")
            ),
            1,
        )
        state = self.manager._world(branch_id).agent_runtime_states["rule_alpha"]
        self.assertTrue(any(
            belief.predicate == "market_signal" and belief.value == "bullish"
            for belief in state.beliefs
        ))

    def test_structured_information_signal_changes_rule_planner_direction(self) -> None:
        _, branch_id = self.create_running()
        world = self.manager._world(branch_id)
        definition = world.agent_definitions["rule_alpha"]
        state = world.agent_runtime_states["rule_alpha"]
        request = next(iter(world.planning_requests.values()))
        observation = ObservationPacket.model_validate(self.manager.observations(branch_id, "rule_alpha")[-1])
        observation = observation.model_copy(update={
            "information_items": [ObservedInformation(
                information_id="signal-bullish",
                source_id="news_agent",
                channel="PublicFeed",
                rendered_content="buying pressure is strengthening",
                sim_time_us=observation.sim_time_us,
                delivered_sim_time_us=observation.sim_time_us,
                viewed_sim_time_us=observation.sim_time_us,
                expires_sim_time_us=observation.sim_time_us + 1_000_000,
                visibility="public",
                signal_direction="bullish",
                signal_confidence_milli=1_000,
            )],
            "provenance": ["signal-bullish"],
        })

        candidate = asyncio.run(RulePlanner(seed=world.rng.root_seed).plan(
            definition=definition,
            observation=observation,
            state=state,
            request=request,
        ))

        trade = next(directive for directive in candidate.directives if directive.type == "trade")
        self.assertEqual(trade.side, "buy")
        self.assertIn("signal-bullish", candidate.rationale.evidence_ids)
        self.assertTrue(candidate.replan_conditions)

    def test_rejected_agent_action_keeps_the_full_audit_chain(self) -> None:
        _, branch_id = self.create_running()
        branch = self.manager._branch(branch_id)
        world = self.manager._world(branch_id)
        before_observations = len(self.manager.observations(branch_id, "rule_alpha"))

        result = self.manager._apply_fixture_agent_action(
            branch_id=branch_id,
            run_id=str(branch["run_id"]),
            working=world,
            state_version=int(branch["state_version"]),
            agent_id="rule_alpha",
            strategy=StrategyDecision(
                "SubmitLimitOrder",
                {"side": "buy", "quantity": 100_000_000, "price": 102},
            ),
            client_command_id="rejected-agent-action",
            command_key="rejected-agent-action-command",
        )

        self.assertFalse(result["accepted"])
        receipt = self.manager.agent_receipts(branch_id, "rule_alpha")[0]
        self.assertEqual(receipt["outcome"], "rejected")
        self.assertTrue(receipt["proposal_id"])
        self.assertTrue(receipt["decision_id"])
        self.assertGreater(len(self.manager.observations(branch_id, "rule_alpha")), before_observations)
        self.assertTrue(any(item["decision"]["decision_id"] == receipt["decision_id"] for item in self.manager.agent_decisions(branch_id, "rule_alpha")))
        self.assertEqual(len(self.manager.agent_plans(branch_id, "rule_alpha")), 1)

    def test_run_for_applies_live_planner_result_in_stable_pipeline(self) -> None:
        self.manager.initializer.llm_gateway = LLMGateway({"openai": FakePlanningAdapter()})
        scenario = self.manager.create_scenario(ScenarioDraft(
            mode="live_llm_smoke",
            llm_provider="openai",
            population={"preset": "smoke"},
        ))
        resolved = asyncio.run(self.manager.resolve_scenario(str(scenario["scenario_id"])))
        self.assertEqual(len(resolved.agent_definitions), 4)
        run = self.manager.create_run(str(scenario["scenario_id"]), resolved.resolution_hash)
        branch_id = str(run["branches"][0]["branch_id"])
        self.manager.command(branch_id, "live-start", "start")
        result = self.manager.command(branch_id, "live-run", "run_for", {"max_requests": 1})
        self.assertEqual(result["processed_requests"], 1)
        self.assertEqual(result["applied_requests"], 1)
        request = self.store.connection.execute(
            "SELECT state,terminal_outcome FROM planning_requests WHERE branch_id=? AND state='Terminal'",
            (branch_id,),
        ).fetchone()
        self.assertEqual((request["state"], request["terminal_outcome"]), ("Terminal", "applied"))
        self.assertEqual(
            self.store.connection.execute("SELECT COUNT(*) count FROM llm_records").fetchone()["count"],
            1,
        )
        fallback = next(
            event for event in self.manager.events.list_events(branch_id, limit=10_000)
            if event.event_type == "AgentNoOpFallbackSampled"
        )
        self.assertTrue(fallback.payload["selected"])
        self.assertTrue(fallback.payload["sampled"] or fallback.payload["forced_activity_floor"])
        active_plan = self.store.connection.execute(
            "SELECT plan_json FROM strategy_plans WHERE branch_id=? AND active=1",
            (branch_id,),
        ).fetchone()
        self.assertTrue(json.loads(active_plan["plan_json"])["directives"])
        activated = next(
            record["decision"]
            for record in self.manager.agent_decisions(branch_id, str(fallback.source_id))
            if record["decision"]["strategy_plan_proposal"] is not None
        )
        self.assertEqual(fallback.payload["probability_milli"], DEMO_NOOP_FALLBACK_PROBABILITY_MILLI)
        self.assertIn("no_op_fallback", activated["rationale"]["risk_flags"])
        self.assertIn("saved observation", activated["rationale"]["stated_reason"])
        self.manager.command(branch_id, "live-save", "save")
        archive_path = Path(self.temp.name) / "live-agent.sandbox"
        self.manager.export_archive(str(run["run_id"]), archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            llm_lines = archive.read("llm/records.jsonl").decode().splitlines()
            self.assertEqual(len(llm_lines), 1)

        restored_store = SQLiteStore(Path(self.temp.name) / "restored-live.db")
        try:
            restored_archive = ArchiveService(restored_store, "0.2.0")
            restored_archive.import_run(archive_path)
            self.assertEqual(
                restored_store.connection.execute("SELECT COUNT(*) count FROM llm_records").fetchone()["count"],
                1,
            )
        finally:
            restored_store.close()

    def test_live_planning_batch_runs_provider_calls_concurrently(self) -> None:
        adapter = SlowPlanningAdapter(0.2)
        self.manager.initializer.llm_gateway = LLMGateway({"openai": adapter}, max_in_flight=4)
        scenario = self.manager.create_scenario(ScenarioDraft(
            mode="live_llm_smoke",
            llm_provider="openai",
            population={"preset": "smoke"},
        ))
        resolved = asyncio.run(self.manager.resolve_scenario(str(scenario["scenario_id"])))
        run = self.manager.create_run(str(scenario["scenario_id"]), resolved.resolution_hash)
        branch_id = str(run["branches"][0]["branch_id"])
        self.manager.command(branch_id, "concurrent-start", "start")

        started = time.monotonic()
        result = self.manager.command(branch_id, "concurrent-run", "run_for", {"max_requests": 4})
        elapsed = time.monotonic() - started

        self.assertEqual(result["processed_requests"], 4)
        self.assertEqual(result["applied_requests"], 4)
        self.assertEqual(len(adapter.requests), 4)
        self.assertLess(elapsed, 0.65)
        self.assertTrue(all(request.based_on_strategy_revision == 0 for request in adapter.requests))
        self.assertTrue(all(request.capabilities for request in adapter.requests))
        self.assertTrue(all(request.role_tags for request in adapter.requests))
        fallback_events = [
            event for event in self.manager.events.list_events(branch_id, limit=10_000)
            if event.event_type == "AgentNoOpFallbackSampled"
        ]
        self.assertEqual(len(fallback_events), 4)
        self.assertTrue(any(event.payload["selected"] for event in fallback_events))

    def test_demo_rule_agents_trade_quote_and_publish_through_the_runtime(self) -> None:
        scenario = self.manager.create_scenario(ScenarioDraft(
            population={"preset": "smoke", "agent_count": 4},
            agent_configuration_drafts=[
                {
                    "draft_id": "active-trader",
                    "input_mode": "detailed",
                    "archetype_ids": ["ordinary_participant"],
                    "base_persona": {"risk_tolerance_milli": 1_000, "trend_bias_milli": 1_000},
                    "latency_profile": {"planning_latency_us": 0, "action_latency_us": 0},
                },
                {
                    "draft_id": "capital-trader",
                    "input_mode": "detailed",
                    "archetype_ids": ["capital_holder"],
                    "base_persona": {"risk_tolerance_milli": 1_000, "trend_bias_milli": 0},
                    "latency_profile": {"planning_latency_us": 0, "action_latency_us": 0},
                },
                {
                    "draft_id": "liquidity-provider",
                    "input_mode": "detailed",
                    "archetype_ids": ["liquidity_provider"],
                    "base_persona": {"risk_tolerance_milli": 1_000},
                    "latency_profile": {"planning_latency_us": 0, "action_latency_us": 0},
                },
                {
                    "draft_id": "information-participant",
                    "input_mode": "detailed",
                    "archetype_ids": ["information_participant"],
                    "base_persona": {"communication_propensity_milli": 1_000},
                    "latency_profile": {"planning_latency_us": 0, "action_latency_us": 0},
                },
            ],
        ))
        resolved = asyncio.run(self.manager.resolve_scenario(str(scenario["scenario_id"])))
        run = self.manager.create_run(str(scenario["scenario_id"]), resolved.resolution_hash)
        branch_id = str(run["branches"][0]["branch_id"])
        self.manager.command(branch_id, "demo-start", "start")
        self.manager._runner_cancel[branch_id].set()
        self.manager._planning_cancel[branch_id].set()

        result = self.manager.command(branch_id, "demo-plan", "run_for", {"max_requests": 4})

        self.assertEqual(result["applied_requests"], 4)
        plans = self.store.connection.execute(
            "SELECT plan_json FROM strategy_plans WHERE branch_id=? AND active=1",
            (branch_id,),
        ).fetchall()
        directive_types = {
            directive["type"]
            for row in plans
            for directive in json.loads(row["plan_json"])["directives"]
        }
        trade_styles = {
            directive["style"]
            for row in plans
            for directive in json.loads(row["plan_json"])["directives"]
            if directive["type"] == "trade"
        }
        self.assertEqual(len(plans), 4)
        self.assertTrue({"trade", "quote", "communication"}.issubset(directive_types))
        self.assertEqual(trade_styles, {"passive", "protected_market"})
        for row in plans:
            for directive in json.loads(row["plan_json"])["directives"]:
                self.assertEqual(directive["emission"]["mode"], "periodic")
                self.assertEqual(directive["emission"]["interval_us"], DEMO_ACTIVITY_EMISSION_INTERVAL_US)
                self.assertEqual(directive["emission"]["max_emissions"], DEMO_ACTIVITY_MAX_EMISSIONS)

        for _ in range(40):
            world = self.manager._world(branch_id)
            if not world.pending_actions and not world.pending_deliveries:
                break
            self.assertTrue(self.manager._advance_background_once(branch_id))
        else:
            self.fail("demo Agent actions and information deliveries did not settle")

        events = self.manager.events.list_events(branch_id, limit=10_000)
        agent_ids = {definition.agent_id for definition in resolved.agent_definitions}
        self.assertTrue(any(event.event_type == "TradeMatched" and event.source_id in agent_ids for event in events))
        self.assertTrue(any(event.event_type == "InformationPublished" and event.source_id in agent_ids for event in events))
        self.assertTrue(any(event.event_type == "InformationViewed" for event in events))
        self.assertFalse(any(
            event.event_type == "ActionAdmissionRejected" and event.source_id in agent_ids
            for event in events
        ))
        self.assertTrue(any(self.manager.agent_receipts(branch_id, agent_id) for agent_id in agent_ids))

    def test_exhausted_plan_cools_down_then_reopens_planning_gate(self) -> None:
        _, branch_id = self.create_running()
        self.manager.command(branch_id, "background-step", "step_fixture")
        self.manager.command(branch_id, "agent-step", "step_fixture")
        world = self.manager._world(branch_id)
        definition = world.agent_definitions["rule_alpha"]
        state = world.agent_runtime_states["rule_alpha"]
        plan = world.strategy_plans[state.active_plan_id]
        cursor_key, cursor = next(iter(state.directive_cursors.items()))
        self.assertGreaterEqual(cursor.emission_count, 1)
        cursor = cursor.model_copy(update={"emission_count": DEMO_ACTIVITY_MAX_EMISSIONS})
        state = state.model_copy(update={
            "directive_cursors": {**state.directive_cursors, cursor_key: cursor},
        })
        emitted_at = cursor.last_eligible_sim_time_us or plan.valid_from_sim_time_us
        previous = ObservationPacket.model_validate(self.manager.observations(branch_id, "rule_alpha")[0])

        cooling_observation = previous.model_copy(update={
            "observation_id": "obs-cooling",
            "sim_time_us": emitted_at + DEMO_ACTIVITY_REPLAN_COOLDOWN_US - 1,
            "decision_triggers": [],
        })
        cooling = self.manager.agent_runtime.decide(
            definition=definition,
            state=state,
            observation=cooling_observation,
            active_plan=plan,
        )
        self.assertIsNotNone(cooling)
        self.assertIsNone(cooling.decision.planning_request_proposal)
        self.assertIn("activity_cooldown", cooling.decision.rationale.risk_flags)

        elapsed_observation = previous.model_copy(update={
            "observation_id": "obs-cooldown-elapsed",
            "sim_time_us": emitted_at + DEMO_ACTIVITY_REPLAN_COOLDOWN_US,
            "decision_triggers": [],
        })
        elapsed = self.manager.agent_runtime.decide(
            definition=definition,
            state=cooling.state,
            observation=elapsed_observation,
            active_plan=plan,
        )
        self.assertIsNotNone(elapsed)
        self.assertIsNotNone(elapsed.decision.planning_request_proposal)
        self.assertEqual(
            elapsed.decision.planning_request_proposal.reason_keys,
            ["plan_directives_exhausted", "activity_cooldown_elapsed"],
        )

    def test_elapsed_budget_window_allows_replanning_in_the_same_decision(self) -> None:
        _, branch_id = self.create_running()
        world = self.manager._world(branch_id)
        definition = world.agent_definitions["rule_alpha"]
        state = world.agent_runtime_states["rule_alpha"]
        exhausted_budget = state.cognitive_budget_state.model_copy(update={"plans_remaining": 0})
        state = state.model_copy(update={
            "cognitive_budget_state": exhausted_budget,
            "planning_request_id": None,
        })
        previous = ObservationPacket.model_validate(self.manager.observations(branch_id, "rule_alpha")[0])
        observation = previous.model_copy(update={
            "observation_id": "obs-budget-window-elapsed",
            "sim_time_us": definition.cognitive_profile.planning_window_us,
            "decision_triggers": [],
        })

        result = self.manager.agent_runtime.decide(
            definition=definition,
            state=state,
            observation=observation,
        )

        self.assertIsNotNone(result)
        self.assertIsNotNone(result.decision.planning_request_proposal)
        self.assertEqual(result.state.cognitive_budget_state.plans_remaining, definition.cognitive_profile.max_plans_per_window - 1)
        self.assertTrue(any(change.operation == "reset" for change in result.outcome.budget_changes))

    def test_autonomous_clock_advances_while_llm_is_still_pending(self) -> None:
        adapter = SlowPlanningAdapter(2.0)
        self.manager.initializer.llm_gateway = LLMGateway({"openai": adapter}, max_in_flight=1)
        scenario = self.manager.create_scenario(ScenarioDraft(
            mode="live_llm_smoke",
            llm_provider="openai",
            population={"preset": "smoke", "agent_count": 1},
            agent_configuration_drafts=[{
                "draft_id": "immediate-planner",
                "input_mode": "detailed",
                "latency_profile": {"planning_latency_us": 0},
            }],
        ))
        resolved = asyncio.run(self.manager.resolve_scenario(str(scenario["scenario_id"])))
        run = self.manager.create_run(str(scenario["scenario_id"]), resolved.resolution_hash)
        branch_id = str(run["branches"][0]["branch_id"])
        self.manager.command(branch_id, "paced-start", "start")

        time.sleep(1.45)
        branch = self.manager._branch(branch_id)

        self.assertGreaterEqual(int(branch["sim_time_us"]), 1_000_000)
        self.assertLess(int(branch["sim_time_us"]), 2_000_000)
        self.assertEqual(
            self.store.connection.execute("SELECT COUNT(*) count FROM llm_records").fetchone()["count"],
            0,
        )
        self.manager.command(branch_id, "paced-pause", "pause")

    def test_projection_exposes_the_latest_planning_failure_message(self) -> None:
        self.manager.initializer.llm_gateway = LLMGateway({"openai": FailingPlanningAdapter()})
        scenario = self.manager.create_scenario(ScenarioDraft(
            mode="live_llm_smoke",
            llm_provider="openai",
            population={"preset": "smoke", "agent_count": 1},
        ))
        resolved = asyncio.run(self.manager.resolve_scenario(str(scenario["scenario_id"])))
        run = self.manager.create_run(str(scenario["scenario_id"]), resolved.resolution_hash)
        branch_id = str(run["branches"][0]["branch_id"])
        self.manager.command(branch_id, "failure-start", "start")

        result = self.manager.command(branch_id, "failure-run", "run_for", {"max_requests": 1})
        projection = self.manager.branch_projection(branch_id)

        self.assertEqual(result["failed_requests"], 1)
        self.assertEqual(projection["planning"]["last_failure_code"], "VALIDATION_FAILED")
        self.assertEqual(projection["planning"]["last_failure_message"], "provider returned truncated JSON")


if __name__ == "__main__":
    unittest.main()
