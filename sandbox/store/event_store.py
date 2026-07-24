from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Iterable

from sandbox.contracts.event import EVENT_SCHEMA_HASH, EventDraft, EventEnvelope
from sandbox.core.ids import new_id
from sandbox.store.sqlite import SQLiteStore


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


class EventStore:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def append_batch(
        self,
        run_id: str,
        branch_id: str,
        drafts: Iterable[EventDraft],
        *,
        world_state: dict[str, object] | None = None,
        observations: Iterable[dict[str, object]] = (),
        branch_status: str | None = None,
        checkpoint: dict[str, object] | None = None,
        command_record: dict[str, object] | None = None,
        run_record: dict[str, object] | None = None,
        branch_record: dict[str, object] | None = None,
        agent_decisions: Iterable[dict[str, object]] = (),
        planning_requests: Iterable[dict[str, object]] = (),
        strategy_plans: Iterable[dict[str, object]] = (),
        llm_records: Iterable[dict[str, object]] = (),
        action_receipts: Iterable[dict[str, object]] = (),
        expected_branch_version: int | None = None,
    ) -> list[EventEnvelope]:
        drafts = sorted(drafts, key=lambda event: (event.sim_time_us, event.priority, event.tie_break_key))
        observations = [dict(item) for item in observations]
        agent_decisions = [
            {"decision": dict(item["decision"]), "outcome": dict(item["outcome"])}
            for item in agent_decisions
        ]
        planning_requests = [dict(item) for item in planning_requests]
        strategy_plans = [dict(item) for item in strategy_plans]
        llm_records = [dict(item) for item in llm_records]
        action_receipts = [dict(item) for item in action_receipts]
        persisted: list[EventEnvelope] = []
        with self.store.transaction() as connection:
            if run_record is not None:
                connection.execute(
                    "INSERT INTO runs(run_id,scenario_id,name,status,runtime_version,resolved_state_json,created_at) VALUES(?,?,?,?,?,?,?)",
                    (run_record["run_id"], run_record["scenario_id"], run_record["name"], run_record["status"], run_record["runtime_version"], canonical_json(run_record["resolved_state"]), run_record["created_at"]),
                )
            if branch_record is not None:
                connection.execute(
                    "INSERT INTO branches(branch_id,run_id,parent_branch_id,fork_checkpoint_id,status,sim_time_us,state_version,last_event_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (branch_record["branch_id"], branch_record["run_id"], branch_record.get("parent_branch_id"), branch_record.get("fork_checkpoint_id"), branch_record["status"], branch_record.get("sim_time_us", 0), 0, "genesis", branch_record["created_at"]),
                )
            row = connection.execute(
                "SELECT state_version, last_event_hash FROM branches WHERE branch_id=?", (branch_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown branch {branch_id}")
            sequence = int(row["state_version"])
            if expected_branch_version is not None and sequence != expected_branch_version:
                from sandbox.core.errors import ConflictError

                raise ConflictError(
                    f"branch version changed from {expected_branch_version} to {sequence}",
                    error_code="BRANCH_VERSION_CONFLICT",
                )
            previous_hash = str(row["last_event_hash"])
            for draft in drafts:
                sequence += 1
                event_id = new_id("evt")
                raw = {
                    "event_id": event_id,
                    "run_id": run_id,
                    "branch_id": branch_id,
                    "branch_seq": sequence,
                    **draft.model_dump(mode="json"),
                    "schema_version": "event.v0.2",
                    "schema_hash": EVENT_SCHEMA_HASH,
                    "prev_event_hash": previous_hash,
                }
                event_hash = "sha256:" + hashlib.sha256(canonical_json(raw).encode()).hexdigest()
                event = EventEnvelope(
                    event_id=event_id,
                    run_id=run_id,
                    branch_id=branch_id,
                    branch_seq=sequence,
                    prev_event_hash=previous_hash,
                    event_hash=event_hash,
                    **draft.model_dump(),
                )
                event_json = canonical_json(event.model_dump(mode="json"))
                connection.execute(
                    "INSERT INTO events(event_id,run_id,branch_id,branch_seq,sim_time_us,priority,tie_break_key,event_type,payload_json,event_json,event_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (event.event_id, run_id, branch_id, sequence, event.sim_time_us, event.priority, event.tie_break_key, event.event_type, canonical_json(event.payload), event_json, event_hash),
                )
                persisted.append(event)
                previous_hash = event_hash
            event_ids_by_action: dict[str, list[str]] = {}
            event_ids_by_decision: dict[str, list[str]] = {}
            for event in persisted:
                if event.action_id is not None:
                    event_ids_by_action.setdefault(event.action_id, []).append(event.event_id)
                decision_id = event.payload.get("decision_id")
                if isinstance(decision_id, str):
                    event_ids_by_decision.setdefault(decision_id, []).append(event.event_id)
            for receipt in action_receipts:
                if not receipt.get("authoritative_event_ids"):
                    receipt["authoritative_event_ids"] = event_ids_by_action.get(str(receipt["action_id"]), [])
            for record in agent_decisions:
                decision = record["decision"]
                outcome = record["outcome"]
                assert isinstance(decision, dict) and isinstance(outcome, dict)
                if not outcome.get("recorded_event_ids"):
                    outcome["recorded_event_ids"] = event_ids_by_decision.get(str(decision["decision_id"]), [])
            receipt_by_id = {str(item["receipt_id"]): item for item in action_receipts}
            for observation in observations:
                observation["action_receipts"] = [
                    receipt_by_id.get(str(item.get("receipt_id")), item)
                    for item in observation.get("action_receipts", [])
                ]
            if world_state is not None:
                world_state = dict(world_state)
                world_state["action_receipts"] = [
                    receipt_by_id.get(str(item.get("receipt_id")), item)
                    for item in world_state.get("action_receipts", [])
                ]
            if persisted:
                last = persisted[-1]
                connection.execute(
                    "UPDATE branches SET state_version=?, sim_time_us=?, last_event_hash=? WHERE branch_id=?",
                    (last.branch_seq, last.sim_time_us, last.event_hash, branch_id),
                )
            if world_state is not None:
                connection.execute(
                    "INSERT INTO branch_worlds(branch_id, world_json) VALUES(?,?) ON CONFLICT(branch_id) DO UPDATE SET world_json=excluded.world_json",
                    (branch_id, canonical_json(world_state)),
                )
            if branch_status is not None:
                connection.execute("UPDATE branches SET status=? WHERE branch_id=?", (branch_status, branch_id))
            for observation in observations:
                connection.execute(
                    "INSERT OR REPLACE INTO observations(observation_id,branch_id,agent_id,sim_time_us,observation_json) VALUES(?,?,?,?,?)",
                    (observation["observation_id"], branch_id, observation["agent_id"], observation["sim_time_us"], canonical_json(observation)),
                )
            for record in agent_decisions:
                decision = record["decision"]
                outcome = record["outcome"]
                assert isinstance(decision, dict) and isinstance(outcome, dict)
                connection.execute(
                    "INSERT INTO agent_decisions(decision_id,branch_id,agent_id,observation_id,sim_time_us,agent_revision,decision_json,outcome_json) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        decision["decision_id"],
                        branch_id,
                        decision["agent_id"],
                        decision["observation_id"],
                        decision["sim_time_us"],
                        outcome["resulting_agent_revision"],
                        canonical_json(decision),
                        canonical_json(outcome),
                    ),
                )
            for request in planning_requests:
                connection.execute(
                    "INSERT INTO planning_requests(request_id,branch_id,agent_id,state,terminal_outcome,activation_time_us,request_json,updated_at) VALUES(?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(request_id) DO UPDATE SET state=excluded.state,terminal_outcome=excluded.terminal_outcome,request_json=excluded.request_json,updated_at=excluded.updated_at",
                    (
                        request["request_id"], branch_id, request["agent_id"], request["state"],
                        request.get("terminal_outcome"), request["activation_time_us"], canonical_json(request), utc_now(),
                    ),
                )
            for record in strategy_plans:
                plan = record["plan"]
                assert isinstance(plan, dict)
                active = bool(record.get("active", True))
                if active:
                    connection.execute(
                        "UPDATE strategy_plans SET active=0 WHERE branch_id=? AND agent_id=?",
                        (branch_id, plan["agent_id"]),
                    )
                connection.execute(
                    "INSERT INTO strategy_plans(plan_id,branch_id,agent_id,strategy_revision,active,valid_from_sim_time_us,valid_until_sim_time_us,plan_json) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        plan["plan_id"], branch_id, plan["agent_id"], plan["strategy_revision"], int(active),
                        plan["valid_from_sim_time_us"], plan["valid_until_sim_time_us"], canonical_json(plan),
                    ),
                )
            for record in llm_records:
                connection.execute(
                    "INSERT INTO llm_records(call_id,request_id,agent_id,attempt,provider,model,status,record_json) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        record["call_id"], record["request_id"], record["agent_id"], record["attempt"],
                        record["provider"], record["model"], record["status"], canonical_json(record),
                    ),
                )
            for receipt in action_receipts:
                connection.execute(
                    "INSERT INTO action_receipts(receipt_id,action_id,branch_id,agent_id,sim_time_us,receipt_json) VALUES(?,?,?,?,?,?)",
                    (
                        receipt["receipt_id"], receipt["action_id"], branch_id, receipt["agent_id"],
                        receipt["resolved_sim_time_us"], canonical_json(receipt),
                    ),
                )
            if checkpoint is not None:
                connection.execute(
                    "INSERT INTO snapshots(checkpoint_id,run_id,branch_id,branch_seq,event_hash,snapshot_json) VALUES(?,?,?,?,?,?)",
                    (checkpoint["checkpoint_id"], run_id, branch_id, checkpoint["branch_seq"], checkpoint["event_hash"], canonical_json(checkpoint)),
                )
            if command_record is not None:
                result = dict(command_record["result"])
                if persisted:
                    result["cursor"] = persisted[-1].branch_seq
                if command_record.get("include_events"):
                    result["events"] = [event.model_dump(mode="json") for event in persisted]
                command_record["persisted_result"] = result
                connection.execute(
                    "INSERT INTO commands(command_id,branch_id,command_type,result_json,created_at) VALUES(?,?,?,?,?)",
                    (command_record["command_id"], branch_id, command_record["command_type"], canonical_json(result), utc_now()),
                )
        return persisted

    def list_events(self, branch_id: str, *, after: int = 0, limit: int = 200) -> list[EventEnvelope]:
        with self.store.locked() as connection:
            rows = connection.execute(
                "SELECT event_json FROM events WHERE branch_id=? AND branch_seq>? ORDER BY branch_seq LIMIT ?",
                (branch_id, after, limit),
            ).fetchall()
        return [EventEnvelope.model_validate(json.loads(row["event_json"])) for row in rows]

    def verify_chain(self, branch_id: str) -> bool:
        events = self.list_events(branch_id, limit=10_000_000)
        previous = "genesis"
        for event in events:
            if event.prev_event_hash != previous:
                return False
            raw = {
                "event_id": event.event_id,
                "run_id": event.run_id,
                "branch_id": event.branch_id,
                "branch_seq": event.branch_seq,
                **event.model_dump(exclude={"event_id", "run_id", "branch_id", "branch_seq", "schema_version", "schema_hash", "event_hash", "prev_event_hash"}),
                "schema_version": event.schema_version,
                "schema_hash": event.schema_hash,
                "prev_event_hash": previous,
            }
            expected = "sha256:" + hashlib.sha256(canonical_json(raw).encode()).hexdigest()
            if event.event_hash != expected:
                return False
            previous = event.event_hash
        return True
