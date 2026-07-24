from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from sandbox.agents.llm_gateway import LLMGateway
from sandbox.agents.strategies import StrategyDecision
from sandbox.contracts.agent import DecisionRationale
from sandbox.contracts.action import ActionContract
from sandbox.contracts.scenario import ScenarioDraft
from sandbox.contracts.planning import LLMRecord, PlanningResultCandidate, ProviderProfile
from sandbox.control.initialization import Initializer
from sandbox.control.run_manager import RunManager
from sandbox.core.ids import new_id
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
            based_on_strategy_revision=0,
            valid_for_us=10_000_000,
            goals=[],
            activation_preconditions=[],
            constraints=[],
            directives=[],
            replan_conditions=[],
            rationale=DecisionRationale(goal_summary="Hold", uncertainty_milli=800, stated_reason="Smoke hold plan"),
        )


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
            payload={"channel": "PrivateChannel", "content": "private", "target_ids": ["rule_alpha"]},
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
                {"side": "buy", "quantity": 10_000_000, "price": 102},
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


if __name__ == "__main__":
    unittest.main()
