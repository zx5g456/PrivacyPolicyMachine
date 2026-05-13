// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract TrustedPolicyRegistry {
    struct OnChainData {
        string rawFile;
        string policyId;
        string policyVersion;
        string hashCode;
    }

    mapping(bytes32 => OnChainData) private records;
    mapping(bytes32 => bool) private exists;

    event TrustedPolicyRecordRegistered(
        bytes32 indexed recordKey,
        string policyId,
        string policyVersion,
        string hashCode
    );

    function registerTrustedPolicyRecord(
        string calldata rawFile,
        string calldata policyId,
        string calldata policyVersion,
        string calldata hashCode
    ) external returns (bytes32 recordKey) {
        recordKey = getRecordKey(policyId, policyVersion);
        records[recordKey] = OnChainData({
            rawFile: rawFile,
            policyId: policyId,
            policyVersion: policyVersion,
            hashCode: hashCode
        });
        exists[recordKey] = true;
        emit TrustedPolicyRecordRegistered(recordKey, policyId, policyVersion, hashCode);
    }

    function readOnChainRecord(
        string calldata policyId,
        string calldata policyVersion
    ) external view returns (OnChainData memory) {
        bytes32 recordKey = getRecordKey(policyId, policyVersion);
        require(exists[recordKey], "Policy record not found");
        return records[recordKey];
    }

    function getRecordKey(
        string memory policyId,
        string memory policyVersion
    ) public pure returns (bytes32) {
        return keccak256(abi.encodePacked(policyId, policyVersion));
    }
}

