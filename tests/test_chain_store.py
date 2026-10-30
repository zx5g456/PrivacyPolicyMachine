"""Regression checks for Base event ordering, reorgs, and invalid records."""

from __future__ import annotations

import hashlib
import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from requests import Response
from requests.exceptions import HTTPError
from web3 import Web3

from server.blockchain import (
    ChainRecord,
    OnChainContent,
    StoredChainData,
    TrustedPolicyRegistry,
    content_commitment,
)
from server.chain_store import ChainPolicyStore


class FakeChain:
    from_block = 1

    def __init__(self) -> None:
        self.head = 5
        self.block_hashes = {number: bytes([number]) * 32 for number in range(1, 6)}
        self.logs = []
        self.records = {}
        self.contents = {}
        self.web3 = SimpleNamespace(eth=self)
        self.contract = SimpleNamespace(
            events=SimpleNamespace(TrustedPolicyRecordRegistered=lambda: self)
        )

    @property
    def block_number(self) -> int:
        return self.head

    def get_block(self, number: int) -> dict:
        return {"hash": self.block_hashes[number]}

    def get_logs(self, from_block: int, to_block: int) -> list[dict]:
        return [log for log in self.logs if from_block <= log["blockNumber"] <= to_block]

    def get_transaction_receipt(self, tx_hash: bytes) -> dict:
        return {"transactionIndex": int.from_bytes(tx_hash[-1:], "big")}

    def _require_connection(self) -> None:
        pass

    def _record_from_event(self, log: dict, receipt: dict) -> ChainRecord:
        return self.records["0x" + bytes(log["args"]["recordKey"]).hex()]

    def read_record_by_key(self, key: str) -> ChainRecord:
        return self.records[key]

    def read_on_chain_content(self, key: str) -> OnChainContent:
        return self.contents[key]

    def _require_content_matches_record(self, content: OnChainContent, data: StoredChainData) -> None:
        TrustedPolicyRegistry._require_content_matches_record(self, content, data)

    def add(self, suffix: int, block: int, version: str, *, valid: bool = True) -> str:
        key_bytes = bytes([suffix]) * 32
        key = Web3.to_hex(key_bytes)
        tx_hash = bytes([suffix]) * 31 + bytes([suffix])
        raw = f"policy version {version}".encode()
        metadata = {
            "policyId": str(uuid.UUID(int=1)),
            "developer": "alice",
            "publisherEntity": "alice",
            "applicationName": "Example",
            "serviceName": "Example",
            "policyVersion": version,
            "effectiveDate": "",
            "documentHash": hashlib.sha256(raw).hexdigest(),
            "wordCount": 3,
            "sectionCount": 1,
        }
        metadata_bytes = json.dumps(metadata).encode()
        content = OnChainContent(key, raw, metadata_bytes, (raw,), (metadata_bytes,))
        data = StoredChainData(
            documentHash=content.document_hash if valid else "0x" + "00" * 32,
            metadataHash=content.metadata_hash,
            documentChunkCommitment=Web3.to_hex(content_commitment([raw])),
            metadataChunkCommitment=Web3.to_hex(content_commitment([metadata_bytes])),
            documentSize=len(raw),
            metadataSize=len(metadata_bytes),
            documentChunkCount=1,
            metadataChunkCount=1,
            publisherEntity="alice",
            serviceName="Example",
            policyVersion=version,
            effectiveDate="",
            registrant="0x" + "01" * 20,
            registeredAt=100 + block,
            previousRecordKey="0x" + "00" * 32,
            previousPolicyVersion="",
            hasPreviousReference=False,
        )
        record = ChainRecord(
            recordKey=key,
            blockNumber=block,
            transactionIndex=suffix,
            txHash=Web3.to_hex(tx_hash),
            timestamp=100 + block,
            gasUsed=1,
            chainId=8453,
            contractAddress="0x" + "02" * 20,
            data=data,
            previousBlockHash="0x" + "00" * 32,
            blockHash=Web3.to_hex(self.block_hashes[block]),
        )
        self.records[key] = record
        self.contents[key] = content
        self.logs.append({
            "args": {"recordKey": key_bytes},
            "transactionHash": tx_hash,
            "blockNumber": block,
        })
        self.logs.sort(key=lambda log: (log["blockNumber"], log["transactionHash"][-1]))
        return key


class ChainStoreTests(unittest.TestCase):
    @staticmethod
    def _rate_limit_error() -> HTTPError:
        response = Response()
        response.status_code = 429
        return HTTPError("Too Many Requests", response=response)

    def test_registration_logs_recover_after_rate_limit(self) -> None:
        chain = FakeChain()
        key = chain.add(1, 2, "first")
        expected_logs = chain.get_logs(from_block=1, to_block=5)
        store = ChainPolicyStore(chain)

        with patch.object(
            chain, "get_logs",
            side_effect=[self._rate_limit_error(), self._rate_limit_error(), expected_logs],
        ) as get_logs, patch("server.chain_store.time.sleep") as sleep:
            self.assertEqual(store.list_policies()[0]["recordKey"], key)

        self.assertEqual(get_logs.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_registration_logs_surface_persistent_rate_limit(self) -> None:
        chain = FakeChain()
        store = ChainPolicyStore(chain)

        with patch.object(chain, "get_logs", side_effect=self._rate_limit_error()) as get_logs, \
                patch("server.chain_store.time.sleep") as sleep:
            with self.assertRaises(HTTPError):
                store.list_policies()

        self.assertEqual(get_logs.call_count, 5)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2, 4, 8])
        self.assertEqual(store._next_block, chain.from_block)

    def test_latest_record_and_reorg_recovery(self) -> None:
        chain = FakeChain()
        first = chain.add(1, 2, "first")
        second = chain.add(2, 3, "second")
        store = ChainPolicyStore(chain)
        self.assertEqual(store.get_by_record_key(second)["recordKey"], second)
        self.assertEqual([p["recordKey"] for p in store.list_policies()], [second, first])

        chain.block_hashes[3] = bytes([9]) * 32
        chain.block_hashes[4] = bytes([9]) * 32
        chain.block_hashes[5] = bytes([9]) * 32
        chain.logs = [log for log in chain.logs if log["blockNumber"] != 3]
        third = chain.add(3, 4, "third")
        self.assertEqual([p["recordKey"] for p in store.list_policies()], [third, first])

    def test_invalid_hash_does_not_hide_later_records(self) -> None:
        chain = FakeChain()
        first = chain.add(1, 2, "first")
        invalid = chain.add(2, 3, "forged", valid=False)
        third = chain.add(3, 4, "third")
        store = ChainPolicyStore(chain)
        self.assertEqual([p["recordKey"] for p in store.list_policies()], [third, first])
        self.assertEqual(store.list_audit_issues()[0]["recordKey"], invalid)


if __name__ == "__main__":
    unittest.main()
