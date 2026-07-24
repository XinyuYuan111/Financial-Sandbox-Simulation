from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path

from sandbox.agents.llm_gateway import LLMGateway
from sandbox.contracts.action import ActionContract
from sandbox.contracts.agent import AgentRuntimeState, MemoryEntryState
from sandbox.contracts.intervention import InterventionPlanDraftInput
from sandbox.contracts.scenario import ScenarioDraft
from sandbox.control.initialization import (
    FinalizedSnapshotFileProvider,
    Initializer,
    definition_from_config,
    fixture_agents,
)
from sandbox.control.run_manager import RunManager
from sandbox.core.errors import ConflictError
from sandbox.core.ids import new_id
from sandbox.store.archive import ArchiveService
from sandbox.store.sqlite import SQLiteStore


class ProductAcceptanceTests(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.manager.close()
        self.store.close()
        self.temp.cleanup()

    def create_fixture(self) -> tuple[str, str]:
        scenario = self.manager.create_scenario(ScenarioDraft())
        asyncio.run(self.manager.resolve_scenario(str(scenario["scenario_id"])))
        run = self.manager.create_run(str(scenario["scenario_id"]))
        return str(run["run_id"]), str(run["branches"][0]["branch_id"])

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

    def test_running_advances_and_pause_freezes_a_complete_boundary(self) -> None:
        _, branch_id = self.create_fixture()
        initial = self.manager.branch_projection(branch_id)
        initial_decisions = self.store.connection.execute(
            "SELECT COUNT(*) count FROM agent_decisions WHERE branch_id=?",
            (branch_id,),
        ).fetchone()["count"]

        self.manager.command(branch_id, "autonomous-start", "start")
        time.sleep(0.7)
        advanced = self.manager.branch_projection(branch_id)
        decisions = self.store.connection.execute(
            "SELECT COUNT(*) count FROM agent_decisions WHERE branch_id=?",
            (branch_id,),
        ).fetchone()["count"]
        self.assertGreater(advanced["sim_time_us"], initial["sim_time_us"])
        self.assertGreater(advanced["cursor"], initial["cursor"])
        self.assertGreater(decisions, initial_decisions)
        self.assertTrue(advanced["market"]["bids"] or advanced["market"]["asks"])

        paused = self.manager.command(branch_id, "autonomous-pause", "pause")
        paused_cursor = int(paused["cursor"])
        time.sleep(0.15)
        self.assertEqual(self.manager.branch_projection(branch_id)["cursor"], paused_cursor)
        self.assertTrue(self.manager.events.verify_chain(branch_id))

    def test_private_delivery_wakes_only_visible_agents_and_builds_belief(self) -> None:
        _, branch_id = self.create_fixture()
        self.manager.command(branch_id, "private-start", "start")
        action = ActionContract(
            action_id=new_id("act"),
            agent_id="replay_agent",
            branch_id=branch_id,
            submitted_sim_time_us=0,
            action_type="PublishInformation",
            payload={"channel": "PrivateChannel", "content": "Selective disclosure", "target_ids": ["rule_alpha"]},
            expected_execution_time_us=1,
            validity_window_us=1_000_000,
            client_command_id="private-disclosure",
        )
        result = self.manager.submit_action(action)
        self.assertTrue(result["accepted"])
        self.assertIn(action.action_id, self.manager._world(branch_id).pending_actions)
        self.wait_for_information_view(branch_id, action.action_id, "rule_alpha")
        target = self.manager.agent_detail(branch_id, "rule_alpha")
        self.assertTrue(target["runtime_state"]["memory_entries"])
        self.assertTrue(target["runtime_state"]["beliefs"])

        related = [
            event for event in self.manager.events.list_events(branch_id, limit=10_000)
            if event.action_id == action.action_id
        ]
        published = next(event for event in related if event.event_type == "InformationPublished")
        delivered = next(
            event for event in related
            if event.event_type == "PrivateMessageDelivered" and event.payload["target_id"] == "rule_alpha"
        )
        viewed = next(
            event for event in related
            if event.event_type == "InformationViewed" and event.payload["agent_id"] == "rule_alpha"
        )
        information_id = str(published.payload["information_id"])
        target_observation = next(
            observation
            for observation in self.manager.observations(branch_id, "rule_alpha")
            if information_id in observation["provenance"]
        )
        self.assertEqual(
            sum(
                decision["decision"]["observation_id"] == target_observation["observation_id"]
                for decision in self.manager.agent_decisions(branch_id, "rule_alpha")
            ),
            1,
        )
        viewed_agents = {
            str(event.payload["agent_id"])
            for event in related
            if event.event_type == "InformationViewed" and event.payload["information_id"] == information_id
        }
        self.assertEqual(viewed_agents, {"rule_alpha", "replay_agent"})
        self.assertFalse(any(
            information_id in observation["provenance"]
            for observation in self.manager.observations(branch_id, "rule_beta")
        ))
        self.assertLess(published.branch_seq, delivered.branch_seq)
        self.assertLess(delivered.branch_seq, viewed.branch_seq)

    def test_stop_is_idempotent_and_completed_save_does_not_append_history(self) -> None:
        _, branch_id = self.create_fixture()
        self.manager.command(branch_id, "stop-start", "start")
        action = ActionContract(
            action_id="stop-pending-information",
            agent_id="replay_agent",
            branch_id=branch_id,
            submitted_sim_time_us=0,
            action_type="PublishInformation",
            payload={"channel": "PrivateChannel", "content": "cancel before delivery", "target_ids": ["rule_alpha"]},
            expected_execution_time_us=1,
            validity_window_us=1_000_000,
            client_command_id="stop-pending-information-command",
        )
        self.assertTrue(self.manager.submit_action(action)["accepted"])
        self.manager._runner_cancel[branch_id].set()
        self.assertTrue(self.manager._advance_background_once(branch_id))
        self.assertGreater(self.manager.branch_projection(branch_id)["pending_delivery_count"], 0)
        stopped = self.manager.command(branch_id, "stop-once", "stop")
        self.assertEqual((stopped["status"], stopped["reason"]), ("Completed", "user_stopped"))
        self.assertEqual(self.manager.branch_projection(branch_id)["pending_delivery_count"], 0)
        self.assertTrue(any(
            event.event_type == "InformationDeliveryCanceled"
            for event in self.manager.events.list_events(branch_id, limit=10_000)
        ))
        event_count = len(self.manager.events.list_events(branch_id, limit=10_000))
        repeated = self.manager.command(branch_id, "stop-twice", "stop")
        self.assertEqual(repeated["reason"], "user_stopped")
        self.assertEqual(len(self.manager.events.list_events(branch_id, limit=10_000)), event_count)
        self.manager.command(branch_id, "save-completed", "save")
        self.assertEqual(len(self.manager.events.list_events(branch_id, limit=10_000)), event_count)
        with self.assertRaises(ConflictError):
            self.manager.command(branch_id, "restart-completed", "start")

    def test_future_halt_rejects_pending_action_and_releases_reservation(self) -> None:
        _, branch_id = self.create_fixture()
        self.manager.command(branch_id, "pending-start", "start")
        action = ActionContract(
            action_id="future-order",
            agent_id="rule_alpha",
            branch_id=branch_id,
            submitted_sim_time_us=0,
            action_type="SubmitLimitOrder",
            payload={"side": "buy", "quantity": 10, "price": 100},
            expected_execution_time_us=10_000_000,
            validity_window_us=20_000_000,
            client_command_id="future-order-command",
        )
        queued = self.manager.submit_action(action)
        self.assertTrue(queued["queued"])
        world = self.manager._world(branch_id)
        self.assertIn(action.action_id, world.pending_actions)
        self.assertTrue(world.action_reservations)

        self.manager.command(branch_id, "pending-pause", "pause")
        plan = self.manager.create_intervention_plan(
            branch_id,
            "future-halt-draft",
            InterventionPlanDraftInput.model_validate({
                "user_intent": "Halt before the admitted order executes",
                "access_scope": {"private_grants": []},
                "private_read_refs": [],
                "stages": [{
                    "stage_id": "future-halt-stage",
                    "effective_sim_time_us": 5_000_000,
                    "effects": [{
                        "effect_id": "future-halt-effect",
                        "effect_type": "set_market_status",
                        "market_id": "TOKEN-USDX",
                        "status": "halted",
                        "reason_code": "acceptance_halt",
                    }],
                    "status": "pending",
                }],
            }),
        )
        self.manager.confirm_intervention_plan(branch_id, str(plan["plan_id"]), "future-halt-confirm")
        self.manager.command(branch_id, "pending-resume", "start")
        time.sleep(1.2)

        world = self.manager._world(branch_id)
        self.assertNotIn(action.action_id, world.pending_actions)
        self.assertFalse(world.action_reservations)
        receipt = next(item for item in self.manager.agent_receipts(branch_id, "rule_alpha") if item["action_id"] == action.action_id)
        self.assertEqual(receipt["outcome"], "rejected")
        event_types = [
            event.event_type for event in self.manager.events.list_events(branch_id, limit=10_000)
            if event.action_id == action.action_id
        ]
        self.assertIn("ActionReservationReleased", event_types)
        self.assertIn("PendingActionResolved", event_types)

    def test_save_retains_branch_state_and_same_branch_can_resume(self) -> None:
        _, branch_id = self.create_fixture()
        self.manager.command(branch_id, "save-start", "start")
        self.manager.command(branch_id, "save-pause", "pause")
        saved = self.manager.command(branch_id, "save-paused", "save")
        self.assertEqual(saved["status"], "Paused")
        resumed = self.manager.command(branch_id, "save-resume", "start")
        self.assertEqual(resumed["status"], "Running")
        stopped = self.manager.command(branch_id, "save-stop", "stop")
        self.assertEqual(stopped["reason"], "user_stopped")

    def test_advanced_agent_definition_and_private_initial_knowledge_survive_resolution(self) -> None:
        agents = fixture_agents()[:2]
        definitions = [definition_from_config(agent, seed=7) for agent in agents]
        definitions[1] = definitions[1].model_copy(update={
            "base_persona": definitions[1].base_persona.model_copy(update={
                "risk_tolerance_milli": 950,
                "skepticism_milli": 50,
                "time_horizon": "long",
            })
        })
        private_memory = MemoryEntryState(
            memory_id="initial-private-memory",
            summary="Privately supplied research note",
            source_ids=["initial:private"],
            confidence_milli=800,
            salience=75,
            created_sim_time_us=0,
        )
        scenario = self.manager.create_scenario(ScenarioDraft(
            agents=agents,
            agent_definitions=definitions,
            initial_agent_states=[AgentRuntimeState(agent_id=agents[1].agent_id, memory_entries=[private_memory])],
        ))
        resolved = asyncio.run(self.manager.resolve_scenario(str(scenario["scenario_id"])))
        self.assertEqual(resolved.agent_definitions[1].base_persona.risk_tolerance_milli, 950)
        self.assertEqual(resolved.initial_agent_states[0].memory_entries[0].source_ids, ["initial:private"])

    def test_finalized_snapshot_provider_rejects_mismatch_without_fixture_fallback(self) -> None:
        path = self.root / "ethereum-token.snapshot.json"
        path.write_text(json.dumps({
            "schema_version": "holder-snapshot.v0.2",
            "chain_id": "ethereum",
            "target_token": "TOKEN",
            "block_height": 123,
            "block_hash": "0xabc",
            "finalized": True,
            "coverage_ratio_milli": 900,
            "total_supply": 1_000_000,
        }), encoding="utf-8")
        provider = FinalizedSnapshotFileProvider(path=path, chain_id="ethereum")
        report = asyncio.run(provider.preflight("ethereum", "TOKEN"))
        self.assertTrue(report["ok"])
        mismatch = asyncio.run(provider.preflight("ethereum", "OTHER"))
        self.assertFalse(mismatch["ok"])
        snapshot = asyncio.run(provider.load_finalized_snapshot("ethereum", "TOKEN"))
        self.assertTrue(snapshot["finalized"])
        self.assertTrue(str(snapshot["content_hash"]).startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
