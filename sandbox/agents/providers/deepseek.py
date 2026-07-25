from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Callable, TypeVar

from pydantic import BaseModel

from sandbox.agents.providers.openai import (
    AGENT_CONFIGURATION_INSTRUCTIONS,
    DIRECTOR_INSTRUCTIONS,
    PLANNER_INSTRUCTIONS,
)
from sandbox.contracts.agent_configuration import (
    AgentConfigurationInterpretationCandidate,
    AgentConfigurationProviderRequest,
)
from sandbox.contracts.intervention import DirectorPlanCandidate, DirectorProviderRequest
from sandbox.contracts.planning import (
    LLMRecord,
    PlanningProviderRequest,
    PlanningResultCandidate,
    ProviderProfile,
    ProviderReport,
)
from sandbox.core.errors import ValidationError
from sandbox.core.ids import new_id


TModel = TypeVar("TModel", bound=BaseModel)


class DeepSeekProviderAdapter:
    """Direct adapter for DeepSeek's official Chat Completions API."""

    name = "deepseek"

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        timeout_seconds: int = 60,
        max_retries: int = 1,
        max_in_flight: int = 4,
        max_output_tokens: int = 4_096,
        client: object | None = None,
    ) -> None:
        self._api_key = api_key
        self._endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self._client = client
        self.profile = ProviderProfile(
            provider="deepseek",
            model=model,
            endpoint_class="chat_completions",
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            max_in_flight=max_in_flight,
            max_output_tokens=max_output_tokens,
            key_present=bool(api_key),
        )

    def _safe_error(self, error: Exception) -> str:
        message = str(error)
        if self._api_key:
            message = message.replace(self._api_key, "[REDACTED]")
        return message[:1_000]

    async def _post(self, body: dict[str, object]) -> dict[str, object]:
        if not self._api_key:
            raise ValidationError("DEEPSEEK_API_KEY is not configured")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._client is not None:
            response = await self._client.post(self._endpoint, headers=headers, json=body)
        else:
            try:
                import httpx
            except ImportError as error:  # pragma: no cover - dependency installation path
                raise ValidationError("DeepSeek support requires the 'httpx' dependency") from error
            async with httpx.AsyncClient(timeout=self.profile.timeout_seconds) as client:
                response = await client.post(self._endpoint, headers=headers, json=body)
        status_code = int(getattr(response, "status_code", 0))
        if status_code < 200 or status_code >= 300:
            response_text = str(getattr(response, "text", ""))[:1_000]
            raise RuntimeError(f"DeepSeek HTTP {status_code}: {response_text}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("DeepSeek response root must be a JSON object")
        return payload

    def _request_body(
        self,
        *,
        instructions: str,
        payload: dict[str, object],
        output_type: type[BaseModel],
        max_tokens: int | None = None,
        validation_feedback: str | None = None,
    ) -> dict[str, object]:
        schema = json.dumps(
            output_type.model_json_schema(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        system_content = (
            f"{instructions}\nReturn only one valid JSON object without Markdown. "
            "Keep optional arrays empty unless they are necessary and keep rationale fields concise. "
            f"It must match this JSON Schema exactly: {schema}"
        )
        if validation_feedback:
            system_content += (
                "\nThe previous attempt was invalid. Correct the stated problem and return a complete "
                f"replacement JSON object. Validation feedback: {validation_feedback}"
            )
        return {
            "model": self.profile.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_content,
                },
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                },
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": max_tokens or self.profile.max_output_tokens,
            "temperature": 0,
            "stream": False,
        }

    @staticmethod
    def _parsed_content(response: dict[str, object], output_type: type[TModel]) -> TModel:
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError("DeepSeek response does not contain a completion choice")
        message = choices[0].get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ValueError("DeepSeek response does not contain JSON message content")
        content = str(message["content"]).strip()
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(lines[1:-1]).strip()
        decoded = json.loads(content)
        return output_type.model_validate(decoded)

    @staticmethod
    def _usage(response: dict[str, object]) -> dict[str, int]:
        usage = response.get("usage")
        if not isinstance(usage, dict):
            return {}
        return {
            str(key): int(value)
            for key, value in usage.items()
            if isinstance(value, int) and not isinstance(value, bool)
        }

    async def preflight(self) -> dict[str, object]:
        checked_at = datetime.now(timezone.utc).isoformat()
        if not self._api_key:
            return ProviderReport(
                ok=False,
                provider="deepseek",
                model=self.profile.model,
                latency_ms=0,
                structured_output_ok=False,
                checked_at=checked_at,
                message="DEEPSEEK_API_KEY is not configured",
            ).model_dump(mode="json")
        started = time.perf_counter()
        try:
            response = await self._post(self._request_body(
                instructions=PLANNER_INSTRUCTIONS,
                payload={
                    "task": (
                        "Provider readiness check. Return a conservative planning candidate with "
                        "based_on_strategy_revision=0, valid_for_us=30000000, no directives, "
                        "and a short rationale."
                    )
                },
                output_type=PlanningResultCandidate,
            ))
            self._parsed_content(response, PlanningResultCandidate)
            return ProviderReport(
                ok=True,
                provider="deepseek",
                model=self.profile.model,
                latency_ms=int((time.perf_counter() - started) * 1_000),
                structured_output_ok=True,
                request_id=str(response.get("id")) if response.get("id") else None,
                checked_at=checked_at,
            ).model_dump(mode="json")
        except Exception as error:
            return ProviderReport(
                ok=False,
                provider="deepseek",
                model=self.profile.model,
                latency_ms=int((time.perf_counter() - started) * 1_000),
                structured_output_ok=False,
                checked_at=checked_at,
                message=self._safe_error(error),
            ).model_dump(mode="json")

    async def _create_typed(
        self,
        *,
        request_id: str,
        agent_id: str,
        context_hash: str,
        instructions: str,
        payload: dict[str, object],
        output_type: type[TModel],
        operation: str,
        redacted_request: dict[str, object],
        record_raw: Callable[[LLMRecord], None] | None,
    ) -> TModel:
        last_error: Exception | None = None
        for attempt in range(1, self.profile.max_retries + 2):
            started = time.perf_counter()
            response: dict[str, object] | None = None
            try:
                response = await self._post(self._request_body(
                    instructions=instructions,
                    payload=payload,
                    output_type=output_type,
                    validation_feedback=self._safe_error(last_error) if last_error is not None else None,
                ))
                candidate = self._parsed_content(response, output_type)
                record = LLMRecord(
                    call_id=new_id("llm"),
                    request_id=request_id,
                    agent_id=agent_id,
                    attempt=attempt,
                    provider="deepseek",
                    model=self.profile.model,
                    context_hash=context_hash,
                    redacted_request=redacted_request,
                    raw_response=response,
                    usage=self._usage(response),
                    latency_ms=int((time.perf_counter() - started) * 1_000),
                    status="succeeded",
                )
                if record_raw is not None:
                    record_raw(record)
                return candidate
            except Exception as error:
                last_error = error
                if record_raw is not None:
                    diagnostic: dict[str, object] = {"error": self._safe_error(error)}
                    if response is not None:
                        choices = response.get("choices")
                        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                            choice = choices[0]
                            diagnostic["finish_reason"] = choice.get("finish_reason")
                            message = choice.get("message")
                            if isinstance(message, dict) and isinstance(message.get("content"), str):
                                content = str(message["content"])
                                diagnostic["content_length"] = len(content)
                                diagnostic["content_excerpt"] = content[:1_000]
                    record_raw(LLMRecord(
                        call_id=new_id("llm"),
                        request_id=request_id,
                        agent_id=agent_id,
                        attempt=attempt,
                        provider="deepseek",
                        model=self.profile.model,
                        context_hash=context_hash,
                        redacted_request=redacted_request,
                        latency_ms=int((time.perf_counter() - started) * 1_000),
                        status="failed",
                        error_code="provider_or_schema_error",
                        raw_response=diagnostic,
                    ))
        raise ValidationError(
            f"DeepSeek {operation} failed: {self._safe_error(last_error or RuntimeError('unknown error'))}"
        )

    async def create_plan(
        self,
        request: PlanningProviderRequest,
        *,
        record_raw: Callable[[LLMRecord], None] | None = None,
    ) -> PlanningResultCandidate:
        payload = {
            "based_on_strategy_revision": request.based_on_strategy_revision,
            "capabilities": request.capabilities,
            "role_tags": request.role_tags,
            "public_identity": request.public_identity,
            "persona": request.persona,
            "observation": request.observation,
            "cognition": request.cognition,
            "account_snapshot": request.account_snapshot,
            "current_strategy": request.current_strategy,
            "task": request.planner_instructions,
        }
        return await self._create_typed(
            request_id=request.request_id,
            agent_id=request.agent_id,
            context_hash=request.context_hash,
            instructions=PLANNER_INSTRUCTIONS,
            payload=payload,
            output_type=PlanningResultCandidate,
            operation="planning",
            redacted_request={
                "request_id": request.request_id,
                "agent_id": request.agent_id,
                "context_hash": request.context_hash,
            },
            record_raw=record_raw,
        )

    async def create_intervention_plan(
        self,
        request: DirectorProviderRequest,
        *,
        record_raw: Callable[[LLMRecord], None] | None = None,
    ) -> DirectorPlanCandidate:
        return await self._create_typed(
            request_id=request.request_id,
            agent_id="scenario_director",
            context_hash=request.context_hash,
            instructions=DIRECTOR_INSTRUCTIONS,
            payload={
                "user_intent": request.user_intent,
                "current_sim_time_us": request.current_sim_time_us,
                "requested_effective_time_us": request.requested_effective_time_us,
                "allowed_effect_types": request.allowed_effect_types,
                "world_context": request.world_context,
                "explicitly_authorized_private_context": request.private_context,
            },
            output_type=DirectorPlanCandidate,
            operation="Scenario Director",
            redacted_request={
                "request_id": request.request_id,
                "branch_id": request.branch_id,
                "context_hash": request.context_hash,
            },
            record_raw=record_raw,
        )

    async def interpret_agent_configuration(
        self,
        request: AgentConfigurationProviderRequest,
        *,
        record_raw: Callable[[LLMRecord], None] | None = None,
    ) -> AgentConfigurationInterpretationCandidate:
        return await self._create_typed(
            request_id=request.request_id,
            agent_id="agent_configuration_interpreter",
            context_hash=request.context_hash,
            instructions=AGENT_CONFIGURATION_INSTRUCTIONS,
            payload={
                "user_intent": request.user_intent,
                "allowed_archetypes": request.allowed_archetypes,
                "allowed_capabilities": request.allowed_capabilities,
                "allowed_persona_fields": request.allowed_persona_fields,
            },
            output_type=AgentConfigurationInterpretationCandidate,
            operation="Agent configuration interpretation",
            redacted_request={
                "request_id": request.request_id,
                "context_hash": request.context_hash,
            },
            record_raw=record_raw,
        )
