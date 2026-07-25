from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    import openai  # noqa: F401
    _OPENAI_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    _OPENAI_AVAILABLE = False

from sandbox.agents.providers.openai import OpenAIProviderAdapter
from sandbox.app.settings import Settings
from sandbox.contracts.agent import DecisionRationale
from sandbox.contracts.intervention import DirectorPlanCandidate, DirectorProviderRequest
from sandbox.contracts.planning import PlanningProviderRequest, PlanningResultCandidate


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content
        self.role = "assistant"


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)
        self.finish_reason = "stop"


class _FakeUsage:
    def __init__(self) -> None:
        self.prompt_tokens = 10
        self.completion_tokens = 5
        self.total_tokens = 15

    def model_dump(self) -> dict[str, int]:
        return {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


class FakeCompletion:
    def __init__(self, parsed: object, response_id: str = "resp_test") -> None:
        self._parsed = parsed
        self.id = response_id
        content = parsed.model_dump_json()
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage()

    def model_dump(self, mode: str = "python") -> dict[str, object]:
        return {"id": self.id, "choices": [{"message": {"content": self._parsed.model_dump_json()}}]}


class FakeChatCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> FakeCompletion:
        self.calls.append(kwargs)
        # Inspect system message to decide which type to return
        messages = kwargs.get("messages", [])
        system_content = ""
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "system":
                system_content = str(msg.get("content", ""))
                break
        if "Scenario Director" in system_content or "command-scoped" in system_content:
            return FakeCompletion(DirectorPlanCandidate(
                stages=[{
                    "stage_id": "stage-director",
                    "effective_sim_time_us": 0,
                    "background_order_flow_impact_milli": -700,
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
        return FakeCompletion(
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


class FakeChat:
    def __init__(self) -> None:
        self.completions = FakeChatCompletions()


class OpenAIAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_preflight_and_plan_use_chat_completions_with_json_object(self) -> None:
        chat = FakeChat()
        adapter = OpenAIProviderAdapter(
            api_key="secret-key-value",
            model="test-model",
            max_retries=0,
            client=SimpleNamespace(chat=chat),
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
                capabilities=["market.trade", "information.read"],
                role_tags=["capital_holder"],
                public_identity="Long-horizon capital holder",
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
        self.assertTrue(
            all(call.get("response_format", {}).get("type") == "json_object" for call in chat.completions.calls)
        )

    async def test_missing_key_is_reported_without_exposing_a_secret(self) -> None:
        adapter = OpenAIProviderAdapter(api_key=None, model="test-model")
        report = await adapter.preflight()
        self.assertFalse(report["ok"])
        self.assertEqual(report["message"], "OPENAI_API_KEY is not configured")
        self.assertEqual(adapter.profile.key_present, False)

    @unittest.skipUnless(_OPENAI_AVAILABLE, "openai package is not installed")
    async def test_custom_base_url_is_forwarded_to_the_sdk_client(self) -> None:
        with patch("openai.AsyncOpenAI") as client_constructor:
            adapter = OpenAIProviderAdapter(
                api_key="relay-key",
                base_url="https://v1.codx.qzz.io",
                model="relay-model",
            )
            adapter._client_or_create()

        client_constructor.assert_called_once_with(
            api_key="relay-key",
            base_url="https://v1.codx.qzz.io",
            timeout=30,
            max_retries=0,
        )

    async def test_settings_read_the_sandbox_openai_base_url_variable(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SANDBOX_OPENAI_BASE_URL": "  https://v1.codx.qzz.io  ",
                "SANDBOX_OPENAI_STORE": "false",
            },
        ):
            settings = Settings.from_environment()

        self.assertEqual(settings.openai_base_url, "https://v1.codx.qzz.io")

    async def test_scenario_director_returns_only_a_typed_candidate_and_redacts_context(self) -> None:
        chat = FakeChat()
        adapter = OpenAIProviderAdapter(
            api_key="secret-key-value",
            model="test-model",
            max_retries=0,
            client=SimpleNamespace(chat=chat),
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
        self.assertEqual(candidate.stages[0].background_order_flow_impact_milli, -700)
        self.assertEqual(records[0].agent_id, "scenario_director")
        self.assertNotIn("Halt the market", str(records[0].redacted_request))
        self.assertNotIn("secret-key-value", str(records[0].model_dump()))


if __name__ == "__main__":
    unittest.main()
