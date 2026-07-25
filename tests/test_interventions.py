from __future__ import annotations

import asyncio
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from sandbox.agents.llm_gateway import LLMGateway
from sandbox.contracts.intervention import DirectorAccessScope, DirectorPlanCandidate, InterventionPlanDraftInput
from sandbox.contracts.agent import DecisionRationale
from sandbox.contracts.planning import LLMRecord, PlanningResultCandidate, ProviderProfile
from sandbox.contracts.scenario import ScenarioDraft
from sandbox.control.initialization import Initializer
from sandbox.control.run_manager import RunManager
from sandbox.core.errors import ConflictError, ValidationError
from sandbox.store.archive import ArchiveService
from sandbox.store.sqlite import SQLiteStore


class BlockingPlanningAdapter:
    name = "openai"
    profile = ProviderProfile(
        provider="openai",
        model="blocking-test",
        timeout_seconds=5,
        max_retries=0,
        max_in_flight=1,
        max_output_tokens=128,
        key_present=True,
    )

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    async def preflight(self) -> dict[str, object]:
        return {"ok": True, "provider": "openai"}

    async def create_plan(self, request, *, record_raw=None):
        self.started.set()
        released = await asyncio.to_thread(self.release.wait, 5)
        if not released:
            raise RuntimeError("test planning adapter was not released")
        return PlanningResultCandidate(
            based_on_strategy_revision=0,
            valid_for_us=1_000_000,
            goals=[],
            activation_preconditions=[],
            constraints=[],
            directives=[],
            replan_conditions=[],
            rationale=DecisionRationale(stated_reason="Deferred hold plan"),
        )


class TypedDirectorAdapter:
    def __init__(self, provider: str = "openai") -> None:
        self.name = provider
        self.provider = provider
        self.profile = BlockingPlanningAdapter.profile.model_copy(update={
            "provider": provider,
            "model": f"{provider}-director-test",
        })
        self.request = None

    async def preflight(self) -> dict[str, object]:
        return {"ok": True, "provider": self.provider}

    async def create_intervention_plan(self, request, *, record_raw=None):
        self.request = request
        if record_raw is not None:
            record_raw(LLMRecord(
                call_id="llm-director-test",
                request_id=request.request_id,
                agent_id="scenario_director",
                attempt=1,
                provider=self.provider,
                model=self.profile.model,
                context_hash=request.context_hash,
                redacted_request={"request_id": request.request_id, "context_hash": request.context_hash},
                raw_response={"typed": True},
                latency_ms=1,
                status="succeeded",
            ))
        return DirectorPlanCandidate(
            stages=[{
                "stage_id": "stage-ai",
                "effective_sim_time_us": request.requested_effective_time_us,
                "background_order_flow_impact_milli": -700,
                "effects": [{
                    "effect_id": "effect-ai-halt",
                    "effect_type": "set_market_status",
                    "market_id": "TOKEN-USDX",
                    "status": "halted",
                    "reason_code": "ai_director_test",
                }],
            }],
            rationale="A bounded market halt candidate.",
        )


class InterventionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = SQLiteStore(self.root / "sandbox.db")
        self.manager = RunManager(
            self.store,
            Initializer({}, LLMGateway({})),
            ArchiveService(self.store, "0.2.0"),
            "0.2.0",
        )
        scenario = self.manager.create_scenario(ScenarioDraft())
        resolved = asyncio.run(self.manager.resolve_scenario(str(scenario["scenario_id"])))
        run = self.manager.create_run(str(scenario["scenario_id"]), resolved.resolution_hash)
        self.run_id = str(run["run_id"])
        self.branch_id = str(run["branches"][0]["branch_id"])

    def tearDown(self) -> None:
        self.manager.close()
        self.store.close()
        self.temp.cleanup()

    @staticmethod
    def draft(*, sim_time_us: int, effects: list[dict[str, object]], intent: str = "Apply a controlled shock", **extra: object) -> InterventionPlanDraftInput:
        return InterventionPlanDraftInput.model_validate({
            "user_intent": intent,
            "access_scope": extra.get("access_scope", {"private_grants": []}),
            "private_read_refs": extra.get("private_read_refs", []),
            "stages": [{
                "stage_id": "stage-1",
                "effective_sim_time_us": sim_time_us,
                "effects": effects,
            }],
        })

    def pause(self) -> None:
        self.manager.command(self.branch_id, "start", "start")
        first = self.manager.command(self.branch_id, "pause-1", "pause")
        second = self.manager.command(self.branch_id, "pause-2", "pause")
        self.assertEqual(first["status"], "Paused")
        self.assertEqual(second["status"], "Paused")
        self.assertEqual(first["cursor"], second["cursor"])

    def test_contract_is_closed_and_director_requires_paused_branch(self) -> None:
        with self.assertRaises(PydanticValidationError):
            self.draft(sim_time_us=0, effects=[{"effect_id": "effect-1", "effect_type": "json_patch", "path": "/ledger"}])
        draft = self.draft(sim_time_us=0, effects=[{
            "effect_id": "effect-1", "effect_type": "set_market_status",
            "market_id": "TOKEN-USDX", "status": "halted", "reason_code": "test",
        }])
        with self.assertRaises(ConflictError):
            self.manager.create_intervention_plan(self.branch_id, "draft-running", draft)

    def test_mixed_current_stage_is_atomic_and_agents_wait_for_resume(self) -> None:
        self.pause()
        revisions_before = {
            item["agent_id"]: item["agent_revision"]
            for item in self.manager.agents(self.branch_id)
        }
        draft = self.draft(sim_time_us=0, effects=[
            {
                "effect_id": "effect-state", "effect_type": "set_market_status",
                "market_id": "TOKEN-USDX", "status": "halted", "reason_code": "venue_incident",
            },
            {
                "effect_id": "effect-info", "effect_type": "publish_information",
                "source_id": "scenario_director", "channel": "OfficialAnnouncement",
                "content": "Trading is halted.", "target_ids": [],
                "depends_on_state_effect_ids": ["effect-state"], "private_source_refs": [],
            },
        ])
        created = self.manager.create_intervention_plan(self.branch_id, "draft-mixed", draft)
        result = self.manager.confirm_intervention_plan(self.branch_id, str(created["plan_id"]), "confirm-mixed")
        self.assertEqual(result["status"], "completed")
        projection = self.manager.branch_projection(self.branch_id)
        self.assertEqual(projection["market_status"], "halted")
        self.assertEqual(projection["deferred_observation_count"], 3)
        self.assertEqual(
            {item["agent_id"]: item["agent_revision"] for item in self.manager.agents(self.branch_id)},
            revisions_before,
        )
        related = [
            event.event_type
            for event in self.manager.events.list_events(self.branch_id)
            if event.correlation_id == created["plan_id"]
        ]
        self.assertLess(related.index("MarketStatusChanged"), related.index("InformationPublished"))
        self.assertLess(related.index("InformationPublished"), related.index("InterventionStageApplied"))
        resumed = self.manager.command(self.branch_id, "resume-after-intervention", "start")
        self.assertEqual(resumed["processed_observations"], 3)
        self.assertEqual(self.manager.branch_projection(self.branch_id)["deferred_observation_count"], 0)
        self.assertTrue(all(
            item["agent_revision"] > revisions_before[item["agent_id"]]
            for item in self.manager.agents(self.branch_id)
        ))

    def test_revalidation_prevents_partial_state_or_information_commit(self) -> None:
        self.pause()
        world = self.manager._world(self.branch_id)
        available = world.ledger.balance("rule_alpha", "TOKEN")
        first = self.draft(sim_time_us=0, effects=[
            {
                "effect_id": "transfer-later", "effect_type": "transfer_asset",
                "from_owner_id": "rule_alpha", "to_owner_id": "rule_beta", "asset": "TOKEN",
                "amount": available, "reason_code": "first_plan", "required_relationship_ids": [],
            },
            {
                "effect_id": "announce-later", "effect_type": "publish_information",
                "source_id": "scenario_director", "channel": "OfficialAnnouncement",
                "content": "First transfer completed.", "target_ids": [],
                "depends_on_state_effect_ids": ["transfer-later"], "private_source_refs": [],
            },
        ])
        first_plan = self.manager.create_intervention_plan(self.branch_id, "draft-first", first)
        competing = self.draft(sim_time_us=0, effects=[{
            "effect_id": "drain", "effect_type": "transfer_asset",
            "from_owner_id": "rule_alpha", "to_owner_id": "rule_beta", "asset": "TOKEN",
            "amount": 1, "reason_code": "competing_plan", "required_relationship_ids": [],
        }])
        competing_plan = self.manager.create_intervention_plan(self.branch_id, "draft-competing", competing)
        self.manager.confirm_intervention_plan(self.branch_id, str(competing_plan["plan_id"]), "confirm-competing")
        info_before = len(self.manager.branch_projection(self.branch_id)["information"])
        with self.assertRaises(ValidationError):
            self.manager.confirm_intervention_plan(self.branch_id, str(first_plan["plan_id"]), "confirm-first")
        after = self.manager._world(self.branch_id)
        self.assertEqual(after.ledger.balance("rule_alpha", "TOKEN"), available - 1)
        self.assertEqual(len(self.manager.branch_projection(self.branch_id)["information"]), info_before)
        self.assertEqual(self.manager.intervention_plan(self.branch_id, str(first_plan["plan_id"]))["status"], "draft")

    def test_private_reads_are_scoped_and_revisioned(self) -> None:
        self.pause()
        effect = {
            "effect_id": "private-info", "effect_type": "publish_information",
            "source_id": "scenario_director", "channel": "PrivateChannel", "content": "Scoped disclosure",
            "target_ids": ["rule_beta"], "depends_on_state_effect_ids": [],
            "private_source_refs": [{"category": "belief", "target_id": "rule_alpha"}],
        }
        unauthorized = self.draft(
            sim_time_us=0,
            effects=[effect],
            private_read_refs=[{"category": "belief", "target_id": "rule_alpha"}],
        )
        with self.assertRaises(ValidationError):
            self.manager.create_intervention_plan(self.branch_id, "private-denied", unauthorized)
        authorized = self.draft(
            sim_time_us=0,
            effects=[effect],
            access_scope={"private_grants": [{"category": "belief", "target_ids": ["rule_alpha"], "purpose": "Targeted disclosure"}]},
            private_read_refs=[{"category": "belief", "target_id": "rule_alpha"}],
        )
        created = self.manager.create_intervention_plan(self.branch_id, "private-allowed", authorized)
        record = created["plan"]["actual_private_reads"][0]
        self.assertEqual((record["category"], record["target_id"]), ("belief", "rule_alpha"))
        self.assertIsInstance(record["state_revision"], int)

    def test_private_information_intervention_uses_the_delivery_queue(self) -> None:
        self.pause()
        draft = self.draft(sim_time_us=0, effects=[{
            "effect_id": "delayed-private-info", "effect_type": "publish_information",
            "source_id": "scenario_director", "channel": "PrivateChannel",
            "content": "Delivered only after channel latency.", "target_ids": ["rule_beta"],
            "depends_on_state_effect_ids": [], "private_source_refs": [],
        }])
        created = self.manager.create_intervention_plan(self.branch_id, "draft-delayed-private", draft)
        self.manager.confirm_intervention_plan(self.branch_id, str(created["plan_id"]), "confirm-delayed-private")
        projection = self.manager.branch_projection(self.branch_id)
        self.assertEqual(projection["deferred_observation_count"], 0)
        self.assertEqual(projection["pending_delivery_count"], 1)
        related = [
            event for event in self.manager.events.list_events(self.branch_id, limit=10_000)
            if event.correlation_id == created["plan_id"]
        ]
        self.assertTrue(any(event.event_type == "InformationPublished" for event in related))
        self.assertFalse(any(event.event_type == "PrivateMessageDelivered" for event in related))

        self.manager.command(self.branch_id, "resume-delayed-private", "start")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if self.manager.branch_projection(self.branch_id)["pending_delivery_count"] == 0:
                break
            time.sleep(0.02)
        self.assertEqual(self.manager.branch_projection(self.branch_id)["pending_delivery_count"], 0)
        related = [
            event for event in self.manager.events.list_events(self.branch_id, limit=10_000)
            if event.correlation_id == created["plan_id"]
        ]
        delivered = next(event for event in related if event.event_type == "PrivateMessageDelivered")
        self.assertEqual(delivered.payload["target_id"], "rule_beta")
        self.assertGreater(delivered.sim_time_us, 0)

    def test_information_intervention_cannot_impersonate_an_agent(self) -> None:
        self.pause()
        draft = self.draft(sim_time_us=0, effects=[{
            "effect_id": "fake-agent-news", "effect_type": "publish_information",
            "source_id": "rule_alpha", "channel": "OfficialAnnouncement",
            "content": "This was not authored by the Agent.", "target_ids": [],
            "depends_on_state_effect_ids": [], "private_source_refs": [],
        }])
        with self.assertRaises(ValidationError):
            self.manager.create_intervention_plan(self.branch_id, "draft-impersonation", draft)

    def test_wallet_access_is_visible_in_the_grantee_observation(self) -> None:
        self.pause()
        expected_balance = self.manager._world(self.branch_id).ledger.balance("rule_alpha", "TOKEN")
        draft = self.draft(sim_time_us=0, effects=[{
            "effect_id": "grant-wallet", "effect_type": "set_wallet_access",
            "wallet_owner_id": "rule_alpha", "grantee_agent_id": "rule_beta",
            "permissions": ["observe", "transact"], "reason_code": "delegated_control",
        }])
        created = self.manager.create_intervention_plan(self.branch_id, "draft-wallet-access", draft)
        self.manager.confirm_intervention_plan(self.branch_id, str(created["plan_id"]), "confirm-wallet-access")
        observation = self.manager.observations(self.branch_id, "rule_beta", limit=1)[0]
        account = observation["account_snapshot"]
        self.assertEqual(account["wallet_permissions"]["rule_alpha"], ["observe", "transact"])
        self.assertEqual(account["accessible_wallet_balances"]["rule_alpha"]["TOKEN"]["free"], expected_balance)

    def test_llm_director_creates_a_draft_but_cannot_apply_it(self) -> None:
        self.pause()
        adapter = TypedDirectorAdapter()
        self.manager.initializer.llm_gateway = LLMGateway({"openai": adapter})
        created = asyncio.run(self.manager.interpret_intervention_plan(
            self.branch_id,
            "ai-director-command",
            user_intent="Halt TOKEN-USDX now",
            requested_effective_time_us=0,
            provider_name="openai",
            access_scope=DirectorAccessScope(),
            private_read_refs=[],
        ))
        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["plan"]["director_record"]["director_kind"], "openai.v0.1")
        self.assertEqual(created["plan"]["director_record"]["call_ids"], ["llm-director-test"])
        self.assertEqual(created["plan"]["stages"][0]["background_order_flow_impact_milli"], -700)
        self.assertEqual(adapter.request.private_context, {})
        self.assertNotIn("base_persona", str(adapter.request.world_context))
        self.assertNotIn("memory_entries", str(adapter.request.world_context))
        self.assertEqual(self.manager.branch_projection(self.branch_id)["market_status"], "active")
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) count FROM llm_records WHERE agent_id='scenario_director'"
            ).fetchone()["count"],
            1,
        )
        confirmed = self.manager.confirm_intervention_plan(
            self.branch_id,
            str(created["plan_id"]),
            "confirm-ai-director",
        )
        self.assertEqual(confirmed["status"], "completed")
        self.assertEqual(self.manager.branch_projection(self.branch_id)["market_status"], "halted")
        archive_path = self.root / "director-record.sandbox"
        self.manager.export_archive(self.run_id, archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            records = archive.read("llm/records.jsonl").decode().splitlines()
            self.assertEqual(len(records), 1)
            self.assertIn("scenario_director", records[0])

    def test_director_uses_resolved_scenario_provider_over_request_hint(self) -> None:
        adapter = TypedDirectorAdapter("deepseek")
        self.manager.initializer.llm_gateway = LLMGateway({"deepseek": adapter})
        scenario = self.manager.create_scenario(ScenarioDraft(
            mode="live_llm_smoke",
            llm_provider="deepseek",
            population={"preset": "smoke"},
        ))
        resolved = asyncio.run(self.manager.resolve_scenario(str(scenario["scenario_id"])))
        run = self.manager.create_run(str(scenario["scenario_id"]), resolved.resolution_hash)
        branch_id = str(run["branches"][0]["branch_id"])
        self.manager.command(branch_id, "deepseek-start", "start")
        self.manager.command(branch_id, "deepseek-pause", "pause")

        # The stale UI hint says OpenAI, but the immutable run configuration
        # must route the director call through DeepSeek.
        created = asyncio.run(self.manager.interpret_intervention_plan(
            branch_id,
            "deepseek-director-command",
            user_intent="Halt TOKEN-USDX now",
            requested_effective_time_us=0,
            provider_name="openai",
            access_scope=DirectorAccessScope(),
            private_read_refs=[],
        ))
        self.assertEqual(created["plan"]["director_record"]["provider"], "deepseek")
        self.assertEqual(created["plan"]["director_record"]["director_kind"], "deepseek.v0.1")
        self.assertEqual(adapter.request.user_intent, "Halt TOKEN-USDX now")

    def test_director_rejects_runtime_secret_material_before_provider_use(self) -> None:
        self.pause()
        adapter = TypedDirectorAdapter()
        self.manager.initializer.llm_gateway = LLMGateway({"openai": adapter})
        with self.assertRaises(ValidationError):
            asyncio.run(self.manager.interpret_intervention_plan(
                self.branch_id,
                "secret-director-command",
                user_intent="Use OPENAI_API_KEY=sk-1234567890abcdefghijkl",
                requested_effective_time_us=0,
                provider_name="openai",
                access_scope=DirectorAccessScope(),
                private_read_refs=[],
            ))
        self.assertIsNone(adapter.request)

    def test_future_stage_runs_before_fixture_action_and_survives_archive(self) -> None:
        self.pause()
        draft = self.draft(sim_time_us=500_000, effects=[{
            "effect_id": "future-halt", "effect_type": "set_market_status",
            "market_id": "TOKEN-USDX", "status": "halted", "reason_code": "scheduled_halt",
        }])
        created = self.manager.create_intervention_plan(self.branch_id, "draft-future", draft)
        confirmed = self.manager.confirm_intervention_plan(self.branch_id, str(created["plan_id"]), "confirm-future")
        self.assertEqual(confirmed["status"], "confirmed")
        saved = self.manager.command(self.branch_id, "save-future", "save")
        child = self.manager.fork(self.branch_id, str(saved["checkpoint_id"]), "fork-future")
        child_id = str(child["branch_id"])
        inherited = self.manager.intervention_plans(child_id)
        self.assertEqual(len(inherited), 1)
        self.assertEqual(inherited[0]["stages"][0]["status"], "pending")

        self.manager.command(child_id, "start-child", "start")
        step = self.manager.command(child_id, "step-child", "step_fixture")
        self.assertFalse(step["accepted"])
        self.assertEqual(self.manager.branch_projection(child_id)["market_status"], "halted")
        self.assertEqual(self.manager.intervention_plans(child_id)[0]["status"], "completed")

        archive_path = self.root / "interventions.sandbox"
        self.manager.export_archive(self.run_id, archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            self.assertIn(f"interventions/{self.branch_id}.jsonl", archive.namelist())
            self.assertIn(f"interventions/{child_id}.jsonl", archive.namelist())
        restored_store = SQLiteStore(self.root / "restored-interventions.db")
        try:
            ArchiveService(restored_store, "0.2.0").import_run(archive_path)
            self.assertGreater(
                restored_store.connection.execute(
                    "SELECT COUNT(*) count FROM intervention_plans WHERE branch_id IN (?,?)",
                    (self.branch_id, child_id),
                ).fetchone()["count"],
                0,
            )
        finally:
            restored_store.close()

    def test_pause_does_not_wait_for_provider_or_activate_its_result(self) -> None:
        adapter = BlockingPlanningAdapter()
        self.manager.initializer.llm_gateway = LLMGateway({"openai": adapter})
        scenario = self.manager.create_scenario(ScenarioDraft(
            mode="live_llm_smoke",
            llm_provider="openai",
            population={"preset": "smoke"},
        ))
        resolved = asyncio.run(self.manager.resolve_scenario(str(scenario["scenario_id"])))
        run = self.manager.create_run(str(scenario["scenario_id"]), resolved.resolution_hash)
        branch_id = str(run["branches"][0]["branch_id"])
        self.manager.command(branch_id, "live-start", "start")
        output: list[dict[str, object]] = []
        errors: list[Exception] = []

        def run_provider() -> None:
            try:
                output.append(self.manager.command(branch_id, "live-run", "run_for", {"max_requests": 1}))
            except Exception as error:  # pragma: no cover - assertion captures thread failures
                errors.append(error)

        thread = threading.Thread(target=run_provider)
        thread.start()
        self.assertTrue(adapter.started.wait(2))
        paused = self.manager.command(branch_id, "pause-during-provider", "pause")
        self.assertEqual(paused["status"], "Paused")
        adapter.release.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(output[0]["deferred_results"], 1)
        pending = self.store.connection.execute(
            "SELECT applied FROM planning_results WHERE branch_id=?",
            (branch_id,),
        ).fetchone()
        self.assertEqual(pending["applied"], 0)
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) count FROM strategy_plans WHERE branch_id=?",
                (branch_id,),
            ).fetchone()["count"],
            0,
        )
        saved = self.manager.command(branch_id, "save-provider-result", "save")
        child = self.manager.fork(branch_id, str(saved["checkpoint_id"]), "fork-provider-result")
        child_id = str(child["branch_id"])
        inherited_result = self.store.connection.execute(
            "SELECT request_id,applied FROM planning_results WHERE branch_id=?",
            (child_id,),
        ).fetchone()
        self.assertIsNotNone(inherited_result)
        self.assertEqual(inherited_result["applied"], 0)
        resumed = self.manager.command(child_id, "resume-provider-result", "start")
        self.assertEqual(resumed["activated_planning_results"], 1)
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) count FROM strategy_plans WHERE branch_id=? AND active=1",
                (child_id,),
            ).fetchone()["count"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
