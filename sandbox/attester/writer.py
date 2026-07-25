from __future__ import annotations

import logging
from typing import Any

from web3 import Web3
from web3.contract import Contract

from sandbox.attester.models import AttestationRequest, AttestationResult

logger = logging.getLogger(__name__)

# Minimal ABI for the SimulationAttestation contract.
# Only the recordAttestation function is needed for write operations.
_RECORD_ATTESTATION_ABI: list[dict[str, Any]] = [
    {
        "inputs": [
            {"internalType": "string", "name": "runId", "type": "string"},
            {"internalType": "string", "name": "branchId", "type": "string"},
            {"internalType": "bytes32", "name": "resultHash", "type": "bytes32"},
            {"internalType": "uint256", "name": "agentCount", "type": "uint256"},
            {"internalType": "uint256", "name": "simTimeUs", "type": "uint256"},
        ],
        "name": "recordAttestation",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

_DEFAULT_GAS = 500_000
_RECEIPT_TIMEOUT_S = 300


class InjectiveAttestationWriter:
    """Write simulation attestation records to an Injective EVM smart contract.

    This writer is responsible for:
    - Connecting to the Injective EVM RPC endpoint
    - Building, signing and broadcasting ``recordAttestation`` transactions
    - Returning a structured :class:`AttestationResult` for every attempt
    """

    def __init__(
        self,
        rpc_url: str,
        contract_address: str,
        private_key: str,
    ) -> None:
        self._rpc_url = rpc_url
        self._contract_address = contract_address
        self._private_key = private_key

        self._w3 = Web3(Web3.HTTPProvider(rpc_url))
        self._account = self._w3.eth.account.from_key(private_key)
        self._contract: Contract = self._w3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=_RECORD_ATTESTATION_ABI,
        )

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def preflight(self) -> dict[str, object]:
        """Check that the RPC endpoint and contract are reachable.

        Returns a dict with at least ``{"ok": True/False, ...}`` so that
        callers can decide whether to proceed.
        """
        try:
            chain_id = self._w3.eth.chain_id
            latest_block = self._w3.eth.block_number
            connected = self._w3.is_connected()
        except Exception as exc:
            logger.warning("attester preflight failed: %s", exc)
            return {"ok": False, "message": str(exc)}

        if not connected:
            return {"ok": False, "message": f"cannot connect to Injective RPC: {self._rpc_url}"}

        return {
            "ok": True,
            "chain_id": chain_id,
            "latest_block": latest_block,
            "contract_address": self._contract_address,
            "wallet_address": self._account.address,
        }

    # ------------------------------------------------------------------
    # Core write path
    # ------------------------------------------------------------------

    def write_attestation(self, request: AttestationRequest) -> AttestationResult:
        """Build, sign and submit a ``recordAttestation`` transaction.

        On success the returned :class:`AttestationResult` has
        ``status="confirmed"``.  On *any* exception the result carries
        ``status="failed"`` together with the error message.
        """
        try:
            return self._send_and_wait(request)
        except Exception as exc:
            logger.warning("attestation write failed for run=%s branch=%s: %s",
                           request.run_id, request.branch_id, exc)
            return AttestationResult(
                run_id=request.run_id,
                branch_id=request.branch_id,
                tx_hash="",
                block_number=0,
                status="failed",
                error_message=str(exc),
            )

    # ------------------------------------------------------------------
    # Two-phase API: broadcast immediately, confirm later
    # ------------------------------------------------------------------

    def broadcast(self, request: AttestationRequest) -> str:
        """Build, sign and broadcast the transaction; return the tx hash hex string.

        This never waits for confirmation — the caller can save the tx hash
        immediately (e.g. mark the attestation as *pending*) and then call
        :meth:`confirm` later.
        """
        result_hash_bytes = bytes.fromhex(request.world_state_hash)
        tx = self._contract.functions.recordAttestation(
            request.run_id,
            request.branch_id,
            result_hash_bytes,
            request.agent_count,
            request.sim_time_us,
        ).build_transaction(
            {
                "from": self._account.address,
                "nonce": self._w3.eth.get_transaction_count(self._account.address),
                "gas": _DEFAULT_GAS,
                "chainId": self._w3.eth.chain_id,
            }
        )
        signed = self._w3.eth.account.sign_transaction(tx, private_key=self._private_key)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        return tx_hash.hex()

    def confirm(self, request: AttestationRequest, tx_hash_hex: str) -> AttestationResult:
        """Wait for the transaction receipt and return the final attestation result.

        Blocks until the receipt is available or ``_RECEIPT_TIMEOUT_S`` elapses.
        """
        return self.confirm_str(request.run_id, request.branch_id, tx_hash_hex)

    def confirm_str(self, run_id: str, branch_id: str, tx_hash_hex: str) -> AttestationResult:
        """Like :meth:`confirm` but accepts raw strings instead of an
        :class:`AttestationRequest` object.  Used by recovery paths."""
        try:
            tx_hash = bytes.fromhex(tx_hash_hex) if isinstance(tx_hash_hex, str) else tx_hash_hex
            receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=_RECEIPT_TIMEOUT_S)
            status: str
            error_msg: str | None = None
            if receipt["status"] == 1:
                status = "confirmed"
            else:
                status = "failed"
                error_msg = f"transaction reverted (receipt status={receipt['status']})"
            return AttestationResult(
                run_id=run_id,
                branch_id=branch_id,
                tx_hash=tx_hash_hex,
                block_number=receipt["blockNumber"],
                status=status,
                error_message=error_msg,
            )
        except Exception as exc:
            logger.warning("attestation confirm failed for run=%s tx=%s: %s",
                           run_id, tx_hash_hex, exc)
            return AttestationResult(
                run_id=run_id,
                branch_id=branch_id,
                tx_hash=tx_hash_hex,
                block_number=0,
                status="failed",
                error_message=str(exc),
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _send_and_wait(self, request: AttestationRequest) -> AttestationResult:
        """Internal: build the tx, sign, broadcast and wait for receipt."""

        # Convert hex world_state_hash → bytes32 expected by the contract.
        result_hash_bytes = bytes.fromhex(request.world_state_hash)

        tx = self._contract.functions.recordAttestation(
            request.run_id,
            request.branch_id,
            result_hash_bytes,
            request.agent_count,
            request.sim_time_us,
        ).build_transaction(
            {
                "from": self._account.address,
                "nonce": self._w3.eth.get_transaction_count(self._account.address),
                "gas": _DEFAULT_GAS,
                "chainId": self._w3.eth.chain_id,
            }
        )

        signed = self._w3.eth.account.sign_transaction(tx, private_key=self._private_key)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)

        receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=_RECEIPT_TIMEOUT_S)

        status: str
        error_msg: str | None = None
        if receipt["status"] == 1:
            status = "confirmed"
        else:
            status = "failed"
            error_msg = f"transaction reverted (receipt status={receipt['status']})"

        return AttestationResult(
            run_id=request.run_id,
            branch_id=request.branch_id,
            tx_hash=tx_hash.hex(),
            block_number=receipt["blockNumber"],
            status=status,  # type: ignore[arg-type]
            error_message=error_msg,
        )
