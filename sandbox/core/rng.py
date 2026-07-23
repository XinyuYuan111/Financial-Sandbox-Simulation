from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class StreamState:
    name: str
    seed: int
    draw_index: int = 0
    version: str = "python-mt19937.v1"


class NamedRandomStreams:
    def __init__(self, root_seed: int, states: dict[str, dict[str, Any]] | None = None) -> None:
        self.root_seed = root_seed
        self._states: dict[str, StreamState] = {}
        if states:
            self._states = {name: StreamState(**state) for name, state in states.items()}

    def _stream(self, name: str) -> tuple[random.Random, StreamState]:
        state = self._states.get(name)
        if state is None:
            digest = hashlib.sha256(f"{self.root_seed}:{name}".encode()).digest()
            state = StreamState(name=name, seed=int.from_bytes(digest[:8], "big"))
            self._states[name] = state
        generator = random.Random(state.seed)
        for _ in range(state.draw_index):
            generator.random()
        return generator, state

    def random(self, name: str) -> tuple[float, int]:
        generator, state = self._stream(name)
        value = generator.random()
        index = state.draw_index
        state.draw_index += 1
        return value, index

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {name: {"name": state.name, "seed": state.seed, "draw_index": state.draw_index, "version": state.version} for name, state in self._states.items()}

