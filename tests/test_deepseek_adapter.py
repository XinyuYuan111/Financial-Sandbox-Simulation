from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sandbox.agents.providers.deepseek import DeepSeekProviderAdapter
from sandbox.app.settings import Settings
from sandbox.contracts.agent import DecisionRationale
from sandbox.contracts.planning import PlanningProviderRequest, PlanningResultCandidate


class FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


class FakeDeepSeekClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        body = kwargs["json"]
        assert isinstance(body, dict)
        system_message = body["messages"][0]["content"]
        assert "JSON Schema" in system_message
        content = PlanningResultCandidate(
            based_on_strategy_revision=0,
            valid_for_us=30_000_000,
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
        ).model_dump(mode="json")
        return FakeResponse({
            "id": "chatcmpl-deepseek-test",
            "choices": [{"message": {"role": "assistant", "content": json.dumps(content)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })


class RetryingDeepSeekClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if len(self.calls) == 1:
            return FakeResponse({
                "id": "chatcmpl-invalid",
                "choices": [{"finish_reason": "length", "message": {"content": '{"based_on_strategy_revision":'}}],
            })
        body = kwargs["json"]
        assert isinstance(body, dict)
        payload = json.loads(body["messages"][1]["content"])
        content = PlanningResultCandidate(
            based_on_strategy_revision=payload["based_on_strategy_revision"],
            valid_for_us=30_000_000,
            goals=[],
            activation_preconditions=[],
            constraints=[],
            directives=[],
            replan_conditions=[],
            rationale=DecisionRationale(
                goal_summary="Hold",
                uncertainty_milli=500,
                stated_reason="Corrected after validation feedback.",
            ),
        ).model_dump(mode="json")
        return FakeResponse({
            "id": "chatcmpl-corrected",
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(content)}}],
        })


class DeepSeekAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_official_endpoint_preflight_and_typed_plan(self) -> None:
        client = FakeDeepSeekClient()
        adapter = DeepSeekProviderAdapter(
            api_key="deepseek-secret",
            client=client,
            max_retries=0,
        )

        report = await adapter.preflight()
        records = []
        candidate = await adapter.create_plan(
            PlanningProviderRequest(
                request_id="request-deepseek",
                agent_id="agent-deepseek",
                context_hash="sha256:deepseek-context",
                planner_instructions="Create a bounded plan.",
                persona={"notes": "untrusted"},
                observation={"observation_id": "observation-deepseek"},
                cognition={"memory_ids": []},
                account_snapshot={"balances": {}},
            ),
            record_raw=records.append,
        )

        self.assertTrue(report["ok"])
        self.assertEqual(candidate.schema_version, "planning-result-candidate.v0.1")
        self.assertEqual(adapter.profile.endpoint_class, "chat_completions")
        self.assertEqual(records[0].provider, "deepseek")
        self.assertNotIn("deepseek-secret", str(records[0].model_dump()))
        self.assertNotIn("untrusted", str(records[0].redacted_request))
        self.assertTrue(all(call["url"] == "https://api.deepseek.com/chat/completions" for call in client.calls))
        self.assertTrue(all(call["json"]["response_format"] == {"type": "json_object"} for call in client.calls))
        self.assertTrue(all(call["headers"]["Authorization"] == "Bearer deepseek-secret" for call in client.calls))

    async def test_missing_key_is_reported(self) -> None:
        adapter = DeepSeekProviderAdapter(api_key=None)

        report = await adapter.preflight()

        self.assertFalse(report["ok"])
        self.assertEqual(report["message"], "DEEPSEEK_API_KEY is not configured")
        self.assertFalse(adapter.profile.key_present)

    async def test_invalid_json_retry_receives_feedback_and_preserves_revision(self) -> None:
        client = RetryingDeepSeekClient()
        adapter = DeepSeekProviderAdapter(api_key="deepseek-secret", client=client, max_retries=1)
        records = []

        candidate = await adapter.create_plan(
            PlanningProviderRequest(
                request_id="request-retry",
                agent_id="agent-retry",
                context_hash="sha256:retry",
                based_on_strategy_revision=3,
                planner_instructions="Create a bounded plan.",
                persona={},
                observation={},
                cognition={},
                account_snapshot={},
            ),
            record_raw=records.append,
        )

        self.assertEqual(candidate.based_on_strategy_revision, 3)
        self.assertEqual([record.status for record in records], ["failed", "succeeded"])
        self.assertEqual(adapter.profile.max_output_tokens, 4_096)
        self.assertEqual(client.calls[0]["json"]["max_tokens"], 4_096)
        self.assertIn("previous attempt was invalid", client.calls[1]["json"]["messages"][0]["content"].lower())
        self.assertEqual(records[0].raw_response["finish_reason"], "length")

    async def test_settings_read_deepseek_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "DEEPSEEK_API_KEY": "deepseek-key",
                "SANDBOX_DEEPSEEK_BASE_URL": " https://api.deepseek.com/v1/ ",
                "SANDBOX_DEEPSEEK_MODEL": "deepseek-chat",
                "SANDBOX_OPENAI_STORE": "false",
            },
        ):
            settings = Settings.from_environment()

        self.assertEqual(settings.deepseek_api_key, "deepseek-key")
        self.assertEqual(settings.deepseek_base_url, "https://api.deepseek.com/v1")
        self.assertEqual(settings.deepseek_model, "deepseek-chat")


if __name__ == "__main__":
    unittest.main()
