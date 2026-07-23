from __future__ import annotations

from dataclasses import dataclass, field
from heapq import heappop, heappush

from sandbox.contracts.event import EventDraft


@dataclass(order=True, slots=True)
class ScheduledEvent:
    sort_key: tuple[int, int, str] = field(init=False)
    event: EventDraft = field(compare=False)

    def __post_init__(self) -> None:
        self.sort_key = (self.event.sim_time_us, self.event.priority, self.event.tie_break_key)


class EventScheduler:
    def __init__(self) -> None:
        self._queue: list[ScheduledEvent] = []

    def push(self, event: EventDraft) -> None:
        heappush(self._queue, ScheduledEvent(event=event))

    def pop(self) -> EventDraft | None:
        return heappop(self._queue).event if self._queue else None

    def snapshot(self) -> list[dict[str, object]]:
        return [item.event.model_dump(mode="json") for item in sorted(self._queue)]

