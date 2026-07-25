from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path

from sandbox.agents.llm_gateway import LLMGateway
from sandbox.contracts.action import ActionContract
from sandbox.contracts.agent import AgentRuntimeState, MemoryEntryState
from sandbox.contracts.intervention import InterventionPlanDraftInput
from sandbox.contracts.scenario import ScenarioDraft
from sandbox.control.initialization import (
    FinalizedSnapshotFileProvider,
    Initializer,
    definition_from_config,
    fixture_agents,
)
from sandbox.control.run_manager import RunManager
from sandbox.core.errors import ConflictError, ValidationError
from sandbox.core.ids import new_id
from sandbox.store.archive import ArchiveService
from sandbox.store.sqlite import SQLiteStore


class ProductAcceptanceTests(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.manager.close()
        self.store.close()
        self.temp.cleanup()

    def create_fixture(self) -> tuple[str, str]:
        scenario = self.manager.create_scenario(ScenarioDraft())
        resolved = asyncio.run(self.manager.resolve_scenario(str(scenario["scenario_id"])))
        run = self.manager.create_run(str(scenario["scenario_id"]), resolved.resolution_hash)
        return str(run["run_id"]), str(run["branches"][0]["branch_id"])

    def wait_for_information_view(self, branch_id: str, action_id: str, agent_id: str, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if any(
                event.action_id == action_id
                and event.event_type == "InformationViewed"
                and event.payload.get("agent_id") == agent_id
                for event in self.manager.events.list_events(branch_id, limit=10_000)
            ):
                return
            time.sleep(0.02)
        self.fail("the information was not viewed before the timeout")

    def test_opening_book_is_asset_backed_tight_and_visible_to_the_first_observation(self) -> None:
        _, branch_id = self.create_fixture()
        world = self.manager._world(branch_id)
        projection = self.manager.branch_projection(branch_id)
        bids = projection["market"]["bids"]
        asks = projection["market"]["asks"]
        self.assertEqual((len(bids), len(asks)), (5, 5))
        best_bid = int(bids[0]["price"])
        best_ask = int(asks[0]["price"])
        mid = int(world.market["initial_mid_price"])
        self.assertEqual((best_ask - best_bid) * 10_000 // mid, 20)
        self.assertGreaterEqual((mid - int(bids[-1]["price"])) * 10_000 // mid, 300)
        self.assertLessEqual((mid - int(bids[-1]["price"])) * 10_000 // mid, 500)
        self.assertEqual({item["agent_id"] for item in [*bids, *asks]}, {"background"})

        balances = world.ledger.to_json()["balances"]["background"]
        self.assertGreater(balances[world.market["base_asset"]]["locked"], 0)
        self.assertGreater(balances[world.market["quote_asset"]]["locked"], 0)
        first_observation = self.manager.observations(branch_id, "rule_alpha")[-1]
        self.assertEqual(first_observation["market_view"]["bids"][0]["price"], best_bid)
        self.assertEqual(first_observation["market_view"]["asks"][0]["price"], best_ask)
        events = self.manager.events.list_events(branch_id, limit=10_000)
        last_opening_seq = max(
            event.branch_seq for event in events
            if event.source_id == "background" and event.event_type != "ObservationCreated"
        )
        first_observation_seq = min(event.branch_seq for event in events if event.event_type == "ObservationCreated")
        self.assertLess(last_opening_seq, first_observation_seq)

    def test_background_assets_are_the_dynamic_residual_of_visible_agents(self) -> None:
        scenario = self.manager.create_scenario(ScenarioDraft())
        resolved = asyncio.run(self.manager.resolve_scenario(str(scenario["scenario_id"])))
        token_asset = resolved.market.base_asset
        quote_asset = resolved.market.quote_asset
        explicit_token = sum(agent.token_balance for agent in resolved.agents)
        explicit_usdx = sum(agent.usdx_balance for agent in resolved.agents)
        self.assertNotIn("background", {agent.agent_id for agent in resolved.agents})
        self.assertEqual(
            resolved.background_market_sector.token_balance,
            resolved.chain_snapshot.eligible_active_supply - explicit_token,
        )
        self.assertEqual(
            resolved.background_market_sector.usdx_balance,
            resolved.total_supply[quote_asset] - explicit_usdx,
        )
        self.assertEqual(
            resolved.preview["assets"]["background_derivation"],
            "eligible_or_active_supply_minus_explicit_accounts",
        )

        configured = fixture_agents()
        configured[0] = configured[0].model_copy(update={
            "token_balance": configured[0].token_balance - 123,
            "usdx_balance": configured[0].usdx_balance - 456,
        })
        changed_scenario = self.manager.create_scenario(ScenarioDraft(agents=configured))
        changed = asyncio.run(self.manager.resolve_scenario(str(changed_scenario["scenario_id"])))
        self.assertEqual(
            changed.background_market_sector.token_balance,
            resolved.background_market_sector.token_balance + 123,
        )
        self.assertEqual(
            changed.background_market_sector.usdx_balance,
            resolved.background_market_sector.usdx_balance + 456,
        )

        expanded_quote_coverage = 1_500_000
        expanded_draft = ScenarioDraft(
            agents=fixture_agents(),
            portfolio=ScenarioDraft().portfolio.model_copy(update={"quote_coverage_ratio_ppm": expanded_quote_coverage}),
        )
        expanded_scenario = self.manager.create_scenario(expanded_draft)
        expanded = asyncio.run(self.manager.resolve_scenario(str(expanded_scenario["scenario_id"])))
        self.assertEqual(
            expanded.total_supply[quote_asset],
            expanded.chain_snapshot.eligible_active_supply
            * expanded.market.initial_mid_price
            * expanded_quote_coverage
            // 1_000_000,
        )

    def test_visible_agents_cannot_expand_the_initial_asset_supply(self) -> None:
        configured = fixture_agents()
        configured[0] = configured[0].model_copy(update={"token_balance": 1_000_001})
        scenario = self.manager.create_scenario(ScenarioDraft(agents=configured))
        with self.assertRaises(ValidationError):
            asyncio.run(self.manager.resolve_scenario(str(scenario["scenario_id"])))

    def test_initial_accounts_cannot_collide_with_reserved_accounts(self) -> None:
        scenario = self.manager.create_scenario(ScenarioDraft(portfolio={
            "other_explicit_accounts": [{"account_id": "background", "token_amount": 1}],
        }))
        with self.assertRaisesRegex(ValidationError, "account ids collide"):
            asyncio.run(self.manager.resolve_scenario(str(scenario["scenario_id"])))

    def test_background_refreshes_quotes_cancels_and_takes_only_external_top_of_book(self) -> None:
        _, branch_id = self.create_fixture()
        world = self.manager._world(branch_id)
        token_total = world.ledger.total(world.market["base_asset"])
        quote_total = world.ledger.total(world.market["quote_asset"])
        self.manager.command(branch_id, "background-start", "start")
        self.manager._runner_cancel[branch_id].set()

        external_offer = ActionContract(
            action_id="external-top-offer",
            agent_id="rule_alpha",
            branch_id=branch_id,
            submitted_sim_time_us=0,
            action_type="SubmitLimitOrder",
            payload={"side": "sell", "quantity": 50, "price": 10_000},
            expected_execution_time_us=0,
            validity_window_us=1_000_000,
            client_command_id="external-top-offer",
        )
        self.assertTrue(self.manager.submit_action(external_offer)["accepted"])
        for _ in range(11):
            self.assertTrue(self.manager._advance_background_once(branch_id))

        current = self.manager._world(branch_id)
        projection = self.manager.branch_projection(branch_id)
        best_bid = int(projection["market"]["bids"][0]["price"])
        best_ask = int(projection["market"]["asks"][0]["price"])
        self.assertLessEqual((best_ask - best_bid) * 10_000 // ((best_ask + best_bid) // 2), 50)
        self.assertTrue(any(
            trade["buyer_id"] == "background" and trade["seller_id"] == "rule_alpha"
            for trade in projection["market"]["trades"]
        ))
        event_types = [event.event_type for event in self.manager.events.list_events(branch_id, limit=10_000)]
        self.assertIn("BackgroundParticipationActivated", event_types)
        self.assertIn("OrderCancelled", event_types)
        self.assertIn("OrderReplaced", event_types)
        self.assertEqual(current.ledger.total(current.market["base_asset"]), token_total)
        self.assertEqual(current.ledger.total(current.market["quote_asset"]), quote_total)
        self.assertTrue(self.manager.events.verify_chain(branch_id))

    def test_background_order_flow_moves_price_without_external_agent_orders(self) -> None:
        _, branch_id = self.create_fixture()
        initial = self.manager.branch_projection(branch_id)
        initial_trade_count = len(initial["market"]["trades"])
        token_total = self.manager._world(branch_id).ledger.total("TOKEN")
        quote_total = self.manager._world(branch_id).ledger.total("USDX")

        self.manager.command(branch_id, "background-flow-start", "start")
        self.manager._runner_cancel[branch_id].set()
        for _ in range(24):
            self.assertTrue(self.manager._advance_background_once(branch_id))

        current = self.manager.branch_projection(branch_id)
        background_trades = [
            trade for trade in current["market"]["trades"]
            if {trade["buyer_id"], trade["seller_id"]} == {"background", "background_order_flow"}
        ]
        self.assertGreater(len(background_trades), 0)
        self.assertGreater(len(current["market"]["trades"]), initial_trade_count)
        self.assertGreater(len({trade["price"] for trade in background_trades}), 1)
        samples = [
            event for event in self.manager.events.list_events(branch_id, limit=10_000)
            if event.event_type == "BackgroundOrderFlowSampled"
        ]
        self.assertTrue(samples)
        self.assertIn("take", {event.payload["selected_kind"] for event in samples})
        self.assertIn("directional_limit", {event.payload["selected_kind"] for event in samples})
        world = self.manager._world(branch_id)
        self.assertEqual(world.ledger.total("TOKEN"), token_total)
        self.assertEqual(world.ledger.total("USDX"), quote_total)
        self.assertTrue(self.manager.events.verify_chain(branch_id))

    def test_running_advances_and_pause_freezes_a_complete_boundary(self) -> None:
        _, branch_id = self.create_fixture()
        initial = self.manager.branch_projection(branch_id)
        initial_decisions = self.store.connection.execute(
            "SELECT COUNT(*) count FROM agent_decisions WHERE branch_id=?",
            (branch_id,),
        ).fetchone()["count"]

        self.manager.command(branch_id, "autonomous-start", "start")
        time.sleep(1.45)
        advanced = self.manager.branch_projection(branch_id)
        decisions = self.store.connection.execute(
            "SELECT COUNT(*) count FROM agent_decisions WHERE branch_id=?",
            (branch_id,),
        ).fetchone()["count"]
        self.assertGreater(advanced["sim_time_us"], initial["sim_time_us"])
        self.assertGreater(advanced["cursor"], initial["cursor"])
        self.assertGreater(decisions, initial_decisions)
        self.assertTrue(advanced["market"]["bids"] or advanced["market"]["asks"])

        paused = self.manager.command(branch_id, "autonomous-pause", "pause")
        paused_cursor = int(paused["cursor"])
        time.sleep(0.15)
        self.assertEqual(self.manager.branch_projection(branch_id)["cursor"], paused_cursor)
        event_types = [event.event_type for event in self.manager.events.list_events(branch_id, limit=10_000)]
        self.assertIn("BranchStarted", event_types)
        self.assertIn("PauseRequested", event_types)
        self.assertIn("BranchPaused", event_types)
        self.assertTrue(self.manager.events.verify_chain(branch_id))

    def test_private_delivery_wakes_only_visible_agents_and_builds_belief(self) -> None:
        _, branch_id = self.create_fixture()
        self.manager.command(branch_id, "private-start", "start")
        action = ActionContract(
            action_id=new_id("act"),
            agent_id="replay_agent",
            branch_id=branch_id,
            submitted_sim_time_us=0,
            action_type="PublishInformation",
            payload={"channel": "PrivateChannel", "content": "Selective disclosure", "target_ids": ["rule_alpha"]},
            expected_execution_time_us=1,
            validity_window_us=1_000_000,
            client_command_id="private-disclosure",
        )
        result = self.manager.submit_action(action)
        self.assertTrue(result["accepted"])
        self.assertIn(action.action_id, self.manager._world(branch_id).pending_actions)
        self.wait_for_information_view(branch_id, action.action_id, "rule_alpha")
        target = self.manager.agent_detail(branch_id, "rule_alpha")
        self.assertTrue(target["runtime_state"]["memory_entries"])
        self.assertTrue(target["runtime_state"]["beliefs"])

        related = [
            event for event in self.manager.events.list_events(branch_id, limit=10_000)
            if event.action_id == action.action_id
        ]
        published = next(event for event in related if event.event_type == "InformationPublished")
        delivered = next(
            event for event in related
            if event.event_type == "PrivateMessageDelivered" and event.payload["target_id"] == "rule_alpha"
        )
        viewed = next(
            event for event in related
            if event.event_type == "InformationViewed" and event.payload["agent_id"] == "rule_alpha"
        )
        information_id = str(published.payload["information_id"])
        target_observation = next(
            observation
            for observation in self.manager.observations(branch_id, "rule_alpha")
            if information_id in observation["provenance"]
        )
        self.assertEqual(
            sum(
                decision["decision"]["observation_id"] == target_observation["observation_id"]
                for decision in self.manager.agent_decisions(branch_id, "rule_alpha")
            ),
            1,
        )
        viewed_agents = {
            str(event.payload["agent_id"])
            for event in related
            if event.event_type == "InformationViewed" and event.payload["information_id"] == information_id
        }
        self.assertEqual(viewed_agents, {"rule_alpha", "replay_agent"})
        self.assertFalse(any(
            information_id in observation["provenance"]
            for observation in self.manager.observations(branch_id, "rule_beta")
        ))
        self.assertLess(published.branch_seq, delivered.branch_seq)
        self.assertLess(delivered.branch_seq, viewed.branch_seq)

    def test_stop_is_idempotent_and_completed_save_does_not_append_history(self) -> None:
        _, branch_id = self.create_fixture()
        self.manager.command(branch_id, "stop-start", "start")
        action = ActionContract(
            action_id="stop-pending-information",
            agent_id="replay_agent",
            branch_id=branch_id,
            submitted_sim_time_us=0,
            action_type="PublishInformation",
            payload={"channel": "PrivateChannel", "content": "cancel before delivery", "target_ids": ["rule_alpha"]},
            expected_execution_time_us=1,
            validity_window_us=1_000_000,
            client_command_id="stop-pending-information-command",
        )
        self.assertTrue(self.manager.submit_action(action)["accepted"])
        self.manager._runner_cancel[branch_id].set()
        self.assertTrue(self.manager._advance_background_once(branch_id))
        self.assertGreater(self.manager.branch_projection(branch_id)["pending_delivery_count"], 0)
        stopped = self.manager.command(branch_id, "stop-once", "stop")
        self.assertEqual((stopped["status"], stopped["reason"]), ("Completed", "user_stopped"))
        self.assertEqual(self.manager.branch_projection(branch_id)["pending_delivery_count"], 0)
        self.assertTrue(any(
            event.event_type == "InformationDeliveryCanceled"
            for event in self.manager.events.list_events(branch_id, limit=10_000)
        ))
        terminal_event_types = [
            event.event_type for event in self.manager.events.list_events(branch_id, limit=10_000)
        ]
        self.assertIn("StopRequested", terminal_event_types)
        self.assertIn("BranchCompleted", terminal_event_types)
        event_count = len(self.manager.events.list_events(branch_id, limit=10_000))
        repeated = self.manager.command(branch_id, "stop-twice", "stop")
        self.assertEqual(repeated["reason"], "user_stopped")
        self.assertEqual(len(self.manager.events.list_events(branch_id, limit=10_000)), event_count)
        self.manager.command(branch_id, "save-completed", "save")
        self.assertEqual(len(self.manager.events.list_events(branch_id, limit=10_000)), event_count)
        with self.assertRaises(ConflictError):
            self.manager.command(branch_id, "restart-completed", "start")

    def test_completed_branch_can_be_exported_without_appending_history(self) -> None:
        run_id, branch_id = self.create_fixture()
        self.manager.command(branch_id, "completed-export-stop", "stop")
        event_count = len(self.manager.events.list_events(branch_id, limit=10_000))
        target = self.root / "completed.sandbox"
        exported = self.manager.export_archive(run_id, target)
        self.assertTrue(target.exists())
        self.assertEqual(exported["manifest"]["included_branches"], [branch_id])
        self.assertEqual(len(self.manager.events.list_events(branch_id, limit=10_000)), event_count)

    def test_fork_remaps_queued_action_to_the_child_branch(self) -> None:
        _, branch_id = self.create_fixture()
        self.manager.command(branch_id, "fork-pending-start", "start")
        self.manager._runner_cancel[branch_id].set()
        action = ActionContract(
            action_id="fork-pending-action",
            agent_id="rule_alpha",
            branch_id=branch_id,
            submitted_sim_time_us=0,
            action_type="SubmitLimitOrder",
            payload={"side": "buy", "quantity": 1, "price": 9_000},
            expected_execution_time_us=2_000_000,
            validity_window_us=4_000_000,
            client_command_id="fork-pending-action-command",
        )
        self.assertTrue(self.manager.submit_action(action)["queued"])
        self.manager.command(branch_id, "fork-pending-pause", "pause")
        saved = self.manager.command(branch_id, "fork-pending-save", "save")
        child = self.manager.fork(branch_id, str(saved["checkpoint_id"]), "fork-pending-child")
        child_id = str(child["branch_id"])
        child_pending = self.manager._world(child_id).pending_actions[action.action_id]
        self.assertEqual(child_pending["action"]["branch_id"], child_id)

        self.manager.command(child_id, "fork-pending-child-start", "start")
        self.manager._runner_cancel[child_id].set()
        for _ in range(4):
            self.manager._advance_background_once(child_id)
            if action.action_id not in self.manager._world(child_id).pending_actions:
                break
        self.assertNotIn(action.action_id, self.manager._world(child_id).pending_actions)
        self.assertIn(action.action_id, self.manager._world(branch_id).pending_actions)
        self.assertTrue(any(
            receipt["action_id"] == action.action_id
            for receipt in self.manager.agent_receipts(child_id, "rule_alpha")
        ))

    def test_action_past_its_validity_window_is_rejected(self) -> None:
        _, branch_id = self.create_fixture()
        self.manager.command(branch_id, "expired-start", "start")
        self.manager._runner_cancel[branch_id].set()
        self.assertTrue(self.manager._advance_background_once(branch_id))
        action = ActionContract(
            action_id="already-expired-action",
            agent_id="rule_alpha",
            branch_id=branch_id,
            submitted_sim_time_us=0,
            action_type="SubmitLimitOrder",
            payload={"side": "buy", "quantity": 1, "price": 9_000},
            expected_execution_time_us=1,
            validity_window_us=10,
            client_command_id="already-expired-command",
        )
        result = self.manager.submit_action(action)
        self.assertFalse(result["accepted"])
        receipt = next(
            item for item in self.manager.agent_receipts(branch_id, "rule_alpha")
            if item["action_id"] == action.action_id
        )
        self.assertEqual(receipt["outcome"], "rejected")

    def test_explicit_definition_cannot_widen_or_narrow_agent_capabilities(self) -> None:
        agents = fixture_agents()[:2]
        definitions = [definition_from_config(agent, seed=9) for agent in agents]
        definitions[0] = definitions[0].model_copy(update={"capability_set": []})
        scenario = self.manager.create_scenario(ScenarioDraft(
            agents=agents,
            agent_definitions=definitions,
        ))
        with self.assertRaises(ValidationError):
            asyncio.run(self.manager.resolve_scenario(str(scenario["scenario_id"])))

    def test_future_halt_rejects_pending_action_and_releases_reservation(self) -> None:
        _, branch_id = self.create_fixture()
        self.manager.command(branch_id, "pending-start", "start")
        action = ActionContract(
            action_id="future-order",
            agent_id="rule_alpha",
            branch_id=branch_id,
            submitted_sim_time_us=0,
            action_type="SubmitLimitOrder",
            payload={"side": "buy", "quantity": 10, "price": 100},
            expected_execution_time_us=1_000_000,
            validity_window_us=3_000_000,
            client_command_id="future-order-command",
        )
        queued = self.manager.submit_action(action)
        self.assertTrue(queued["queued"])
        world = self.manager._world(branch_id)
        self.assertIn(action.action_id, world.pending_actions)
        self.assertTrue(world.action_reservations)

        self.manager.command(branch_id, "pending-pause", "pause")
        plan = self.manager.create_intervention_plan(
            branch_id,
            "future-halt-draft",
            InterventionPlanDraftInput.model_validate({
                "user_intent": "Halt before the admitted order executes",
                "access_scope": {"private_grants": []},
                "private_read_refs": [],
                "stages": [{
                    "stage_id": "future-halt-stage",
                    "effective_sim_time_us": 0,
                    "effects": [{
                        "effect_id": "future-halt-effect",
                        "effect_type": "set_market_status",
                        "market_id": "TOKEN-USDX",
                        "status": "halted",
                        "reason_code": "acceptance_halt",
                    }],
                    "status": "pending",
                }],
            }),
        )
        self.manager.confirm_intervention_plan(branch_id, str(plan["plan_id"]), "future-halt-confirm")
        self.manager.command(branch_id, "pending-resume", "start")
        time.sleep(1.45)

        world = self.manager._world(branch_id)
        self.assertNotIn(action.action_id, world.pending_actions)
        self.assertFalse(world.action_reservations)
        receipt = next(item for item in self.manager.agent_receipts(branch_id, "rule_alpha") if item["action_id"] == action.action_id)
        self.assertEqual(receipt["outcome"], "rejected")
        event_types = [
            event.event_type for event in self.manager.events.list_events(branch_id, limit=10_000)
            if event.action_id == action.action_id
        ]
        self.assertIn("ActionReservationReleased", event_types)
        self.assertIn("PendingActionResolved", event_types)

    def test_save_retains_branch_state_and_same_branch_can_resume(self) -> None:
        _, branch_id = self.create_fixture()
        self.manager.command(branch_id, "save-start", "start")
        self.manager.command(branch_id, "save-pause", "pause")
        saved = self.manager.command(branch_id, "save-paused", "save")
        self.assertEqual(saved["status"], "Paused")
        resumed = self.manager.command(branch_id, "save-resume", "start")
        self.assertEqual(resumed["status"], "Running")
        stopped = self.manager.command(branch_id, "save-stop", "stop")
        self.assertEqual(stopped["reason"], "user_stopped")

    def test_advanced_agent_definition_and_private_initial_knowledge_survive_resolution(self) -> None:
        agents = fixture_agents()[:2]
        definitions = [definition_from_config(agent, seed=7) for agent in agents]
        definitions[1] = definitions[1].model_copy(update={
            "base_persona": definitions[1].base_persona.model_copy(update={
                "risk_tolerance_milli": 950,
                "skepticism_milli": 50,
                "time_horizon": "long",
            })
        })
        private_memory = MemoryEntryState(
            memory_id="initial-private-memory",
            summary="Privately supplied research note",
            source_ids=["initial:private"],
            confidence_milli=800,
            salience=75,
            created_sim_time_us=0,
        )
        scenario = self.manager.create_scenario(ScenarioDraft(
            agents=agents,
            agent_definitions=definitions,
            initial_agent_states=[AgentRuntimeState(agent_id=agents[1].agent_id, memory_entries=[private_memory])],
        ))
        resolved = asyncio.run(self.manager.resolve_scenario(str(scenario["scenario_id"])))
        self.assertEqual(resolved.agent_definitions[1].base_persona.risk_tolerance_milli, 950)
        self.assertEqual(resolved.initial_agent_states[0].memory_entries[0].source_ids, ["initial:private"])

    def test_finalized_snapshot_provider_rejects_mismatch_without_fixture_fallback(self) -> None:
        path = self.root / "ethereum-token.snapshot.json"
        path.write_text(json.dumps({
            "schema_version": "holder-snapshot.v0.3",
            "provider": "test-provider",
            "chain_id": "ethereum",
            "target_token": "TOKEN",
            "block_height": 123,
            "block_hash": "0xabc",
            "finalized": True,
            "coverage_ratio_milli": 900,
            "total_supply": 1_000_000,
            "eligible_active_supply": 900_000,
            "covered_eligible_supply": 810_000,
            "source_buckets": [
                {
                    "bucket_id": "eligible",
                    "category": "eligible_active",
                    "amount": 900_000,
                    "eligible_for_active_market": True,
                },
                {
                    "bucket_id": "locked",
                    "category": "locked",
                    "amount": 100_000,
                    "eligible_for_active_market": False,
                },
            ],
            "holder_distribution": {
                "distribution_version": "holder-distribution.v0.1",
                "active_holder_count": 100,
                "p25_balance": 100,
                "p50_balance": 500,
                "p75_balance": 1_000,
                "p90_balance": 5_000,
                "p99_balance": 20_000,
                "top_10_concentration_milli": 500,
            },
        }), encoding="utf-8")
        provider = FinalizedSnapshotFileProvider(path=path, chain_id="ethereum")
        report = asyncio.run(provider.preflight("ethereum", "TOKEN"))
        self.assertTrue(report["ok"])
        mismatch = asyncio.run(provider.preflight("ethereum", "OTHER"))
        self.assertFalse(mismatch["ok"])
        snapshot = asyncio.run(provider.load_finalized_snapshot("ethereum", "TOKEN"))
        self.assertTrue(snapshot["finalized"])
        self.assertTrue(str(snapshot["content_hash"]).startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
