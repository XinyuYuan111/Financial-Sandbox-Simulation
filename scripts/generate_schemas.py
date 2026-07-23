from __future__ import annotations

import json
from pathlib import Path

from sandbox.contracts.action import ActionContract
from sandbox.contracts.event import EventEnvelope
from sandbox.contracts.observation import ObservationPacket
from sandbox.contracts.scenario import ResolvedInitialState, ScenarioDraft
from sandbox.contracts.snapshot import ArchiveManifest, Checkpoint


MODELS = {
    "action.v0.2.json": ActionContract,
    "event.v0.2.json": EventEnvelope,
    "observation.v0.2.json": ObservationPacket,
    "scenario.v0.2.json": ScenarioDraft,
    "resolved-initial-state.v0.2.json": ResolvedInitialState,
    "checkpoint.v0.2.json": Checkpoint,
    "archive.v0.2.json": ArchiveManifest,
}

root = Path(__file__).resolve().parents[1] / "sandbox" / "contracts" / "schemas"
root.mkdir(parents=True, exist_ok=True)
for filename, model in MODELS.items():
    (root / filename).write_text(json.dumps(model.model_json_schema(), ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

