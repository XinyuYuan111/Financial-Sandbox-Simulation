from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from sandbox.contracts.agent import (
    ActionProposal,
    AgentDecision,
    AgentDefinition,
    BasePersona,
    BeliefProposal,
    DecisionRationale,
    DecisionOutcome,
    MemoryProposal,
)
from sandbox.contracts.planning import (
    CommunicationDirective,
    CompareCondition,
    EmissionPolicy,
    PlanningRequest,
    validate_planning_transition,
)
from sandbox.store.sqlite import SQLiteStore


def persona() -> BasePersona:
    return BasePersona(
        template_id="balanced",
        risk_tolerance_milli=500,
        time_horizon="medium",
        loss_aversion_milli=500,
        trend_bias_milli=500,
        skepticism_milli=500,
        communication_propensity_milli=500,
    )


class AgentContractTests(unittest.TestCase):
    def test_agent_definition_is_strict_and_does_not_contain_balance(self) -> None:
        definition = AgentDefinition(
            agent_id="agent_1",
            display_name="Agent One",
            capability_set=["market.trade"],
            base_persona=persona(),
            planner_profile_id="rule.default.v0.1",
        )
        self.assertNotIn("balance", definition.model_dump())
        self.assertNotIn("funding_profile", definition.model_dump())
        with self.assertRaises(PydanticValidationError):
            AgentDefinition.model_validate({**definition.model_dump(), "funding_profile": "ordinary"})
        with self.assertRaises(PydanticValidationError):
            AgentDefinition.model_validate({**definition.model_dump(), "token_balance": 1})

    def test_condition_and_emission_are_closed_contracts(self) -> None:
        with self.assertRaises(PydanticValidationError):
            CompareCondition(path="world.secret", op="eq", value=1)  # type: ignore[arg-type]
        with self.assertRaises(PydanticValidationError):
            EmissionPolicy(mode="periodic", max_emissions=2)

    def test_communication_contract_distinguishes_disclosure_withholding_and_deception(self) -> None:
        emission = EmissionPolicy(mode="periodic", interval_us=2_000_000, max_emissions=6)
        withheld = CommunicationDirective(
            directive_key="keep-private-view",
            channel="PublicFeed",
            communication_mode="withhold",
            private_assessment_direction="bullish",
            emission=emission,
        )
        deceptive = CommunicationDirective(
            directive_key="misstate-view",
            channel="PublicFeed",
            message_payload="Selling pressure is building.",
            signal_direction="bearish",
            signal_confidence_milli=700,
            claim_intent="strategic_deception",
            private_assessment_direction="bullish",
            emission=emission,
        )
        self.assertEqual(withheld.communication_mode, "withhold")
        self.assertEqual(deceptive.claim_intent, "strategic_deception")
        with self.assertRaises(PydanticValidationError):
            CommunicationDirective(
                directive_key="invalid-deception",
                channel="PublicFeed",
                message_payload="Demand is strong.",
                signal_direction="bullish",
                signal_confidence_milli=700,
                claim_intent="strategic_deception",
                private_assessment_direction="bullish",
                emission=emission,
            )

    def test_decision_dependencies_only_point_forward_through_pipeline(self) -> None:
        memory = MemoryProposal(
            proposal_id="memory-1",
            kind="write",
            summary="observed",
            source_ids=["info-1"],
        )
        belief = BeliefProposal(
            proposal_id="belief-1",
            depends_on=["memory-1"],
            subject="TOKEN",
            predicate="direction",
            value="up",
            confidence_milli=600,
        )
        action = ActionProposal(
            proposal_id="action-1",
            depends_on=["belief-1"],
            action_type="SubmitLimitOrder",
            payload={"side": "buy", "quantity": 1, "price": 100},
            expected_execution_time_us=1,
            validity_window_us=10,
        )
        decision = AgentDecision(
            decision_id="decision-1",
            branch_id="branch-1",
            agent_id="agent-1",
            observation_id="observation-1",
            sim_time_us=0,
            base_agent_revision=0,
            memory_proposals=[memory],
            belief_proposals=[belief],
            action_proposals=[action],
            rationale=DecisionRationale(proposal_ids=["memory-1", "belief-1", "action-1"]),
        )
        self.assertEqual(decision.action_proposals[0].depends_on, ["belief-1"])
        with self.assertRaises(PydanticValidationError):
            decision.model_copy(
                update={
                    "memory_proposals": [
                        memory.model_copy(update={"depends_on": ["action-1"]})
                    ]
                }
            ).__class__.model_validate(
                {
                    **decision.model_dump(),
                    "memory_proposals": [
                        {**memory.model_dump(), "depends_on": ["action-1"]}
                    ],
                }
            )

    def test_planning_lifecycle_is_monotonic_and_terminal_is_closed(self) -> None:
        queued = PlanningRequest(
            request_id="request-1",
            branch_id="branch-1",
            agent_id="agent-1",
            source_decision_id="decision-1",
            source_observation_id="observation-1",
            requested_sim_time_us=0,
            activation_time_us=10,
            planner_profile_id="rule.default.v0.1",
            based_on_strategy_revision=0,
            memory_revision=0,
            belief_revision=0,
        )
        running = queued.model_copy(update={"state": "Running"})
        validate_planning_transition(queued, running)
        terminal = running.model_copy(update={"state": "Terminal", "terminal_outcome": "failed"})
        validate_planning_transition(running, terminal)
        with self.assertRaises(ValueError):
            validate_planning_transition(terminal, running)

    def test_agent_migration_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "sandbox.db")
            try:
                tables = {
                    row["name"]
                    for row in store.connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                self.assertTrue(
                    {"agent_decisions", "planning_requests", "strategy_plans", "llm_records", "action_receipts"}.issubset(tables)
                )
                migration = store.connection.execute(
                    "SELECT version,checksum FROM schema_migrations"
                ).fetchone()
                self.assertEqual(migration["version"], "0001_agent_v0_1")
                self.assertTrue(str(migration["checksum"]).startswith("sha256:"))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
