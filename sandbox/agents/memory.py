from __future__ import annotations

from dataclasses import dataclass, field

from sandbox.core.errors import ValidationError
from sandbox.core.ids import new_id


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    memory_id: str
    agent_id: str
    summary: str
    source_ids: tuple[str, ...]
    confidence_milli: int
    salience: int
    created_sim_time_us: int


@dataclass(slots=True)
class MemoryStore:
    capacity: int = 100
    entries: dict[str, list[MemoryEntry]] = field(default_factory=dict)

    def propose_write(self, *, agent_id: str, summary: str, source_ids: list[str], observed_ids: set[str], confidence_milli: int, salience: int, sim_time_us: int) -> MemoryEntry:
        if not source_ids or not set(source_ids).issubset(observed_ids):
            raise ValidationError("memory sources must be present in the agent observation history")
        if not 0 <= confidence_milli <= 1_000:
            raise ValidationError("memory confidence must be within 0..1000")
        entry = MemoryEntry(new_id("mem"), agent_id, summary[:1_000], tuple(source_ids), confidence_milli, salience, sim_time_us)
        bucket = self.entries.setdefault(agent_id, [])
        bucket.append(entry)
        if len(bucket) > self.capacity:
            bucket.sort(key=lambda item: (item.salience, item.created_sim_time_us))
            bucket.pop(0)
        return entry

    def search(self, agent_id: str, query: str, *, limit: int, budget_state: dict[str, int]) -> list[MemoryEntry]:
        if budget_state.get("searches_remaining", 0) <= 0:
            return []
        budget_state["searches_remaining"] -= 1
        terms = {term.casefold() for term in query.split() if term}
        matches = [item for item in self.entries.get(agent_id, []) if terms & set(item.summary.casefold().split())]
        matches.sort(key=lambda item: (-item.salience, -item.created_sim_time_us))
        return matches[:limit]

