from __future__ import annotations

import sqlite3
import threading
import hashlib
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


BASE_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS scenarios (
  scenario_id TEXT PRIMARY KEY,
  draft_json TEXT NOT NULL,
  resolved_json TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  scenario_id TEXT NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL,
  runtime_version TEXT NOT NULL,
  resolved_state_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS branches (
  branch_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  parent_branch_id TEXT,
  fork_checkpoint_id TEXT,
  status TEXT NOT NULL,
  sim_time_us INTEGER NOT NULL DEFAULT 0,
  state_version INTEGER NOT NULL DEFAULT 0,
  last_event_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  branch_id TEXT NOT NULL REFERENCES branches(branch_id),
  branch_seq INTEGER NOT NULL,
  sim_time_us INTEGER NOT NULL,
  priority INTEGER NOT NULL,
  tie_break_key TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  event_json TEXT NOT NULL,
  event_hash TEXT NOT NULL,
  UNIQUE(branch_id, branch_seq)
);
CREATE TABLE IF NOT EXISTS snapshots (
  checkpoint_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  branch_id TEXT NOT NULL REFERENCES branches(branch_id),
  branch_seq INTEGER NOT NULL,
  event_hash TEXT NOT NULL,
  snapshot_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS commands (
  command_id TEXT PRIMARY KEY,
  branch_id TEXT NOT NULL,
  command_type TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observations (
  observation_id TEXT PRIMARY KEY,
  branch_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  sim_time_us INTEGER NOT NULL,
  observation_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS branch_worlds (
  branch_id TEXT PRIMARY KEY REFERENCES branches(branch_id),
  world_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  checksum TEXT NOT NULL,
  applied_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_branch_seq ON events(branch_id, branch_seq);
CREATE INDEX IF NOT EXISTS idx_observations_agent ON observations(branch_id, agent_id, sim_time_us);
"""


AGENT_V0_1_MIGRATION = """
CREATE TABLE IF NOT EXISTS agent_decisions (
  decision_id TEXT PRIMARY KEY,
  branch_id TEXT NOT NULL REFERENCES branches(branch_id),
  agent_id TEXT NOT NULL,
  observation_id TEXT NOT NULL,
  sim_time_us INTEGER NOT NULL,
  agent_revision INTEGER NOT NULL,
  decision_json TEXT NOT NULL,
  outcome_json TEXT NOT NULL,
  UNIQUE(branch_id, agent_id, observation_id)
);
CREATE TABLE IF NOT EXISTS planning_requests (
  request_id TEXT PRIMARY KEY,
  branch_id TEXT NOT NULL REFERENCES branches(branch_id),
  agent_id TEXT NOT NULL,
  state TEXT NOT NULL,
  terminal_outcome TEXT,
  activation_time_us INTEGER NOT NULL,
  request_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strategy_plans (
  plan_id TEXT PRIMARY KEY,
  branch_id TEXT NOT NULL REFERENCES branches(branch_id),
  agent_id TEXT NOT NULL,
  strategy_revision INTEGER NOT NULL,
  active INTEGER NOT NULL DEFAULT 0,
  valid_from_sim_time_us INTEGER NOT NULL,
  valid_until_sim_time_us INTEGER NOT NULL,
  plan_json TEXT NOT NULL,
  UNIQUE(branch_id, agent_id, strategy_revision)
);
CREATE TABLE IF NOT EXISTS llm_records (
  call_id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  status TEXT NOT NULL,
  record_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS action_receipts (
  receipt_id TEXT PRIMARY KEY,
  action_id TEXT NOT NULL,
  branch_id TEXT NOT NULL REFERENCES branches(branch_id),
  agent_id TEXT NOT NULL,
  sim_time_us INTEGER NOT NULL,
  receipt_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_history ON agent_decisions(branch_id, agent_id, sim_time_us);
CREATE INDEX IF NOT EXISTS idx_planning_requests_state ON planning_requests(branch_id, agent_id, state);
CREATE UNIQUE INDEX IF NOT EXISTS idx_planning_requests_one_open
  ON planning_requests(branch_id, agent_id) WHERE state != 'Terminal';
CREATE INDEX IF NOT EXISTS idx_strategy_plans_history ON strategy_plans(branch_id, agent_id, strategy_revision);
CREATE INDEX IF NOT EXISTS idx_llm_records_request ON llm_records(request_id, attempt);
CREATE INDEX IF NOT EXISTS idx_action_receipts_history ON action_receipts(branch_id, agent_id, sim_time_us);
CREATE INDEX IF NOT EXISTS idx_action_receipts_action ON action_receipts(action_id);
"""


INTERVENTION_V0_1_MIGRATION = """
CREATE TABLE IF NOT EXISTS intervention_plans (
  plan_id TEXT PRIMARY KEY,
  branch_id TEXT NOT NULL REFERENCES branches(branch_id),
  status TEXT NOT NULL,
  base_world_revision INTEGER NOT NULL,
  created_branch_seq INTEGER NOT NULL,
  plan_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_intervention_plans_branch
  ON intervention_plans(branch_id, created_branch_seq, plan_id);
CREATE INDEX IF NOT EXISTS idx_intervention_plans_due
  ON intervention_plans(branch_id, status);
"""


DEFERRED_PLANNING_RESULT_MIGRATION = """
CREATE TABLE IF NOT EXISTS planning_results (
  request_id TEXT PRIMARY KEY REFERENCES planning_requests(request_id),
  branch_id TEXT NOT NULL REFERENCES branches(branch_id),
  result_status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  applied INTEGER NOT NULL DEFAULT 0,
  received_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_planning_results_pending
  ON planning_results(branch_id, applied, request_id);
"""


MIGRATIONS = (
    ("0001_agent_v0_1", AGENT_V0_1_MIGRATION),
    ("0002_intervention_v0_1", INTERVENTION_V0_1_MIGRATION),
    ("0003_deferred_planning_result", DEFERRED_PLANNING_RESULT_MIGRATION),
)


class SQLiteStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self._transaction_lock = threading.RLock()
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(BASE_SCHEMA)
        self._apply_migrations()
        self.connection.commit()

    def _apply_migrations(self) -> None:
        for version, script in MIGRATIONS:
            checksum = "sha256:" + hashlib.sha256(script.encode()).hexdigest()
            existing = self.connection.execute(
                "SELECT checksum FROM schema_migrations WHERE version=?", (version,)
            ).fetchone()
            if existing is not None:
                if existing["checksum"] != checksum:
                    raise RuntimeError(f"database migration checksum mismatch for {version}")
                continue
            self.connection.executescript(script)
            self.connection.execute(
                "INSERT INTO schema_migrations(version,checksum,applied_at) VALUES(?,?,datetime('now'))",
                (version, checksum),
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._transaction_lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                yield self.connection
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise

    @contextmanager
    def locked(self) -> Iterator[sqlite3.Connection]:
        with self._transaction_lock:
            yield self.connection

    def close(self) -> None:
        self.connection.close()
