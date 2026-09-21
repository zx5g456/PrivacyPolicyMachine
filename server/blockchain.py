from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from web3 import Web3


DEFAULT_ONCHAIN_CHUNK_BYTES = 8 * 1024


def split_bytes(value: bytes, chunk_size: int) -> list[bytes]:
    """Split exact file bytes without changing UTF-8 or other encodings."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    return [value[offset:offset + chunk_size] for offset in range(0, len(value), chunk_size)]


def next_chunk_commitment(current: bytes, chunk_index: int, chunk: bytes) -> bytes:
    """Mirror the ordered chunk commitment calculated by the Solidity contract."""
    if len(current) != 32:
        raise ValueError("current chunk commitment must be 32 bytes")
    if not chunk:
        raise ValueError("chunk must not be empty")
    chunk_hash = hashlib.sha256(chunk).digest()
    return bytes(
        Web3.solidity_keccak(
            ["bytes32", "uint32", "uint64", "bytes32"],
            [current, chunk_index, len(chunk), chunk_hash],
        )
    )


def content_commitment(chunks: list[bytes]) -> bytes:
    commitment = bytes(32)
    for index, chunk in enumerate(chunks):
        commitment = next_chunk_commitment(commitment, index, chunk)
    return commitment


@dataclass(frozen=True)
class OnChainData:
    rawFile: bytes
    metadataJson: bytes
    publisherEntity: str
    serviceName: str
    policyVersion: str
    effectiveDate: str = ""


@dataclass(frozen=True)
class StoredChainData:
    documentHash: str
    metadataHash: str
    documentChunkCommitment: str
    metadataChunkCommitment: str
    documentSize: int
    metadataSize: int
    documentChunkCount: int
    metadataChunkCount: int
    publisherEntity: str
    serviceName: str
    policyVersion: str
    effectiveDate: str
    registrant: str
    registeredAt: int
    previousRecordKey: str
    previousPolicyVersion: str
    hasPreviousReference: bool


@dataclass(frozen=True)
class ChainTransaction:
    phase: str
    txHash: str
    blockNumber: int
    gasUsed: int
    contentType: str = ""
    chunkIndex: int | None = None
    chunkBytes: int = 0


@dataclass(frozen=True)
class ChainRecord:
    recordKey: str
    blockNumber: int
    txHash: str
    timestamp: int
    gasUsed: int
    chainId: int
    contractAddress: str
    data: StoredChainData
    previousBlockHash: str
    blockHash: str
    transactions: tuple[ChainTransaction, ...] = ()


@dataclass(frozen=True)
class OnChainContent:
    recordKey: str
    rawFile: bytes
    metadataJson: bytes
    documentChunks: tuple[bytes, ...]
    metadataChunks: tuple[bytes, ...]

    @property
    def document_hash(self) -> str:
        return "0x" + hashlib.sha256(self.rawFile).hexdigest()

    @property
    def metadata_hash(self) -> str:
        return "0x" + hashlib.sha256(self.metadataJson).hexdigest()

    @property
    def document_commitment(self) -> str:
        return Web3.to_hex(content_commitment(list(self.documentChunks)))

    @property
    def metadata_commitment(self) -> str:
        return Web3.to_hex(content_commitment(list(self.metadataChunks)))


@dataclass(frozen=True)
class ComplianceResult:
    recordKey: str
    bundleHash: str
    sourceDocumentHash: str
    pipelineVersionHash: str
    chunkCommitment: str
    bundleSize: int
    chunkCount: int
    submitter: str
    registeredAt: int


@dataclass(frozen=True)
class OnChainComplianceContent:
    result: ComplianceResult
    bundle: bytes
    chunks: tuple[bytes, ...]

    @property
    def bundle_hash(self) -> str:
        return "0x" + hashlib.sha256(self.bundle).hexdigest()

    @property
    def chunk_commitment(self) -> str:
        return Web3.to_hex(content_commitment(list(self.chunks)))


@dataclass(frozen=True)
class UploadProgress:
    documentHash: str
    metadataHash: str
    documentChunkCommitment: str
    metadataChunkCommitment: str
    documentSize: int
    metadataSize: int
    documentBytesStored: int
    metadataBytesStored: int
    documentChunkCount: int
    metadataChunkCount: int
    publisherEntity: str
    serviceName: str
    policyVersion: str
    effectiveDate: str
    registrant: str


class TrustedPolicyRegistry:
    """Web3 client for chunked, contract-storage-backed policy records."""

    def __init__(self, artifact_path: Path):
        self.rpc_url = os.environ.get("RPC_URL", "http://127.0.0.1:8545")
        self.contract_address = os.environ.get("CONTRACT_ADDRESS", "")
        self.from_block = int(os.environ.get("CONTRACT_DEPLOYMENT_BLOCK", "0"))
        configured_chunk_size = int(
            os.environ.get("ONCHAIN_CHUNK_BYTES", str(DEFAULT_ONCHAIN_CHUNK_BYTES))
        )
        if configured_chunk_size <= 0:
            raise RuntimeError("ONCHAIN_CHUNK_BYTES must be a positive integer")
        self.configured_chunk_size = configured_chunk_size
        self.web3 = Web3(Web3.HTTPProvider(self.rpc_url))
        self._transaction_lock = threading.Lock()
        if not artifact_path.exists():
            raise RuntimeError("Contract artifact not found. Run `npm run contract:compile` before starting the server.")
        if not self.contract_address:
            raise RuntimeError("CONTRACT_ADDRESS is required. Deploy the contract before starting the server.")
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        self.abi = artifact["abi"]
        self.abi_hash = "0x" + hashlib.sha256(
            json.dumps(self.abi, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.contract = self.web3.eth.contract(
            address=Web3.to_checksum_address(self.contract_address), abi=self.abi
        )

    def register_trusted_policy_record(self, data: OnChainData) -> ChainRecord:
        """Upload exact bytes in resumable transactions and finalize one visible record."""
        self._require_connection()
        if not data.rawFile:
            raise ValueError("rawFile is required")
        if not data.metadataJson:
            raise ValueError("metadataJson is required")

        sender = self._sender_account()
        record_key = self.contract.functions.getRecordKey(
            data.publisherEntity, data.serviceName, data.policyVersion
        ).call()
        transactions: list[ChainTransaction] = []

        with self._transaction_lock:
            finalized = self._try_read_record_by_key(record_key)
            if finalized is not None:
                content = self.read_on_chain_content(finalized.recordKey)
                self._require_finalized_request_matches(finalized, content, data)
                return finalized
            if self.contract.functions.hasPendingUpload(record_key).call():
                progress = self._read_upload_progress(record_key)
                self._validate_resumable_upload(record_key, progress, data, sender)
            else:
                begin = self.contract.functions.beginPolicyRegistration(
                    self._manifest_tuple(data)
                )
                receipt = self._transact(begin, sender)
                transactions.append(self._transaction(receipt, "begin"))
                progress = self._read_upload_progress(record_key)

            document_chunks = self._read_chunks(record_key, "document", progress.documentChunkCount)
            metadata_chunks = self._read_chunks(record_key, "metadata", progress.metadataChunkCount)
            self._validate_pending_chunks(progress, document_chunks, metadata_chunks)
            document_offset = self._validated_prefix(data.rawFile, document_chunks, "document")
            metadata_offset = self._validated_prefix(data.metadataJson, metadata_chunks, "metadata")

            transactions.extend(
                self._append_content(
                    record_key,
                    "document",
                    data.rawFile,
                    document_offset,
                    progress.documentChunkCount,
                    sender,
                )
            )
            transactions.extend(
                self._append_content(
                    record_key,
                    "metadata",
                    data.metadataJson,
                    metadata_offset,
                    progress.metadataChunkCount,
                    sender,
                )
            )

            final_receipt = self._transact(
                self.contract.functions.finalizePolicyRegistration(record_key), sender
            )
            transactions.append(self._transaction(final_receipt, "finalize"))

        events = self.contract.events.TrustedPolicyRecordRegistered().process_receipt(final_receipt)
        if not events:
            raise RuntimeError("Registration finalized but its contract event was not found")
        complete_transactions = self._registration_transactions(record_key)
        record = self._record_from_event(events[0], final_receipt, complete_transactions)
        content = self.read_on_chain_content(record.recordKey)
        self._require_content_matches_record(content, record.data)
        return record

    def read_on_chain_record(
        self, publisher: str, service: str, version: str | None = None
    ) -> ChainRecord | None:
        self._require_connection()
        if version is None:
            matches = [
                record
                for record in self.list_records()
                if record.data.publisherEntity == publisher and record.data.serviceName == service
            ]
            return matches[-1] if matches else None
        record_key = self.contract.functions.getRecordKey(publisher, service, version).call()
        if not self.contract.functions.hasRecord(record_key).call():
            return None
        record = self.contract.functions.readRecordByKey(record_key).call()
        event = self._find_registration_event_by_key(record_key)
        receipt = self.web3.eth.get_transaction_receipt(event["transactionHash"])
        return self._record_from_contract(record, event, receipt)

    def read_record_by_key(self, record_key: str | bytes) -> ChainRecord:
        self._require_connection()
        key = self._record_key_bytes(record_key)
        record = self.contract.functions.readRecordByKey(key).call()
        event = self._find_registration_event_by_key(key)
        receipt = self.web3.eth.get_transaction_receipt(event["transactionHash"])
        return self._record_from_contract(record, event, receipt)

    def read_on_chain_content(self, record_key: str | bytes) -> OnChainContent:
        """Read every stored chunk. Callers can stream with the contract getters if needed."""
        self._require_connection()
        key = self._record_key_bytes(record_key)
        record = self.contract.functions.readRecordByKey(key).call()
        document_chunks = tuple(self._read_chunks(key, "document", int(record[6])))
        metadata_chunks = tuple(self._read_chunks(key, "metadata", int(record[7])))
        return OnChainContent(
            recordKey=Web3.to_hex(key),
            rawFile=b"".join(document_chunks),
            metadataJson=b"".join(metadata_chunks),
            documentChunks=document_chunks,
            metadataChunks=metadata_chunks,
        )

    def read_compliance_status(self, record_key: str | bytes) -> dict[str, Any]:
        """Return lightweight compliance state without downloading the result bundle."""
        self._require_connection()
        key = self._record_key_bytes(record_key)
        if self.contract.functions.hasComplianceResult(key).call():
            result = self._compliance_result_from_contract(
                key,
                self.contract.functions.readComplianceResult(key).call(),
            )
            return {"status": "finalized", **asdict(result)}
        if self.contract.functions.hasPendingComplianceUpload(key).call():
            pending = self.contract.functions.readComplianceUploadProgress(key).call()
            return {
                "status": "uploading",
                "recordKey": Web3.to_hex(key),
                "bundleHash": Web3.to_hex(pending[0]),
                "sourceDocumentHash": Web3.to_hex(pending[1]),
                "pipelineVersionHash": Web3.to_hex(pending[2]),
                "chunkCommitment": Web3.to_hex(pending[3]),
                "bundleSize": int(pending[4]),
                "bytesStored": int(pending[5]),
                "chunkCount": int(pending[6]),
                "submitter": pending[7],
            }
        return {"status": "pending", "recordKey": Web3.to_hex(key)}

    def read_compliance_content(
        self, record_key: str | bytes
    ) -> OnChainComplianceContent:
        """Download and verify the one finalized compliance bundle for a policy."""
        self._require_connection()
        key = self._record_key_bytes(record_key)
        result = self._compliance_result_from_contract(
            key,
            self.contract.functions.readComplianceResult(key).call(),
        )
        chunks = tuple(
            bytes(self.contract.functions.readComplianceChunk(key, index).call())
            for index in range(result.chunkCount)
        )
        content = OnChainComplianceContent(
            result=result,
            bundle=b"".join(chunks),
            chunks=chunks,
        )
        comparisons = {
            "bundle hash": content.bundle_hash == result.bundleHash,
            "bundle size": len(content.bundle) == result.bundleSize,
            "chunk count": len(content.chunks) == result.chunkCount,
            "chunk commitment": content.chunk_commitment == result.chunkCommitment,
        }
        failures = [name for name, valid in comparisons.items() if not valid]
        if failures:
            raise RuntimeError(
                "Stored compliance bundle failed validation: " + ", ".join(failures)
            )
        return content

    def list_records(self) -> list[ChainRecord]:
        self._require_connection()
        logs = self.contract.events.TrustedPolicyRecordRegistered().get_logs(
            from_block=self.from_block, to_block="latest"
        )
        return [
            self._record_from_event(
                log, self.web3.eth.get_transaction_receipt(log["transactionHash"])
            )
            for log in logs
        ]

    def audit_registration(self, identifier: str) -> dict[str, Any]:
        """Audit finalized content from contract storage, using a record key or final tx hash."""
        self._require_connection()
        record = self._record_from_identifier(identifier)
        content = self.read_on_chain_content(record.recordKey)
        final_transaction = self.web3.eth.get_transaction(record.txHash)
        final_receipt = self.web3.eth.get_transaction_receipt(record.txHash)
        function, arguments = self.contract.decode_function_input(final_transaction["input"])
        finalized_key = self._record_key_bytes(arguments.get("recordKey", bytes(32)))
        checks = {
            "finalizationTransactionSucceeded": final_receipt["status"] == 1,
            "finalizationTargetsContract": (
                final_transaction.get("to") is not None
                and final_transaction["to"].lower() == self.contract.address.lower()
            ),
            "finalizationFunctionMatches": function.fn_name == "finalizePolicyRegistration",
            "finalizationRecordKeyMatches": Web3.to_hex(finalized_key) == record.recordKey,
            "documentHashMatchesStoredContent": content.document_hash == record.data.documentHash,
            "metadataHashMatchesStoredContent": content.metadata_hash == record.data.metadataHash,
            "documentSizeMatchesStoredContent": len(content.rawFile) == record.data.documentSize,
            "metadataSizeMatchesStoredContent": len(content.metadataJson) == record.data.metadataSize,
            "documentChunkCountMatchesStorage": (
                len(content.documentChunks) == record.data.documentChunkCount
            ),
            "metadataChunkCountMatchesStorage": (
                len(content.metadataChunks) == record.data.metadataChunkCount
            ),
            "documentCommitmentMatchesStorage": (
                content.document_commitment == record.data.documentChunkCommitment
            ),
            "metadataCommitmentMatchesStorage": (
                content.metadata_commitment == record.data.metadataChunkCommitment
            ),
            "senderMatchesRegistrant": (
                final_transaction["from"].lower() == record.data.registrant.lower()
            ),
        }
        return {
            "valid": all(checks.values()),
            "checks": checks,
            "chainId": record.chainId,
            "contractAddress": record.contractAddress,
            "finalizationTxHash": record.txHash,
            "blockNumber": record.blockNumber,
            "blockHash": record.blockHash,
            "recordKey": record.recordKey,
            "registrant": record.data.registrant,
            "abiHash": self.abi_hash,
            "runtimeBytecodeHash": "0x" + Web3.keccak(
                self.web3.eth.get_code(self.contract.address)
            ).hex().removeprefix("0x"),
            "documentHash": content.document_hash,
            "metadataHash": content.metadata_hash,
            "documentBytes": len(content.rawFile),
            "metadataBytes": len(content.metadataJson),
            "documentChunkCount": len(content.documentChunks),
            "metadataChunkCount": len(content.metadataChunks),
            "publisherEntity": record.data.publisherEntity,
            "serviceName": record.data.serviceName,
            "policyVersion": record.data.policyVersion,
        }

    def _append_content(
        self,
        record_key: bytes,
        content_type: str,
        complete_content: bytes,
        offset: int,
        chunk_index: int,
        sender: str,
    ) -> list[ChainTransaction]:
        transactions: list[ChainTransaction] = []
        while offset < len(complete_content):
            remaining = complete_content[offset:]
            chunk, function = self._build_storable_chunk(
                record_key, content_type, chunk_index, remaining, sender
            )
            receipt = self._transact(function, sender)
            transactions.append(
                self._transaction(
                    receipt,
                    "chunk",
                    content_type=content_type,
                    chunk_index=chunk_index,
                    chunk_bytes=len(chunk),
                )
            )
            offset += len(chunk)
            chunk_index += 1
        return transactions

    def _build_storable_chunk(
        self,
        record_key: bytes,
        content_type: str,
        chunk_index: int,
        remaining: bytes,
        sender: str,
    ) -> tuple[bytes, Any]:
        contract_limit = int(self.contract.functions.MAX_CHUNK_BYTES().call())
        size = min(self.configured_chunk_size, contract_limit, len(remaining))
        last_error: Exception | None = None
        while size > 0:
            chunk = remaining[:size]
            function = self._append_function(record_key, content_type, chunk_index, chunk)
            try:
                estimated = int(function.estimate_gas({"from": sender}))
                block_gas_limit = int(self.web3.eth.get_block("latest")["gasLimit"])
                if estimated >= int(block_gas_limit * 0.8):
                    raise RuntimeError(
                        f"estimated chunk gas {estimated} is too close to block gas limit {block_gas_limit}"
                    )
                return chunk, function
            except Exception as exc:
                last_error = exc
                if size == 1:
                    break
                size = max(1, size // 2)
        raise RuntimeError(
            f"Unable to store {content_type} chunk {chunk_index}, even after reducing its size"
        ) from last_error

    def _append_function(
        self, record_key: bytes, content_type: str, chunk_index: int, chunk: bytes
    ) -> Any:
        if content_type == "document":
            return self.contract.functions.appendDocumentChunk(record_key, chunk_index, chunk)
        if content_type == "metadata":
            return self.contract.functions.appendMetadataChunk(record_key, chunk_index, chunk)
        raise ValueError(f"Unsupported content type: {content_type}")

    def _transact(self, function: Any, sender: str) -> Any:
        tx_hash = function.transact({"from": sender})
        receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status != 1:
            raise RuntimeError(f"On-chain policy transaction reverted: {tx_hash.hex()}")
        return receipt

    def _transaction(
        self,
        receipt: Any,
        phase: str,
        content_type: str = "",
        chunk_index: int | None = None,
        chunk_bytes: int = 0,
    ) -> ChainTransaction:
        return ChainTransaction(
            phase=phase,
            txHash=Web3.to_hex(receipt["transactionHash"]),
            blockNumber=int(receipt["blockNumber"]),
            gasUsed=int(receipt["gasUsed"]),
            contentType=content_type,
            chunkIndex=chunk_index,
            chunkBytes=chunk_bytes,
        )

    def _read_upload_progress(self, record_key: bytes) -> UploadProgress:
        pending = self.contract.functions.readUploadProgress(record_key).call()
        return UploadProgress(
            documentHash=Web3.to_hex(pending[0]),
            metadataHash=Web3.to_hex(pending[1]),
            documentChunkCommitment=Web3.to_hex(pending[2]),
            metadataChunkCommitment=Web3.to_hex(pending[3]),
            documentSize=int(pending[4]),
            metadataSize=int(pending[5]),
            documentBytesStored=int(pending[6]),
            metadataBytesStored=int(pending[7]),
            documentChunkCount=int(pending[8]),
            metadataChunkCount=int(pending[9]),
            publisherEntity=pending[10],
            serviceName=pending[11],
            policyVersion=pending[12],
            effectiveDate=pending[13],
            registrant=pending[14],
        )

    def _validate_resumable_upload(
        self, record_key: bytes, progress: UploadProgress, data: OnChainData, sender: str
    ) -> None:
        expected = {
            "documentHash": "0x" + hashlib.sha256(data.rawFile).hexdigest(),
            "metadataHash": "0x" + hashlib.sha256(data.metadataJson).hexdigest(),
            "documentSize": len(data.rawFile),
            "metadataSize": len(data.metadataJson),
            "publisherEntity": data.publisherEntity,
            "serviceName": data.serviceName,
            "policyVersion": data.policyVersion,
            "effectiveDate": data.effectiveDate,
        }
        mismatches = [
            name for name, value in expected.items() if getattr(progress, name) != value
        ]
        if progress.registrant.lower() != sender.lower():
            mismatches.append("registrant")
        if mismatches:
            raise RuntimeError(
                f"Pending upload {Web3.to_hex(record_key)} does not match this request: "
                + ", ".join(mismatches)
            )

    def _validated_prefix(
        self, complete_content: bytes, stored_chunks: list[bytes], content_type: str
    ) -> int:
        stored = b"".join(stored_chunks)
        if not complete_content.startswith(stored):
            raise RuntimeError(
                f"Pending {content_type} chunks do not match the supplied content"
            )
        return len(stored)

    def _validate_pending_chunks(
        self,
        progress: UploadProgress,
        document_chunks: list[bytes],
        metadata_chunks: list[bytes],
    ) -> None:
        comparisons = {
            "document byte count": (
                sum(map(len, document_chunks)) == progress.documentBytesStored
            ),
            "metadata byte count": (
                sum(map(len, metadata_chunks)) == progress.metadataBytesStored
            ),
            "document commitment": (
                Web3.to_hex(content_commitment(document_chunks))
                == progress.documentChunkCommitment
            ),
            "metadata commitment": (
                Web3.to_hex(content_commitment(metadata_chunks))
                == progress.metadataChunkCommitment
            ),
        }
        failures = [name for name, valid in comparisons.items() if not valid]
        if failures:
            raise RuntimeError(
                "Pending on-chain upload failed validation: " + ", ".join(failures)
            )

    def _read_chunks(
        self, record_key: bytes, content_type: str, chunk_count: int
    ) -> list[bytes]:
        if content_type == "document":
            reader: Callable[[bytes, int], Any] = (
                lambda key, index: self.contract.functions.readDocumentChunk(key, index)
            )
        elif content_type == "metadata":
            reader = lambda key, index: self.contract.functions.readMetadataChunk(key, index)
        else:
            raise ValueError(f"Unsupported content type: {content_type}")
        return [bytes(reader(record_key, index).call()) for index in range(chunk_count)]

    def _require_content_matches_record(
        self, content: OnChainContent, record: StoredChainData
    ) -> None:
        comparisons = {
            "document hash": content.document_hash == record.documentHash,
            "metadata hash": content.metadata_hash == record.metadataHash,
            "document size": len(content.rawFile) == record.documentSize,
            "metadata size": len(content.metadataJson) == record.metadataSize,
            "document commitment": (
                content.document_commitment == record.documentChunkCommitment
            ),
            "metadata commitment": (
                content.metadata_commitment == record.metadataChunkCommitment
            ),
        }
        failures = [name for name, valid in comparisons.items() if not valid]
        if failures:
            raise RuntimeError("Stored on-chain content failed validation: " + ", ".join(failures))

    def _require_finalized_request_matches(
        self, record: ChainRecord, content: OnChainContent, data: OnChainData
    ) -> None:
        """Make retries idempotent when finalization succeeded before SQL persistence."""
        self._require_content_matches_record(content, record.data)
        comparisons = {
            "document content": content.rawFile == data.rawFile,
            "metadata content": content.metadataJson == data.metadataJson,
            "publisher": record.data.publisherEntity == data.publisherEntity,
            "service": record.data.serviceName == data.serviceName,
            "version": record.data.policyVersion == data.policyVersion,
            "effective date": record.data.effectiveDate == data.effectiveDate,
        }
        failures = [name for name, valid in comparisons.items() if not valid]
        if failures:
            raise RuntimeError(
                "Finalized record exists but does not match this retry: " + ", ".join(failures)
            )

    def _manifest_tuple(self, data: OnChainData) -> tuple[Any, ...]:
        return (
            hashlib.sha256(data.rawFile).digest(),
            hashlib.sha256(data.metadataJson).digest(),
            len(data.rawFile),
            len(data.metadataJson),
            data.publisherEntity,
            data.serviceName,
            data.policyVersion,
            data.effectiveDate,
        )

    def _sender_account(self) -> str:
        configured = os.environ.get("BLOCKCHAIN_ACCOUNT")
        if configured:
            return Web3.to_checksum_address(configured)
        accounts = self.web3.eth.accounts
        if not accounts:
            raise RuntimeError("RPC node exposes no unlocked account. Set BLOCKCHAIN_ACCOUNT.")
        return accounts[0]

    def _require_connection(self) -> None:
        if not self.web3.is_connected():
            raise RuntimeError(f"Cannot connect to Ethereum RPC at {self.rpc_url}")
        if not self.web3.eth.get_code(self.contract.address):
            raise RuntimeError(f"No contract is deployed at {self.contract.address} on {self.rpc_url}")

    def _find_registration_event_by_key(self, record_key: bytes) -> Any:
        logs = self.contract.events.TrustedPolicyRecordRegistered().get_logs(
            from_block=self.from_block,
            to_block="latest",
            argument_filters={"recordKey": record_key},
        )
        if logs:
            return logs[-1]
        raise RuntimeError("On-chain record exists but its finalization event was not found")

    def _registration_transactions(
        self, record_key: bytes
    ) -> tuple[ChainTransaction, ...]:
        entries: list[tuple[int, int, ChainTransaction]] = []
        started_logs = self.contract.events.PolicyUploadStarted().get_logs(
            from_block=self.from_block,
            to_block="latest",
            argument_filters={"recordKey": record_key},
        )
        for event in started_logs:
            receipt = self.web3.eth.get_transaction_receipt(event["transactionHash"])
            entries.append(
                (
                    int(event["blockNumber"]),
                    int(event["logIndex"]),
                    self._transaction(receipt, "begin"),
                )
            )
        chunk_logs = self.contract.events.PolicyChunkStored().get_logs(
            from_block=self.from_block,
            to_block="latest",
            argument_filters={"recordKey": record_key},
        )
        for event in chunk_logs:
            receipt = self.web3.eth.get_transaction_receipt(event["transactionHash"])
            content_type = "document" if int(event["args"]["contentType"]) == 0 else "metadata"
            entries.append(
                (
                    int(event["blockNumber"]),
                    int(event["logIndex"]),
                    self._transaction(
                        receipt,
                        "chunk",
                        content_type=content_type,
                        chunk_index=int(event["args"]["chunkIndex"]),
                        chunk_bytes=int(event["args"]["chunkSize"]),
                    ),
                )
            )
        finalized_logs = self.contract.events.TrustedPolicyRecordRegistered().get_logs(
            from_block=self.from_block,
            to_block="latest",
            argument_filters={"recordKey": record_key},
        )
        for event in finalized_logs:
            receipt = self.web3.eth.get_transaction_receipt(event["transactionHash"])
            entries.append(
                (
                    int(event["blockNumber"]),
                    int(event["logIndex"]),
                    self._transaction(receipt, "finalize"),
                )
            )
        return tuple(item[2] for item in sorted(entries, key=lambda item: item[:2]))

    def _try_read_record_by_key(self, record_key: bytes) -> ChainRecord | None:
        if not self.contract.functions.hasRecord(record_key).call():
            return None
        record = self.contract.functions.readRecordByKey(record_key).call()
        event = self._find_registration_event_by_key(record_key)
        receipt = self.web3.eth.get_transaction_receipt(event["transactionHash"])
        return self._record_from_contract(
            record, event, receipt, self._registration_transactions(record_key)
        )

    def _record_from_identifier(self, identifier: str) -> ChainRecord:
        try:
            receipt = self.web3.eth.get_transaction_receipt(identifier)
        except Exception:
            return self.read_record_by_key(identifier)
        events = self.contract.events.TrustedPolicyRecordRegistered().process_receipt(receipt)
        if not events:
            raise RuntimeError("Transaction is not a finalized policy registration")
        return self._record_from_event(events[0], receipt)

    def _record_key_bytes(self, record_key: str | bytes) -> bytes:
        if isinstance(record_key, str):
            value = Web3.to_bytes(hexstr=record_key)
        else:
            value = bytes(record_key)
        if len(value) != 32:
            raise ValueError("recordKey must be exactly 32 bytes")
        return value

    def _compliance_result_from_contract(
        self, record_key: bytes, result: Any
    ) -> ComplianceResult:
        return ComplianceResult(
            recordKey=Web3.to_hex(record_key),
            bundleHash=Web3.to_hex(result[0]),
            sourceDocumentHash=Web3.to_hex(result[1]),
            pipelineVersionHash=Web3.to_hex(result[2]),
            chunkCommitment=Web3.to_hex(result[3]),
            bundleSize=int(result[4]),
            chunkCount=int(result[5]),
            submitter=result[6],
            registeredAt=int(result[7]),
        )

    def _record_from_event(
        self,
        event: Any,
        receipt: Any,
        transactions: tuple[ChainTransaction, ...] = (),
    ) -> ChainRecord:
        record = self.contract.functions.readRecordByKey(event["args"]["recordKey"]).call()
        return self._record_from_contract(record, event, receipt, transactions)

    def _record_from_contract(
        self,
        record: Any,
        event: Any,
        receipt: Any,
        transactions: tuple[ChainTransaction, ...] = (),
    ) -> ChainRecord:
        args = event["args"]
        block = self.web3.eth.get_block(event["blockNumber"])
        previous_version = ""
        if record[15]:
            previous = self.contract.functions.readRecordByKey(record[14]).call()
            previous_version = previous[10]
        data = StoredChainData(
            documentHash=Web3.to_hex(record[0]),
            metadataHash=Web3.to_hex(record[1]),
            documentChunkCommitment=Web3.to_hex(record[2]),
            metadataChunkCommitment=Web3.to_hex(record[3]),
            documentSize=int(record[4]),
            metadataSize=int(record[5]),
            documentChunkCount=int(record[6]),
            metadataChunkCount=int(record[7]),
            publisherEntity=record[8],
            serviceName=record[9],
            policyVersion=record[10],
            effectiveDate=record[11],
            registrant=record[12],
            registeredAt=int(record[13]),
            previousRecordKey=Web3.to_hex(record[14]),
            previousPolicyVersion=previous_version,
            hasPreviousReference=bool(record[15]),
        )
        return ChainRecord(
            recordKey=Web3.to_hex(args["recordKey"]),
            blockNumber=int(event["blockNumber"]),
            txHash=Web3.to_hex(event["transactionHash"]),
            timestamp=int(block["timestamp"]),
            gasUsed=int(receipt["gasUsed"]),
            chainId=int(self.web3.eth.chain_id),
            contractAddress=self.contract.address,
            data=data,
            previousBlockHash=Web3.to_hex(block["parentHash"]),
            blockHash=Web3.to_hex(block["hash"]),
            transactions=transactions,
        )
