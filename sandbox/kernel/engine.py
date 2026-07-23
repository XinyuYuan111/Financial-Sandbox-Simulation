from __future__ import annotations

from collections.abc import Callable

from sandbox.contracts.event import EventDraft, EventEnvelope
from sandbox.kernel.scheduler import EventScheduler
from sandbox.store.event_store import EventStore


Handler = Callable[[EventEnvelope], list[EventDraft]]


class Kernel:
    def __init__(self, run_id: str, branch_id: str, event_store: EventStore) -> None:
        self.run_id = run_id
        self.branch_id = branch_id
        self.event_store = event_store
        self.scheduler = EventScheduler()
        self.handlers: dict[str, Handler] = {}
        self.published: list[EventEnvelope] = []

    def register(self, event_type: str, handler: Handler) -> None:
        self.handlers[event_type] = handler

    def schedule(self, event: EventDraft) -> None:
        if event.sim_time_us == 0 and event.event_type.startswith("Background"):
            event = event.model_copy(update={"sim_time_us": 1})
        self.scheduler.push(event)

    def step(self) -> list[EventEnvelope]:
        draft = self.scheduler.pop()
        if draft is None:
            return []
        # Drafts are persisted atomically before external publication.
        persisted = self.event_store.append_batch(self.run_id, self.branch_id, [draft])
        committed = persisted[0]
        self.published.extend(persisted)
        handler = self.handlers.get(committed.event_type)
        if handler:
            for derived in handler(committed):
                self.schedule(derived)
        return persisted

    def drain(self, limit: int = 10_000) -> list[EventEnvelope]:
        output: list[EventEnvelope] = []
        for _ in range(limit):
            committed = self.step()
            if not committed:
                break
            output.extend(committed)
        return output

