from __future__ import annotations

import json
from pathlib import Path

from sandbox.contracts.action import ActionContract
from sandbox.contracts.intervention import DirectorPlanCandidate, DirectorProviderRequest, InterventionPlan
from sandbox.contracts.agent import ActionReceipt, AgentDecision, AgentDefinition, AgentRuntimeState, DecisionOutcome
from sandbox.contracts.agent_configuration import (
    AgentConfigurationDraft,
    AgentConfigurationInterpretationCandidate,
    AgentConfigurationProviderRequest,
)
from sandbox.contracts.event import EventEnvelope
from sandbox.contracts.observation import ObservationPacket
from sandbox.contracts.scenario import ResolvedInitialState, ScenarioDraft
from sandbox.contracts.snapshot import ArchiveManifest, Checkpoint
from sandbox.contracts.planning import PlanningRequest, PlanningResultCandidate, StrategyPlan


MODELS = {
    "action.v0.2.json": ActionContract,
    "event.v0.2.json": EventEnvelope,
    "observation.v0.3.json": ObservationPacket,
    "scenario.v0.3.json": ScenarioDraft,
    "resolved-initial-state.v0.3.json": ResolvedInitialState,
    "checkpoint.v0.2.json": Checkpoint,
    "archive.v0.2.json": ArchiveManifest,
    "agent-definition.v0.2.json": AgentDefinition,
    "agent-configuration-draft.v0.1.json": AgentConfigurationDraft,
    "agent-configuration-provider-request.v0.1.json": AgentConfigurationProviderRequest,
    "agent-configuration-interpretation.v0.1.json": AgentConfigurationInterpretationCandidate,
    "agent-runtime-state.v0.1.json": AgentRuntimeState,
    "agent-decision.v0.1.json": AgentDecision,
    "decision-outcome.v0.1.json": DecisionOutcome,
    "planning-request.v0.1.json": PlanningRequest,
    "planning-result-candidate.v0.1.json": PlanningResultCandidate,
    "strategy-plan.v0.1.json": StrategyPlan,
    "action-receipt.v0.1.json": ActionReceipt,
    "intervention-plan.v0.1.json": InterventionPlan,
    "director-plan-candidate.v0.1.json": DirectorPlanCandidate,
    "director-provider-request.v0.1.json": DirectorProviderRequest,
}

root = Path(__file__).resolve().parents[1] / "sandbox" / "contracts" / "schemas"
root.mkdir(parents=True, exist_ok=True)
for filename, model in MODELS.items():
    (root / filename).write_text(json.dumps(model.model_json_schema(), ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
