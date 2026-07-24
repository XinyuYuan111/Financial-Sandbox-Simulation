from __future__ import annotations

import json
import asyncio
import hashlib
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sandbox.agents.strategies import FixtureStrategies
from sandbox.agents.planning import PlanningCoordinator, fixture_candidate
from sandbox.agents.runtime import AgentRuntime, RuntimeResult
from sandbox.contracts.action import ActionContract
from sandbox.contracts.agent import ActionReceipt, DecisionTrigger
from sandbox.contracts.event import EventDraft
from sandbox.contracts.scenario import ResolvedInitialState, ScenarioDraft
from sandbox.contracts.observation import ObservationPacket
from sandbox.contracts.planning import PlanningRequest, validate_planning_transition
from sandbox.contracts.planning import PlanningProviderRequest, PlanningResultCandidate
from sandbox.contracts.snapshot import Checkpoint
from sandbox.control.initialization import Initializer
from sandbox.control.branch_runner import BranchRunner
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
        self.agent_runtime = AgentRuntime()
        self.planning = PlanningCoordinator()
        self.branch_runner = BranchRunner(self)
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
        decision_records: list[dict[str, object]] = []
        planning_records: list[dict[str, object]] = []
        for observation in observations:
            definition = world.agent_definitions.get(observation.agent_id)
            state = world.agent_runtime_states.get(observation.agent_id)
            if definition is None or state is None:
                continue
            runtime_result = self.agent_runtime.decide(
                definition=definition,
                state=state,
                observation=observation,
            )
            if runtime_result is None:
                continue
            world.agent_runtime_states[observation.agent_id] = runtime_result.state
            if runtime_result.planning_request is not None:
                world.planning_requests[runtime_result.planning_request.request_id] = runtime_result.planning_request
                planning_records.append(runtime_result.planning_request.model_dump(mode="json"))
            decision_records.append({
                "decision": runtime_result.decision.model_dump(mode="json"),
                "outcome": runtime_result.outcome.model_dump(mode="json"),
            })
            drafts.extend(runtime_result.events)
        created_at = utc_now()
        self.events.append_batch(
            run_id, branch_id, drafts,
            world_state=world.to_json(),
            observations=[item.model_dump(mode="json") for item in observations],
            agent_decisions=decision_records,
            planning_requests=planning_records,
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

    def provider_profiles(self) -> list[dict[str, object]]:
        return self.initializer.llm_gateway.profiles()

    async def provider_preflight(self, provider_name: str) -> dict[str, object]:
        return await self.initializer.llm_gateway.preflight(provider_name)

    def agents(self, branch_id: str) -> list[dict[str, object]]:
        with self.store.locked():
            world = self._world(branch_id)
            return [self._agent_summary(world, agent_id) for agent_id in sorted(world.agents)]

    def agent_detail(self, branch_id: str, agent_id: str) -> dict[str, object]:
        with self.store.locked():
            world = self._world(branch_id)
            if agent_id not in world.agents:
                raise NotFoundError("agent", agent_id)
            return self._agent_summary(world, agent_id, include_private=True)

    def agent_decisions(self, branch_id: str, agent_id: str, *, limit: int = 200) -> list[dict[str, object]]:
        with self.store.locked():
            rows = self.store.connection.execute(
                "SELECT decision_json,outcome_json FROM agent_decisions WHERE branch_id=? AND agent_id=? ORDER BY sim_time_us DESC LIMIT ?",
                (branch_id, agent_id, limit),
            ).fetchall()
            return [{"decision": json.loads(row["decision_json"]), "outcome": json.loads(row["outcome_json"])} for row in rows]

    def agent_plans(self, branch_id: str, agent_id: str, *, limit: int = 200) -> list[dict[str, object]]:
        with self.store.locked():
            rows = self.store.connection.execute(
                "SELECT plan_json,active FROM strategy_plans WHERE branch_id=? AND agent_id=? ORDER BY strategy_revision DESC LIMIT ?",
                (branch_id, agent_id, limit),
            ).fetchall()
            return [{"plan": json.loads(row["plan_json"]), "active": bool(row["active"])} for row in rows]

    def agent_receipts(self, branch_id: str, agent_id: str, *, limit: int = 200) -> list[dict[str, object]]:
        with self.store.locked():
            rows = self.store.connection.execute(
                "SELECT receipt_json FROM action_receipts WHERE branch_id=? AND agent_id=? ORDER BY sim_time_us DESC LIMIT ?",
                (branch_id, agent_id, limit),
            ).fetchall()
            return [json.loads(row["receipt_json"]) for row in rows]

    @staticmethod
    def _agent_summary(world: SimulationWorld, agent_id: str, *, include_private: bool = False) -> dict[str, object]:
        state = world.agent_runtime_states.get(agent_id)
        definition = world.agent_definitions.get(agent_id)
        summary = world.agent_projection(agent_id)
        if include_private:
            summary["definition"] = definition.model_dump(mode="json") if definition else None
            summary["runtime_state"] = state.model_dump(mode="json") if state else None
        return summary

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
                    if agent_id in working.agents:
                        return self._apply_fixture_agent_action(
                            branch_id=branch_id,
                            run_id=run_id,
                            working=working,
                            state_version=int(branch["state_version"]),
                            agent_id=agent_id,
                            strategy=strategy,
                            client_command_id=client_command_id,
                            command_key=command_key,
                        )
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
            elif command_type == "run_for":
                if status != "Running":
                    raise ConflictError("run_for requires a Running branch")
                max_requests = int(payload.get("max_requests", 1))
                if not 1 <= max_requests <= 100:
                    raise ValidationError("run_for max_requests must be within 1..100")
                run_result = asyncio.run(self.branch_runner.run_for(branch_id, max_requests=max_requests))
                current_branch = self._branch(branch_id)
                current_world = self._world(branch_id)
                record = self._command_record(command_key, command_type, {"branch_id": branch_id, **run_result})
                persisted = self.events.append_batch(
                    run_id,
                    branch_id,
                    [self._system_event("ControlInterventionApplied", branch_id, {"kind": "run_for", **run_result}, sim_time_us=current_world.sim_time_us)],
                    world_state=current_world.to_json(),
                    command_record=record,
                    expected_branch_version=int(current_branch["state_version"]),
                )
                result = record["persisted_result"]
            else:
                raise ValidationError(f"unsupported command '{command_type}'")
            return result

    async def _run_planning_requests(self, branch_id: str, *, max_requests: int) -> dict[str, object]:
        processed = 0
        applied = 0
        failed = 0
        while processed < max_requests:
            branch = self._branch(branch_id)
            world = self._world(branch_id)
            candidates = sorted(
                (request for request in world.planning_requests.values() if request.state in {"Queued", "Running"}),
                key=lambda item: (item.activation_time_us, item.agent_id, item.request_id),
            )
            if not candidates:
                break
            request = candidates[0]
            state = world.agent_runtime_states[request.agent_id]
            definition = world.agent_definitions[request.agent_id]
            observation = self._latest_observation(branch_id, request.agent_id)
            if request.state == "Queued":
                running = request.model_copy(update={"state": "Running"})
                validate_planning_transition(request, running)
                world.planning_requests[request.request_id] = running
                self.events.append_batch(
                    str(branch["run_id"]),
                    branch_id,
                    [EventDraft(
                        sim_time_us=world.sim_time_us,
                        priority=58,
                        tie_break_key=f"planning:{request.request_id}:running",
                        event_type="PlanningRequestStateChanged",
                        source_id=request.agent_id,
                        target_ids=[request.agent_id],
                        payload={"request_id": request.request_id, "from": "Queued", "to": "Running", "activation_time_us": request.activation_time_us},
                        visibility="agent_private",
                    )],
                    world_state=world.to_json(),
                    planning_requests=[running.model_dump(mode="json")],
                    expected_branch_version=int(branch["state_version"]),
                )
                request = running
                branch = self._branch(branch_id)
            provider_name = definition.planner_profile_id.split(".", 1)[0]
            context = {
                "persona": definition.base_persona.model_dump(mode="json"),
                "observation": observation.model_dump(mode="json"),
                "cognition": {
                    "memory": [item.model_dump(mode="json") for item in state.memory_entries if item.accessible],
                    "beliefs": [item.model_dump(mode="json") for item in state.beliefs],
                    "revisions": state.component_revisions,
                },
                "account_snapshot": observation.account_snapshot.model_dump(mode="json") if observation.account_snapshot else {},
                "current_strategy": world.strategy_plans[state.active_plan_id].model_dump(mode="json") if state.active_plan_id in world.strategy_plans else None,
            }
            context_hash = "sha256:" + hashlib.sha256(canonical_json(context).encode()).hexdigest()
            provider_request = PlanningProviderRequest(
                request_id=request.request_id,
                agent_id=request.agent_id,
                context_hash=context_hash,
                planner_instructions="Return one complete bounded candidate StrategyPlan.",
                **context,
            )

            def persist_raw(record: Any) -> None:
                current = self._branch(branch_id)
                self.events.append_batch(
                    str(current["run_id"]),
                    branch_id,
                    [],
                    llm_records=[record.model_dump(mode="json")],
                    expected_branch_version=int(current["state_version"]),
                )

            try:
                candidate = await self.initializer.llm_gateway.plan(provider_name, provider_request, record_raw=persist_raw)
                self._complete_planning_candidate(branch_id, request.request_id, candidate)
                applied += 1
            except SandboxError as error:
                self._fail_planning_request(branch_id, request.request_id, error.error_code)
                failed += 1
            processed += 1
        return {"processed_requests": processed, "applied_requests": applied, "failed_requests": failed}

    def _complete_planning_candidate(
        self,
        branch_id: str,
        request_id: str,
        candidate: PlanningResultCandidate,
    ) -> None:
        branch = self._branch(branch_id)
        world = self._world(branch_id)
        request = world.planning_requests[request_id]
        state = world.agent_runtime_states[request.agent_id]
        definition = world.agent_definitions[request.agent_id]
        ready = request.model_copy(update={"state": "Ready"})
        validate_planning_transition(request, ready)
        world.sim_time_us = max(world.sim_time_us, request.activation_time_us)
        observations = world.create_observations(
            branch_id,
            int(branch["state_version"]) + 1,
            recipient_ids=[request.agent_id],
            triggers_by_agent={request.agent_id: [DecisionTrigger(
                type="planning_result",
                semantic_key=f"planning_result:{request.request_id}",
                source_event_ids=[],
                severity=80,
                first_sim_time_us=world.sim_time_us,
                last_sim_time_us=world.sim_time_us,
            )]},
        )
        observation = observations[0]
        plan = self.planning.activate_candidate(
            definition=definition,
            state=state,
            observation=observation,
            request=ready,
            candidate=candidate,
        )
        runtime_result = self.agent_runtime.decide(
            definition=definition,
            state=state,
            observation=observation,
            activate_plan=plan,
        )
        if runtime_result is None:
            raise ConflictError("planning activation observation was already processed", error_code="DUPLICATE_DECISION")
        terminal = ready.model_copy(update={"state": "Terminal", "terminal_outcome": "applied", "result_plan_id": plan.plan_id})
        validate_planning_transition(ready, terminal)
        next_budget = runtime_result.state.cognitive_budget_state.model_copy(update={
            "plans_reserved": max(0, runtime_result.state.cognitive_budget_state.plans_reserved - 1)
        })
        world.agent_runtime_states[request.agent_id] = runtime_result.state.model_copy(update={"cognitive_budget_state": next_budget})
        world.planning_requests[request_id] = terminal
        world.strategy_plans[plan.plan_id] = plan
        events = [
            self._observation_event(observation, str(branch["run_id"])),
            EventDraft(sim_time_us=world.sim_time_us, priority=59, tie_break_key=f"planning:{request_id}:ready", event_type="PlanningRequestStateChanged", source_id=request.agent_id, target_ids=[request.agent_id], payload={"request_id": request_id, "from": "Running", "to": "Ready", "activation_time_us": request.activation_time_us}, visibility="agent_private"),
            *runtime_result.events,
            EventDraft(sim_time_us=world.sim_time_us, priority=63, tie_break_key=f"planning:{request_id}:terminal", event_type="PlanningRequestStateChanged", source_id=request.agent_id, target_ids=[request.agent_id], payload={"request_id": request_id, "from": "Ready", "to": "Terminal", "terminal_outcome": "applied", "activation_time_us": request.activation_time_us}, visibility="agent_private"),
        ]
        receipts = []
        action_observations: list[ObservationPacket] = []
        for proposal in runtime_result.action_proposals:
            action = ActionContract(
                action_id=new_id("act"),
                agent_id=request.agent_id,
                branch_id=branch_id,
                submitted_sim_time_us=world.sim_time_us,
                action_type=proposal.action_type,
                payload=proposal.payload,
                expected_execution_time_us=proposal.expected_execution_time_us,
                validity_window_us=proposal.validity_window_us,
                parent_observation_id=observation.observation_id,
                client_command_id=deterministic_id("provider-action", request_id, proposal.proposal_id),
            )
            action_result = world.apply_action(
                action,
                world_version=int(branch["state_version"]) + len(events),
                proposal_id=proposal.proposal_id,
                decision_id=runtime_result.decision.decision_id,
            )
            world = action_result.world
            events.extend(action_result.events)
            action_observations.extend(action_result.observations)
            receipts.extend(action_result.receipts)
        self.events.append_batch(
            str(branch["run_id"]),
            branch_id,
            events,
            world_state=world.to_json(),
            observations=[item.model_dump(mode="json") for item in [*observations, *action_observations]],
            agent_decisions=[{"decision": runtime_result.decision.model_dump(mode="json"), "outcome": runtime_result.outcome.model_dump(mode="json")}],
            planning_requests=[terminal.model_dump(mode="json")],
            strategy_plans=[{"plan": plan.model_dump(mode="json"), "active": True}],
            action_receipts=[item.model_dump(mode="json") for item in receipts],
            expected_branch_version=int(branch["state_version"]),
        )

    def _fail_planning_request(self, branch_id: str, request_id: str, error_code: str) -> None:
        branch = self._branch(branch_id)
        world = self._world(branch_id)
        request = world.planning_requests[request_id]
        terminal = request.model_copy(update={"state": "Terminal", "terminal_outcome": "failed", "error_code": error_code})
        validate_planning_transition(request, terminal)
        state = world.agent_runtime_states[request.agent_id]
        budget = state.cognitive_budget_state.model_copy(update={"plans_reserved": max(0, state.cognitive_budget_state.plans_reserved - 1)})
        world.agent_runtime_states[request.agent_id] = state.model_copy(update={"planning_request_id": None, "cognitive_budget_state": budget})
        world.planning_requests[request_id] = terminal
        self.events.append_batch(
            str(branch["run_id"]),
            branch_id,
            [EventDraft(sim_time_us=world.sim_time_us, priority=63, tie_break_key=f"planning:{request_id}:failed", event_type="PlanningRequestStateChanged", source_id=request.agent_id, target_ids=[request.agent_id], payload={"request_id": request_id, "from": request.state, "to": "Terminal", "terminal_outcome": "failed", "reason": error_code}, visibility="agent_private")],
            world_state=world.to_json(),
            planning_requests=[terminal.model_dump(mode="json")],
            expected_branch_version=int(branch["state_version"]),
        )

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
        remapped_requests: dict[str, PlanningRequest] = {}
        request_id_map: dict[str, str] = {}
        for request in world.planning_requests.values():
            if request.state == "Terminal":
                remapped_requests[request.request_id] = request
                continue
            next_id = deterministic_id("request", new_branch_id, request.agent_id, request.request_id)
            request_id_map[request.request_id] = next_id
            remapped_requests[next_id] = request.model_copy(update={"request_id": next_id, "branch_id": new_branch_id})
        world.planning_requests = remapped_requests
        for agent_id, state in list(world.agent_runtime_states.items()):
            if state.planning_request_id in request_id_map:
                world.agent_runtime_states[agent_id] = state.model_copy(update={"planning_request_id": request_id_map[state.planning_request_id]})
        observations = world.create_observations(new_branch_id, 1)
        drafts = [self._system_event("BranchCreated", new_branch_id, {"parent_branch_id": branch_id, "fork_checkpoint_id": checkpoint_id}, sim_time_us=checkpoint.sim_time_us)]
        drafts.extend(self._observation_event(observation, new_branch_id) for observation in observations)
        record = self._command_record(command_key, "fork", {"branch_id": new_branch_id, "parent_branch_id": branch_id, "checkpoint_id": checkpoint_id, "status": "Ready"})
        self.events.append_batch(
            checkpoint.run_id, new_branch_id, drafts,
            world_state=world.to_json(), observations=[item.model_dump(mode="json") for item in observations], branch_status="Ready", command_record=record,
            planning_requests=[request.model_dump(mode="json") for request in remapped_requests.values() if request.branch_id == new_branch_id],
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

    def _apply_fixture_agent_action(
        self,
        *,
        branch_id: str,
        run_id: str,
        working: SimulationWorld,
        state_version: int,
        agent_id: str,
        strategy: Any,
        client_command_id: str,
        command_key: str,
    ) -> dict[str, object]:
        definition = working.agent_definitions[agent_id]
        state = working.agent_runtime_states[agent_id]
        decision_records: list[dict[str, object]] = []
        planning_records: list[dict[str, object]] = []
        extra_events: list[EventDraft] = []
        pre_observations: list[ObservationPacket] = []

        request = working.planning_requests.get(state.planning_request_id or "")
        planning_observation = self._latest_observation(branch_id, agent_id)
        if request is None:
            replan_result = self.agent_runtime.decide(
                definition=definition,
                state=state,
                observation=planning_observation,
                active_plan=None,
            )
            if replan_result is None or replan_result.planning_request is None:
                raise ConflictError("fixture step could not create a planning request", error_code="PLANNING_REQUEST_NOT_CREATED")
            state = replan_result.state
            request = replan_result.planning_request
            working.agent_runtime_states[agent_id] = state
            working.planning_requests[request.request_id] = request
            decision_records.append({"decision": replan_result.decision.model_dump(mode="json"), "outcome": replan_result.outcome.model_dump(mode="json")})
            planning_records.append(request.model_dump(mode="json"))
            extra_events.extend(replan_result.events)

        running = request.model_copy(update={"state": "Running"})
        validate_planning_transition(request, running)
        ready = running.model_copy(update={"state": "Ready"})
        validate_planning_transition(running, ready)
        activation_time = max(working.sim_time_us, ready.activation_time_us)
        working.sim_time_us = activation_time
        activation_observations = working.create_observations(
            branch_id,
            state_version + len(extra_events) + 1,
            recipient_ids=[agent_id],
            triggers_by_agent={
                agent_id: [DecisionTrigger(
                    type="planning_result",
                    semantic_key=f"planning_result:{ready.request_id}",
                    source_event_ids=[],
                    severity=80,
                    first_sim_time_us=activation_time,
                    last_sim_time_us=activation_time,
                )]
            },
        )
        activation_observation = activation_observations[0]
        pre_observations.extend(activation_observations)
        extra_events.extend(self._observation_event(item, run_id) for item in activation_observations)
        candidate = fixture_candidate(
            action_type=strategy.action_type,
            payload=strategy.payload,
            observation=planning_observation,
            strategy_revision=state.active_strategy_revision,
        )
        plan = self.planning.activate_candidate(
            definition=definition,
            state=state,
            observation=activation_observation,
            request=ready,
            candidate=candidate,
        )
        activation_result = self.agent_runtime.decide(
            definition=definition,
            state=state,
            observation=activation_observation,
            activate_plan=plan,
        )
        if activation_result is None or not activation_result.action_proposals:
            raise ConflictError("fixture plan produced no action proposal", error_code="FIXTURE_PLAN_NO_ACTION")
        terminal = ready.model_copy(update={"state": "Terminal", "terminal_outcome": "applied", "result_plan_id": plan.plan_id})
        validate_planning_transition(ready, terminal)
        budget = activation_result.state.cognitive_budget_state
        next_budget = budget.model_copy(update={"plans_reserved": max(0, budget.plans_reserved - 1)})
        next_state = activation_result.state.model_copy(update={"cognitive_budget_state": next_budget})
        working.agent_runtime_states[agent_id] = next_state
        working.planning_requests[terminal.request_id] = terminal
        working.strategy_plans[plan.plan_id] = plan
        decision_records.append({"decision": activation_result.decision.model_dump(mode="json"), "outcome": activation_result.outcome.model_dump(mode="json")})
        planning_records.append(terminal.model_dump(mode="json"))
        extra_events.extend([
            EventDraft(sim_time_us=activation_time, priority=58, tie_break_key=f"planning:{request.request_id}:running", event_type="PlanningRequestStateChanged", source_id=agent_id, target_ids=[agent_id], payload={"request_id": request.request_id, "from": "Queued", "to": "Running", "activation_time_us": request.activation_time_us}, visibility="agent_private"),
            EventDraft(sim_time_us=activation_time, priority=59, tie_break_key=f"planning:{request.request_id}:ready", event_type="PlanningRequestStateChanged", source_id=agent_id, target_ids=[agent_id], payload={"request_id": request.request_id, "from": "Running", "to": "Ready", "activation_time_us": request.activation_time_us}, visibility="agent_private"),
            *activation_result.events,
            EventDraft(sim_time_us=activation_time, priority=63, tie_break_key=f"planning:{request.request_id}:terminal", event_type="PlanningRequestStateChanged", source_id=agent_id, target_ids=[agent_id], payload={"request_id": request.request_id, "from": "Ready", "to": "Terminal", "terminal_outcome": "applied", "activation_time_us": request.activation_time_us}, visibility="agent_private"),
        ])
        proposal = activation_result.action_proposals[0]
        action = ActionContract(
            action_id=new_id("act"),
            agent_id=agent_id,
            branch_id=branch_id,
            submitted_sim_time_us=activation_time,
            action_type=proposal.action_type,
            payload=proposal.payload,
            expected_execution_time_us=proposal.expected_execution_time_us,
            validity_window_us=proposal.validity_window_us,
            parent_observation_id=activation_observation.observation_id,
            client_command_id=client_command_id,
        )
        return self._apply_action(
            action,
            working,
            state_version,
            command_key=command_key,
            proposal_id=proposal.proposal_id,
            decision_id=activation_result.decision.decision_id,
            extra_events=extra_events,
            pre_observations=pre_observations,
            decision_records=decision_records,
            planning_records=planning_records,
            strategy_records=[{"plan": plan.model_dump(mode="json"), "active": True}],
        )

    def _latest_observation(self, branch_id: str, agent_id: str) -> ObservationPacket:
        row = self.store.connection.execute(
            "SELECT observation_json FROM observations WHERE branch_id=? AND agent_id=? ORDER BY rowid DESC LIMIT 1",
            (branch_id, agent_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("agent observation", agent_id)
        return ObservationPacket.model_validate(json.loads(row["observation_json"]))

    def _apply_action(
        self,
        action: ActionContract,
        world: SimulationWorld,
        state_version: int,
        *,
        command_key: str | None = None,
        proposal_id: str | None = None,
        decision_id: str | None = None,
        extra_events: list[EventDraft] | None = None,
        pre_observations: list[ObservationPacket] | None = None,
        decision_records: list[dict[str, object]] | None = None,
        planning_records: list[dict[str, object]] | None = None,
        strategy_records: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        branch = self._branch(action.branch_id)
        try:
            action_result: ActionResult = world.apply_action(
                action,
                world_version=state_version,
                proposal_id=proposal_id,
                decision_id=decision_id,
            )
            all_events = [*(extra_events or []), *action_result.events]
            all_observations = [*(pre_observations or []), *action_result.observations]
            record = self._command_record(command_key, action.action_type, {"accepted": True, "action_id": action.action_id, "branch_id": action.branch_id}, include_events=True) if command_key else None
            persisted = self.events.append_batch(
                str(branch["run_id"]), action.branch_id, all_events,
                world_state=action_result.world.to_json(),
                observations=[item.model_dump(mode="json") for item in all_observations],
                action_receipts=[item.model_dump(mode="json") for item in action_result.receipts],
                agent_decisions=decision_records or [],
                planning_requests=planning_records or [],
                strategy_plans=strategy_records or [],
                command_record=record,
                expected_branch_version=state_version,
            )
            return record["persisted_result"] if record else {"accepted": True, "action_id": action.action_id, "branch_id": action.branch_id, "cursor": persisted[-1].branch_seq, "events": [event.model_dump(mode="json") for event in persisted]}
        except SandboxError as error:
            working = world.clone()
            rejected = working.rejection_event(action, error.message)
            receipt = ActionReceipt(
                receipt_id=new_id("receipt"),
                action_id=action.action_id,
                proposal_id=proposal_id,
                decision_id=decision_id,
                agent_id=action.agent_id,
                branch_id=action.branch_id,
                outcome="rejected",
                reason_code=error.error_code.lower(),
                submitted_sim_time_us=action.submitted_sim_time_us,
                scheduled_sim_time_us=max(action.submitted_sim_time_us, action.expected_execution_time_us),
                resolved_sim_time_us=max(working.sim_time_us, action.submitted_sim_time_us),
                result_state_refs={"portfolio_revision": state_version},
            )
            working.action_receipts.append(receipt)
            observations = []
            if action.agent_id in working.agents:
                observations = working.create_observations(
                    action.branch_id,
                    state_version + 1,
                    recipient_ids=[action.agent_id],
                    triggers_by_agent={
                        action.agent_id: [DecisionTrigger(
                            type="own_action_outcome",
                            semantic_key=f"receipt:{action.action_id}",
                            source_event_ids=[],
                            severity=80,
                            first_sim_time_us=working.sim_time_us,
                            last_sim_time_us=working.sim_time_us,
                        )]
                    },
                )
            drafts = [*(extra_events or []), rejected]
            drafts.extend(self._observation_event(observation, str(branch["run_id"])) for observation in observations)
            all_observations = [*(pre_observations or []), *observations]
            record = self._command_record(command_key, action.action_type, {"accepted": False, "action_id": action.action_id, "branch_id": action.branch_id, "error": {"error_code": error.error_code, "message": error.message}}) if command_key else None
            persisted = self.events.append_batch(
                str(branch["run_id"]), action.branch_id, drafts,
                world_state=working.to_json(),
                observations=[item.model_dump(mode="json") for item in all_observations],
                action_receipts=[receipt.model_dump(mode="json")],
                agent_decisions=decision_records or [],
                planning_requests=planning_records or [],
                strategy_plans=strategy_records or [],
                command_record=record,
                expected_branch_version=state_version,
            )
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
