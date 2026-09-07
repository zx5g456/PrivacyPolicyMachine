import sqlite3
import tempfile
import unittest
from pathlib import Path

from server.storage import PolicyStore


class PolicyStorageTests(unittest.TestCase):
    def test_ai_upload_method_is_saved_and_returned(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PolicyStore(Path(directory) / "policies.db")

            policy = store.create_policy(
                policy_id="policy-1",
                policy_name="Reviewed App",
                policy_version="2026-08-06T10:00:00",
                developer_name="alice",
                raw_file="Privacy policy",
                hash_code="hash",
                metadata={},
                report={},
                tx_hash="tx",
                metadata_hash="metadata-hash",
                record_key="record-key",
                block_number=7,
                block_hash="block-hash",
                contract_address="0xcontract",
                chain_id=31337,
            )

            self.assertEqual(policy["uploadMethod"], "ai")
            self.assertEqual(policy["metadataHash"], "metadata-hash")
            self.assertEqual(policy["blockNumber"], 7)
            self.assertEqual(policy["policyId"], "policy-1")
            self.assertEqual(policy["chainTransactions"], [])
            self.assertEqual(policy["documentChunkCount"], 0)
            self.assertNotIn("policy_id", policy)

    def test_chunk_manifest_is_saved_and_returned(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PolicyStore(Path(directory) / "policies.db")

            policy = store.create_policy(
                policy_id="policy-chunked",
                policy_name="Large Policy App",
                policy_version="2026-09-07T10:00:00",
                developer_name="alice",
                raw_file="large privacy policy",
                hash_code="chunked-hash",
                metadata={},
                report={},
                tx_hash="finalize-tx",
                metadata_hash="metadata-hash",
                record_key="record-key",
                block_number=12,
                block_hash="block-hash",
                contract_address="0xcontract",
                chain_id=31337,
                chain_transactions=[
                    {"phase": "chunk", "chunkIndex": 0, "txHash": "chunk-tx"}
                ],
                document_chunk_count=3,
                metadata_chunk_count=1,
                document_size=10000,
                metadata_size=500,
                document_chunk_commitment="document-commitment",
                metadata_chunk_commitment="metadata-commitment",
            )

            self.assertEqual(policy["chainTransactions"][0]["txHash"], "chunk-tx")
            self.assertEqual(policy["documentChunkCount"], 3)
            self.assertEqual(policy["metadataChunkCount"], 1)
            self.assertEqual(policy["documentSize"], 10000)
            self.assertEqual(policy["documentChunkCommitment"], "document-commitment")

    def test_existing_database_is_migrated_for_chunk_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "policies.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    create table policies (
                        id integer primary key autoincrement,
                        policyId text not null,
                        policyName text not null default '',
                        policyVersion text not null,
                        developerName text not null default '',
                        rawFile text not null,
                        hashCode text not null unique,
                        uploadMethod text not null default 'ai',
                        metadataJson text not null,
                        reportJson text not null,
                        txHash text not null unique,
                        metadataHash text not null,
                        recordKey text not null unique,
                        blockNumber integer not null,
                        blockHash text not null default '',
                        contractAddress text not null default '',
                        chainId integer not null,
                        createdAt text not null default current_timestamp,
                        unique (policyId, policyVersion)
                    )
                    """
                )

            PolicyStore(db_path)

            with sqlite3.connect(db_path) as conn:
                columns = {row[1] for row in conn.execute("pragma table_info(policies)")}
            self.assertIn("chainTransactionsJson", columns)
            self.assertIn("documentChunkCommitment", columns)

    def test_fresh_schema_rejects_duplicate_policy_content(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PolicyStore(Path(directory) / "policies.db")
            common = {
                "policy_name": "Reviewed App",
                "developer_name": "alice",
                "raw_file": "Privacy policy",
                "hash_code": "same-hash",
                "metadata": {},
                "report": {},
                "metadata_hash": "metadata-hash",
                "block_number": 7,
                "block_hash": "block-hash",
                "contract_address": "0xcontract",
                "chain_id": 31337,
            }
            store.create_policy(
                policy_id="policy-1",
                policy_version="2026-08-30T10:00:00",
                tx_hash="tx-1",
                record_key="record-1",
                **common,
            )

            with self.assertRaises(sqlite3.IntegrityError):
                store.create_policy(
                    policy_id="policy-2",
                    policy_version="2026-08-30T11:00:00",
                    tx_hash="tx-2",
                    record_key="record-2",
                    **common,
                )


if __name__ == "__main__":
    unittest.main()
