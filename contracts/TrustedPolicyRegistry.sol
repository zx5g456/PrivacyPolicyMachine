// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract TrustedPolicyRegistry {
    uint256 public constant MAX_CHUNK_BYTES = 24 * 1024;
    address public immutable owner;

    mapping(address => bool) public complianceUploaders;

    struct RegistrationManifest {
        bytes32 documentHash;
        bytes32 metadataHash;
        uint64 documentSize;
        uint64 metadataSize;
        string publisherEntity;
        string serviceName;
        string policyVersion;
        string effectiveDate;
    }

    struct PendingUpload {
        bytes32 documentHash;
        bytes32 metadataHash;
        bytes32 documentChunkCommitment;
        bytes32 metadataChunkCommitment;
        uint64 documentSize;
        uint64 metadataSize;
        uint64 documentBytesStored;
        uint64 metadataBytesStored;
        uint32 documentChunkCount;
        uint32 metadataChunkCount;
        string publisherEntity;
        string serviceName;
        string policyVersion;
        string effectiveDate;
        address registrant;
        bool active;
    }

    struct TrustedPolicyRecord {
        bytes32 documentHash;
        bytes32 metadataHash;
        bytes32 documentChunkCommitment;
        bytes32 metadataChunkCommitment;
        uint64 documentSize;
        uint64 metadataSize;
        uint32 documentChunkCount;
        uint32 metadataChunkCount;
        string publisherEntity;
        string serviceName;
        string policyVersion;
        string effectiveDate;
        address registrant;
        uint64 registeredAt;
        bytes32 previousRecordKey;
        bool hasPreviousReference;
    }

    struct ComplianceManifest {
        bytes32 bundleHash;
        bytes32 sourceDocumentHash;
        bytes32 pipelineVersionHash;
        uint64 bundleSize;
    }

    struct PendingComplianceUpload {
        bytes32 bundleHash;
        bytes32 sourceDocumentHash;
        bytes32 pipelineVersionHash;
        bytes32 chunkCommitment;
        uint64 bundleSize;
        uint64 bytesStored;
        uint32 chunkCount;
        address submitter;
        bool active;
    }

    struct ComplianceResult {
        bytes32 bundleHash;
        bytes32 sourceDocumentHash;
        bytes32 pipelineVersionHash;
        bytes32 chunkCommitment;
        uint64 bundleSize;
        uint32 chunkCount;
        address submitter;
        uint64 registeredAt;
    }

    mapping(bytes32 => TrustedPolicyRecord) private records;
    mapping(bytes32 => PendingUpload) private pendingUploads;
    mapping(bytes32 => mapping(uint32 => bytes)) private documentChunks;
    mapping(bytes32 => mapping(uint32 => bytes)) private metadataChunks;
    mapping(bytes32 => bool) private exists;
    mapping(bytes32 => bytes32) private latestRecordKeyByPolicy;
    mapping(bytes32 => bytes32[]) private recordKeysByPolicy;
    mapping(bytes32 => ComplianceResult) private complianceResults;
    mapping(bytes32 => PendingComplianceUpload) private pendingComplianceUploads;
    mapping(bytes32 => mapping(uint32 => bytes)) private complianceChunks;
    mapping(bytes32 => bool) private complianceExists;

    event PolicyUploadStarted(
        bytes32 indexed recordKey,
        bytes32 indexed documentHash,
        bytes32 indexed metadataHash,
        address registrant,
        uint64 documentSize,
        uint64 metadataSize
    );

    event PolicyChunkStored(
        bytes32 indexed recordKey,
        uint8 indexed contentType,
        uint32 indexed chunkIndex,
        bytes32 chunkHash,
        uint64 chunkSize,
        bytes32 chunkCommitment
    );

    event PolicyUploadCancelled(bytes32 indexed recordKey, address indexed registrant);

    event TrustedPolicyRecordRegistered(
        bytes32 indexed recordKey,
        bytes32 indexed documentHash,
        bytes32 indexed metadataHash,
        bytes32 previousRecordKey,
        address registrant,
        uint64 registeredAt
    );

    event ComplianceUploaderUpdated(address indexed uploader, bool authorized);

    event ComplianceUploadStarted(
        bytes32 indexed recordKey,
        bytes32 indexed bundleHash,
        address indexed submitter,
        uint64 bundleSize
    );

    event ComplianceChunkStored(
        bytes32 indexed recordKey,
        uint32 indexed chunkIndex,
        bytes32 chunkHash,
        uint64 chunkSize,
        bytes32 chunkCommitment
    );

    event ComplianceUploadCancelled(bytes32 indexed recordKey, address indexed submitter);

    event ComplianceResultRegistered(
        bytes32 indexed recordKey,
        bytes32 indexed bundleHash,
        address indexed submitter,
        uint64 registeredAt
    );

    constructor() {
        owner = msg.sender;
        complianceUploaders[msg.sender] = true;
        emit ComplianceUploaderUpdated(msg.sender, true);
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "Only the owner can perform this action");
        _;
    }

    modifier onlyComplianceUploader() {
        require(complianceUploaders[msg.sender], "Not an authorized compliance uploader");
        _;
    }

    function setComplianceUploader(address uploader, bool authorized) external onlyOwner {
        require(uploader != address(0), "Uploader is required");
        complianceUploaders[uploader] = authorized;
        emit ComplianceUploaderUpdated(uploader, authorized);
    }

    function beginPolicyRegistration(RegistrationManifest calldata manifest)
        external returns (bytes32 recordKey)
    {
        require(manifest.documentHash != bytes32(0), "documentHash is required");
        require(manifest.metadataHash != bytes32(0), "metadataHash is required");
        require(manifest.documentSize > 0, "documentSize is required");
        require(manifest.metadataSize > 0, "metadataSize is required");
        require(bytes(manifest.publisherEntity).length > 0, "publisherEntity is required");
        require(bytes(manifest.serviceName).length > 0, "serviceName is required");
        require(bytes(manifest.policyVersion).length > 0, "policyVersion is required");

        recordKey = getRecordKey(manifest.publisherEntity, manifest.serviceName, manifest.policyVersion);
        require(!exists[recordKey], "Policy record already exists");
        require(!pendingUploads[recordKey].active, "Policy upload already started");

        PendingUpload storage pending = pendingUploads[recordKey];
        pending.documentHash = manifest.documentHash;
        pending.metadataHash = manifest.metadataHash;
        pending.documentSize = manifest.documentSize;
        pending.metadataSize = manifest.metadataSize;
        pending.publisherEntity = manifest.publisherEntity;
        pending.serviceName = manifest.serviceName;
        pending.policyVersion = manifest.policyVersion;
        pending.effectiveDate = manifest.effectiveDate;
        pending.registrant = msg.sender;
        pending.active = true;

        emit PolicyUploadStarted(
            recordKey,
            manifest.documentHash,
            manifest.metadataHash,
            msg.sender,
            manifest.documentSize,
            manifest.metadataSize
        );
    }

    function appendDocumentChunk(bytes32 recordKey, uint32 chunkIndex, bytes calldata chunk) external {
        PendingUpload storage pending = _ownedPendingUpload(recordKey);
        require(chunkIndex == pending.documentChunkCount, "Unexpected document chunk index");
        require(
            uint256(pending.documentBytesStored) + chunk.length <= pending.documentSize,
            "Document exceeds declared size"
        );

        documentChunks[recordKey][chunkIndex] = chunk;
        bytes32 chunkHash = sha256(chunk);
        pending.documentChunkCommitment = _nextChunkCommitment(
            pending.documentChunkCommitment, chunkIndex, uint64(chunk.length), chunkHash
        );
        pending.documentBytesStored += uint64(chunk.length);
        pending.documentChunkCount += 1;

        emit PolicyChunkStored(
            recordKey, 0, chunkIndex, chunkHash, uint64(chunk.length), pending.documentChunkCommitment
        );
    }

    function appendMetadataChunk(bytes32 recordKey, uint32 chunkIndex, bytes calldata chunk) external {
        PendingUpload storage pending = _ownedPendingUpload(recordKey);
        require(chunkIndex == pending.metadataChunkCount, "Unexpected metadata chunk index");
        require(
            uint256(pending.metadataBytesStored) + chunk.length <= pending.metadataSize,
            "Metadata exceeds declared size"
        );

        metadataChunks[recordKey][chunkIndex] = chunk;
        bytes32 chunkHash = sha256(chunk);
        pending.metadataChunkCommitment = _nextChunkCommitment(
            pending.metadataChunkCommitment, chunkIndex, uint64(chunk.length), chunkHash
        );
        pending.metadataBytesStored += uint64(chunk.length);
        pending.metadataChunkCount += 1;

        emit PolicyChunkStored(
            recordKey, 1, chunkIndex, chunkHash, uint64(chunk.length), pending.metadataChunkCommitment
        );
    }

    function finalizePolicyRegistration(bytes32 recordKey) external {
        PendingUpload storage pending = _ownedPendingUpload(recordKey);
        require(pending.documentBytesStored == pending.documentSize, "Document upload is incomplete");
        require(pending.metadataBytesStored == pending.metadataSize, "Metadata upload is incomplete");
        require(pending.documentChunkCount > 0, "Document chunks are required");
        require(pending.metadataChunkCount > 0, "Metadata chunks are required");

        bytes32 policyKey = getPolicyKey(pending.publisherEntity, pending.serviceName);
        bytes32 previousRecordKey = latestRecordKeyByPolicy[policyKey];
        bool hasPreviousReference = previousRecordKey != bytes32(0);
        uint64 registeredAt = uint64(block.timestamp);

        TrustedPolicyRecord storage record = records[recordKey];
        record.documentHash = pending.documentHash;
        record.metadataHash = pending.metadataHash;
        record.documentChunkCommitment = pending.documentChunkCommitment;
        record.metadataChunkCommitment = pending.metadataChunkCommitment;
        record.documentSize = pending.documentSize;
        record.metadataSize = pending.metadataSize;
        record.documentChunkCount = pending.documentChunkCount;
        record.metadataChunkCount = pending.metadataChunkCount;
        record.publisherEntity = pending.publisherEntity;
        record.serviceName = pending.serviceName;
        record.policyVersion = pending.policyVersion;
        record.effectiveDate = pending.effectiveDate;
        record.registrant = pending.registrant;
        record.registeredAt = registeredAt;
        record.previousRecordKey = previousRecordKey;
        record.hasPreviousReference = hasPreviousReference;

        exists[recordKey] = true;
        latestRecordKeyByPolicy[policyKey] = recordKey;
        recordKeysByPolicy[policyKey].push(recordKey);

        emit TrustedPolicyRecordRegistered(
            recordKey,
            pending.documentHash,
            pending.metadataHash,
            previousRecordKey,
            pending.registrant,
            registeredAt
        );

        delete pendingUploads[recordKey];
    }

    function cancelPolicyRegistration(bytes32 recordKey) external {
        PendingUpload storage pending = _ownedPendingUpload(recordKey);
        address registrant = pending.registrant;
        delete pendingUploads[recordKey];
        emit PolicyUploadCancelled(recordKey, registrant);
    }

    function beginComplianceUpload(bytes32 recordKey, ComplianceManifest calldata manifest)
        external onlyComplianceUploader
    {
        require(exists[recordKey], "Policy record not found");
        require(!complianceExists[recordKey], "Compliance result already exists");
        require(!pendingComplianceUploads[recordKey].active, "Compliance upload already started");
        require(manifest.bundleHash != bytes32(0), "bundleHash is required");
        require(manifest.pipelineVersionHash != bytes32(0), "pipelineVersionHash is required");
        require(manifest.bundleSize > 0, "bundleSize is required");
        require(
            manifest.sourceDocumentHash == records[recordKey].documentHash,
            "Compliance source document does not match policy"
        );

        PendingComplianceUpload storage pending = pendingComplianceUploads[recordKey];
        pending.bundleHash = manifest.bundleHash;
        pending.sourceDocumentHash = manifest.sourceDocumentHash;
        pending.pipelineVersionHash = manifest.pipelineVersionHash;
        pending.bundleSize = manifest.bundleSize;
        pending.submitter = msg.sender;
        pending.active = true;

        emit ComplianceUploadStarted(recordKey, manifest.bundleHash, msg.sender, manifest.bundleSize);
    }

    function appendComplianceChunk(bytes32 recordKey, uint32 chunkIndex, bytes calldata chunk)
        external onlyComplianceUploader
    {
        PendingComplianceUpload storage pending = _ownedPendingComplianceUpload(recordKey);
        require(chunkIndex == pending.chunkCount, "Unexpected compliance chunk index");
        require(
            uint256(pending.bytesStored) + chunk.length <= pending.bundleSize,
            "Compliance bundle exceeds declared size"
        );

        complianceChunks[recordKey][chunkIndex] = chunk;
        bytes32 chunkHash = sha256(chunk);
        pending.chunkCommitment = _nextChunkCommitment(
            pending.chunkCommitment, chunkIndex, uint64(chunk.length), chunkHash
        );
        pending.bytesStored += uint64(chunk.length);
        pending.chunkCount += 1;

        emit ComplianceChunkStored(
            recordKey,
            chunkIndex,
            chunkHash,
            uint64(chunk.length),
            pending.chunkCommitment
        );
    }

    function finalizeComplianceUpload(bytes32 recordKey) external onlyComplianceUploader {
        PendingComplianceUpload storage pending = _ownedPendingComplianceUpload(recordKey);
        require(!complianceExists[recordKey], "Compliance result already exists");
        require(pending.bytesStored == pending.bundleSize, "Compliance upload is incomplete");
        require(pending.chunkCount > 0, "Compliance chunks are required");

        uint64 registeredAt = uint64(block.timestamp);
        complianceResults[recordKey] = ComplianceResult({
            bundleHash: pending.bundleHash,
            sourceDocumentHash: pending.sourceDocumentHash,
            pipelineVersionHash: pending.pipelineVersionHash,
            chunkCommitment: pending.chunkCommitment,
            bundleSize: pending.bundleSize,
            chunkCount: pending.chunkCount,
            submitter: pending.submitter,
            registeredAt: registeredAt
        });
        complianceExists[recordKey] = true;

        emit ComplianceResultRegistered(
            recordKey,
            pending.bundleHash,
            pending.submitter,
            registeredAt
        );

        delete pendingComplianceUploads[recordKey];
    }

    function cancelComplianceUpload(bytes32 recordKey) external {
        PendingComplianceUpload storage pending = pendingComplianceUploads[recordKey];
        require(pending.active, "Compliance upload not found");
        require(
            pending.submitter == msg.sender || msg.sender == owner,
            "Only the submitter or owner can cancel this upload"
        );
        address submitter = pending.submitter;
        delete pendingComplianceUploads[recordKey];
        emit ComplianceUploadCancelled(recordKey, submitter);
    }

    function hasPendingUpload(bytes32 recordKey) external view returns (bool) {
        return pendingUploads[recordKey].active;
    }

    function hasRecord(bytes32 recordKey) external view returns (bool) {
        return exists[recordKey];
    }

    function hasComplianceResult(bytes32 recordKey) external view returns (bool) {
        return complianceExists[recordKey];
    }

    function hasPendingComplianceUpload(bytes32 recordKey) external view returns (bool) {
        return pendingComplianceUploads[recordKey].active;
    }

    function readUploadProgress(bytes32 recordKey) external view returns (PendingUpload memory) {
        require(pendingUploads[recordKey].active, "Policy upload not found");
        return pendingUploads[recordKey];
    }

    function readComplianceUploadProgress(bytes32 recordKey)
        external view returns (PendingComplianceUpload memory)
    {
        require(pendingComplianceUploads[recordKey].active, "Compliance upload not found");
        return pendingComplianceUploads[recordKey];
    }

    function readComplianceResult(bytes32 recordKey) external view returns (ComplianceResult memory) {
        require(complianceExists[recordKey], "Compliance result not found");
        return complianceResults[recordKey];
    }

    function readComplianceChunk(bytes32 recordKey, uint32 chunkIndex)
        external view returns (bytes memory)
    {
        require(
            complianceExists[recordKey] || pendingComplianceUploads[recordKey].active,
            "Compliance content not found"
        );
        uint32 chunkCount = complianceExists[recordKey]
            ? complianceResults[recordKey].chunkCount
            : pendingComplianceUploads[recordKey].chunkCount;
        require(chunkIndex < chunkCount, "Compliance chunk not found");
        return complianceChunks[recordKey][chunkIndex];
    }

    function readDocumentChunk(bytes32 recordKey, uint32 chunkIndex) external view returns (bytes memory) {
        _requireReadableChunk(recordKey);
        uint32 chunkCount = exists[recordKey]
            ? records[recordKey].documentChunkCount
            : pendingUploads[recordKey].documentChunkCount;
        require(chunkIndex < chunkCount, "Document chunk not found");
        return documentChunks[recordKey][chunkIndex];
    }

    function readMetadataChunk(bytes32 recordKey, uint32 chunkIndex) external view returns (bytes memory) {
        _requireReadableChunk(recordKey);
        uint32 chunkCount = exists[recordKey]
            ? records[recordKey].metadataChunkCount
            : pendingUploads[recordKey].metadataChunkCount;
        require(chunkIndex < chunkCount, "Metadata chunk not found");
        return metadataChunks[recordKey][chunkIndex];
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

    function _ownedPendingUpload(bytes32 recordKey) private view returns (PendingUpload storage pending) {
        pending = pendingUploads[recordKey];
        require(pending.active, "Policy upload not found");
        require(pending.registrant == msg.sender, "Only the registrant can modify this upload");
    }

    function _ownedPendingComplianceUpload(bytes32 recordKey)
        private view returns (PendingComplianceUpload storage pending)
    {
        pending = pendingComplianceUploads[recordKey];
        require(pending.active, "Compliance upload not found");
        require(pending.submitter == msg.sender, "Only the submitter can modify this upload");
    }

    function _requireReadableChunk(bytes32 recordKey) private view {
        require(exists[recordKey] || pendingUploads[recordKey].active, "Policy content not found");
    }

    function _nextChunkCommitment(
        bytes32 currentCommitment,
        uint32 chunkIndex,
        uint64 chunkSize,
        bytes32 chunkHash
    ) private pure returns (bytes32) {
        require(chunkSize > 0, "Chunk is required");
        require(chunkSize <= MAX_CHUNK_BYTES, "Chunk exceeds maximum size");
        return keccak256(abi.encodePacked(currentCommitment, chunkIndex, chunkSize, chunkHash));
    }
}
