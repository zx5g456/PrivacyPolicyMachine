from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from web3 import Web3


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


@dataclass(frozen=True)
class RecoveredRegistration:
    txHash: str
    blockNumber: int
    blockHash: str
    chainId: int
    contractAddress: str
    sender: str
    status: int
    functionName: str
    rawFile: bytes
    metadataJson: bytes
    publisherEntity: str
    serviceName: str
    policyVersion: str
    effectiveDate: str

    @property
    def document_hash(self) -> str:
        return "0x" + hashlib.sha256(self.rawFile).hexdigest()

    @property
    def metadata_hash(self) -> str:
        return "0x" + hashlib.sha256(self.metadataJson).hexdigest()


class TrustedPolicyRegistry:
    """Web3 client and independent calldata audit helper for the registry."""

    def __init__(self, artifact_path: Path):
        self.rpc_url = os.environ.get("RPC_URL", "http://127.0.0.1:8545")
        self.contract_address = os.environ.get("CONTRACT_ADDRESS", "")
        self.from_block = int(os.environ.get("CONTRACT_DEPLOYMENT_BLOCK", "0"))
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
        self._require_connection()
        with self._transaction_lock:
            tx_hash = self.contract.functions.registerTrustedPolicyRecord(
                self._registration_tuple(data)
            ).transact({"from": self._sender_account()})
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status != 1:
            raise RuntimeError(f"Policy registration transaction reverted: {tx_hash.hex()}")
        events = self.contract.events.TrustedPolicyRecordRegistered().process_receipt(receipt)
        if not events:
            raise RuntimeError("Registration succeeded but its contract event was not found")
        return self._record_from_event(events[0], receipt)

    def read_on_chain_record(self, publisher: str, service: str, version: str | None = None) -> ChainRecord | None:
        self._require_connection()
        if version is None:
            matches = [r for r in self.list_records() if r.data.publisherEntity == publisher and r.data.serviceName == service]
            return matches[-1] if matches else None
        try:
            record = self.contract.functions.readOnChainRecord(publisher, service, version).call()
        except Exception as exc:
            if "Policy record not found" in str(exc):
                return None
            raise
        event = self._find_registration_event(publisher, service, version)
        receipt = self.web3.eth.get_transaction_receipt(event["transactionHash"])
        return self._record_from_contract(record, event, receipt)

    def list_records(self) -> list[ChainRecord]:
        self._require_connection()
        logs = self.contract.events.TrustedPolicyRecordRegistered().get_logs(
            from_block=self.from_block, to_block="latest"
        )
        return [self._record_from_event(log, self.web3.eth.get_transaction_receipt(log["transactionHash"])) for log in logs]

    def recover_registration(self, tx_hash: str) -> RecoveredRegistration:
        self._require_connection()
        transaction = self.web3.eth.get_transaction(tx_hash)
        receipt = self.web3.eth.get_transaction_receipt(tx_hash)
        destination = transaction.get("to")
        if destination is None or destination.lower() != self.contract.address.lower():
            raise RuntimeError("Transaction was not sent to the configured registry contract")
        function, arguments = self.contract.decode_function_input(transaction["input"])
        if function.fn_name != "registerTrustedPolicyRecord":
            raise RuntimeError("Transaction is not a policy registration")
        values = self._registration_values(arguments["data"])
        block = self.web3.eth.get_block(receipt["blockNumber"])
        return RecoveredRegistration(
            txHash=Web3.to_hex(transaction["hash"]), blockNumber=receipt["blockNumber"],
            blockHash=Web3.to_hex(block["hash"]), chainId=self.web3.eth.chain_id,
            contractAddress=self.contract.address, sender=transaction["from"], status=receipt["status"],
            functionName=function.fn_name, rawFile=bytes(values[0]), metadataJson=bytes(values[1]),
            publisherEntity=values[2], serviceName=values[3], policyVersion=values[4], effectiveDate=values[5],
        )

    def audit_registration(self, tx_hash: str) -> dict[str, Any]:
        recovered = self.recover_registration(tx_hash)
        record = self.read_on_chain_record(recovered.publisherEntity, recovered.serviceName, recovered.policyVersion)
        if record is None:
            raise RuntimeError("Registration calldata has no matching contract record")
        checks = {
            "transactionSucceeded": recovered.status == 1,
            "transactionTargetsContract": recovered.contractAddress.lower() == self.contract.address.lower(),
            "registrationFunctionMatches": recovered.functionName == "registerTrustedPolicyRecord",
            "documentHashMatchesStorage": recovered.document_hash == record.data.documentHash,
            "metadataHashMatchesStorage": recovered.metadata_hash == record.data.metadataHash,
            "publisherMatchesStorage": recovered.publisherEntity == record.data.publisherEntity,
            "serviceNameMatchesStorage": recovered.serviceName == record.data.serviceName,
            "versionMatchesStorage": recovered.policyVersion == record.data.policyVersion,
            "senderMatchesRegistrant": recovered.sender.lower() == record.data.registrant.lower(),
            "eventTransactionMatches": recovered.txHash == record.txHash,
        }
        return {
            "valid": all(checks.values()), "checks": checks, "chainId": recovered.chainId,
            "contractAddress": recovered.contractAddress, "txHash": recovered.txHash,
            "blockNumber": recovered.blockNumber, "blockHash": recovered.blockHash,
            "recordKey": record.recordKey, "registrant": recovered.sender,
            "abiHash": self.abi_hash,
            "runtimeBytecodeHash": "0x" + Web3.keccak(
                self.web3.eth.get_code(self.contract.address)
            ).hex().removeprefix("0x"),
            "documentHash": recovered.document_hash, "metadataHash": recovered.metadata_hash,
            "rawFileBytes": len(recovered.rawFile), "metadataBytes": len(recovered.metadataJson),
            "publisherEntity": recovered.publisherEntity, "serviceName": recovered.serviceName,
            "policyVersion": recovered.policyVersion,
        }

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

    def _registration_tuple(self, data: OnChainData) -> tuple[Any, ...]:
        return (data.rawFile, data.metadataJson, data.publisherEntity, data.serviceName, data.policyVersion, data.effectiveDate)

    def _registration_values(self, registration: Any) -> tuple[Any, ...]:
        if isinstance(registration, dict):
            keys = ("rawFile", "metadataJson", "publisherEntity", "serviceName", "policyVersion", "effectiveDate")
            return tuple(registration[key] for key in keys)
        return tuple(registration)

    def _find_registration_event(self, publisher: str, service: str, version: str) -> Any:
        expected_key = self.contract.functions.getRecordKey(publisher, service, version).call()
        logs = self.contract.events.TrustedPolicyRecordRegistered().get_logs(from_block=self.from_block, to_block="latest")
        for event in reversed(logs):
            if event["args"]["recordKey"] == expected_key:
                return event
        raise RuntimeError("On-chain record exists but its registration event was not found")

    def _record_from_event(self, event: Any, receipt: Any) -> ChainRecord:
        record = self.contract.functions.readRecordByKey(event["args"]["recordKey"]).call()
        return self._record_from_contract(record, event, receipt)

    def _record_from_contract(self, record: Any, event: Any, receipt: Any) -> ChainRecord:
        args = event["args"]
        block = self.web3.eth.get_block(event["blockNumber"])
        previous_version = ""
        if record[9]:
            previous = self.contract.functions.readRecordByKey(record[8]).call()
            previous_version = previous[4]
        data = StoredChainData(
            documentHash=Web3.to_hex(record[0]), metadataHash=Web3.to_hex(record[1]),
            publisherEntity=record[2], serviceName=record[3], policyVersion=record[4], effectiveDate=record[5],
            registrant=record[6], registeredAt=record[7], previousRecordKey=Web3.to_hex(record[8]),
            previousPolicyVersion=previous_version, hasPreviousReference=record[9],
        )
        return ChainRecord(
            recordKey=Web3.to_hex(args["recordKey"]), blockNumber=event["blockNumber"],
            txHash=Web3.to_hex(event["transactionHash"]), timestamp=block["timestamp"],
            gasUsed=receipt["gasUsed"], chainId=self.web3.eth.chain_id, contractAddress=self.contract.address,
            data=data, previousBlockHash=Web3.to_hex(block["parentHash"]), blockHash=Web3.to_hex(block["hash"]),
        )
