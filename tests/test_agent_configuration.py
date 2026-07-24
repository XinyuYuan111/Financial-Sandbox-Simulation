from __future__ import annotations

import unittest

from pydantic import ValidationError as PydanticValidationError

from sandbox.agents.configuration import compile_agent_configuration, draft_from_interpretation
from sandbox.agents.population import generate_population
from sandbox.contracts.agent_configuration import (
    AgentConfigurationDraft,
    AgentConfigurationInterpretationCandidate,
    ConfigurationSuggestion,
)
from sandbox.contracts.scenario import AgentConfig, HolderDistribution, PortfolioSynthesisConfig
from sandbox.core.errors import ValidationError


def holder_distribution() -> HolderDistribution:
    return HolderDistribution(
        active_holder_count=10_000,
        p25_balance=100,
        p50_balance=500,
        p75_balance=2_000,
        p90_balance=10_000,
        p99_balance=50_000,
        top_10_concentration_milli=600,
    )


def population(drafts: list[AgentConfigurationDraft]):
    return generate_population(
        seed=20260724,
        preset="smoke",
        agent_count=None,
        eligible_active_supply=900_000,
        covered_eligible_supply=600_000,
        total_token_supply=1_000_000,
        active_usdx_supply=9_000_000_000,
        holder_distribution=holder_distribution(),
        portfolio=PortfolioSynthesisConfig(),
        planner_kind="rule",
        drafts=drafts,
    )


class AgentConfigurationTests(unittest.TestCase):
    def test_funding_profile_is_not_a_current_agent_input(self) -> None:
        with self.assertRaises(PydanticValidationError):
            AgentConfig.model_validate({
                "agent_id": "agent-1",
                "display_name": "Agent One",
                "strategy": "rule",
                "funding_profile": "capital",
                "token_balance": 1,
                "usdx_balance": 1,
            })

    def test_detailed_configuration_has_no_implicit_randomness(self) -> None:
        draft = AgentConfigurationDraft(
            draft_id="detailed-1",
            input_mode="detailed",
            agent_id="agent-1",
            archetype_ids=["liquidity_provider", "capital_holder"],
            base_persona={"risk_tolerance_milli": 321},
        )
        first = compile_agent_configuration(draft, seed=1, ordinal=1, planner_kind="rule")
        second = compile_agent_configuration(draft, seed=999, ordinal=1, planner_kind="rule")
        self.assertEqual(first.definition, second.definition)
        self.assertEqual(first.definition.base_persona.risk_tolerance_milli, 321)
        self.assertEqual(first.definition.configuration_provenance["base_persona.risk_tolerance_milli"].source, "user")
        self.assertTrue(all(item.source != "random" for item in first.definition.configuration_provenance.values()))

    def test_roles_and_archetypes_do_not_determine_wealth(self) -> None:
        ordinary = [
            AgentConfigurationDraft(
                draft_id=f"draft-{index}",
                input_mode="detailed",
                agent_id=f"agent-{index}",
                archetype_ids=["ordinary_participant"],
            )
            for index in range(1, 4)
        ]
        specialized = [
            draft.model_copy(update={"archetype_ids": [archetype]})
            for draft, archetype in zip(
                ordinary,
                ["capital_holder", "liquidity_provider", "asset_issuer"],
                strict=True,
            )
        ]
        ordinary_result = population(ordinary)
        specialized_result = population(specialized)
        self.assertEqual(
            [(item.token_balance, item.usdx_balance) for item in ordinary_result.allocations],
            [(item.token_balance, item.usdx_balance) for item in specialized_result.allocations],
        )
        self.assertNotEqual(
            [item.role_tags for item in ordinary_result.definitions],
            [item.role_tags for item in specialized_result.definitions],
        )

    def test_every_interpreter_suggestion_requires_a_disposition(self) -> None:
        suggestion = ConfigurationSuggestion(
            suggestion_id="suggestion-1",
            kind="archetype",
            value="liquidity_provider",
            reason="The user described continuous two-sided quoting.",
            confidence_milli=800,
        )
        pending = AgentConfigurationDraft(
            draft_id="nl-1",
            input_mode="natural_language",
            suggestions=[suggestion],
        )
        with self.assertRaisesRegex(ValidationError, "unconfirmed suggestions"):
            compile_agent_configuration(pending, seed=1, ordinal=1, planner_kind="rule")
        accepted = pending.model_copy(update={"accepted_suggestion_ids": ["suggestion-1"]})
        compiled = compile_agent_configuration(accepted, seed=1, ordinal=1, planner_kind="rule")
        self.assertIn("liquidity_provider", compiled.definition.role_tags)

    def test_interpreter_cannot_write_protected_or_unregistered_fields(self) -> None:
        with self.assertRaises(PydanticValidationError):
            AgentConfigurationInterpretationCandidate.model_validate({"strategy": "openai"})
        candidate = AgentConfigurationInterpretationCandidate(
            suggestions=[ConfigurationSuggestion(
                suggestion_id="suggestion-1",
                kind="capability",
                value="ledger.mint",
                reason="Requested by model",
                confidence_milli=500,
            )],
        )
        with self.assertRaisesRegex(ValidationError, "unregistered capability"):
            draft_from_interpretation(candidate, draft_id="nl-1", request_id="request-1")

    def test_fully_manual_portfolio_leaves_auditable_background_residual(self) -> None:
        drafts = [
            AgentConfigurationDraft(
                draft_id="manual-1",
                input_mode="detailed",
                agent_id="agent-1",
                portfolio={"token_amount": 12_345, "usdx_amount": 67_890},
            ),
            AgentConfigurationDraft(
                draft_id="manual-2",
                input_mode="detailed",
                agent_id="agent-2",
                portfolio={"token_amount": 54_321, "usdx_amount": 98_765},
            ),
        ]
        result = population(drafts)
        self.assertEqual(sum(item.token_balance for item in result.allocations), 66_666)
        self.assertEqual(sum(item.usdx_balance for item in result.allocations), 166_655)
        self.assertEqual(result.background.token_balance, 900_000 - 66_666)
        self.assertEqual(result.background.usdx_balance, 9_000_000_000 - 166_655)
        self.assertTrue(result.preview["assets"]["token_conserved"])
        self.assertTrue(result.preview["assets"]["usdx_conserved"])


if __name__ == "__main__":
    unittest.main()
