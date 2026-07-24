from __future__ import annotations

import asyncio
import zipfile
import tempfile
import threading
import unittest
from pathlib import Path

from sandbox.agents.llm_gateway import LLMGateway
from sandbox.contracts.action import ActionContract
from sandbox.contracts.scenario import ScenarioDraft
from sandbox.control.initialization import Initializer
from sandbox.control.run_manager import RunManager
from sandbox.core.errors import ValidationError
from sandbox.core.ids import new_id
from sandbox.store.archive import ArchiveService
from sandbox.store.sqlite import SQLiteStore


class FrameworkAlphaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = SQLiteStore(self.root / "sandbox.db")
        initializer = Initializer({}, LLMGateway({}))
        archive = ArchiveService(self.store, "0.2.0")
        self.manager = RunManager(self.store, initializer, archive, "0.2.0")

    def tearDown(self) -> None:
        self.manager.close()
        self.store.close()
        self.temp.cleanup()

    def create_running_fixture(self) -> tuple[str, str]:
        scenario = self.manager.create_scenario(ScenarioDraft())
        resolved = asyncio.run(self.manager.resolve_scenario(str(scenario["scenario_id"])))
        run = self.manager.create_run(str(scenario["scenario_id"]), resolved.resolution_hash)
        run_id = str(run["run_id"])
        branch_id = str(run["branches"][0]["branch_id"])
        self.manager.command(branch_id, "start-1", "start")
        self.assertEqual(self.manager.command(branch_id, "start-1", "start")["cursor"], self.manager.branch_projection(branch_id)["cursor"])
        return run_id, branch_id

    def test_fixture_closes_market_observation_and_information_loop(self) -> None:
        _, branch_id = self.create_running_fixture()
        for index in range(6):
            result = self.manager.command(branch_id, f"step-{index}", "step_fixture")
            self.assertTrue(result["accepted"])
        projection = self.manager.branch_projection(branch_id)
        self.assertEqual(len(projection["market"]["trades"]), 3)
        self.assertTrue(any(trade["buyer_id"] == "replay_agent" for trade in projection["market"]["trades"]))
        self.assertEqual(len(projection["information"]), 1)
        self.assertTrue(self.manager.events.verify_chain(branch_id))
        event_types = [event.event_type for event in self.manager.events.list_events(branch_id)]
        self.assertIn("InformationPublished", event_types)
        self.assertIn("InformationDelivered", event_types)
        self.assertIn("InformationViewed", event_types)
        ordered_events = self.manager.events.list_events(branch_id)
        for trade in projection["market"]["trades"]:
            related = [event.event_type for event in ordered_events if event.payload.get("trade_id") == trade["trade_id"]]
            self.assertEqual(related, ["TradeMatched", "TradeSettled", "FeeCharged"])
        observations = self.manager.observations(branch_id, "rule_alpha")
        self.assertGreaterEqual(len(observations), 6)

    def test_invalid_financial_payload_is_rejected_and_persisted(self) -> None:
        _, branch_id = self.create_running_fixture()
        action = ActionContract(
            action_id=new_id("act"), agent_id="rule_alpha", branch_id=branch_id,
            submitted_sim_time_us=0, action_type="SubmitLimitOrder",
            payload={"side": "buy", "quantity": 1.5, "price": 100},
            expected_execution_time_us=1, validity_window_us=10,
            client_command_id="float-rejected",
        )
        result = self.manager.submit_action(action)
        self.assertFalse(result["accepted"])
        self.assertEqual(self.manager.submit_action(action), result)
        self.assertEqual(self.manager.events.list_events(branch_id)[-1].event_type, "ActionRejected")

    def test_checkpoint_fork_isolation_and_archive_restore(self) -> None:
        run_id, branch_id = self.create_running_fixture()
        for index in range(2):
            self.manager.command(branch_id, f"step-{index}", "step_fixture")
        saved = self.manager.command(branch_id, "save-1", "save")
        child = self.manager.fork(branch_id, str(saved["checkpoint_id"]), "fork-1")
        child_id = str(child["branch_id"])
        parent_before = self.manager.branch_projection(branch_id)
        child_before = self.manager.branch_projection(child_id)
        self.assertEqual(parent_before["market"], child_before["market"])
        self.assertTrue(self.manager.observations(child_id, "rule_alpha"))
        self.manager.command(child_id, "child-start", "start")
        self.manager.command(child_id, "child-step", "step_fixture")
        self.assertNotEqual(self.manager.branch_projection(child_id)["cursor"], child_before["cursor"])
        self.assertEqual(self.manager.branch_projection(branch_id)["cursor"], parent_before["cursor"])

        archive_path = self.root / "experiment.sandbox"
        exported = self.manager.export_archive(run_id, archive_path)
        self.assertTrue(archive_path.exists())
        self.assertEqual(exported["manifest"]["included_branches"], [branch_id, child_id])
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            self.assertIn("agents/definitions.json", names)
            self.assertIn(f"agents/decisions/{branch_id}.jsonl", names)
            self.assertIn(f"agents/plans/{branch_id}.jsonl", names)
            self.assertIn(f"agents/planning_requests/{branch_id}.jsonl", names)
            self.assertIn(f"actions/receipts/{branch_id}.jsonl", names)
            self.assertIn("llm/records.jsonl", names)

        restored_store = SQLiteStore(self.root / "restored.db")
        try:
            restored_archive = ArchiveService(restored_store, "0.2.0")
            restored = restored_archive.import_run(archive_path)
            self.assertFalse(restored["already_present"])
            restored_events = __import__("sandbox.store.event_store", fromlist=["EventStore"]).EventStore(restored_store)
            self.assertTrue(restored_events.verify_chain(branch_id))
            self.assertTrue(restored_events.verify_chain(child_id))
            self.assertGreater(
                restored_store.connection.execute(
                    "SELECT COUNT(*) count FROM agent_decisions WHERE branch_id=?", (branch_id,)
                ).fetchone()["count"],
                0,
            )
            self.assertGreater(
                restored_store.connection.execute(
                    "SELECT COUNT(*) count FROM action_receipts WHERE branch_id=?", (branch_id,)
                ).fetchone()["count"],
                0,
            )
        finally:
            restored_store.close()

    def test_two_branches_can_prepare_concurrently_and_commit_serially(self) -> None:
        _, branch_id = self.create_running_fixture()
        saved = self.manager.command(branch_id, "save-concurrent", "save")
        child_a = str(self.manager.fork(branch_id, str(saved["checkpoint_id"]), "fork-a")["branch_id"])
        child_b = str(self.manager.fork(branch_id, str(saved["checkpoint_id"]), "fork-b")["branch_id"])
        self.manager.command(child_a, "start-a", "start")
        self.manager.command(child_b, "start-b", "start")
        errors: list[Exception] = []

        def step(child_id: str, command_id: str) -> None:
            try:
                self.manager.command(child_id, command_id, "step_fixture")
            except Exception as error:  # pragma: no cover - assertion captures thread failures
                errors.append(error)

        threads = [threading.Thread(target=step, args=(child_a, "step-a")), threading.Thread(target=step, args=(child_b, "step-b"))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.manager.branch_projection(child_a)["fixture_step"], 1)
        self.assertEqual(self.manager.branch_projection(child_b)["fixture_step"], 1)

    def test_archive_rejects_unhashed_extra_checkpoint(self) -> None:
        run_id, _ = self.create_running_fixture()
        archive_path = self.root / "tampered.sandbox"
        self.manager.export_archive(run_id, archive_path)
        with zipfile.ZipFile(archive_path, "a", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("checkpoints/unhashed.json", "{}")
        with self.assertRaises(ValidationError):
            self.manager.archive_service.validate_archive(archive_path)


if __name__ == "__main__":
    unittest.main()
