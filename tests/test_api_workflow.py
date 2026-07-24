from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import sandbox.app.main as app_main
from sandbox.agents.llm_gateway import LLMGateway
from sandbox.app.settings import Settings
from sandbox.contracts.agent_configuration import (
    AgentConfigurationInterpretationCandidate,
    ConfigurationSuggestion,
)


class FakeAgentConfigurationAdapter:
    name = "openai"

    async def interpret_agent_configuration(self, request, *, record_raw=None):
        return AgentConfigurationInterpretationCandidate(
            display_name="Quoted Desk",
            base_persona={"risk_tolerance_milli": 720},
            field_sources={
                "display_name": "user",
                "base_persona.risk_tolerance_milli": "llm_interpreted",
            },
            suggestions=[ConfigurationSuggestion(
                suggestion_id="suggestion-quote",
                kind="archetype",
                value="liquidity_provider",
                reason="The user described continuous two-sided quotes.",
                confidence_milli=900,
            )],
        )


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

        run_response = self.client.post(
            "/api/v1/runs",
            json={"scenario_id": scenario_id, "resolution_hash": resolved.json()["resolution_hash"]},
        )
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

    def test_public_api_does_not_allow_callers_to_impersonate_agents(self) -> None:
        response = self.client.post(
            "/api/v1/branches/untrusted/actions",
            json={
                "action_id": "forged-action",
                "agent_id": "rule_alpha",
                "branch_id": "untrusted",
                "submitted_sim_time_us": 0,
                "action_type": "SubmitLimitOrder",
                "payload": {"side": "buy", "quantity": 1, "price": 10_000},
                "expected_execution_time_us": 0,
                "validity_window_us": 1,
                "client_command_id": "forged-command",
            },
        )
        self.assertEqual(response.status_code, 405)

    def test_agent_interpretation_requires_suggestion_disposition_and_resolution_confirmation(self) -> None:
        self.client.app.state.manager.initializer.llm_gateway = LLMGateway({
            "openai": FakeAgentConfigurationAdapter(),  # type: ignore[dict-item]
        })
        interpretation = self.client.post(
            "/api/v1/agent-configurations/interpret",
            json={"user_intent": "Create Quoted Desk with risk tolerance 720 and continuous quotes."},
        )
        self.assertEqual(interpretation.status_code, 200)
        draft = interpretation.json()["draft"]
        self.assertEqual(draft["display_name"], "Quoted Desk")
        self.assertNotIn("strategy", draft["provenance"])

        pending = self.client.post("/api/v1/scenarios", json={"agent_configuration_drafts": [draft]})
        self.assertEqual(pending.status_code, 201)
        rejected = self.client.post(f"/api/v1/scenarios/{pending.json()['scenario_id']}/resolve")
        self.assertEqual(rejected.status_code, 422)

        draft["accepted_suggestion_ids"] = ["suggestion-quote"]
        accepted = self.client.post("/api/v1/scenarios", json={"agent_configuration_drafts": [draft]})
        resolved = self.client.post(f"/api/v1/scenarios/{accepted.json()['scenario_id']}/resolve")
        self.assertEqual(resolved.status_code, 200)
        self.assertIn("liquidity_provider", resolved.json()["agent_definitions"][0]["role_tags"])

        scenario_id = accepted.json()["scenario_id"]
        stale = self.client.post(
            "/api/v1/runs",
            json={"scenario_id": scenario_id, "resolution_hash": "sha256:stale"},
        )
        self.assertEqual(stale.status_code, 409)
        confirmed = self.client.post(
            "/api/v1/runs",
            json={"scenario_id": scenario_id, "resolution_hash": resolved.json()["resolution_hash"]},
        )
        self.assertEqual(confirmed.status_code, 201)


if __name__ == "__main__":
    unittest.main()
