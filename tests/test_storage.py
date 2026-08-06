import sqlite3
import tempfile
import unittest
from pathlib import Path

from server.storage import PolicyStore


class UploadMethodStorageTests(unittest.TestCase):
    def test_existing_database_is_migrated_with_fast_default(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "policies.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """create table policies (
                        id integer primary key autoincrement,
                        policy_id text not null,
                        policy_name text not null default '',
                        policy_version text,
                        developer_name text not null default '',
                        raw_file text not null,
                        hash_code text not null,
                        metadata_json text not null,
                        report_json text not null,
                        tx_hash text not null,
                        created_at text not null default current_timestamp
                    )"""
                )
                conn.execute(
                    """insert into policies (
                        policy_id, policy_name, developer_name, raw_file, hash_code,
                        metadata_json, report_json, tx_hash
                    ) values ('old', 'Old App', 'alice', 'text', 'hash', '{}', '{}', 'tx')"""
                )

            store = PolicyStore(db_path)

            self.assertEqual(store.get_latest("old")["upload_method"], "fast")

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
            )

            self.assertEqual(policy["upload_method"], "manual")


if __name__ == "__main__":
    unittest.main()
