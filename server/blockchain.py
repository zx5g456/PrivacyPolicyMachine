from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OnChainData:
    rawFile: str
    policyId: str
    policyVersion: str | None = None
    hashCode: str | None = None


@dataclass(frozen=True)
class ChainRecord:
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
        block_number = len(chain) + 1
        timestamp = int(time.time())
        tx_hash = "0x" + hashlib.sha256(
            f"{uuid.uuid4()}:{data.policyId}:{data.policyVersion}:{timestamp}".encode("utf-8")
        ).hexdigest()
        block_hash = self._block_hash(block_number, tx_hash, timestamp, data, previous_hash)
        record = ChainRecord(
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

    def read_on_chain_record(self, policy_id: str, policy_version: str | None = None) -> ChainRecord | None:
        matches = []
        for item in self._load():
            data = item["data"]
            same_policy = data["policyId"] == policy_id
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
            "blockNumber": record.blockNumber,
            "txHash": record.txHash,
            "timestamp": record.timestamp,
            "data": asdict(record.data),
            "previousBlockHash": record.previousBlockHash,
            "blockHash": record.blockHash,
        }

    def _from_json(self, item: dict[str, Any]) -> ChainRecord:
        return ChainRecord(
            blockNumber=item["blockNumber"],
            txHash=item["txHash"],
            timestamp=item["timestamp"],
            data=OnChainData(**item["data"]),
            previousBlockHash=item["previousBlockHash"],
            blockHash=item["blockHash"],
        )

