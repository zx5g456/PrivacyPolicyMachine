// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract TrustedPolicyRegistry {
    struct RegistrationData {
        bytes rawFile;
        bytes metadataJson;
        string publisherEntity;
        string serviceName;
        string policyVersion;
        string effectiveDate;
    }

    struct TrustedPolicyRecord {
        bytes32 documentHash;
        bytes32 metadataHash;
        string publisherEntity;
        string serviceName;
        string policyVersion;
        string effectiveDate;
        address registrant;
        uint64 registeredAt;
        bytes32 previousRecordKey;
        bool hasPreviousReference;
    }

    mapping(bytes32 => TrustedPolicyRecord) private records;
    mapping(bytes32 => bool) private exists;
    mapping(bytes32 => bytes32) private latestRecordKeyByPolicy;
    mapping(bytes32 => bytes32[]) private recordKeysByPolicy;

    event TrustedPolicyRecordRegistered(
        bytes32 indexed recordKey,
        bytes32 indexed documentHash,
        bytes32 indexed metadataHash,
        bytes32 previousRecordKey,
        address registrant,
        uint64 registeredAt
    );

    function registerTrustedPolicyRecord(RegistrationData calldata data) external returns (bytes32 recordKey) {
        require(data.rawFile.length > 0, "rawFile is required");
        require(data.metadataJson.length > 0, "metadataJson is required");
        require(bytes(data.publisherEntity).length > 0, "publisherEntity is required");
        require(bytes(data.serviceName).length > 0, "serviceName is required");
        require(bytes(data.policyVersion).length > 0, "policyVersion is required");

        recordKey = getRecordKey(data.publisherEntity, data.serviceName, data.policyVersion);
        require(!exists[recordKey], "Policy record already exists");
        bytes32 policyKey = getPolicyKey(data.publisherEntity, data.serviceName);
        bytes32 previousRecordKey = latestRecordKeyByPolicy[policyKey];
        bool hasPreviousReference = previousRecordKey != bytes32(0);
        bytes32 documentHash = sha256(data.rawFile);
        bytes32 metadataHash = sha256(data.metadataJson);
        uint64 registeredAt = uint64(block.timestamp);

        TrustedPolicyRecord storage record = records[recordKey];
        record.documentHash = documentHash;
        record.metadataHash = metadataHash;
        record.publisherEntity = data.publisherEntity;
        record.serviceName = data.serviceName;
        record.policyVersion = data.policyVersion;
        record.effectiveDate = data.effectiveDate;
        record.registrant = msg.sender;
        record.registeredAt = registeredAt;
        record.previousRecordKey = previousRecordKey;
        record.hasPreviousReference = hasPreviousReference;
        exists[recordKey] = true;
        latestRecordKeyByPolicy[policyKey] = recordKey;
        recordKeysByPolicy[policyKey].push(recordKey);

        emit TrustedPolicyRecordRegistered(
            recordKey, documentHash, metadataHash, previousRecordKey, msg.sender, registeredAt
        );
    }

    function readOnChainRecord(string calldata publisherEntity, string calldata serviceName, string calldata policyVersion)
        external view returns (TrustedPolicyRecord memory)
    {
        bytes32 recordKey = getRecordKey(publisherEntity, serviceName, policyVersion);
        require(exists[recordKey], "Policy record not found");
        return records[recordKey];
    }

    function readPreviousOnChainRecord(string calldata publisherEntity, string calldata serviceName, string calldata policyVersion)
        external view returns (TrustedPolicyRecord memory)
    {
        bytes32 recordKey = getRecordKey(publisherEntity, serviceName, policyVersion);
        require(exists[recordKey], "Policy record not found");
        require(records[recordKey].hasPreviousReference, "Previous policy record not found");
        return records[records[recordKey].previousRecordKey];
    }

    function readRecordByKey(bytes32 recordKey) external view returns (TrustedPolicyRecord memory) {
        require(exists[recordKey], "Policy record not found");
        return records[recordKey];
    }

    function readLatestOnChainRecord(string calldata publisherEntity, string calldata serviceName)
        external view returns (TrustedPolicyRecord memory)
    {
        bytes32 recordKey = latestRecordKeyByPolicy[getPolicyKey(publisherEntity, serviceName)];
        require(recordKey != bytes32(0), "Policy record not found");
        return records[recordKey];
    }

    function getPolicyRecordKeys(string calldata publisherEntity, string calldata serviceName)
        external view returns (bytes32[] memory)
    {
        return recordKeysByPolicy[getPolicyKey(publisherEntity, serviceName)];
    }

    function getRecordKey(string memory publisherEntity, string memory serviceName, string memory policyVersion)
        public pure returns (bytes32)
    {
        return keccak256(abi.encode(publisherEntity, serviceName, policyVersion));
    }

    function getPolicyKey(string memory publisherEntity, string memory serviceName) public pure returns (bytes32) {
        return keccak256(abi.encode(publisherEntity, serviceName));
    }
}
