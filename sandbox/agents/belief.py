from __future__ import annotations

from dataclasses import dataclass, field

from sandbox.core.errors import ValidationError
from sandbox.core.ids import new_id


@dataclass(frozen=True, slots=True)
class Belief:
    belief_id: str
    agent_id: str
    subject: str
    predicate: str
    value: str
    confidence_milli: int
    evidence_memory_ids: tuple[str, ...]
    updated_sim_time_us: int
    stated_reason: str


@dataclass(slots=True)
class BeliefService:
    beliefs: dict[str, list[Belief]] = field(default_factory=dict)

    def update(self, *, agent_id: str, subject: str, predicate: str, value: str, confidence_milli: int, evidence_memory_ids: list[str], accessible_memory_ids: set[str], sim_time_us: int, stated_reason: str) -> Belief:
        if not set(evidence_memory_ids).issubset(accessible_memory_ids):
            raise ValidationError("belief evidence is not accessible to this agent")
        if not 0 <= confidence_milli <= 1_000:
            raise ValidationError("belief confidence must be within 0..1000")
        belief = Belief(new_id("belief"), agent_id, subject, predicate, value, confidence_milli, tuple(evidence_memory_ids), sim_time_us, stated_reason[:500])
        self.beliefs.setdefault(agent_id, []).append(belief)
        return belief

