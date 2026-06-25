from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OnChainData:
    rawFile: str
    policyVersion: str | None = None
    publisherEntity: str = ""
    policyUrl: str = ""
    serviceName: str = ""
    effectiveDate: str = ""
    dataTypeTags: str = ""
    dataSourceTypes: str = ""
    collectionContext: str = ""
    processingPurpose: str = ""
    permittedUsage: str = ""
    thirdPartySources: str = ""
    downstreamStakeholders: str = ""
    thirdPartyPurpose: str = ""
    sharingCondition: str = ""
    consentRequired: str = ""
    optOutAvailable: str = ""
    deletionAvailable: str = ""
    requestChannel: str = ""
    retentionPolicy: str = ""
    encryptionApplied: str = ""
    anonymisation: str = ""
    regulatoryFramework: str = ""
    crossBorderTransfer: str = ""
    childDataInvolved: str = ""
    changeSummary: str = ""
    contactChannel: str = ""
    riskFlags: str = ""
    previousRecordKey: str = ""
    previousPolicyVersion: str = ""
    hasPreviousReference: bool = False


@dataclass(frozen=True)
class ChainRecord:
    recordKey: str
    blockNumber: int
    txHash: str
    timestamp: int
    data: OnChainData
    previousBlockHash: str
    blockHash: str


class TrustedPolicyRegistry:
    """Append-only local ledger that mirrors a smart-contract registration API."""

    def __init__(self, ledger_path: Path):
        self.ledger_path = ledger_path
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.ledger_path.exists():
            self.ledger_path.write_text("[]\n", encoding="utf-8")

    def register_trusted_policy_record(self, data: OnChainData) -> ChainRecord:
        chain = self._load()
        previous_hash = chain[-1]["blockHash"] if chain else "GENESIS"
        previous_policy_record = self._latest_policy_record(chain, data.publisherEntity, data.serviceName)
        previous_record_key = previous_policy_record["recordKey"] if previous_policy_record else ""
        data = replace(
            data,
            previousRecordKey=previous_record_key,
            previousPolicyVersion=(
                previous_policy_record["data"].get("policyVersion", "") if previous_policy_record else ""
            ),
            hasPreviousReference=bool(previous_policy_record),
        )
        record_key = self._record_key(data.publisherEntity, data.serviceName, data.policyVersion)
        block_number = len(chain) + 1
        timestamp = int(time.time())
        tx_hash = "0x" + hashlib.sha256(
            f"{uuid.uuid4()}:{data.publisherEntity}:{data.serviceName}:{data.policyVersion}:{timestamp}".encode("utf-8")
        ).hexdigest()
        block_hash = self._block_hash(block_number, tx_hash, timestamp, data, previous_hash)
        record = ChainRecord(
            recordKey=record_key,
            blockNumber=block_number,
            txHash=tx_hash,
            timestamp=timestamp,
            data=data,
            previousBlockHash=previous_hash,
            blockHash=block_hash,
        )
        chain.append(self._to_json(record))
        self.ledger_path.write_text(json.dumps(chain, indent=2), encoding="utf-8")
        return record

    def read_on_chain_record(
        self,
        publisher_entity: str,
        service_name: str,
        policy_version: str | None = None,
    ) -> ChainRecord | None:
        matches = []
        for item in self._load():
            data = item["data"]
            same_policy = (
                data.get("publisherEntity") == publisher_entity
                and data.get("serviceName") == service_name
            )
            same_version = policy_version is None or data.get("policyVersion") == policy_version
            if same_policy and same_version:
                matches.append(item)
        if not matches:
            return None
        return self._from_json(matches[-1])

    def list_records(self) -> list[ChainRecord]:
        return [self._from_json(item) for item in self._load()]

    def _load(self) -> list[dict[str, Any]]:
        return json.loads(self.ledger_path.read_text(encoding="utf-8"))

    def _latest_policy_record(
        self,
        chain: list[dict[str, Any]],
        publisher_entity: str,
        service_name: str,
    ) -> dict[str, Any] | None:
        for item in reversed(chain):
            data = item["data"]
            if data.get("publisherEntity") == publisher_entity and data.get("serviceName") == service_name:
                return item
        return None

    def _record_key(self, publisher_entity: str, service_name: str, policy_version: str | None) -> str:
        payload = json.dumps([publisher_entity, service_name, policy_version or ""], ensure_ascii=False)
        return "0x" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _block_hash(
        self,
        block_number: int,
        tx_hash: str,
        timestamp: int,
        data: OnChainData,
        previous_hash: str,
    ) -> str:
        payload = json.dumps(
            {
                "blockNumber": block_number,
                "txHash": tx_hash,
                "timestamp": timestamp,
                "data": asdict(data),
                "previousBlockHash": previous_hash,
            },
            sort_keys=True,
        )
        return "0x" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _to_json(self, record: ChainRecord) -> dict[str, Any]:
        return {
            "recordKey": record.recordKey,
            "blockNumber": record.blockNumber,
            "txHash": record.txHash,
            "timestamp": record.timestamp,
            "data": asdict(record.data),
            "previousBlockHash": record.previousBlockHash,
            "blockHash": record.blockHash,
        }

    def _from_json(self, item: dict[str, Any]) -> ChainRecord:
        data = dict(item["data"])
        data.pop("policyId", None)
        data.pop("hashCode", None)
        return ChainRecord(
            recordKey=item.get("recordKey", ""),
            blockNumber=item["blockNumber"],
            txHash=item["txHash"],
            timestamp=item["timestamp"],
            data=OnChainData(**data),
            previousBlockHash=item["previousBlockHash"],
            blockHash=item["blockHash"],
        )
