from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from sandbox.control.initialization import (
    InjectiveHolderDataProvider,
    _compute_distribution,
)
from sandbox.core.errors import ValidationError


_TRANSFER_EVENT_SIGNATURE_HASH = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def _build_mock_w3(*, transfer_logs: list[dict[str, object]] | None = None) -> MagicMock:
    """Build a mock Web3 instance that simulates an Injective EVM RPC node."""
    mock_w3 = MagicMock()
    mock_w3.is_connected.return_value = True
    mock_w3.eth.block_number = 100
    mock_w3.eth.get_block.return_value = {"hash": b"block_hash_100", "timestamp": 1234567890}

    mock_event = MagicMock()
    mock_event.event_signature_hash = _TRANSFER_EVENT_SIGNATURE_HASH
    mock_event.process_log.side_effect = lambda log: {
        "args": {
            "from": log["from"],
            "to": log["to"],
            "value": log["value"],
        }
    }

    mock_contract = MagicMock()
    mock_contract.events.Transfer.return_value = mock_event
    mock_contract.address = "0xTokenAddress"
    mock_contract.functions.decimals.return_value.call.return_value = 18
    mock_contract.functions.totalSupply.return_value.call.return_value = 10_000
    mock_contract.functions.symbol.return_value.call.return_value = "TEST"

    mock_w3.eth.contract.return_value = mock_contract
    mock_w3.eth.get_logs.return_value = transfer_logs or []

    return mock_w3


def _patch_web3(mock_web3_class: MagicMock, mock_w3: MagicMock) -> None:
    """Configure the patched Web3 class and return a usable instance."""
    mock_web3_class.return_value = mock_w3
    mock_web3_class.is_address.return_value = True
    mock_web3_class.to_checksum_address.return_value = "0xTokenAddress"
    mock_web3_class.HTTPProvider = MagicMock()


class InjectiveProviderTests(unittest.IsolatedAsyncioTestCase):
    @patch("sandbox.control.initialization.Web3")
    async def test_preflight_returns_ok_when_contract_reachable(self, mock_web3_class: MagicMock) -> None:
        mock_w3 = _build_mock_w3()
        _patch_web3(mock_web3_class, mock_w3)

        provider = InjectiveHolderDataProvider(
            chain_id="injective",
            token_address="0xTokenAddress",
            rpc_url="http://localhost:8545",
            target_token="TEST",
        )
        report = await provider.preflight("injective", "TEST")

        self.assertTrue(report["ok"])
        self.assertEqual(report["provider"], "injective-chain")
        self.assertEqual(report["chain_id"], "injective")
        self.assertEqual(report["target_token"], "TEST")
        self.assertEqual(report["token_symbol"], "TEST")
        self.assertEqual(report["token_address"], "0xTokenAddress")
        self.assertEqual(report["decimals"], 18)
        self.assertEqual(report["total_supply"], 10_000)
        self.assertEqual(report["latest_block"], 100)

    @patch("sandbox.control.initialization.Web3")
    async def test_preflight_rejects_wrong_chain_id(self, mock_web3_class: MagicMock) -> None:
        mock_w3 = _build_mock_w3()
        _patch_web3(mock_web3_class, mock_w3)

        provider = InjectiveHolderDataProvider(
            chain_id="injective",
            token_address="0xTokenAddress",
            rpc_url="http://localhost:8545",
        )
        report = await provider.preflight("ethereum", "TEST")

        self.assertFalse(report["ok"])
        self.assertIn("chain_id mismatch", report["message"])

    @patch("sandbox.control.initialization.Web3")
    async def test_preflight_fails_when_rpc_unreachable(self, mock_web3_class: MagicMock) -> None:
        mock_w3 = _build_mock_w3()
        mock_w3.is_connected.return_value = False
        _patch_web3(mock_web3_class, mock_w3)

        provider = InjectiveHolderDataProvider(
            chain_id="injective",
            token_address="0xTokenAddress",
            rpc_url="http://localhost:8545",
        )
        report = await provider.preflight("injective", "TEST")

        self.assertFalse(report["ok"])
        self.assertIn("cannot connect", report["message"])

    @patch("sandbox.control.initialization.Web3")
    async def test_load_snapshot_computes_balances_and_distribution(self, mock_web3_class: MagicMock) -> None:
        # Mint 1000 to A, 2000 to B, then A transfers 300 to C.
        transfer_logs = [
            {"from": _ZERO_ADDRESS, "to": "0xA", "value": 1000},
            {"from": _ZERO_ADDRESS, "to": "0xB", "value": 2000},
            {"from": "0xA", "to": "0xC", "value": 300},
        ]
        mock_w3 = _build_mock_w3(transfer_logs=transfer_logs)
        _patch_web3(mock_web3_class, mock_w3)

        provider = InjectiveHolderDataProvider(
            chain_id="injective",
            token_address="0xTokenAddress",
            rpc_url="http://localhost:8545",
        )
        snapshot = await provider.load_finalized_snapshot("injective", "TEST")

        self.assertEqual(snapshot["schema_version"], "holder-snapshot.v0.3")
        self.assertEqual(snapshot["provider"], "injective-chain")
        self.assertEqual(snapshot["chain_id"], "injective")
        self.assertEqual(snapshot["target_token"], "TEST")
        self.assertEqual(snapshot["block_height"], 100)
        self.assertEqual(snapshot["total_supply"], 10_000)
        self.assertEqual(snapshot["eligible_active_supply"], 3000)
        self.assertEqual(snapshot["covered_eligible_supply"], 2100)  # 70% of eligible

        distribution = snapshot["holder_distribution"]
        self.assertEqual(distribution["active_holder_count"], 3)
        self.assertEqual(distribution["p50_balance"], 700)

        bucket_amounts = {bucket["bucket_id"]: bucket["amount"] for bucket in snapshot["source_buckets"]}
        self.assertEqual(bucket_amounts["injective-eligible-active"], 3000)
        self.assertEqual(bucket_amounts["injective-protocol-or-burned"], 7000)

    @patch("sandbox.control.initialization.Web3")
    async def test_load_snapshot_raises_when_no_active_holders(self, mock_web3_class: MagicMock) -> None:
        mock_w3 = _build_mock_w3(transfer_logs=[])
        _patch_web3(mock_web3_class, mock_w3)

        provider = InjectiveHolderDataProvider(
            chain_id="injective",
            token_address="0xTokenAddress",
            rpc_url="http://localhost:8545",
        )
        with self.assertRaises(ValidationError):
            await provider.load_finalized_snapshot("injective", "TEST")

    def test_invalid_token_address_raises_validation_error(self) -> None:
        with patch("sandbox.control.initialization.Web3") as mock_web3_class:
            mock_web3_class.is_address.return_value = False
            with self.assertRaises(ValidationError):
                InjectiveHolderDataProvider(
                    chain_id="injective",
                    token_address="not-an-address",
                    rpc_url="http://localhost:8545",
                )

    def test_compute_distribution_produces_non_decreasing_quantiles(self) -> None:
        distribution = _compute_distribution([1, 2, 3, 4, 5])

        self.assertEqual(distribution["active_holder_count"], 5)
        self.assertEqual(distribution["p25_balance"], 2)
        self.assertEqual(distribution["p50_balance"], 3)
        self.assertEqual(distribution["p75_balance"], 4)
        self.assertEqual(distribution["p90_balance"], 5)
        self.assertEqual(distribution["p99_balance"], 5)
        self.assertEqual(distribution["top_10_concentration_milli"], 1000)

    def test_compute_distribution_for_single_holder(self) -> None:
        distribution = _compute_distribution([42])

        self.assertEqual(distribution["active_holder_count"], 1)
        self.assertEqual(distribution["p25_balance"], 42)
        self.assertEqual(distribution["p99_balance"], 42)
        self.assertEqual(distribution["top_10_concentration_milli"], 1000)


if __name__ == "__main__":
    unittest.main()
