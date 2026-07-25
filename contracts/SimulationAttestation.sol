// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract SimulationAttestation {
    struct Attestation {
        string runId;
        string branchId;
        bytes32 resultHash;
        uint256 agentCount;
        uint256 simTimeUs;
        address submitter;
        uint256 timestamp;
    }

    mapping(bytes32 => Attestation) public attestations;
    event AttestationRecorded(bytes32 indexed id, string runId, bytes32 resultHash, address submitter);

    function recordAttestation(
        string memory runId,
        string memory branchId,
        bytes32 resultHash,
        uint256 agentCount,
        uint256 simTimeUs
    ) external returns (bytes32) {
        bytes32 id = keccak256(abi.encodePacked(runId, branchId, block.timestamp));
        attestations[id] = Attestation(runId, branchId, resultHash, agentCount, simTimeUs, msg.sender, block.timestamp);
        emit AttestationRecorded(id, runId, resultHash, msg.sender);
        return id;
    }

    function getAttestation(bytes32 id) external view returns (Attestation memory) {
        return attestations[id];
    }
}
