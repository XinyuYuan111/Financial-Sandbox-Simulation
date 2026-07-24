from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from sandbox.contracts.event import EventEnvelope
from sandbox.contracts.agent import ActionReceipt, AgentDecision, AgentDefinition, DecisionOutcome
from sandbox.contracts.observation import ObservationPacket
from sandbox.contracts.planning import LLMRecord, PlanningRequest, StrategyPlan
from sandbox.contracts.scenario import ResolvedInitialState
from sandbox.contracts.snapshot import ArchiveManifest
from sandbox.core.errors import ValidationError
from sandbox.store.event_store import canonical_json
from sandbox.store.sqlite import SQLiteStore


class ArchiveService:
    def __init__(self, store: SQLiteStore, runtime_version: str) -> None:
        self.store = store
        self.runtime_version = runtime_version

    def export_run(self, run_id: str, output_path: Path) -> ArchiveManifest:
        run = self.store.connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        branches = self.store.connection.execute("SELECT * FROM branches WHERE run_id=? ORDER BY created_at", (run_id,)).fetchall()
        if run is None or not branches:
            raise ValidationError("run has no persisted state")
        files: dict[str, bytes] = {}
        files["config/resolved_scenario.json"] = str(run["resolved_state_json"]).encode()
        branch_records = [dict(branch) for branch in branches]
        files["branches.json"] = canonical_json(branch_records).encode()
        resolved = ResolvedInitialState.model_validate_json(str(run["resolved_state_json"]))
        files["agents/definitions.json"] = canonical_json(
            [item.model_dump(mode="json") for item in resolved.agent_definitions]
        ).encode()
        for branch in branches:
            rows = self.store.connection.execute("SELECT event_json FROM events WHERE branch_id=? ORDER BY branch_seq", (branch["branch_id"],)).fetchall()
            files[f"events/branch_{branch['branch_id']}.jsonl"] = ("\n".join(row["event_json"] for row in rows) + "\n").encode()
            observations = self.store.connection.execute("SELECT observation_json FROM observations WHERE branch_id=? ORDER BY sim_time_us, observation_id", (branch["branch_id"],)).fetchall()
            files[f"observations/branch_{branch['branch_id']}.jsonl"] = ("\n".join(row["observation_json"] for row in observations) + "\n").encode()
            decisions = self.store.connection.execute(
                "SELECT decision_json,outcome_json FROM agent_decisions WHERE branch_id=? ORDER BY sim_time_us,decision_id",
                (branch["branch_id"],),
            ).fetchall()
            files[f"agents/decisions/{branch['branch_id']}.jsonl"] = (
                "\n".join(canonical_json({"decision": json.loads(row["decision_json"]), "outcome": json.loads(row["outcome_json"])}) for row in decisions) + "\n"
            ).encode()
            plans = self.store.connection.execute(
                "SELECT plan_json,active FROM strategy_plans WHERE branch_id=? ORDER BY agent_id,strategy_revision",
                (branch["branch_id"],),
            ).fetchall()
            files[f"agents/plans/{branch['branch_id']}.jsonl"] = (
                "\n".join(canonical_json({"plan": json.loads(row["plan_json"]), "active": bool(row["active"])}) for row in plans) + "\n"
            ).encode()
            requests = self.store.connection.execute(
                "SELECT request_json FROM planning_requests WHERE branch_id=? ORDER BY agent_id,activation_time_us,request_id",
                (branch["branch_id"],),
            ).fetchall()
            files[f"agents/planning_requests/{branch['branch_id']}.jsonl"] = (
                "\n".join(row["request_json"] for row in requests) + "\n"
            ).encode()
            receipts = self.store.connection.execute(
                "SELECT receipt_json FROM action_receipts WHERE branch_id=? ORDER BY sim_time_us,receipt_id",
                (branch["branch_id"],),
            ).fetchall()
            files[f"actions/receipts/{branch['branch_id']}.jsonl"] = (
                "\n".join(row["receipt_json"] for row in receipts) + "\n"
            ).encode()
            snapshot = self.store.connection.execute("SELECT checkpoint_id,snapshot_json FROM snapshots WHERE branch_id=? ORDER BY branch_seq DESC LIMIT 1", (branch["branch_id"],)).fetchone()
            if snapshot is None:
                raise ValidationError(f"branch {branch['branch_id']} must be checkpointed before export")
            files[f"checkpoints/{snapshot['checkpoint_id']}.json"] = str(snapshot["snapshot_json"]).encode()
        llm_rows = self.store.connection.execute(
            "SELECT DISTINCT lr.record_json FROM llm_records lr JOIN planning_requests pr ON pr.request_id=lr.request_id JOIN branches b ON b.branch_id=pr.branch_id WHERE b.run_id=? ORDER BY lr.request_id,lr.attempt",
            (run_id,),
        ).fetchall()
        files["llm/records.jsonl"] = ("\n".join(row["record_json"] for row in llm_rows) + "\n").encode()
        hashes = {name: "sha256:" + hashlib.sha256(content).hexdigest() for name, content in files.items()}
        manifest = ArchiveManifest(
            runtime_version=self.runtime_version,
            run_id=run_id,
            root_branch_id=branches[0]["branch_id"],
            included_branches=[branch["branch_id"] for branch in branches],
            file_hashes=hashes,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", canonical_json(manifest.model_dump(mode="json")))
            for name, content in files.items():
                archive.writestr(name, content)
        return manifest

    def validate_archive(self, path: Path) -> ArchiveManifest:
        if path.stat().st_size > 250 * 1024 * 1024:
            raise ValidationError("archive exceeds the import size limit")
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) > 10_000 or any(name.startswith("/") or ".." in Path(name).parts for name in names):
                raise ValidationError("archive contains unsafe paths")
            expanded_size = sum(item.file_size for item in archive.infolist())
            if expanded_size > 1024 * 1024 * 1024 or any(item.file_size > 250 * 1024 * 1024 for item in archive.infolist()):
                raise ValidationError("archive expanded content exceeds the import limit")
            if any(item.flag_bits & 0x1 for item in archive.infolist()):
                raise ValidationError("encrypted archive members are not supported")
            manifest = ArchiveManifest.model_validate(json.loads(archive.read("manifest.json")))
            for name, expected in manifest.file_hashes.items():
                if name not in names:
                    raise ValidationError(f"archive is missing {name}")
                actual = "sha256:" + hashlib.sha256(archive.read(name)).hexdigest()
                if actual != expected:
                    raise ValidationError(f"hash mismatch for {name}")
                lowered = archive.read(name).lower()
                if b"openai_api_key" in lowered or b"authorization:" in lowered or b"bearer sk-" in lowered:
                    raise ValidationError(f"archive member {name} contains secret material")
            for branch_id in manifest.included_branches:
                event_name = f"events/branch_{branch_id}.jsonl"
                if event_name not in names:
                    raise ValidationError(f"archive is missing {event_name}")
                previous_hash = "genesis"
                expected_sequence = 1
                for line in archive.read(event_name).decode().splitlines():
                    if not line:
                        continue
                    event = EventEnvelope.model_validate(json.loads(line))
                    if event.branch_id != branch_id or event.run_id != manifest.run_id:
                        raise ValidationError(f"event ownership mismatch in {event_name}")
                    if event.branch_seq != expected_sequence or event.prev_event_hash != previous_hash:
                        raise ValidationError(f"event chain continuity failed in {event_name}")
                    raw = {
                        "event_id": event.event_id,
                        "run_id": event.run_id,
                        "branch_id": event.branch_id,
                        "branch_seq": event.branch_seq,
                        **event.model_dump(exclude={"event_id", "run_id", "branch_id", "branch_seq", "schema_version", "schema_hash", "event_hash", "prev_event_hash"}),
                        "schema_version": event.schema_version,
                        "schema_hash": event.schema_hash,
                        "prev_event_hash": previous_hash,
                    }
                    calculated = "sha256:" + hashlib.sha256(canonical_json(raw).encode()).hexdigest()
                    if calculated != event.event_hash:
                        raise ValidationError(f"event hash mismatch in {event_name}")
                    previous_hash = event.event_hash
                    expected_sequence += 1
            return manifest

    def import_run(self, path: Path) -> dict[str, object]:
        manifest = self.validate_archive(path)
        if manifest.runtime_version != self.runtime_version:
            raise ValidationError("cross-version archive import is not supported")
        existing = self.store.connection.execute("SELECT run_id FROM runs WHERE run_id=?", (manifest.run_id,)).fetchone()
        if existing is not None:
            return {"run_id": manifest.run_id, "already_present": True, "manifest": manifest.model_dump(mode="json")}
        with zipfile.ZipFile(path) as archive:
            resolved = ResolvedInitialState.model_validate(json.loads(archive.read("config/resolved_scenario.json")))
            definitions_name = "agents/definitions.json"
            if definitions_name in archive.namelist():
                [AgentDefinition.model_validate(item) for item in json.loads(archive.read(definitions_name))]
            branches = json.loads(archive.read("branches.json"))
            checkpoints: dict[str, dict[str, object]] = {}
            for name in archive.namelist():
                if name.startswith("checkpoints/") and name.endswith(".json"):
                    checkpoint = json.loads(archive.read(name))
                    checkpoints[str(checkpoint["branch_id"])] = checkpoint
            with self.store.transaction() as connection:
                scenario_id = resolved.scenario_id
                connection.execute(
                    "INSERT OR IGNORE INTO scenarios(scenario_id,draft_json,resolved_json,created_at) VALUES(?,?,?,?)",
                    (scenario_id, canonical_json({"name": resolved.name, "mode": resolved.mode, "seed": resolved.seed, "target_token": resolved.market.base_asset}), canonical_json(resolved.model_dump(mode="json")), "archive-import"),
                )
                connection.execute(
                    "INSERT INTO runs(run_id,scenario_id,name,status,runtime_version,resolved_state_json,created_at) VALUES(?,?,?,?,?,?,?)",
                    (manifest.run_id, scenario_id, resolved.name, "Checkpointed", manifest.runtime_version, canonical_json(resolved.model_dump(mode="json")), "archive-import"),
                )
                for branch in branches:
                    branch_id = str(branch["branch_id"])
                    checkpoint = checkpoints.get(branch_id)
                    if checkpoint is None:
                        raise ValidationError(f"archive has no checkpoint for branch {branch_id}")
                    connection.execute(
                        "INSERT INTO branches(branch_id,run_id,parent_branch_id,fork_checkpoint_id,status,sim_time_us,state_version,last_event_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (branch_id, manifest.run_id, branch.get("parent_branch_id"), branch.get("fork_checkpoint_id"), "Checkpointed", branch["sim_time_us"], branch["state_version"], branch["last_event_hash"], branch.get("created_at", "archive-import")),
                    )
                    connection.execute("INSERT INTO branch_worlds(branch_id,world_json) VALUES(?,?)", (branch_id, canonical_json(checkpoint["state"])))
                    connection.execute(
                        "INSERT INTO snapshots(checkpoint_id,run_id,branch_id,branch_seq,event_hash,snapshot_json) VALUES(?,?,?,?,?,?)",
                        (checkpoint["checkpoint_id"], manifest.run_id, branch_id, checkpoint["branch_seq"], checkpoint["event_hash"], canonical_json(checkpoint)),
                    )
                    event_name = f"events/branch_{branch_id}.jsonl"
                    for line in archive.read(event_name).decode().splitlines():
                        if not line:
                            continue
                        event = EventEnvelope.model_validate(json.loads(line))
                        connection.execute(
                            "INSERT INTO events(event_id,run_id,branch_id,branch_seq,sim_time_us,priority,tie_break_key,event_type,payload_json,event_json,event_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (event.event_id, event.run_id, event.branch_id, event.branch_seq, event.sim_time_us, event.priority, event.tie_break_key, event.event_type, canonical_json(event.payload), canonical_json(event.model_dump(mode="json")), event.event_hash),
                        )
                    observation_name = f"observations/branch_{branch_id}.jsonl"
                    if observation_name in archive.namelist():
                        for line in archive.read(observation_name).decode().splitlines():
                            if not line:
                                continue
                            observation = ObservationPacket.model_validate(json.loads(line))
                            connection.execute(
                                "INSERT INTO observations(observation_id,branch_id,agent_id,sim_time_us,observation_json) VALUES(?,?,?,?,?)",
                                (observation.observation_id, branch_id, observation.agent_id, observation.sim_time_us, canonical_json(observation.model_dump(mode="json"))),
                            )
                    decisions_name = f"agents/decisions/{branch_id}.jsonl"
                    if decisions_name in archive.namelist():
                        for line in archive.read(decisions_name).decode().splitlines():
                            if not line:
                                continue
                            record = json.loads(line)
                            decision = AgentDecision.model_validate(record["decision"])
                            outcome = DecisionOutcome.model_validate(record["outcome"])
                            connection.execute(
                                "INSERT INTO agent_decisions(decision_id,branch_id,agent_id,observation_id,sim_time_us,agent_revision,decision_json,outcome_json) VALUES(?,?,?,?,?,?,?,?)",
                                (decision.decision_id, branch_id, decision.agent_id, decision.observation_id, decision.sim_time_us, outcome.resulting_agent_revision, canonical_json(decision.model_dump(mode="json")), canonical_json(outcome.model_dump(mode="json"))),
                            )
                    requests_name = f"agents/planning_requests/{branch_id}.jsonl"
                    if requests_name in archive.namelist():
                        for line in archive.read(requests_name).decode().splitlines():
                            if not line:
                                continue
                            planning = PlanningRequest.model_validate(json.loads(line))
                            connection.execute(
                                "INSERT INTO planning_requests(request_id,branch_id,agent_id,state,terminal_outcome,activation_time_us,request_json,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                                (planning.request_id, branch_id, planning.agent_id, planning.state, planning.terminal_outcome, planning.activation_time_us, canonical_json(planning.model_dump(mode="json")), "archive-import"),
                            )
                    plans_name = f"agents/plans/{branch_id}.jsonl"
                    if plans_name in archive.namelist():
                        for line in archive.read(plans_name).decode().splitlines():
                            if not line:
                                continue
                            record = json.loads(line)
                            plan = StrategyPlan.model_validate(record["plan"])
                            connection.execute(
                                "INSERT INTO strategy_plans(plan_id,branch_id,agent_id,strategy_revision,active,valid_from_sim_time_us,valid_until_sim_time_us,plan_json) VALUES(?,?,?,?,?,?,?,?)",
                                (plan.plan_id, branch_id, plan.agent_id, plan.strategy_revision, int(bool(record["active"])), plan.valid_from_sim_time_us, plan.valid_until_sim_time_us, canonical_json(plan.model_dump(mode="json"))),
                            )
                    receipts_name = f"actions/receipts/{branch_id}.jsonl"
                    if receipts_name in archive.namelist():
                        for line in archive.read(receipts_name).decode().splitlines():
                            if not line:
                                continue
                            receipt = ActionReceipt.model_validate(json.loads(line))
                            connection.execute(
                                "INSERT INTO action_receipts(receipt_id,action_id,branch_id,agent_id,sim_time_us,receipt_json) VALUES(?,?,?,?,?,?)",
                                (receipt.receipt_id, receipt.action_id, branch_id, receipt.agent_id, receipt.resolved_sim_time_us, canonical_json(receipt.model_dump(mode="json"))),
                            )
                llm_name = "llm/records.jsonl"
                if llm_name in archive.namelist():
                    for line in archive.read(llm_name).decode().splitlines():
                        if not line:
                            continue
                        record = LLMRecord.model_validate(json.loads(line))
                        connection.execute(
                            "INSERT INTO llm_records(call_id,request_id,agent_id,attempt,provider,model,status,record_json) VALUES(?,?,?,?,?,?,?,?)",
                            (record.call_id, record.request_id, record.agent_id, record.attempt, record.provider, record.model, record.status, canonical_json(record.model_dump(mode="json"))),
                        )
        return {"run_id": manifest.run_id, "already_present": False, "manifest": manifest.model_dump(mode="json")}
