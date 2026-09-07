from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class PolicyStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def create_policy(
        self,
        policy_id: str,
        policy_name: str,
        policy_version: str,
        developer_name: str,
        raw_file: str,
        hash_code: str,
        metadata: dict[str, Any],
        report: dict[str, Any],
        tx_hash: str,
        metadata_hash: str,
        record_key: str,
        block_number: int,
        block_hash: str,
        contract_address: str,
        chain_id: int,
        chain_transactions: list[dict[str, Any]] | None = None,
        document_chunk_count: int = 0,
        metadata_chunk_count: int = 0,
        document_size: int = 0,
        metadata_size: int = 0,
        document_chunk_commitment: str = "",
        metadata_chunk_commitment: str = "",
    ) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                """
                insert into policies (
                    policyId, policyName, policyVersion, developerName, rawFile, hashCode, uploadMethod,
                    metadataJson, reportJson, txHash, metadataHash, recordKey, blockNumber,
                    blockHash, contractAddress, chainId, chainTransactionsJson,
                    documentChunkCount, metadataChunkCount, documentSize, metadataSize,
                    documentChunkCommitment, metadataChunkCommitment
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    policy_id,
                    policy_name,
                    policy_version,
                    developer_name,
                    raw_file,
                    hash_code,
                    "ai",
                    json.dumps(metadata, ensure_ascii=False),
                    json.dumps(report, ensure_ascii=False),
                    tx_hash,
                    metadata_hash,
                    record_key,
                    block_number,
                    block_hash,
                    contract_address,
                    chain_id,
                    json.dumps(chain_transactions or [], ensure_ascii=False),
                    document_chunk_count,
                    metadata_chunk_count,
                    document_size,
                    metadata_size,
                    document_chunk_commitment,
                    metadata_chunk_commitment,
                ),
            )
            conn.commit()
        policy = self.get_latest(policy_id, policy_version)
        if policy is None:
            raise RuntimeError("Policy insert succeeded but lookup failed")
        return policy

    def list_policies(self, application_name: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if application_name:
            where = "where lower(policyName) like lower(?)"
            params.append(f"%{application_name}%")
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select * from policies
                {where}
                order by createdAt desc, id desc
                """,
                params,
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_manageable_policies(self, developer_name: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if developer_name:
            where = "where lower(developerName) = lower(?)"
            params.append(developer_name)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select p.*
                from policies p
                join (
                    select policyId, max(id) as latestId
                    from policies
                    {where}
                    group by policyId
                ) latest on latest.latestId = p.id
                order by p.createdAt desc, p.id desc
                """,
                params,
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_latest(self, policy_id: str, policy_version: str | None = None) -> dict[str, Any] | None:
        sql = "select * from policies where policyId = ?"
        params: list[Any] = [policy_id]
        if policy_version is not None:
            sql += " and policyVersion = ?"
            params.append(policy_version)
        sql += " order by createdAt desc, id desc limit 1"
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return self._row_to_dict(row) if row else None

    def get_by_hash(self, hash_code: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select * from policies
                where hashCode = ?
                order by createdAt desc, id desc
                limit 1
                """,
                (hash_code,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_latest_by_application_name(self, application_name: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select * from policies
                where lower(policyName) = lower(?)
                order by createdAt desc, id desc
                limit 1
                """,
                (application_name,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists policies (
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
                    chainTransactionsJson text not null default '[]',
                    documentChunkCount integer not null default 0,
                    metadataChunkCount integer not null default 0,
                    documentSize integer not null default 0,
                    metadataSize integer not null default 0,
                    documentChunkCommitment text not null default '',
                    metadataChunkCommitment text not null default '',
                    createdAt text not null default current_timestamp,
                    unique (policyId, policyVersion)
                )
                """
            )
            self._add_missing_columns(conn)
            conn.execute("create index if not exists idxPoliciesPolicyId on policies(policyId)")
            conn.execute("create index if not exists idxPoliciesPolicyName on policies(policyName)")
            conn.execute("create index if not exists idxPoliciesDeveloperName on policies(developerName)")
            conn.commit()

    def _add_missing_columns(self, conn: sqlite3.Connection) -> None:
        """Migrate databases created before chunked on-chain storage was added."""
        existing = {
            row["name"]
            for row in conn.execute("pragma table_info(policies)").fetchall()
        }
        columns = {
            "chainTransactionsJson": "text not null default '[]'",
            "documentChunkCount": "integer not null default 0",
            "metadataChunkCount": "integer not null default 0",
            "documentSize": "integer not null default 0",
            "metadataSize": "integer not null default 0",
            "documentChunkCommitment": "text not null default ''",
            "metadataChunkCommitment": "text not null default ''",
        }
        for name, declaration in columns.items():
            if name not in existing:
                conn.execute(f"alter table policies add column {name} {declaration}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadataJson"))
        item["report"] = json.loads(item.pop("reportJson"))
        item["chainTransactions"] = json.loads(item.pop("chainTransactionsJson", "[]"))
        return item
