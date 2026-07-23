from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
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
CREATE INDEX IF NOT EXISTS idx_events_branch_seq ON events(branch_id, branch_seq);
CREATE INDEX IF NOT EXISTS idx_observations_agent ON observations(branch_id, agent_id, sim_time_us);
"""


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
        self.connection.executescript(SCHEMA)
        self.connection.commit()

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
