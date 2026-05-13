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
        policy_version: str | None,
        developer_name: str,
        raw_file: str,
        hash_code: str,
        metadata: dict[str, Any],
        report: dict[str, Any],
        tx_hash: str,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                """
                insert into policies (
                    policy_id, policy_name, policy_version, developer_name, raw_file, hash_code, metadata_json,
                    report_json, tx_hash
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    policy_id,
                    policy_name,
                    policy_version,
                    developer_name,
                    raw_file,
                    hash_code,
                    json.dumps(metadata, ensure_ascii=False),
                    json.dumps(report, ensure_ascii=False),
                    tx_hash,
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
            where = "where lower(policy_name) like lower(?)"
            params.append(f"%{application_name}%")
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select * from policies
                {where}
                order by created_at desc, id desc
                """,
                params,
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_manageable_policies(self, developer_name: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if developer_name:
            where = "where lower(developer_name) = lower(?)"
            params.append(developer_name)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select p.*
                from policies p
                join (
                    select policy_id, max(id) as latest_id
                    from policies
                    {where}
                    group by policy_id
                ) latest on latest.latest_id = p.id
                order by p.created_at desc, p.id desc
                """,
                params,
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_latest(self, policy_id: str, policy_version: str | None = None) -> dict[str, Any] | None:
        sql = "select * from policies where policy_id = ?"
        params: list[Any] = [policy_id]
        if policy_version is not None:
            sql += " and policy_version = ?"
            params.append(policy_version)
        sql += " order by created_at desc, id desc limit 1"
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return self._row_to_dict(row) if row else None

    def get_by_hash(self, hash_code: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select * from policies
                where hash_code = ?
                order by created_at desc, id desc
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
                where lower(policy_name) = lower(?)
                order by created_at desc, id desc
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
                )
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("pragma table_info(policies)").fetchall()
            }
            if "policy_name" not in columns:
                conn.execute("alter table policies add column policy_name text not null default ''")
            if "developer_name" not in columns:
                conn.execute("alter table policies add column developer_name text not null default ''")
            conn.execute("create index if not exists idx_policies_policy_id on policies(policy_id)")
            conn.execute("create index if not exists idx_policies_hash_code on policies(hash_code)")
            conn.execute("create index if not exists idx_policies_policy_name on policies(policy_name)")
            conn.execute("create index if not exists idx_policies_developer_name on policies(developer_name)")
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json"))
        item["report"] = json.loads(item.pop("report_json"))
        return item
