from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sandbox.agents.llm_gateway import LLMGateway
from sandbox.agents.providers.openai import OpenAIProviderAdapter
from sandbox.contracts.scenario import PopulationConfig, ScenarioDraft
from sandbox.control.initialization import Initializer
from sandbox.control.run_manager import RunManager
from sandbox.core.ids import new_id
from sandbox.store.archive import ArchiveService
from sandbox.store.sqlite import SQLiteStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the opt-in 4-Agent OpenAI planning smoke test.")
    parser.add_argument("--preset", default="agent.smoke-openai.v0.1")
    parser.add_argument("--seed", type=int, default=20260724)
    parser.add_argument("--max-sim-seconds", type=int, default=90)
    parser.add_argument("--database", type=Path)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> dict[str, object]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for the live OpenAI smoke test")
    model = os.getenv("SANDBOX_OPENAI_MODEL", "gpt-5.6-terra")
    database = args.database or Path("data") / f"agent-smoke-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{new_id('db')[-8:]}.db"
    store = SQLiteStore(database)
    try:
        adapter = OpenAIProviderAdapter(
            api_key=api_key,
            model=model,
            timeout_seconds=int(os.getenv("SANDBOX_OPENAI_TIMEOUT_SECONDS", "30")),
            max_retries=int(os.getenv("SANDBOX_OPENAI_MAX_RETRIES", "1")),
            max_in_flight=min(4, int(os.getenv("SANDBOX_OPENAI_MAX_IN_FLIGHT", "4"))),
            max_output_tokens=int(os.getenv("SANDBOX_OPENAI_MAX_OUTPUT_TOKENS", "4096")),
        )
        gateway = LLMGateway({"openai": adapter}, max_in_flight=4)
        initializer = Initializer({}, gateway)
        manager = RunManager(store, initializer, ArchiveService(store, "0.3.0"), "0.3.0")
        preflight = await gateway.preflight("openai")
        scenario = manager.create_scenario(ScenarioDraft(
            name="4-Agent OpenAI smoke",
            mode="live_llm_smoke",
            seed=args.seed,
            target_token="TOKEN",
            llm_provider="openai",
            preset_version=args.preset,
            population=PopulationConfig(preset="smoke"),
        ))
        resolved = await manager.resolve_scenario(str(scenario["scenario_id"]))
        run_record = manager.create_run(str(scenario["scenario_id"]), resolved.resolution_hash)
        run_id = str(run_record["run_id"])
        branch_id = str(run_record["branches"][0]["branch_id"])
        manager.command(branch_id, "smoke-start", "start")
        run_result = manager.command(branch_id, "smoke-run", "run_for", {"max_requests": 4})
        checkpoint = manager.command(branch_id, "smoke-save", "save")
        child = manager.fork(branch_id, str(checkpoint["checkpoint_id"]), "smoke-fork")
        world = manager._world(branch_id)
        event_types = [event.event_type for event in manager.events.list_events(branch_id, limit=100_000)]
        decisions = store.connection.execute("SELECT COUNT(*) count FROM agent_decisions WHERE branch_id=?", (branch_id,)).fetchone()["count"]
        requests = store.connection.execute("SELECT COUNT(*) count FROM planning_requests WHERE branch_id=?", (branch_id,)).fetchone()["count"]
        plans = store.connection.execute("SELECT COUNT(*) count FROM strategy_plans WHERE branch_id=?", (branch_id,)).fetchone()["count"]
        receipts = store.connection.execute("SELECT COUNT(*) count FROM action_receipts WHERE branch_id=?", (branch_id,)).fetchone()["count"]
        llm_records = store.connection.execute("SELECT COUNT(*) count FROM llm_records").fetchone()["count"]
        return {
            "provider": preflight["provider"],
            "model": preflight["model"],
            "run_id": run_id,
            "branch_id": branch_id,
            "child_branch_id": child["branch_id"],
            "agent_ids": [item.agent_id for item in resolved.agent_definitions],
            "request_count": requests,
            "decision_count": decisions,
            "plan_count": plans,
            "outcome_count": decisions,
            "llm_record_count": llm_records,
            "accepted_actions": event_types.count("ActionAccepted"),
            "rejected_actions": event_types.count("ActionRejected"),
            "receipt_count": receipts,
            "final_cursor": manager.branch_projection(branch_id)["cursor"],
            "event_chain_valid": manager.events.verify_chain(branch_id),
            "asset_conservation": {
                resolved.market.base_asset: world.ledger.total(resolved.market.base_asset) == resolved.total_supply[resolved.market.base_asset],
                resolved.market.quote_asset: world.ledger.total(resolved.market.quote_asset) == resolved.total_supply[resolved.market.quote_asset],
            },
            "run_result": run_result,
            "database_path": str(database.resolve()),
        }
    finally:
        store.close()


def main() -> int:
    args = parse_args()
    try:
        result = asyncio.run(run(args))
    except RuntimeError as error:
        print(json.dumps({"ok": False, "error": str(error), "hint": "Set OPENAI_API_KEY and optionally SANDBOX_OPENAI_MODEL, then rerun."}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
