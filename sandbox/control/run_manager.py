from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

from sandbox.agents.strategies import FixtureStrategies
from sandbox.agents.planning import PlanningCoordinator, fixture_candidate
from sandbox.agents.runtime import AgentRuntime
from sandbox.contracts.action import ActionContract
from sandbox.contracts.agent import ActionReceipt, DecisionRationale, DecisionTrigger
from sandbox.contracts.event import EventDraft
from sandbox.contracts.intervention import (
    DirectorAccessScope,
    DirectorProviderRequest,
    DirectorRecord,
    InterventionPlan,
    InterventionPlanDraftInput,
    PrivateStateRef,
)
from sandbox.contracts.scenario import ResolvedInitialState, ScenarioDraft
from sandbox.contracts.observation import ObservationPacket
from sandbox.contracts.planning import PlanningRequest, validate_planning_transition
from sandbox.contracts.planning import PlanningProviderRequest, PlanningResultCandidate
from sandbox.contracts.snapshot import Checkpoint
from sandbox.control.initialization import Initializer
from sandbox.control.branch_runner import BranchRunner
from sandbox.control.scenario_director import ScenarioDirector
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
        self.scenario_director = ScenarioDirector()
        self._locks: defaultdict[str, threading.RLock] = defaultdict(threading.RLock)
        self._runner_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        self._runner_threads: dict[str, threading.Thread] = {}
        self._runner_cancel: dict[str, threading.Event] = {}

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

    def agents(self, branch_id: str, *, cursor: int | None = None) -> list[dict[str, object]]:
        with self.store.locked():
            world = self._world(branch_id)
            if cursor is None:
                return [self._agent_summary(world, agent_id) for agent_id in sorted(world.agents)]
            return [self._historical_agent_summary(branch_id, world, agent_id, cursor) for agent_id in sorted(world.agents)]

    def agent_detail(self, branch_id: str, agent_id: str, *, cursor: int | None = None) -> dict[str, object]:
        with self.store.locked():
            world = self._world(branch_id)
            if agent_id not in world.agents:
                raise NotFoundError("agent", agent_id)
            if cursor is not None:
                return self._historical_agent_summary(branch_id, world, agent_id, cursor, include_private=True)
            return self._agent_summary(world, agent_id, include_private=True)

    def agent_decisions(self, branch_id: str, agent_id: str, *, cursor: int | None = None, limit: int = 200) -> list[dict[str, object]]:
        with self.store.locked():
            rows = self.store.connection.execute(
                "SELECT decision_json,outcome_json FROM agent_decisions WHERE branch_id=? AND agent_id=? ORDER BY sim_time_us DESC LIMIT ?",
                (branch_id, agent_id, limit),
            ).fetchall()
            records = [{"decision": json.loads(row["decision_json"]), "outcome": json.loads(row["outcome_json"])} for row in rows]
            if cursor is None:
                return records
            versions = self._observation_versions(branch_id)
            return [record for record in records if versions.get(str(record["decision"]["observation_id"]), cursor + 1) <= cursor]

    def agent_plans(self, branch_id: str, agent_id: str, *, cursor: int | None = None, limit: int = 200) -> list[dict[str, object]]:
        with self.store.locked():
            rows = self.store.connection.execute(
                "SELECT plan_json,active FROM strategy_plans WHERE branch_id=? AND agent_id=? ORDER BY strategy_revision DESC LIMIT ?",
                (branch_id, agent_id, limit),
            ).fetchall()
            records = [{"plan": json.loads(row["plan_json"]), "active": bool(row["active"])} for row in rows]
            if cursor is None:
                return records
            versions = self._observation_versions(branch_id)
            return [record for record in records if versions.get(str(record["plan"]["source_observation_id"]), cursor + 1) <= cursor]

    def agent_receipts(self, branch_id: str, agent_id: str, *, cursor: int | None = None, limit: int = 200) -> list[dict[str, object]]:
        with self.store.locked():
            rows = self.store.connection.execute(
                "SELECT receipt_json FROM action_receipts WHERE branch_id=? AND agent_id=? ORDER BY sim_time_us DESC LIMIT ?",
                (branch_id, agent_id, limit),
            ).fetchall()
            records = [json.loads(row["receipt_json"]) for row in rows]
            if cursor is None:
                return records
            return [
                record for record in records
                if int(record.get("result_state_refs", {}).get("portfolio_revision", cursor + 1)) <= cursor
            ]

    def _observation_versions(self, branch_id: str) -> dict[str, int]:
        rows = self.store.connection.execute(
            "SELECT observation_id,observation_json FROM observations WHERE branch_id=?",
            (branch_id,),
        ).fetchall()
        return {
            str(row["observation_id"]): int(json.loads(row["observation_json"])["world_version"])
            for row in rows
        }

    def _historical_agent_summary(
        self,
        branch_id: str,
        world: SimulationWorld,
        agent_id: str,
        cursor: int,
        *,
        include_private: bool = False,
    ) -> dict[str, object]:
        row = self.store.connection.execute(
            "SELECT observation_json FROM observations WHERE branch_id=? AND agent_id=? ORDER BY sim_time_us DESC,rowid DESC",
            (branch_id, agent_id),
        ).fetchall()
        observation = next(
            (
                json.loads(item["observation_json"])
                for item in row
                if int(json.loads(item["observation_json"])["world_version"]) <= cursor
            ),
            None,
        )
        if observation is None:
            raise ValidationError(f"no saved Agent observation exists at or before cursor {cursor}")
        summary = self._agent_summary(world, agent_id, include_private=include_private)
        summary["portfolio"] = observation["portfolio_view"]
        summary["planning_request_id"] = None
        decisions = self.agent_decisions(branch_id, agent_id, cursor=cursor, limit=1)
        summary["agent_revision"] = int(decisions[0]["outcome"]["resulting_agent_revision"]) if decisions else 0
        if include_private:
            summary["runtime_state"] = None
        summary["historical_cursor"] = cursor
        return summary

    def intervention_plans(self, branch_id: str) -> list[dict[str, object]]:
        with self.store.locked():
            self._branch(branch_id)
            rows = self.store.connection.execute(
                "SELECT plan_json FROM intervention_plans WHERE branch_id=? ORDER BY created_branch_seq,plan_id",
                (branch_id,),
            ).fetchall()
            return [json.loads(row["plan_json"]) for row in rows]

    def intervention_templates(self) -> list[dict[str, object]]:
        return self.scenario_director.templates()

    def intervention_plan(self, branch_id: str, plan_id: str) -> dict[str, object]:
        with self.store.locked():
            return self._intervention_plan(branch_id, plan_id).model_dump(mode="json")

    def create_intervention_plan(
        self,
        branch_id: str,
        client_command_id: str,
        draft: InterventionPlanDraftInput,
    ) -> dict[str, object]:
        with self.store.locked():
            command_key = deterministic_id("cmd", branch_id, client_command_id)
            existing = self._command_result(command_key)
            if existing is not None:
                return existing
            with self._locks[branch_id]:
                branch = self._branch(branch_id)
                if branch["status"] != "Paused":
                    raise ConflictError(
                        "Scenario Director only accepts commands on a Paused branch",
                        error_code="BRANCH_NOT_PAUSED",
                    )
                world = self._world(branch_id)
                plan = self.scenario_director.draft(
                    branch_id=branch_id,
                    created_command_id=command_key,
                    branch_seq=int(branch["state_version"]),
                    world=world,
                    request=draft,
                )
                record = self._command_record(
                    command_key,
                    "draft_intervention_plan",
                    {"branch_id": branch_id, "plan_id": plan.plan_id, "status": plan.status, "plan": plan.model_dump(mode="json")},
                )
                self.events.append_batch(
                    str(branch["run_id"]),
                    branch_id,
                    [],
                    intervention_plans=[plan.model_dump(mode="json")],
                    command_record=record,
                    expected_branch_version=int(branch["state_version"]),
                )
                return record["persisted_result"]

    async def interpret_intervention_plan(
        self,
        branch_id: str,
        client_command_id: str,
        *,
        user_intent: str,
        requested_effective_time_us: int,
        provider_name: str,
        access_scope: DirectorAccessScope,
        private_read_refs: list[PrivateStateRef],
    ) -> dict[str, object]:
        command_key = deterministic_id("cmd", branch_id, client_command_id)
        self.scenario_director.reject_secret_text(user_intent)
        with self.store.locked():
            existing = self._command_result(command_key)
            if existing is not None:
                return existing
            branch = self._branch(branch_id)
            if branch["status"] != "Paused":
                raise ConflictError(
                    "Scenario Director only accepts commands on a Paused branch",
                    error_code="BRANCH_NOT_PAUSED",
                )
            world = self._world(branch_id)
            if requested_effective_time_us < world.sim_time_us:
                raise ValidationError("requested intervention time cannot target committed history")
            base_branch_seq = int(branch["state_version"])
            base_world_revision = world.world_revision
            self.scenario_director.authorize_private_reads(world, access_scope, private_read_refs)
            world_context, private_context = self.scenario_director.provider_context(world, private_read_refs)
            context = {
                "user_intent": user_intent,
                "requested_effective_time_us": requested_effective_time_us,
                "world_context": world_context,
                "private_context": private_context,
            }
            context_hash = "sha256:" + hashlib.sha256(canonical_json(context).encode()).hexdigest()
            provider_request = DirectorProviderRequest(
                request_id=command_key,
                branch_id=branch_id,
                context_hash=context_hash,
                user_intent=user_intent,
                current_sim_time_us=world.sim_time_us,
                requested_effective_time_us=requested_effective_time_us,
                world_context=world_context,
                private_context=private_context,
                allowed_effect_types=[
                    "publish_information",
                    "transfer_asset",
                    "set_market_status",
                    "set_account_freeze",
                    "set_wallet_access",
                    "create_world_entity",
                    "create_relationship",
                ],
            )
        llm_records: list[Any] = []

        def persist_raw(record: Any) -> None:
            llm_records.append(record)
            with self.store.locked():
                current = self._branch(branch_id)
                self.events.append_batch(
                    str(current["run_id"]), branch_id, [],
                    llm_records=[record.model_dump(mode="json")],
                    expected_branch_version=int(current["state_version"]),
                )

        candidate = await self.initializer.llm_gateway.direct_intervention(
            provider_name,
            provider_request,
            record_raw=persist_raw,
        )
        with self.store.locked():
            branch = self._branch(branch_id)
            if branch["status"] != "Paused":
                raise ConflictError(
                    "branch resumed before the Scenario Director result was ready",
                    error_code="DIRECTOR_RESULT_DEFERRED",
                )
            world = self._world(branch_id)
            if int(branch["state_version"]) != base_branch_seq or world.world_revision != base_world_revision:
                raise ConflictError(
                    "World changed while the Scenario Director was interpreting the command",
                    error_code="DIRECTOR_CONTEXT_STALE",
                )
            typed_draft = InterventionPlanDraftInput(
                user_intent=user_intent,
                access_scope=access_scope,
                private_read_refs=private_read_refs,
                stages=candidate.stages,
            )
            plan = self.scenario_director.draft(
                branch_id=branch_id,
                created_command_id=command_key,
                branch_seq=base_branch_seq,
                world=world,
                request=typed_draft,
            )
            profile = next(
                (item for item in self.provider_profiles() if item.get("provider") == provider_name),
                {"provider": provider_name},
            )
            plan = plan.model_copy(update={
                "director_record": DirectorRecord(
                    director_kind="openai.v0.1",
                    submitted_intent=user_intent,
                    typed_output=[stage.model_dump(mode="json") for stage in candidate.stages],
                    provider=provider_name,
                    model=str(profile.get("model", "")) or None,
                    context_hash=context_hash,
                    call_ids=[record.call_id for record in llm_records],
                    rationale=candidate.rationale,
                )
            })
            record = self._command_record(
                command_key,
                "interpret_intervention_plan",
                {"branch_id": branch_id, "plan_id": plan.plan_id, "status": plan.status, "plan": plan.model_dump(mode="json")},
            )
            self.events.append_batch(
                str(branch["run_id"]), branch_id, [],
                intervention_plans=[plan.model_dump(mode="json")],
                command_record=record,
                expected_branch_version=int(branch["state_version"]),
            )
            return record["persisted_result"]

    def confirm_intervention_plan(
        self,
        branch_id: str,
        plan_id: str,
        client_command_id: str,
    ) -> dict[str, object]:
        with self.store.locked():
            command_key = deterministic_id("cmd", branch_id, client_command_id)
            existing = self._command_result(command_key)
            if existing is not None:
                return existing
            with self._locks[branch_id]:
                branch = self._branch(branch_id)
                if branch["status"] != "Paused":
                    raise ConflictError(
                        "intervention plans can only be confirmed on a Paused branch",
                        error_code="BRANCH_NOT_PAUSED",
                    )
                plan = self._intervention_plan(branch_id, plan_id)
                if plan.status != "draft":
                    raise ConflictError(f"cannot confirm intervention plan from {plan.status}")
                world = self._world(branch_id)
                self._revalidate_intervention_plan(plan, world, int(branch["state_version"]))
                confirmed = plan.model_copy(update={
                    "status": "confirmed",
                    "base_world_revision": world.world_revision,
                    "plan_revision": plan.plan_revision + (1 if plan.base_world_revision != world.world_revision else 0),
                    "confirmed_command_id": command_key,
                })
                working = world
                stages = list(confirmed.stages)
                stage_events: list[EventDraft] = []
                stage_observations: list[ObservationPacket] = []
                applied = 0
                for index, stage in enumerate(stages):
                    if stage.status != "pending" or stage.effective_sim_time_us != working.sim_time_us:
                        continue
                    stage_result = working.apply_intervention_stage(
                        stage,
                        branch_id=branch_id,
                        plan_id=confirmed.plan_id,
                        world_version=int(branch["state_version"]) + len(stage_events),
                    )
                    working = stage_result.world
                    stage_events.extend(stage_result.events)
                    stage_events.append(EventDraft(
                        sim_time_us=stage.effective_sim_time_us,
                        priority=49,
                        tie_break_key=f"intervention:{confirmed.plan_id}:{stage.stage_id}:stage-applied",
                        event_type="InterventionStageApplied",
                        source_id="scenario_director",
                        payload={"plan_id": confirmed.plan_id, "stage_id": stage.stage_id},
                        correlation_id=confirmed.plan_id,
                        visibility="analyst_only",
                    ))
                    stage_observations.extend(stage_result.observations)
                    stages[index] = stage.model_copy(update={"status": "applied"})
                    applied += 1
                next_status = "completed" if all(stage.status != "pending" for stage in stages) else "confirmed"
                confirmed = confirmed.model_copy(update={"status": next_status, "stages": stages})
                record = self._command_record(
                    command_key,
                    "confirm_intervention_plan",
                    {
                        "branch_id": branch_id,
                        "plan_id": plan_id,
                        "status": next_status,
                        "applied_stages": applied,
                        "failed_stages": 0,
                        "plan": confirmed.model_dump(mode="json"),
                    },
                )
                self.events.append_batch(
                    str(branch["run_id"]),
                    branch_id,
                    stage_events,
                    world_state=working.to_json() if applied else None,
                    observations=[item.model_dump(mode="json") for item in stage_observations],
                    intervention_plans=[confirmed.model_dump(mode="json")],
                    command_record=record,
                    expected_branch_version=int(branch["state_version"]),
                )
                return record["persisted_result"]

    def reject_intervention_plan(
        self,
        branch_id: str,
        plan_id: str,
        client_command_id: str,
    ) -> dict[str, object]:
        with self.store.locked():
            command_key = deterministic_id("cmd", branch_id, client_command_id)
            existing = self._command_result(command_key)
            if existing is not None:
                return existing
            with self._locks[branch_id]:
                branch = self._branch(branch_id)
                if branch["status"] != "Paused":
                    raise ConflictError(
                        "intervention plans can only be rejected on a Paused branch",
                        error_code="BRANCH_NOT_PAUSED",
                    )
                plan = self._intervention_plan(branch_id, plan_id)
                if plan.status != "draft":
                    raise ConflictError(f"cannot reject intervention plan from {plan.status}")
                rejected = plan.model_copy(update={"status": "rejected", "terminal_command_id": command_key})
                record = self._command_record(
                    command_key,
                    "reject_intervention_plan",
                    {"branch_id": branch_id, "plan_id": plan_id, "status": "rejected"},
                )
                self.events.append_batch(
                    str(branch["run_id"]), branch_id, [],
                    intervention_plans=[rejected.model_dump(mode="json")],
                    command_record=record,
                    expected_branch_version=int(branch["state_version"]),
                )
                return record["persisted_result"]

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
        queued = False
        with self.store.locked():
            command_key = deterministic_id("cmd", action.branch_id, action.client_command_id)
            existing = self._command_result(command_key)
            if existing is not None:
                return existing
            with self._locks[action.branch_id]:
                branch = self._branch(action.branch_id)
                if branch["status"] != "Running":
                    raise ConflictError("actions can only execute on a Running branch", error_code="BRANCH_NOT_RUNNING")
                current_branch = self._branch(action.branch_id)
                world = self._world(action.branch_id)
                if action.expected_execution_time_us > world.sim_time_us:
                    result = self._queue_action(action, world, int(current_branch["state_version"]), command_key=command_key)
                    queued = bool(result.get("queued"))
                else:
                    self._apply_due_intervention_stages(action.branch_id, through_sim_time_us=action.expected_execution_time_us)
                    current_branch = self._branch(action.branch_id)
                    result = self._apply_action(action, self._world(action.branch_id), int(current_branch["state_version"]), command_key=command_key)
        if queued:
            self._ensure_autonomous_runner(action.branch_id)
        return result

    def _queue_action(
        self,
        action: ActionContract,
        world: SimulationWorld,
        state_version: int,
        *,
        command_key: str,
        proposal_id: str | None = None,
        decision_id: str | None = None,
    ) -> dict[str, object]:
        branch = self._branch(action.branch_id)
        try:
            queued = world.apply_action(
                action,
                world_version=state_version,
                proposal_id=proposal_id,
                decision_id=decision_id,
                defer_execution=True,
            )
        except SandboxError:
            return self._apply_action(
                action,
                world,
                state_version,
                command_key=command_key,
                proposal_id=proposal_id,
                decision_id=decision_id,
            )
        record = self._command_record(command_key, action.action_type, {
            "accepted": True,
            "queued": True,
            "outcome": "queued",
            "action_id": action.action_id,
            "branch_id": action.branch_id,
            "scheduled_sim_time_us": action.expected_execution_time_us,
        }, include_events=True)
        self.events.append_batch(
            str(branch["run_id"]),
            action.branch_id,
            queued.events,
            world_state=queued.world.to_json(),
            command_record=record,
            expected_branch_version=state_version,
        )
        return record["persisted_result"]

    def command(self, branch_id: str, client_command_id: str, command_type: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        if command_type == "run_for":
            return self._run_for_command(branch_id, client_command_id, payload or {})
        with self.store.locked():
            result = self._command_locked(branch_id, client_command_id, command_type, payload)
        if command_type == "start":
            self._ensure_autonomous_runner(branch_id)
        return result

    def _ensure_autonomous_runner(self, branch_id: str) -> None:
        current = self._runner_threads.get(branch_id)
        if current is not None and current.is_alive():
            return
        cancel = threading.Event()
        self._runner_cancel[branch_id] = cancel
        thread = threading.Thread(
            target=self._autonomous_runner,
            args=(branch_id, cancel),
            name=f"sandbox-runner-{branch_id}",
            daemon=True,
        )
        self._runner_threads[branch_id] = thread
        thread.start()

    def _autonomous_runner(self, branch_id: str, cancel: threading.Event) -> None:
        # A short control-plane grace period lets an immediate Pause win without
        # consuming another virtual-time boundary.
        if cancel.wait(0.25):
            return
        while not cancel.is_set():
            try:
                with self.store.locked():
                    branch = self._branch(branch_id)
                    if branch["status"] != "Running":
                        return
                    manual = self.store.connection.execute(
                        "SELECT 1 FROM commands WHERE branch_id=? AND command_type IN ('step_fixture','run_for') LIMIT 1",
                        (branch_id,),
                    ).fetchone()
                    if manual is not None:
                        return
                if not self._advance_background_once(branch_id):
                    planning_result = asyncio.run(self._run_planning_requests(branch_id, max_requests=1))
                    if not planning_result["processed_requests"]:
                        return
                else:
                    asyncio.run(self._run_planning_requests(branch_id, max_requests=1))
            except Exception as error:
                try:
                    with self.store.locked():
                        branch = self._branch(branch_id)
                        if branch["status"] == "Running":
                            world = self._world(branch_id)
                            world.terminal_reason = "runner_failed"
                            self.events.append_batch(
                                str(branch["run_id"]),
                                branch_id,
                                [self._system_event(
                                    "BranchFailed",
                                    branch_id,
                                    {"reason": "runner_failed", "error_type": type(error).__name__},
                                    sim_time_us=world.sim_time_us,
                                )],
                                world_state=world.to_json(),
                                branch_status="Failed",
                                expected_branch_version=int(branch["state_version"]),
                            )
                except Exception:
                    pass
                return
            if cancel.wait(0.05):
                return

    def _advance_background_once(self, branch_id: str) -> bool:
        with self._runner_locks[branch_id], self.store.locked():
            branch = self._branch(branch_id)
            if branch["status"] != "Running":
                return False
            world = self._world(branch_id)
            sequence = int(world.background_market_sector.get("policy_sequence", 0))
            policy_limit = int(world.background_market_sector.get("policy_step_limit", 200))
            background_id = str(world.background_market_sector.get("sector_id", "background"))
            pending = sorted(
                world.pending_actions.values(),
                key=lambda item: (int(item["expected_execution_time_us"]), str(item["action_id"])),
            )
            next_pending_time = int(pending[0]["expected_execution_time_us"]) if pending else None
            deliveries = sorted(
                world.pending_deliveries.values(),
                key=lambda item: (int(item["delivery_sim_time_us"]), str(item["delivery_id"])),
            )
            next_delivery_time = int(deliveries[0]["delivery_sim_time_us"]) if deliveries else None
            next_background_time = (
                world.sim_time_us + 1_000_000
                if sequence < policy_limit and world.market.get("status", "active") == "active"
                else None
            )
            intervention_times = [
                stage.effective_sim_time_us
                for row in self.store.connection.execute(
                    "SELECT plan_json FROM intervention_plans WHERE branch_id=? AND status='confirmed'",
                    (branch_id,),
                ).fetchall()
                for stage in InterventionPlan.model_validate(json.loads(row["plan_json"])).stages
                if stage.status == "pending"
            ]
            candidates = [
                time
                for time in [next_pending_time, next_delivery_time, next_background_time, *intervention_times]
                if time is not None
            ]
            if not candidates:
                return False
            next_time = min(candidates)
            applied, failed = self._apply_due_intervention_stages(branch_id, through_sim_time_us=next_time)
            if applied or failed:
                return True
            branch = self._branch(branch_id)
            world = self._world(branch_id)
            due_deliveries = sorted(
                (
                    item for item in world.pending_deliveries.values()
                    if int(item["delivery_sim_time_us"]) <= next_time
                ),
                key=lambda item: (int(item["delivery_sim_time_us"]), str(item["delivery_id"])),
            )
            if due_deliveries:
                return self._deliver_pending_information(
                    branch_id,
                    world,
                    due_deliveries[0],
                    int(branch["state_version"]),
                )
            due_pending = sorted(
                (
                    item for item in world.pending_actions.values()
                    if int(item["expected_execution_time_us"]) <= next_time
                ),
                key=lambda item: (int(item["expected_execution_time_us"]), str(item["action_id"])),
            )
            if due_pending:
                item = due_pending[0]
                action = ActionContract.model_validate(item["action"])
                reservation_id = str(item["reservation_id"])
                self._apply_action(
                    action,
                    world,
                    int(branch["state_version"]),
                    proposal_id=str(item["proposal_id"]),
                    decision_id=str(item["decision_id"]) if item.get("decision_id") is not None else None,
                    admitted_reservation_id=reservation_id,
                )
                return True
            if sequence >= policy_limit or world.market.get("status", "active") != "active":
                return False
            working = world.clone()
            working.background_market_sector["policy_sequence"] = sequence + 1
            working.background_market_sector["policy_step_limit"] = policy_limit
            mid = int(working.market["initial_mid_price"])
            side = "sell" if sequence % 2 == 0 else "buy"
            distance = 15 + (sequence % 5)
            price = max(1, (mid * ((100 + distance) if side == "sell" else (100 - distance))) // 100)
            asset = working.market["base_asset"] if side == "sell" else working.market["quote_asset"]
            free = working.ledger.balance(background_id, asset)
            affordable = free if side == "sell" else free // max(1, price + 1)
            quantity = min(1_000, max(0, affordable // 100))
            if quantity <= 0:
                working.background_market_sector["policy_exhausted"] = True
                self.events.append_batch(
                    str(branch["run_id"]),
                    branch_id,
                    [self._system_event(
                        "BackgroundParticipationExhausted",
                        background_id,
                        {"sequence": sequence, "asset": asset},
                        sim_time_us=working.sim_time_us,
                    )],
                    world_state=working.to_json(),
                    expected_branch_version=int(branch["state_version"]),
                )
                return False
            action = ActionContract(
                action_id=deterministic_id("action", working.rng.root_seed, "background", sequence),
                agent_id=background_id,
                branch_id=branch_id,
                submitted_sim_time_us=working.sim_time_us,
                action_type="SubmitLimitOrder",
                payload={"side": side, "quantity": quantity, "price": price},
                expected_execution_time_us=working.sim_time_us + 1_000_000,
                validity_window_us=2_000_000,
                parent_observation_id=None,
                client_command_id=f"background-policy:{sequence}",
            )
            return bool(self._apply_action(
                action,
                working,
                int(branch["state_version"]),
            )["accepted"])

    def _deliver_pending_information(
        self,
        branch_id: str,
        world: SimulationWorld,
        delivery: dict[str, object],
        state_version: int,
    ) -> bool:
        working = world.clone()
        delivery_id = str(delivery["delivery_id"])
        information_id = str(delivery["information_id"])
        target_id = str(delivery["target_id"])
        delivery_time = int(delivery["delivery_sim_time_us"])
        working.pending_deliveries.pop(delivery_id, None)
        working.sim_time_us = max(working.sim_time_us, delivery_time)
        item = next(
            (candidate for candidate in working.information_items if candidate.get("information_id") == information_id),
            None,
        )
        source_id = str(delivery.get("source_id", "information_system"))
        visibility = str(delivery.get("visibility", "public"))
        action_id = str(delivery["action_id"]) if delivery.get("action_id") is not None else None
        correlation_id = str(delivery["client_command_id"]) if delivery.get("client_command_id") is not None else None
        if item is None:
            delivery_event = EventDraft(
                sim_time_us=working.sim_time_us,
                priority=41,
                tie_break_key=f"delivery:{delivery_id}:missing",
                event_type="InformationDeliveryFailed",
                source_id=source_id,
                target_ids=[target_id],
                payload={"delivery_id": delivery_id, "information_id": information_id, "reason": "information_not_found"},
                action_id=action_id,
                correlation_id=correlation_id,
                visibility="agent_private" if visibility == "agent_private" else "participants",
            )
            self.events.append_batch(
                str(self._branch(branch_id)["run_id"]),
                branch_id,
                [delivery_event],
                world_state=working.to_json(),
                expected_branch_version=state_version,
            )
            return True

        expires_at = int(delivery.get("expires_sim_time_us", item.get("expires_sim_time_us", delivery_time)))
        if expires_at < delivery_time:
            delivery_event = EventDraft(
                sim_time_us=working.sim_time_us,
                priority=41,
                tie_break_key=f"delivery:{delivery_id}:expired",
                event_type="InformationDeliveryExpired",
                source_id=source_id,
                target_ids=[target_id],
                payload={"delivery_id": delivery_id, "information_id": information_id, "expires_sim_time_us": expires_at},
                action_id=action_id,
                correlation_id=correlation_id,
                visibility="agent_private" if visibility == "agent_private" else "participants",
            )
            self.events.append_batch(
                str(self._branch(branch_id)["run_id"]),
                branch_id,
                [delivery_event],
                world_state=working.to_json(),
                expected_branch_version=state_version,
            )
            return True

        delivery_event = EventDraft(
            sim_time_us=working.sim_time_us,
            priority=41,
            tie_break_key=f"delivery:{delivery_id}:delivered",
            event_type="PrivateMessageDelivered" if visibility == "agent_private" else "InformationDelivered",
            source_id=source_id,
            target_ids=[target_id],
            payload={"delivery_id": delivery_id, "information_id": information_id, "target_id": target_id},
            action_id=action_id,
            correlation_id=correlation_id,
            visibility="agent_private" if visibility == "agent_private" else "participants",
        )
        previous_observation_id = working.latest_observation_ids.get(target_id)
        trigger_type = "private_message" if visibility == "agent_private" else "information"
        observations = working.create_observations(
            branch_id,
            state_version + 1,
            recipient_ids=[target_id],
            triggers_by_agent={
                target_id: [DecisionTrigger(
                    type=trigger_type,
                    semantic_key=f"delivery:{delivery_id}",
                    source_event_ids=[],
                    severity=70,
                    first_sim_time_us=working.sim_time_us,
                    last_sim_time_us=working.sim_time_us,
                )]
            },
        )
        observations = [observation for observation in observations if observation.information_items]
        if not observations:
            if previous_observation_id is None:
                working.latest_observation_ids.pop(target_id, None)
            else:
                working.latest_observation_ids[target_id] = previous_observation_id
        evaluation = self._evaluate_observations(working, observations)
        drafts = [delivery_event]
        drafts.extend(self._observation_event(observation, source_id) for observation in observations)
        for observation in observations:
            drafts.extend(
                EventDraft(
                    sim_time_us=working.sim_time_us,
                    priority=55,
                    tie_break_key=f"delivery:{delivery_id}:viewed:{visible.information_id}",
                    event_type="InformationViewed",
                    source_id=source_id,
                    target_ids=[observation.agent_id],
                    payload={"information_id": visible.information_id, "agent_id": observation.agent_id},
                    observation_id=observation.observation_id,
                    action_id=action_id,
                    correlation_id=correlation_id,
                    visibility="agent_private",
                )
                for visible in observation.information_items
            )
        drafts.extend(evaluation["events"])
        self.events.append_batch(
            str(self._branch(branch_id)["run_id"]),
            branch_id,
            drafts,
            world_state=working.to_json(),
            observations=[observation.model_dump(mode="json") for observation in observations],
            agent_decisions=evaluation["decisions"],
            planning_requests=evaluation["planning_requests"],
            expected_branch_version=state_version,
        )
        return True

    def close(self) -> None:
        for cancel in self._runner_cancel.values():
            cancel.set()
        for thread in self._runner_threads.values():
            if thread.is_alive():
                thread.join(timeout=1)

    def _run_for_command(
        self,
        branch_id: str,
        client_command_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        command_key = deterministic_id("cmd", branch_id, client_command_id)
        max_requests = int(payload.get("max_requests", 1))
        if not 1 <= max_requests <= 100:
            raise ValidationError("run_for max_requests must be within 1..100")
        with self._runner_locks[branch_id]:
            with self.store.locked():
                existing = self._command_result(command_key)
                if existing is not None:
                    return existing
                branch = self._branch(branch_id)
                if branch["status"] != "Running":
                    raise ConflictError("run_for requires a Running branch")
                run_id = str(branch["run_id"])
            run_result = asyncio.run(self.branch_runner.run_for(branch_id, max_requests=max_requests))
            with self.store.locked():
                current_branch = self._branch(branch_id)
                record = self._command_record(command_key, "run_for", {"branch_id": branch_id, **run_result})
                self.events.append_batch(
                    run_id,
                    branch_id,
                    [],
                    world_state=self._world(branch_id).to_json(),
                    command_record=record,
                    expected_branch_version=int(current_branch["state_version"]),
                )
                return record["persisted_result"]

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
                if status == "Running":
                    record = self._command_record(command_key, command_type, {"branch_id": branch_id, "status": "Running", "cursor": int(branch["state_version"])})
                    self.events.append_batch(run_id, branch_id, [], command_record=record, expected_branch_version=int(branch["state_version"]))
                    result = record["persisted_result"]
                elif status not in {"Ready", "Paused", "Checkpointed"}:
                    raise ConflictError(f"cannot start branch from {status}")
                else:
                    barrier = self._process_deferred_observation_barrier(branch_id, world, int(branch["state_version"])) if status == "Paused" else None
                    next_world = barrier["world"] if barrier else world
                    drafts = barrier["events"] if barrier else []
                    record = self._command_record(command_key, command_type, {
                        "branch_id": branch_id,
                        "status": "Running",
                        "processed_observations": barrier["processed"] if barrier else 0,
                        "cursor": int(branch["state_version"]),
                    })
                    self.events.append_batch(
                        run_id, branch_id, drafts,
                        world_state=next_world.to_json(),
                        branch_status="Running",
                        command_record=record,
                        agent_decisions=barrier["decisions"] if barrier else [],
                        planning_requests=barrier["planning_requests"] if barrier else [],
                        action_receipts=barrier["receipts"] if barrier else [],
                        expected_branch_version=int(branch["state_version"]),
                    )
                    result = record["persisted_result"]
                    activated_results = self._activate_pending_planning_results(branch_id)
                    if activated_results:
                        current = self._branch(branch_id)
                        result = {**result, "activated_planning_results": activated_results, "cursor": int(current["state_version"])}
                        with self.store.transaction() as connection:
                            connection.execute(
                                "UPDATE commands SET result_json=? WHERE command_id=?",
                                (canonical_json(result), command_key),
                            )
            elif command_type == "pause":
                if status == "Paused":
                    record = self._command_record(command_key, command_type, {"branch_id": branch_id, "status": "Paused", "cursor": int(branch["state_version"])})
                    self.events.append_batch(run_id, branch_id, [], command_record=record, expected_branch_version=int(branch["state_version"]))
                    result = record["persisted_result"]
                elif status != "Running":
                    raise ConflictError(f"cannot pause branch from {status}")
                else:
                    record = self._command_record(command_key, command_type, {"branch_id": branch_id, "status": "Paused", "cursor": int(branch["state_version"])})
                    self.events.append_batch(run_id, branch_id, [], world_state=world.to_json(), branch_status="Paused", command_record=record, expected_branch_version=int(branch["state_version"]))
                    result = record["persisted_result"]
            elif command_type == "stop":
                if status == "Completed":
                    record = self._command_record(command_key, command_type, {
                        "branch_id": branch_id,
                        "status": "Completed",
                        "reason": world.terminal_reason or "completed",
                        "cursor": int(branch["state_version"]),
                    })
                    self.events.append_batch(
                        run_id,
                        branch_id,
                        [],
                        command_record=record,
                        expected_branch_version=int(branch["state_version"]),
                    )
                    result = record["persisted_result"]
                elif status not in {"Ready", "Running", "Paused", "Checkpointed"}:
                    raise ConflictError(f"cannot stop branch from {status}")
                else:
                    working = world.clone()
                    cancellation_events = [
                        self._system_event(
                            "PendingActionCanceled",
                            branch_id,
                            {"action_id": action_id, "reason": "user_stopped"},
                            sim_time_us=working.sim_time_us,
                            tie=f"00-cancel:{action_id}",
                        )
                        for action_id in sorted(working.pending_actions)
                    ]
                    cancellation_events.extend(
                        self._system_event(
                            "ActionReservationReleased",
                            branch_id,
                            {"reservation_id": reservation_id, "reason": "user_stopped"},
                            sim_time_us=working.sim_time_us,
                            tie=f"01-release:{reservation_id}",
                        )
                        for reservation_id in sorted(working.action_reservations)
                    )
                    cancellation_events.extend(
                        self._system_event(
                            "InformationDeliveryCanceled",
                            branch_id,
                            {
                                "delivery_id": delivery_id,
                                "information_id": delivery["information_id"],
                                "target_id": delivery["target_id"],
                                "reason": "user_stopped",
                            },
                            sim_time_us=working.sim_time_us,
                            tie=f"02-delivery-cancel:{delivery_id}",
                        )
                        for delivery_id, delivery in sorted(working.pending_deliveries.items())
                    )
                    working.pending_actions.clear()
                    working.action_reservations.clear()
                    working.pending_deliveries.clear()
                    working.deferred_observation_ids.clear()
                    working.terminal_reason = "user_stopped"
                    cancellation_events.append(self._system_event(
                        "BranchStopped",
                        branch_id,
                        {"reason": "user_stopped"},
                        sim_time_us=working.sim_time_us,
                        tie="99-stopped",
                    ))
                    record = self._command_record(command_key, command_type, {
                        "branch_id": branch_id,
                        "status": "Completed",
                        "reason": "user_stopped",
                    })
                    self.events.append_batch(
                        run_id,
                        branch_id,
                        cancellation_events,
                        world_state=working.to_json(),
                        branch_status="Completed",
                        command_record=record,
                        expected_branch_version=int(branch["state_version"]),
                    )
                    result = record["persisted_result"]
            elif command_type == "step_fixture":
                if status != "Running":
                    raise ConflictError("fixture step requires a Running branch")
                self._apply_due_intervention_stages(branch_id, through_sim_time_us=world.sim_time_us + 1_000_000)
                branch = self._branch(branch_id)
                world = self._world(branch_id)
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
                        client_command_id=f"fixture:{client_command_id}",
                    )
                    result = self._apply_action(action, working, int(branch["state_version"]), command_key=command_key)
            elif command_type == "save":
                result = self._checkpoint(branch_id, world, branch, command_key=command_key)
            else:
                raise ValidationError(f"unsupported command '{command_type}'")
            return result

    async def _run_planning_requests(self, branch_id: str, *, max_requests: int) -> dict[str, object]:
        processed = 0
        applied = 0
        failed = 0
        deferred = 0
        while processed < max_requests:
            with self.store.locked():
                branch = self._branch(branch_id)
                if branch["status"] != "Running":
                    break
                world = self._world(branch_id)
                candidates = sorted(
                    (request for request in world.planning_requests.values() if request.state in {"Queued", "Running"}),
                    key=lambda item: (item.activation_time_us, item.agent_id, item.request_id),
                )
                if not candidates:
                    break
                request = candidates[0]
                self._apply_due_intervention_stages(
                    branch_id,
                    through_sim_time_us=max(world.sim_time_us, request.activation_time_us),
                )
                branch = self._branch(branch_id)
                world = self._world(branch_id)
                request = world.planning_requests[request.request_id]
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
                with self.store.locked():
                    current = self._branch(branch_id)
                    self.events.append_batch(
                        str(current["run_id"]),
                        branch_id,
                        [],
                        llm_records=[record.model_dump(mode="json")],
                        expected_branch_version=int(current["state_version"]),
                    )

            try:
                if provider_name in {"rule", "replay"}:
                    candidate = PlanningResultCandidate(
                        based_on_strategy_revision=state.active_strategy_revision,
                        valid_for_us=300_000_000,
                        goals=[],
                        activation_preconditions=[],
                        constraints=[],
                        directives=[],
                        replan_conditions=[],
                        rationale=DecisionRationale(
                            goal_summary="Hold and protect until a deterministic strategy condition is available.",
                            uncertainty_milli=700,
                            stated_reason="The local planner produced a bounded no-new-risk plan.",
                        ),
                    )
                else:
                    candidate = await self.initializer.llm_gateway.plan(provider_name, provider_request, record_raw=persist_raw)
                with self.store.locked():
                    current = self._branch(branch_id)
                    self.events.append_batch(
                        str(current["run_id"]), branch_id, [],
                        planning_results=[{
                            "request_id": request.request_id,
                            "result_status": "ready",
                            "payload": candidate.model_dump(mode="json"),
                            "applied": False,
                        }],
                        expected_branch_version=int(current["state_version"]),
                    )
                    if current["status"] == "Running":
                        self._complete_planning_candidate(branch_id, request.request_id, candidate)
                        applied += 1
                    else:
                        deferred += 1
            except SandboxError as error:
                with self.store.locked():
                    current = self._branch(branch_id)
                    self.events.append_batch(
                        str(current["run_id"]), branch_id, [],
                        planning_results=[{
                            "request_id": request.request_id,
                            "result_status": "failed",
                            "payload": {"error_code": error.error_code},
                            "applied": False,
                        }],
                        expected_branch_version=int(current["state_version"]),
                    )
                    if current["status"] == "Running":
                        self._fail_planning_request(branch_id, request.request_id, error.error_code)
                        failed += 1
                    else:
                        deferred += 1
            processed += 1
        return {
            "processed_requests": processed,
            "applied_requests": applied,
            "failed_requests": failed,
            "deferred_results": deferred,
        }

    def _complete_planning_candidate(
        self,
        branch_id: str,
        request_id: str,
        candidate: PlanningResultCandidate,
    ) -> None:
        branch = self._branch(branch_id)
        if branch["status"] != "Running":
            raise ConflictError("planning results cannot activate while the branch is Paused", error_code="BRANCH_NOT_RUNNING")
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
                defer_execution=True,
            )
            world = action_result.world
            events.extend(action_result.events)
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
            planning_results=[{
                "request_id": request_id,
                "result_status": "ready",
                "payload": candidate.model_dump(mode="json"),
                "applied": True,
            }],
            expected_branch_version=int(branch["state_version"]),
        )

    def _fail_planning_request(self, branch_id: str, request_id: str, error_code: str) -> None:
        branch = self._branch(branch_id)
        if branch["status"] != "Running":
            raise ConflictError("planning failures cannot settle while the branch is Paused", error_code="BRANCH_NOT_RUNNING")
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
            planning_results=[{
                "request_id": request_id,
                "result_status": "failed",
                "payload": {"error_code": error_code},
                "applied": True,
            }],
            expected_branch_version=int(branch["state_version"]),
        )

    def _activate_pending_planning_results(self, branch_id: str) -> int:
        activated = 0
        while True:
            branch = self._branch(branch_id)
            if branch["status"] != "Running":
                break
            row = self.store.connection.execute(
                "SELECT request_id,result_status,payload_json FROM planning_results WHERE branch_id=? AND applied=0 ORDER BY received_at,request_id LIMIT 1",
                (branch_id,),
            ).fetchone()
            if row is None:
                break
            request_id = str(row["request_id"])
            payload = json.loads(row["payload_json"])
            if row["result_status"] == "ready":
                self._complete_planning_candidate(
                    branch_id,
                    request_id,
                    PlanningResultCandidate.model_validate(payload),
                )
            else:
                self._fail_planning_request(
                    branch_id,
                    request_id,
                    str(payload.get("error_code", "PLANNING_PROVIDER_FAILED")),
                )
            activated += 1
        return activated

    def _intervention_plan(self, branch_id: str, plan_id: str) -> InterventionPlan:
        row = self.store.connection.execute(
            "SELECT plan_json FROM intervention_plans WHERE plan_id=? AND branch_id=?",
            (plan_id, branch_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("intervention plan", plan_id)
        return InterventionPlan.model_validate(json.loads(row["plan_json"]))

    def _revalidate_intervention_plan(
        self,
        plan: InterventionPlan,
        world: SimulationWorld,
        state_version: int,
    ) -> None:
        working = world.clone()
        for stage in plan.stages:
            if stage.status != "pending":
                continue
            if stage.effective_sim_time_us < world.sim_time_us:
                raise ConflictError(
                    "intervention plan targets committed history",
                    error_code="INTERVENTION_IN_PAST",
                )
            working.sim_time_us = stage.effective_sim_time_us
            result = working.apply_intervention_stage(
                stage,
                branch_id=plan.branch_id,
                plan_id=plan.plan_id,
                world_version=state_version,
            )
            working = result.world

    def _apply_due_intervention_stages(
        self,
        branch_id: str,
        *,
        through_sim_time_us: int,
    ) -> tuple[int, int]:
        applied = 0
        failed = 0
        while True:
            branch = self._branch(branch_id)
            if branch["status"] != "Running":
                break
            world = self._world(branch_id)
            plans = [
                InterventionPlan.model_validate(json.loads(row["plan_json"]))
                for row in self.store.connection.execute(
                    "SELECT plan_json FROM intervention_plans WHERE branch_id=? AND status='confirmed' ORDER BY created_branch_seq,plan_id",
                    (branch_id,),
                ).fetchall()
            ]
            due = [
                (stage.effective_sim_time_us, plan.created_branch_seq, plan.plan_id, stage.stage_id, plan, index, stage)
                for plan in plans
                for index, stage in enumerate(plan.stages)
                if stage.status == "pending" and stage.effective_sim_time_us <= through_sim_time_us
            ]
            if not due:
                break
            _, _, _, _, plan, stage_index, stage = min(due, key=lambda item: item[:4])
            if stage.effective_sim_time_us < world.sim_time_us:
                failed_stage = stage.model_copy(update={
                    "status": "failed",
                    "failure_reason": "execution boundary was already committed",
                })
                stages = list(plan.stages)
                stages[stage_index] = failed_stage
                failed_plan = plan.model_copy(update={"status": "failed", "stages": stages})
                self.events.append_batch(
                    str(branch["run_id"]), branch_id, [],
                    intervention_plans=[failed_plan.model_dump(mode="json")],
                    expected_branch_version=int(branch["state_version"]),
                )
                failed += 1
                continue
            working = world.clone()
            working.sim_time_us = stage.effective_sim_time_us
            try:
                result = working.apply_intervention_stage(
                    stage,
                    branch_id=branch_id,
                    plan_id=plan.plan_id,
                    world_version=int(branch["state_version"]),
                    defer_observations=True,
                )
            except SandboxError as error:
                stages = list(plan.stages)
                stages[stage_index] = stage.model_copy(update={
                    "status": "failed",
                    "failure_reason": f"{error.error_code}: {error.message}",
                })
                failed_plan = plan.model_copy(update={"status": "failed", "stages": stages})
                self.events.append_batch(
                    str(branch["run_id"]), branch_id, [],
                    intervention_plans=[failed_plan.model_dump(mode="json")],
                    expected_branch_version=int(branch["state_version"]),
                )
                failed += 1
                continue
            stages = list(plan.stages)
            stages[stage_index] = stage.model_copy(update={"status": "applied"})
            next_status = "completed" if all(item.status != "pending" for item in stages) else "confirmed"
            updated_plan = plan.model_copy(update={"status": next_status, "stages": stages})
            stage_event = EventDraft(
                sim_time_us=stage.effective_sim_time_us,
                priority=49,
                tie_break_key=f"intervention:{plan.plan_id}:{stage.stage_id}:stage-applied",
                event_type="InterventionStageApplied",
                source_id="scenario_director",
                payload={"plan_id": plan.plan_id, "stage_id": stage.stage_id},
                correlation_id=plan.plan_id,
                visibility="analyst_only",
            )
            self.events.append_batch(
                str(branch["run_id"]), branch_id, [*result.events, stage_event],
                world_state=result.world.to_json(),
                observations=[item.model_dump(mode="json") for item in result.observations],
                intervention_plans=[updated_plan.model_dump(mode="json")],
                expected_branch_version=int(branch["state_version"]),
            )
            barrier_branch = self._branch(branch_id)
            barrier_world = self._world(branch_id)
            barrier = self._process_deferred_observation_barrier(
                branch_id,
                barrier_world,
                int(barrier_branch["state_version"]),
            )
            if barrier["processed"]:
                self.events.append_batch(
                    str(branch["run_id"]), branch_id, barrier["events"],
                    world_state=barrier["world"].to_json(),
                    agent_decisions=barrier["decisions"],
                    planning_requests=barrier["planning_requests"],
                    action_receipts=barrier["receipts"],
                    expected_branch_version=int(barrier_branch["state_version"]),
                )
            applied += 1
        return applied, failed

    def _process_deferred_observation_barrier(
        self,
        branch_id: str,
        world: SimulationWorld,
        state_version: int,
    ) -> dict[str, Any]:
        observation_ids = list(dict.fromkeys(world.deferred_observation_ids))
        if not observation_ids:
            return {"world": world, "events": [], "decisions": [], "planning_requests": [], "receipts": [], "processed": 0}
        placeholders = ",".join("?" for _ in observation_ids)
        rows = self.store.connection.execute(
            f"SELECT observation_json FROM observations WHERE branch_id=? AND observation_id IN ({placeholders}) ORDER BY sim_time_us,observation_id",
            (branch_id, *observation_ids),
        ).fetchall()
        observations_by_id = {
            item.observation_id: item
            for item in (ObservationPacket.model_validate(json.loads(row["observation_json"])) for row in rows)
        }
        ordered = [observations_by_id[item_id] for item_id in observation_ids if item_id in observations_by_id]
        batch = self._evaluate_observations(world, ordered)
        events = batch["events"]
        events = [
            event
            for observation in ordered
            for event in [
                EventDraft(
                    sim_time_us=observation.sim_time_us,
                    priority=55,
                    tie_break_key=f"observation:{observation.observation_id}:viewed:{visible.information_id}",
                    event_type="InformationViewed",
                    source_id=observation.agent_id,
                    target_ids=[observation.agent_id],
                    payload={"information_id": visible.information_id, "agent_id": observation.agent_id},
                    observation_id=observation.observation_id,
                    visibility="agent_private",
                )
                for visible in observation.information_items
            ]
        ] + events
        decisions = batch["decisions"]
        planning_requests = batch["planning_requests"]
        processed = len(ordered)
        world.deferred_observation_ids = [item_id for item_id in world.deferred_observation_ids if item_id not in observations_by_id]
        events.insert(0, self._system_event(
            "ObservationBarrierProcessed",
            branch_id,
            {"observation_ids": observation_ids, "processed": processed},
            sim_time_us=world.sim_time_us,
            tie=f"observation-barrier:{state_version}",
        ))
        return {
            "world": world,
            "events": events,
            "decisions": decisions,
            "planning_requests": planning_requests,
            "receipts": [],
            "processed": processed,
        }

    def _evaluate_observations(
        self,
        world: SimulationWorld,
        observations: list[ObservationPacket],
    ) -> dict[str, list[Any]]:
        events: list[EventDraft] = []
        decisions: list[dict[str, object]] = []
        planning_requests: list[dict[str, object]] = []
        for observation in observations:
            definition = world.agent_definitions.get(observation.agent_id)
            state = world.agent_runtime_states.get(observation.agent_id)
            if definition is None or state is None:
                continue
            active_plan = world.strategy_plans.get(state.active_plan_id or "")
            runtime_result = self.agent_runtime.decide(
                definition=definition,
                state=state,
                observation=observation,
                active_plan=active_plan,
            )
            if runtime_result is None:
                continue
            world.agent_runtime_states[observation.agent_id] = runtime_result.state
            if runtime_result.planning_request is not None:
                world.planning_requests[runtime_result.planning_request.request_id] = runtime_result.planning_request
                planning_requests.append(runtime_result.planning_request.model_dump(mode="json"))
            decisions.append({
                "decision": runtime_result.decision.model_dump(mode="json"),
                "outcome": runtime_result.outcome.model_dump(mode="json"),
            })
            events.extend(runtime_result.events)
            for proposal in runtime_result.action_proposals:
                action = ActionContract(
                    action_id=deterministic_id("action", runtime_result.decision.decision_id, proposal.proposal_id),
                    agent_id=observation.agent_id,
                    branch_id=observation.branch_id,
                    submitted_sim_time_us=observation.sim_time_us,
                    action_type=proposal.action_type,
                    payload=proposal.payload,
                    expected_execution_time_us=proposal.expected_execution_time_us,
                    validity_window_us=proposal.validity_window_us,
                    parent_observation_id=observation.observation_id,
                    client_command_id=deterministic_id("agent-action", runtime_result.decision.decision_id, proposal.proposal_id),
                )
                try:
                    admission = world.apply_action(
                        action,
                        world_version=observation.world_version,
                        proposal_id=proposal.proposal_id,
                        decision_id=runtime_result.decision.decision_id,
                        defer_execution=True,
                    )
                except SandboxError as error:
                    events.append(EventDraft(
                        sim_time_us=observation.sim_time_us,
                        priority=69,
                        tie_break_key=f"agent:{observation.agent_id}:{action.action_id}:admission-rejected",
                        event_type="ActionAdmissionRejected",
                        source_id=observation.agent_id,
                        target_ids=[observation.agent_id],
                        payload={"action_id": action.action_id, "reason": error.error_code},
                        observation_id=observation.observation_id,
                        action_id=action.action_id,
                        visibility="agent_private",
                    ))
                    continue
                world.pending_actions = admission.world.pending_actions
                world.action_reservations = admission.world.action_reservations
                events.extend(admission.events)
        return {
            "events": events,
            "decisions": decisions,
            "planning_requests": planning_requests,
        }

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
        inherited_interventions: list[dict[str, object]] = []
        for item in checkpoint.control_state.get("intervention_plans", []):
            parent_plan = InterventionPlan.model_validate(item)
            pending_stages = [stage for stage in parent_plan.stages if stage.status == "pending"]
            if parent_plan.status != "confirmed" or not pending_stages:
                continue
            next_plan_id = deterministic_id("intervention-plan", new_branch_id, parent_plan.plan_id)
            inherited = parent_plan.model_copy(update={
                "plan_id": next_plan_id,
                "branch_id": new_branch_id,
                "created_branch_seq": 0,
                "base_world_revision": world.world_revision,
                "stages": pending_stages,
                "plan_revision": parent_plan.plan_revision + 1,
            })
            inherited_interventions.append(inherited.model_dump(mode="json"))
        inherited_planning_results: list[dict[str, object]] = []
        for item in checkpoint.control_state.get("planning_results", []):
            parent_request_id = str(item["request_id"])
            next_request_id = request_id_map.get(parent_request_id)
            if next_request_id is None:
                continue
            inherited_planning_results.append({
                "request_id": next_request_id,
                "result_status": item["result_status"],
                "payload": item["payload"],
                "applied": False,
            })
        observations = world.create_observations(new_branch_id, 1)
        drafts = [self._system_event("BranchCreated", new_branch_id, {"parent_branch_id": branch_id, "fork_checkpoint_id": checkpoint_id}, sim_time_us=checkpoint.sim_time_us)]
        drafts.extend(self._observation_event(observation, new_branch_id) for observation in observations)
        record = self._command_record(command_key, "fork", {"branch_id": new_branch_id, "parent_branch_id": branch_id, "checkpoint_id": checkpoint_id, "status": "Ready"})
        self.events.append_batch(
            checkpoint.run_id, new_branch_id, drafts,
            world_state=world.to_json(), observations=[item.model_dump(mode="json") for item in observations], branch_status="Ready", command_record=record,
            planning_requests=[request.model_dump(mode="json") for request in remapped_requests.values() if request.branch_id == new_branch_id],
            intervention_plans=inherited_interventions,
            planning_results=inherited_planning_results,
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
                        client_command_id=f"fixture:{client_command_id}",
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
        admitted_reservation_id: str | None = None,
    ) -> dict[str, object]:
        branch = self._branch(action.branch_id)
        try:
            action_result: ActionResult = world.apply_action(
                action,
                world_version=state_version,
                proposal_id=proposal_id,
                decision_id=decision_id,
                admitted_reservation_id=admitted_reservation_id,
            )
            observation_batch = (
                {"events": [], "decisions": [], "planning_requests": []}
                if action.client_command_id.startswith("fixture:")
                else self._evaluate_observations(action_result.world, action_result.observations)
            )
            all_events = [*(extra_events or []), *action_result.events, *observation_batch["events"]]
            all_observations = [*(pre_observations or []), *action_result.observations]
            record = self._command_record(command_key, action.action_type, {"accepted": True, "action_id": action.action_id, "branch_id": action.branch_id}, include_events=True) if command_key else None
            persisted = self.events.append_batch(
                str(branch["run_id"]), action.branch_id, all_events,
                world_state=action_result.world.to_json(),
                observations=[item.model_dump(mode="json") for item in all_observations],
                action_receipts=[item.model_dump(mode="json") for item in action_result.receipts],
                agent_decisions=[*(decision_records or []), *observation_batch["decisions"]],
                planning_requests=[*(planning_records or []), *observation_batch["planning_requests"]],
                strategy_plans=strategy_records or [],
                command_record=record,
                expected_branch_version=state_version,
            )
            return record["persisted_result"] if record else {"accepted": True, "action_id": action.action_id, "branch_id": action.branch_id, "cursor": persisted[-1].branch_seq, "events": [event.model_dump(mode="json") for event in persisted]}
        except SandboxError as error:
            working = world.clone()
            if admitted_reservation_id is not None:
                working.pending_actions.pop(action.action_id, None)
                working.action_reservations.pop(admitted_reservation_id, None)
                working.sim_time_us = max(working.sim_time_us, action.expected_execution_time_us)
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
            observation_batch = {"events": [], "decisions": [], "planning_requests": []}
            drafts = [*(extra_events or [])]
            if admitted_reservation_id is not None:
                drafts.extend([
                    EventDraft(
                        sim_time_us=working.sim_time_us,
                        priority=73,
                        tie_break_key=f"{action.agent_id}:{action.action_id}:reservation-released",
                        event_type="ActionReservationReleased",
                        source_id=action.agent_id,
                        target_ids=[action.agent_id],
                        payload={"reservation_id": admitted_reservation_id, "reason": error.error_code},
                        action_id=action.action_id,
                        correlation_id=action.client_command_id,
                        visibility="participants",
                    ),
                    EventDraft(
                        sim_time_us=working.sim_time_us,
                        priority=74,
                        tie_break_key=f"{action.agent_id}:{action.action_id}:pending-rejected",
                        event_type="PendingActionResolved",
                        source_id=action.agent_id,
                        target_ids=[action.agent_id],
                        payload={"reservation_id": admitted_reservation_id, "outcome": "rejected"},
                        action_id=action.action_id,
                        correlation_id=action.client_command_id,
                        visibility="participants",
                    ),
                ])
            drafts.append(rejected)
            drafts.extend(self._observation_event(observation, str(branch["run_id"])) for observation in observations)
            drafts.extend(observation_batch["events"])
            all_observations = [*(pre_observations or []), *observations]
            record = self._command_record(command_key, action.action_type, {"accepted": False, "action_id": action.action_id, "branch_id": action.branch_id, "error": {"error_code": error.error_code, "message": error.message}}) if command_key else None
            persisted = self.events.append_batch(
                str(branch["run_id"]), action.branch_id, drafts,
                world_state=working.to_json(),
                observations=[item.model_dump(mode="json") for item in all_observations],
                action_receipts=[receipt.model_dump(mode="json")],
                agent_decisions=[*(decision_records or []), *observation_batch["decisions"]],
                planning_requests=[*(planning_records or []), *observation_batch["planning_requests"]],
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
            sim_time_us=world.sim_time_us,
            state=world.to_json(),
            control_state={
                "branch_status": str(branch["status"]),
                "intervention_plans": self.intervention_plans(branch_id),
                "planning_results": self._pending_planning_results(branch_id),
            },
            runtime_version=self.runtime_version,
        )
        drafts = [] if branch["status"] == "Completed" else [
            self._system_event("BranchQuiescing", branch_id, {}, sim_time_us=world.sim_time_us, tie="00-quiesce"),
            self._system_event("CheckpointCreated", branch_id, {"checkpoint_id": checkpoint_id, "cursor": checkpoint.branch_seq}, sim_time_us=world.sim_time_us, tie="01-checkpoint"),
        ]
        retained_status = str(branch["status"])
        record = self._command_record(command_key, "save", {"branch_id": branch_id, "checkpoint_id": checkpoint_id, "status": retained_status}) if command_key else None
        persisted = self.events.append_batch(
            str(branch["run_id"]),
            branch_id,
            drafts,
            world_state=world.to_json(),
            branch_status=retained_status,
            checkpoint=checkpoint.model_dump(mode="json"),
            command_record=record,
        )
        return record["persisted_result"] if record else {"branch_id": branch_id, "checkpoint_id": checkpoint_id, "status": retained_status, "cursor": persisted[-1].branch_seq}

    def _pending_planning_results(self, branch_id: str) -> list[dict[str, object]]:
        rows = self.store.connection.execute(
            "SELECT request_id,result_status,payload_json FROM planning_results WHERE branch_id=? AND applied=0 ORDER BY received_at,request_id",
            (branch_id,),
        ).fetchall()
        return [
            {
                "request_id": row["request_id"],
                "result_status": row["result_status"],
                "payload": json.loads(row["payload_json"]),
                "applied": False,
            }
            for row in rows
        ]

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
