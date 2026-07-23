from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from sandbox.agents.belief import BeliefService
from sandbox.agents.llm_gateway import LLMGateway
from sandbox.agents.memory import MemoryStore
from sandbox.contracts.event import EventDraft
from sandbox.contracts.scenario import ScenarioDraft
from sandbox.control.initialization import Initializer
from sandbox.core.errors import ValidationError
from sandbox.core.rng import NamedRandomStreams
from sandbox.kernel.scheduler import EventScheduler


class ContractBoundaryTests(unittest.TestCase):
    def test_named_random_streams_are_isolated_and_recoverable(self) -> None:
        streams_a = NamedRandomStreams(42)
        first_market = streams_a.random("market.background")
        streams_a.random("agent.alpha.attention")
        second_market = streams_a.random("market.background")

        streams_b = NamedRandomStreams(42)
        self.assertEqual(first_market, streams_b.random("market.background"))
        self.assertEqual(second_market, streams_b.random("market.background"))
        restored = NamedRandomStreams(42, streams_a.snapshot())
        self.assertEqual(streams_a.random("market.background"), restored.random("market.background"))

    def test_scheduler_orders_virtual_time_priority_and_stable_key(self) -> None:
        scheduler = EventScheduler()
        for sim_time, priority, tie in ((2, 10, "a"), (1, 20, "a"), (1, 10, "z"), (1, 10, "a")):
            scheduler.push(EventDraft(sim_time_us=sim_time, priority=priority, tie_break_key=tie, event_type=tie, source_id="test"))
        self.assertEqual([(item.sim_time_us, item.priority, item.tie_break_key) for item in (scheduler.pop(), scheduler.pop(), scheduler.pop(), scheduler.pop())], [(1, 10, "a"), (1, 10, "z"), (1, 20, "a"), (2, 10, "a")])

    def test_memory_and_belief_reject_unobserved_or_inaccessible_evidence(self) -> None:
        memory = MemoryStore(capacity=2)
        with self.assertRaises(ValidationError):
            memory.propose_write(agent_id="alpha", summary="hidden", source_ids=["info-hidden"], observed_ids=set(), confidence_milli=500, salience=1, sim_time_us=1)
        belief = BeliefService()
        with self.assertRaises(ValidationError):
            belief.update(agent_id="alpha", subject="TOKEN", predicate="rises", value="yes", confidence_milli=700, evidence_memory_ids=["mem-other"], accessible_memory_ids=set(), sim_time_us=1, stated_reason="private")

    def test_live_mode_does_not_fall_back_to_fixture(self) -> None:
        initializer = Initializer({}, LLMGateway({}))
        draft = ScenarioDraft(mode="live", chain_id="ethereum", llm_provider="openai")
        with self.assertRaisesRegex(ValidationError, "holder provider"):
            asyncio.run(initializer.resolve("scenario-live", draft))


if __name__ == "__main__":
    unittest.main()

