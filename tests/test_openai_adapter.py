from __future__ import annotations

import unittest
from types import SimpleNamespace

from sandbox.agents.providers.openai import OpenAIProviderAdapter
from sandbox.contracts.agent import DecisionRationale
from sandbox.contracts.intervention import DirectorPlanCandidate, DirectorProviderRequest
from sandbox.contracts.planning import PlanningProviderRequest, PlanningResultCandidate


class FakeResponse:
    def __init__(self, parsed: object, response_id: str = "resp_test") -> None:
        self.output_parsed = parsed
        self.id = response_id
        self.usage = {"input_tokens": 10, "output_tokens": 5}

    def model_dump(self, mode: str = "python") -> dict[str, object]:
        return {"id": self.id, "output": "structured"}


class FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def parse(self, **kwargs: object) -> FakeResponse:
        self.calls.append(kwargs)
        text_format = kwargs["text_format"]
        if getattr(text_format, "__name__", "") == "PlanningPreflightResult":
            return FakeResponse({"ok": True}, "resp_preflight")
        if getattr(text_format, "__name__", "") == "DirectorPlanCandidate":
            return FakeResponse(DirectorPlanCandidate(
                stages=[{
                    "stage_id": "stage-director",
                    "effective_sim_time_us": 0,
                    "effects": [{
                        "effect_id": "effect-director",
                        "effect_type": "set_market_status",
                        "market_id": "TOKEN-USDX",
                        "status": "halted",
                        "reason_code": "director_test",
                    }],
                }],
                rationale="Typed venue halt.",
            ))
        return FakeResponse(
            PlanningResultCandidate(
                based_on_strategy_revision=0,
                valid_for_us=1_000_000,
                goals=[],
                activation_preconditions=[],
                constraints=[],
                directives=[],
                replan_conditions=[],
                rationale=DecisionRationale(
                    goal_summary="Hold",
                    uncertainty_milli=500,
                    stated_reason="Insufficient evidence.",
                ),
            )
        )


class OpenAIAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_preflight_and_plan_use_structured_responses_without_storing(self) -> None:
        responses = FakeResponses()
        adapter = OpenAIProviderAdapter(
            api_key="secret-key-value",
            model="test-model",
            max_retries=0,
            client=SimpleNamespace(responses=responses),
        )
        report = await adapter.preflight()
        self.assertTrue(report["ok"])
        records = []
        candidate = await adapter.create_plan(
            PlanningProviderRequest(
                request_id="request-1",
                agent_id="agent-1",
                context_hash="sha256:context",
                planner_instructions="Create a bounded plan.",
                persona={"notes": "untrusted"},
                observation={"observation_id": "observation-1"},
                cognition={"memory_ids": []},
                account_snapshot={"balances": {}},
            ),
            record_raw=records.append,
        )
        self.assertEqual(candidate.schema_version, "planning-result-candidate.v0.1")
        self.assertEqual(len(records), 1)
        self.assertNotIn("secret-key-value", str(records[0].model_dump()))
        self.assertNotIn("untrusted", str(records[0].redacted_request))
        self.assertTrue(all(call["store"] is False for call in responses.calls))

    async def test_missing_key_is_reported_without_exposing_a_secret(self) -> None:
        adapter = OpenAIProviderAdapter(api_key=None, model="test-model")
        report = await adapter.preflight()
        self.assertFalse(report["ok"])
        self.assertEqual(report["message"], "OPENAI_API_KEY is not configured")
        self.assertEqual(adapter.profile.key_present, False)

    async def test_scenario_director_returns_only_a_typed_candidate_and_redacts_context(self) -> None:
        responses = FakeResponses()
        adapter = OpenAIProviderAdapter(
            api_key="secret-key-value",
            model="test-model",
            max_retries=0,
            client=SimpleNamespace(responses=responses),
        )
        records = []
        candidate = await adapter.create_intervention_plan(
            DirectorProviderRequest(
                request_id="director-request-1",
                branch_id="branch-1",
                context_hash="sha256:director-context",
                user_intent="Halt the market",
                current_sim_time_us=0,
                requested_effective_time_us=0,
                world_context={"market_status": "active"},
                private_context={},
                allowed_effect_types=["set_market_status"],
            ),
            record_raw=records.append,
        )
        self.assertEqual(candidate.stages[0].effects[0].effect_type, "set_market_status")
        self.assertEqual(records[0].agent_id, "scenario_director")
        self.assertNotIn("Halt the market", str(records[0].redacted_request))
        self.assertNotIn("secret-key-value", str(records[0].model_dump()))
        self.assertTrue(responses.calls[-1]["store"] is False)


if __name__ == "__main__":
    unittest.main()
