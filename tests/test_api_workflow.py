from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import sandbox.app.main as app_main
from sandbox.app.settings import Settings


class ApiWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.previous_settings = app_main.settings
        app_main.settings = Settings(
            data_dir=root,
            database_path=root / "sandbox.db",
            frontend_dist=Path(__file__).resolve().parents[1] / "frontend" / "dist",
            archive_dir=root / "archives",
        )
        self.client_context = TestClient(app_main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        app_main.settings = self.previous_settings
        self.temp.cleanup()

    def test_fixture_run_historical_agent_audit_and_stop_via_public_routes(self) -> None:
        scenario_response = self.client.post("/api/v1/scenarios", json={})
        self.assertEqual(scenario_response.status_code, 201)
        scenario_id = scenario_response.json()["scenario_id"]
        resolved = self.client.post(f"/api/v1/scenarios/{scenario_id}/resolve")
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(len(resolved.json()["agent_definitions"]), 3)

        run_response = self.client.post("/api/v1/runs", json={"scenario_id": scenario_id})
        self.assertEqual(run_response.status_code, 201)
        run = run_response.json()
        branch_id = run["branches"][0]["branch_id"]
        historical_cursor = int(run["branches"][0]["state_version"])

        started = self.client.post(
            f"/api/v1/branches/{branch_id}/commands",
            json={"client_command_id": "api-start", "command_type": "start", "payload": {}},
        )
        self.assertEqual(started.status_code, 200)
        time.sleep(0.45)
        paused = self.client.post(
            f"/api/v1/branches/{branch_id}/commands",
            json={"client_command_id": "api-pause", "command_type": "pause", "payload": {}},
        )
        self.assertEqual(paused.status_code, 200)

        current = self.client.get(f"/api/v1/branches/{branch_id}/state").json()
        historical = self.client.get(
            f"/api/v1/branches/{branch_id}/state",
            params={"cursor": historical_cursor},
        ).json()
        self.assertGreater(current["cursor"], historical["cursor"])
        self.assertTrue(historical["historical"])

        agents = self.client.get(
            f"/api/v1/branches/{branch_id}/agents",
            params={"cursor": historical_cursor},
        )
        self.assertEqual(agents.status_code, 200)
        self.assertEqual(len(agents.json()["agents"]), 3)
        decisions = self.client.get(
            f"/api/v1/branches/{branch_id}/agents/rule_alpha/decisions",
            params={"cursor": historical_cursor},
        )
        self.assertEqual(decisions.status_code, 200)
        self.assertTrue(all(
            int(record["decision"]["sim_time_us"]) <= int(historical["sim_time_us"])
            for record in decisions.json()["decisions"]
        ))

        templates = self.client.get("/api/v1/intervention-templates")
        self.assertEqual(templates.status_code, 200)
        self.assertEqual(len(templates.json()["templates"]), 7)
        stopped = self.client.post(
            f"/api/v1/branches/{branch_id}/commands",
            json={"client_command_id": "api-stop", "command_type": "stop", "payload": {}},
        )
        self.assertEqual(stopped.status_code, 200)
        self.assertEqual(stopped.json()["reason"], "user_stopped")
        self.assertEqual(
            self.client.get(f"/api/v1/branches/{branch_id}/state").json()["status"],
            "Completed",
        )


if __name__ == "__main__":
    unittest.main()
