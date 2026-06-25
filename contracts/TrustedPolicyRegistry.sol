// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract TrustedPolicyRegistry {
    struct PolicyIdentity {
        string publisherEntity;
        string policyUrl;
        string serviceName;
        string effectiveDate;
        string policyVersion;
    }

    struct DataCollectionMetadata {
        string dataTypeTags;
        string dataSourceTypes;
        string collectionContext;
        string processingPurpose;
        string permittedUsage;
    }

    struct DataSharingMetadata {
        string thirdPartySources;
        string downstreamStakeholders;
        string thirdPartyPurpose;
        string sharingCondition;
    }

    struct UserRightsMetadata {
        string consentRequired;
        string optOutAvailable;
        string deletionAvailable;
        string requestChannel;
    }

    struct RetentionSecurityMetadata {
        string retentionPolicy;
        string encryptionApplied;
        string anonymisation;
    }

    struct ComplianceMetadata {
        string regulatoryFramework;
        string crossBorderTransfer;
        string childDataInvolved;
    }

    struct AccountabilityMetadata {
        string changeSummary;
        string contactChannel;
        string riskFlags;
    }

    struct RegistrationData {
        string rawFile;
        PolicyIdentity identity;
        DataCollectionMetadata dataCollection;
        DataSharingMetadata dataSharing;
        UserRightsMetadata userRights;
        RetentionSecurityMetadata retentionSecurity;
        ComplianceMetadata compliance;
        AccountabilityMetadata accountability;
    }

    struct TrustedPolicyRecord {
        string rawFile;
        PolicyIdentity identity;
        DataCollectionMetadata dataCollection;
        DataSharingMetadata dataSharing;
        UserRightsMetadata userRights;
        RetentionSecurityMetadata retentionSecurity;
        ComplianceMetadata compliance;
        AccountabilityMetadata accountability;
        bytes32 previousRecordKey;
        string previousPolicyVersion;
        bool hasPreviousReference;
    }

    mapping(bytes32 => TrustedPolicyRecord) private records;
    mapping(bytes32 => bool) private exists;
    mapping(bytes32 => bytes32) private latestRecordKeyByPolicy;
    mapping(bytes32 => bytes32[]) private recordKeysByPolicy;

    event TrustedPolicyRecordRegistered(
        bytes32 indexed recordKey,
        bytes32 indexed previousRecordKey,
        string publisherEntity,
        string serviceName,
        string policyVersion,
        string previousPolicyVersion
    );

    function registerTrustedPolicyRecord(
        RegistrationData calldata data
    ) external returns (bytes32 recordKey) {
        recordKey = getRecordKey(
            data.identity.publisherEntity,
            data.identity.serviceName,
            data.identity.policyVersion
        );
        require(!exists[recordKey], "Policy record already exists");
        require(bytes(data.identity.publisherEntity).length > 0, "publisherEntity is required");
        require(bytes(data.identity.policyVersion).length > 0, "policyVersion is required");

        bytes32 policyKey = getPolicyKey(data.identity.publisherEntity, data.identity.serviceName);
        bytes32 previousRecordKey = latestRecordKeyByPolicy[policyKey];
        bool hasPreviousReference = previousRecordKey != bytes32(0);
        string memory previousPolicyVersion = hasPreviousReference
            ? records[previousRecordKey].identity.policyVersion
            : "";

        TrustedPolicyRecord storage record = records[recordKey];
        record.rawFile = data.rawFile;
        record.identity = data.identity;
        record.dataCollection = data.dataCollection;
        record.dataSharing = data.dataSharing;
        record.userRights = data.userRights;
        record.retentionSecurity = data.retentionSecurity;
        record.compliance = data.compliance;
        record.accountability = data.accountability;
        record.previousRecordKey = previousRecordKey;
        record.previousPolicyVersion = previousPolicyVersion;
        record.hasPreviousReference = hasPreviousReference;

        exists[recordKey] = true;
        latestRecordKeyByPolicy[policyKey] = recordKey;
        recordKeysByPolicy[policyKey].push(recordKey);

        emit TrustedPolicyRecordRegistered(
            recordKey,
            previousRecordKey,
            data.identity.publisherEntity,
            data.identity.serviceName,
            data.identity.policyVersion,
            previousPolicyVersion
        );
    }

    function readOnChainRecord(
        string calldata publisherEntity,
        string calldata serviceName,
        string calldata policyVersion
    ) external view returns (TrustedPolicyRecord memory) {
        bytes32 recordKey = getRecordKey(publisherEntity, serviceName, policyVersion);
        require(exists[recordKey], "Policy record not found");
        return records[recordKey];
    }

    function readPreviousOnChainRecord(
        string calldata publisherEntity,
        string calldata serviceName,
        string calldata policyVersion
    ) external view returns (TrustedPolicyRecord memory) {
        bytes32 recordKey = getRecordKey(publisherEntity, serviceName, policyVersion);
        require(exists[recordKey], "Policy record not found");

        TrustedPolicyRecord storage record = records[recordKey];
        require(record.hasPreviousReference, "Previous policy record not found");
        return records[record.previousRecordKey];
    }

    function readLatestOnChainRecord(
        string calldata publisherEntity,
        string calldata serviceName
    ) external view returns (TrustedPolicyRecord memory) {
        bytes32 recordKey = latestRecordKeyByPolicy[getPolicyKey(publisherEntity, serviceName)];
        require(recordKey != bytes32(0), "Policy record not found");
        return records[recordKey];
    }

    function getPolicyRecordKeys(
        string calldata publisherEntity,
        string calldata serviceName
    ) external view returns (bytes32[] memory) {
        return recordKeysByPolicy[getPolicyKey(publisherEntity, serviceName)];
    }

    function getRecordKey(
        string memory publisherEntity,
        string memory serviceName,
        string memory policyVersion
    ) public pure returns (bytes32) {
        return keccak256(abi.encode(publisherEntity, serviceName, policyVersion));
    }

    function getPolicyKey(
        string memory publisherEntity,
        string memory serviceName
    ) public pure returns (bytes32) {
        return keccak256(abi.encode(publisherEntity, serviceName));
    }
}
