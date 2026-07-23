from __future__ import annotations

import json
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sandbox.agents.strategies import FixtureStrategies
from sandbox.contracts.action import ActionContract
from sandbox.contracts.event import EventDraft
from sandbox.contracts.scenario import ResolvedInitialState, ScenarioDraft
from sandbox.contracts.snapshot import Checkpoint
from sandbox.control.initialization import Initializer
from sandbox.core.errors import ConflictError, NotFoundError, SandboxError, ValidationError
from sandbox.core.ids import deterministic_id, new_id
from sandbox.store.archive import ArchiveService
from sandbox.store.event_store import EventStore, canonical_json, utc_now
from sandbox.store.sqlite import SQLiteStore
from sandbox.world.state import ActionResult, SimulationWorld


class RunManager:
    def __init__(self, store: SQLiteStore, initializer: Initializer, archive_service: ArchiveService, runtime_version: str) -> None:
        self.store = store
        self.events = EventStore(store)
        self.initializer = initializer
        self.archive_service = archive_service
        self.runtime_version = runtime_version
        self._locks: defaultdict[str, threading.RLock] = defaultdict(threading.RLock)

    def create_scenario(self, draft: ScenarioDraft) -> dict[str, object]:
        scenario_id = new_id("scenario")
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO scenarios(scenario_id,draft_json,created_at) VALUES(?,?,?)",
                (scenario_id, canonical_json(draft.model_dump(mode="json")), utc_now()),
            )
        return {"scenario_id": scenario_id, "status": "Draft", "draft": draft.model_dump(mode="json")}

    async def resolve_scenario(self, scenario_id: str) -> ResolvedInitialState:
        row = self.store.connection.execute("SELECT draft_json FROM scenarios WHERE scenario_id=?", (scenario_id,)).fetchone()
        if row is None:
            raise NotFoundError("scenario", scenario_id)
        draft = ScenarioDraft.model_validate(json.loads(row["draft_json"]))
        resolved = await self.initializer.resolve(scenario_id, draft)
        with self.store.transaction() as connection:
            connection.execute("UPDATE scenarios SET resolved_json=? WHERE scenario_id=?", (canonical_json(resolved.model_dump(mode="json")), scenario_id))
        return resolved

    def create_run(self, scenario_id: str) -> dict[str, object]:
        row = self.store.connection.execute("SELECT resolved_json FROM scenarios WHERE scenario_id=?", (scenario_id,)).fetchone()
        if row is None:
            raise NotFoundError("scenario", scenario_id)
        if row["resolved_json"] is None:
            raise ConflictError("scenario must be resolved and confirmed before creating a run", error_code="SCENARIO_NOT_RESOLVED")
        resolved = ResolvedInitialState.model_validate(json.loads(row["resolved_json"]))
        run_id = new_id("run")
        branch_id = new_id("branch")
        world = SimulationWorld.from_resolved(resolved)
        drafts = [
            self._system_event("RunCreated", run_id, {"scenario_id": scenario_id}, tie="00-run"),
            self._system_event("InitialStateResolved", run_id, {"schema_version": resolved.schema_version, "total_supply": resolved.total_supply}, tie="01-initial"),
            self._system_event("BranchCreated", run_id, {"branch_id": branch_id, "parent_branch_id": None}, tie="02-branch"),
        ]
        observations = world.create_observations(branch_id, len(drafts))
        drafts.extend(self._observation_event(observation, run_id) for observation in observations)
        created_at = utc_now()
        self.events.append_batch(
            run_id, branch_id, drafts,
            world_state=world.to_json(),
            observations=[item.model_dump(mode="json") for item in observations],
            branch_status="Ready",
            run_record={"run_id": run_id, "scenario_id": scenario_id, "name": resolved.name, "status": "Ready", "runtime_version": self.runtime_version, "resolved_state": resolved.model_dump(mode="json"), "created_at": created_at},
            branch_record={"branch_id": branch_id, "run_id": run_id, "status": "Initializing", "created_at": created_at},
        )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, object]:
        with self.store.locked():
            return self._get_run_locked(run_id)

    def _get_run_locked(self, run_id: str) -> dict[str, object]:
        run = self.store.connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None:
            raise NotFoundError("run", run_id)
        branches = self.store.connection.execute("SELECT * FROM branches WHERE run_id=? ORDER BY created_at", (run_id,)).fetchall()
        return {
            "run_id": run_id,
            "scenario_id": run["scenario_id"],
            "name": run["name"],
            "status": run["status"],
            "runtime_version": run["runtime_version"],
            "branches": [dict(branch) for branch in branches],
        }

    def list_runs(self) -> list[dict[str, object]]:
        with self.store.locked():
            return [self._get_run_locked(row["run_id"]) for row in self.store.connection.execute("SELECT run_id FROM runs ORDER BY created_at DESC").fetchall()]

    def branch_projection(self, branch_id: str, cursor: int | None = None) -> dict[str, object]:
        with self.store.locked():
            return self._branch_projection_locked(branch_id, cursor)

    def _branch_projection_locked(self, branch_id: str, cursor: int | None = None) -> dict[str, object]:
        branch = self._branch(branch_id)
        if cursor is not None and cursor < int(branch["state_version"]):
            rows = self.store.connection.execute("SELECT observation_json FROM observations WHERE branch_id=? ORDER BY sim_time_us, observation_id", (branch_id,)).fetchall()
            observations = [json.loads(row["observation_json"]) for row in rows]
            visible = [item for item in observations if int(item["world_version"]) <= cursor]
            if not visible:
                raise ValidationError("no saved projection exists at or before this cursor")
            latest_by_agent: dict[str, dict[str, object]] = {}
            for item in visible:
                latest_by_agent[str(item["agent_id"])] = item
            sample = max(latest_by_agent.values(), key=lambda item: int(item["world_version"]))
            return {
                "branch_id": branch_id,
                "cursor": cursor,
                "status": "Historical",
                "sim_time_us": sample["sim_time_us"],
                "market": sample["market_view"],
                "agents": [{"agent_id": agent_id, "portfolio": item["portfolio_view"]} for agent_id, item in latest_by_agent.items()],
                "information": sample["information_items"],
                "historical": True,
                "parent_branch_id": branch["parent_branch_id"],
                "fork_checkpoint_id": branch["fork_checkpoint_id"],
            }
        world = self._world(branch_id)
        projection = world.projection(branch_id, int(branch["state_version"]), str(branch["status"]))
        projection["parent_branch_id"] = branch["parent_branch_id"]
        projection["fork_checkpoint_id"] = branch["fork_checkpoint_id"]
        return projection

    def observations(self, branch_id: str, agent_id: str, *, cursor: int | None = None, limit: int = 200) -> list[dict[str, object]]:
        with self.store.locked():
            self._branch(branch_id)
            rows = self.store.connection.execute("SELECT observation_json FROM observations WHERE branch_id=? AND agent_id=? ORDER BY sim_time_us DESC LIMIT ?", (branch_id, agent_id, limit)).fetchall()
            items = [json.loads(row["observation_json"]) for row in rows]
            if cursor is not None:
                items = [item for item in items if int(item["world_version"]) <= cursor]
            return items

    def submit_action(self, action: ActionContract) -> dict[str, object]:
        with self.store.locked():
            command_key = deterministic_id("cmd", action.branch_id, action.client_command_id)
            existing = self._command_result(command_key)
            if existing is not None:
                return existing
            with self._locks[action.branch_id]:
                branch = self._branch(action.branch_id)
                if branch["status"] != "Running":
                    raise ConflictError("actions can only execute on a Running branch", error_code="BRANCH_NOT_RUNNING")
                return self._apply_action(action, self._world(action.branch_id), int(branch["state_version"]), command_key=command_key)

    def command(self, branch_id: str, client_command_id: str, command_type: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        with self.store.locked():
            return self._command_locked(branch_id, client_command_id, command_type, payload)

    def _command_locked(self, branch_id: str, client_command_id: str, command_type: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        payload = payload or {}
        command_key = deterministic_id("cmd", branch_id, client_command_id)
        existing = self._command_result(command_key)
        if existing is not None:
            return existing
        with self._locks[branch_id]:
            branch = self._branch(branch_id)
            status = str(branch["status"])
            run_id = str(branch["run_id"])
            world = self._world(branch_id)
            if command_type == "start":
                if status not in {"Ready", "Paused"}:
                    raise ConflictError(f"cannot start branch from {status}")
                event_type = "BranchResumed" if status == "Paused" else "BranchResumed"
                record = self._command_record(command_key, command_type, {"branch_id": branch_id, "status": "Running"})
                self.events.append_batch(run_id, branch_id, [self._system_event(event_type, branch_id, {}, sim_time_us=world.sim_time_us)], world_state=world.to_json(), branch_status="Running", command_record=record)
                result = record["persisted_result"]
            elif command_type == "pause":
                if status != "Running":
                    raise ConflictError(f"cannot pause branch from {status}")
                record = self._command_record(command_key, command_type, {"branch_id": branch_id, "status": "Paused"})
                self.events.append_batch(run_id, branch_id, [self._system_event("BranchPaused", branch_id, {}, sim_time_us=world.sim_time_us)], world_state=world.to_json(), branch_status="Paused", command_record=record)
                result = record["persisted_result"]
            elif command_type == "step_fixture":
                if status != "Running":
                    raise ConflictError("fixture step requires a Running branch")
                decision = FixtureStrategies.at(world.fixture_step)
                if decision is None:
                    record = self._command_record(command_key, command_type, {"branch_id": branch_id, "status": "Completed", "message": "fixture sequence is complete"})
                    self.events.append_batch(run_id, branch_id, [self._system_event("ControlInterventionApplied", branch_id, {"kind": "fixture_completed"}, sim_time_us=world.sim_time_us)], world_state=world.to_json(), branch_status="Completed", command_record=record)
                    result = record["persisted_result"]
                else:
                    agent_id, strategy = decision
                    working = world.clone()
                    working.fixture_step += 1
                    action = ActionContract(
                        action_id=new_id("act"), agent_id=agent_id, branch_id=branch_id,
                        submitted_sim_time_us=working.sim_time_us,
                        action_type=strategy.action_type, payload=strategy.payload,
                        expected_execution_time_us=working.sim_time_us + 1_000_000,
                        validity_window_us=2_000_000,
                        parent_observation_id=working.latest_observation_ids.get(agent_id),
                        client_command_id=client_command_id,
                    )
                    result = self._apply_action(action, working, int(branch["state_version"]), command_key=command_key)
            elif command_type == "save":
                result = self._checkpoint(branch_id, world, branch, command_key=command_key)
            else:
                raise ValidationError(f"unsupported command '{command_type}'")
            return result

    def fork(self, branch_id: str, checkpoint_id: str, client_command_id: str) -> dict[str, object]:
        with self.store.locked():
            return self._fork_locked(branch_id, checkpoint_id, client_command_id)

    def _fork_locked(self, branch_id: str, checkpoint_id: str, client_command_id: str) -> dict[str, object]:
        command_key = deterministic_id("cmd", branch_id, client_command_id)
        existing = self._command_result(command_key)
        if existing is not None:
            return existing
        checkpoint_row = self.store.connection.execute("SELECT snapshot_json FROM snapshots WHERE checkpoint_id=? AND branch_id=?", (checkpoint_id, branch_id)).fetchone()
        if checkpoint_row is None:
            raise NotFoundError("checkpoint", checkpoint_id)
        checkpoint = Checkpoint.model_validate(json.loads(checkpoint_row["snapshot_json"]))
        new_branch_id = new_id("branch")
        world = SimulationWorld.from_json(checkpoint.state)
        observations = world.create_observations(new_branch_id, 1)
        drafts = [self._system_event("BranchCreated", new_branch_id, {"parent_branch_id": branch_id, "fork_checkpoint_id": checkpoint_id}, sim_time_us=checkpoint.sim_time_us)]
        drafts.extend(self._observation_event(observation, new_branch_id) for observation in observations)
        record = self._command_record(command_key, "fork", {"branch_id": new_branch_id, "parent_branch_id": branch_id, "checkpoint_id": checkpoint_id, "status": "Ready"})
        self.events.append_batch(
            checkpoint.run_id, new_branch_id, drafts,
            world_state=world.to_json(), observations=[item.model_dump(mode="json") for item in observations], branch_status="Ready", command_record=record,
            branch_record={"branch_id": new_branch_id, "run_id": checkpoint.run_id, "parent_branch_id": branch_id, "fork_checkpoint_id": checkpoint_id, "status": "Created", "sim_time_us": checkpoint.sim_time_us, "created_at": utc_now()},
        )
        result = record["persisted_result"]
        return result

    def export_archive(self, run_id: str, output_path: Path) -> dict[str, object]:
        branches = self.store.connection.execute("SELECT * FROM branches WHERE run_id=? ORDER BY created_at", (run_id,)).fetchall()
        if not branches:
            raise NotFoundError("run", run_id)
        for branch in branches:
            if branch["status"] != "Checkpointed":
                self._checkpoint(str(branch["branch_id"]), self._world(str(branch["branch_id"])), branch)
        manifest = self.archive_service.export_run(run_id, output_path)
        return {"path": str(output_path), "manifest": manifest.model_dump(mode="json")}

    def import_archive(self, path: Path) -> dict[str, object]:
        return self.archive_service.import_run(path)

    def _apply_action(self, action: ActionContract, world: SimulationWorld, state_version: int, *, command_key: str | None = None) -> dict[str, object]:
        branch = self._branch(action.branch_id)
        try:
            action_result: ActionResult = world.apply_action(action, world_version=state_version)
            record = self._command_record(command_key, action.action_type, {"accepted": True, "action_id": action.action_id, "branch_id": action.branch_id}, include_events=True) if command_key else None
            persisted = self.events.append_batch(
                str(branch["run_id"]), action.branch_id, action_result.events,
                world_state=action_result.world.to_json(),
                observations=[item.model_dump(mode="json") for item in action_result.observations],
                command_record=record,
            )
            return record["persisted_result"] if record else {"accepted": True, "action_id": action.action_id, "branch_id": action.branch_id, "cursor": persisted[-1].branch_seq, "events": [event.model_dump(mode="json") for event in persisted]}
        except SandboxError as error:
            rejected = world.rejection_event(action, error.message)
            record = self._command_record(command_key, action.action_type, {"accepted": False, "action_id": action.action_id, "branch_id": action.branch_id, "error": {"error_code": error.error_code, "message": error.message}}) if command_key else None
            persisted = self.events.append_batch(str(branch["run_id"]), action.branch_id, [rejected], world_state=world.to_json(), command_record=record)
            return record["persisted_result"] if record else {"accepted": False, "action_id": action.action_id, "branch_id": action.branch_id, "cursor": persisted[-1].branch_seq, "error": {"error_code": error.error_code, "message": error.message}}

    def _checkpoint(self, branch_id: str, world: SimulationWorld, branch: Any, *, command_key: str | None = None) -> dict[str, object]:
        if branch["status"] not in {"Running", "Paused", "Ready", "Completed"}:
            raise ConflictError(f"cannot checkpoint branch from {branch['status']}")
        checkpoint_id = new_id("checkpoint")
        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            run_id=str(branch["run_id"]), branch_id=branch_id,
            branch_seq=int(branch["state_version"]), event_hash=str(branch["last_event_hash"]),
            sim_time_us=world.sim_time_us, state=world.to_json(), runtime_version=self.runtime_version,
        )
        drafts = [
            self._system_event("BranchQuiescing", branch_id, {}, sim_time_us=world.sim_time_us, tie="00-quiesce"),
            self._system_event("CheckpointCreated", branch_id, {"checkpoint_id": checkpoint_id, "cursor": checkpoint.branch_seq}, sim_time_us=world.sim_time_us, tie="01-checkpoint"),
        ]
        record = self._command_record(command_key, "save", {"branch_id": branch_id, "checkpoint_id": checkpoint_id, "status": "Checkpointed"}) if command_key else None
        persisted = self.events.append_batch(str(branch["run_id"]), branch_id, drafts, world_state=world.to_json(), branch_status="Checkpointed", checkpoint=checkpoint.model_dump(mode="json"), command_record=record)
        return record["persisted_result"] if record else {"branch_id": branch_id, "checkpoint_id": checkpoint_id, "status": "Checkpointed", "cursor": persisted[-1].branch_seq}

    def _branch(self, branch_id: str) -> Any:
        row = self.store.connection.execute("SELECT * FROM branches WHERE branch_id=?", (branch_id,)).fetchone()
        if row is None:
            raise NotFoundError("branch", branch_id)
        return row

    def _world(self, branch_id: str) -> SimulationWorld:
        row = self.store.connection.execute("SELECT world_json FROM branch_worlds WHERE branch_id=?", (branch_id,)).fetchone()
        if row is None:
            raise NotFoundError("branch world", branch_id)
        return SimulationWorld.from_json(json.loads(row["world_json"]))

    def _command_result(self, command_key: str) -> dict[str, object] | None:
        row = self.store.connection.execute("SELECT result_json FROM commands WHERE command_id=?", (command_key,)).fetchone()
        return json.loads(row["result_json"]) if row else None

    @staticmethod
    def _command_record(command_key: str | None, command_type: str, result: dict[str, object], *, include_events: bool = False) -> dict[str, object]:
        if command_key is None:
            raise ValueError("command_key is required for an idempotent command record")
        return {"command_id": command_key, "command_type": command_type, "result": result, "include_events": include_events}

    @staticmethod
    def _system_event(event_type: str, source_id: str, payload: dict[str, object], *, sim_time_us: int = 0, tie: str | None = None) -> EventDraft:
        return EventDraft(sim_time_us=sim_time_us, priority=10, tie_break_key=tie or f"system:{event_type}", event_type=event_type, source_id=source_id, payload=payload, visibility="analyst_only")

    @staticmethod
    def _observation_event(observation: Any, source_id: str) -> EventDraft:
        return EventDraft(sim_time_us=observation.sim_time_us, priority=50, tie_break_key=f"observation:{observation.agent_id}", event_type="ObservationCreated", source_id=source_id, target_ids=[observation.agent_id], payload={"agent_id": observation.agent_id, "observation_id": observation.observation_id}, observation_id=observation.observation_id, visibility="agent_private")
