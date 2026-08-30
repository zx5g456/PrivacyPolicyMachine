import sqlite3
import tempfile
import unittest
from pathlib import Path

from server.storage import PolicyStore


class UploadMethodStorageTests(unittest.TestCase):
    def test_upload_method_is_saved_and_returned(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PolicyStore(Path(directory) / "policies.db")

            policy = store.create_policy(
                policy_id="policy-1",
                policy_name="Reviewed App",
                policy_version="2026-08-06T10:00:00",
                developer_name="alice",
                raw_file="Privacy policy",
                hash_code="hash",
                upload_method="manual",
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

            self.assertEqual(policy["uploadMethod"], "manual")
            self.assertEqual(policy["metadataHash"], "metadata-hash")
            self.assertEqual(policy["blockNumber"], 7)
            self.assertEqual(policy["policyId"], "policy-1")
            self.assertNotIn("policy_id", policy)

    def test_fresh_schema_rejects_duplicate_policy_content(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PolicyStore(Path(directory) / "policies.db")
            common = {
                "policy_name": "Reviewed App",
                "developer_name": "alice",
                "raw_file": "Privacy policy",
                "hash_code": "same-hash",
                "upload_method": "manual",
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
