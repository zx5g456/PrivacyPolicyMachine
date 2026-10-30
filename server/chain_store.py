"""Rebuildable policy views backed exclusively by the Base registry."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from requests.exceptions import HTTPError

from .blockchain import ChainRecord, TrustedPolicyRegistry
from .processor import generate_report


RATE_LIMIT_RETRIES = 4
RATE_LIMIT_INITIAL_DELAY_SECONDS = 1


class InvalidChainRecordError(RuntimeError):
    """A finalized record's stored content contradicts its on-chain claims."""


class ChainPolicyStore:
    """Index finalized events in memory; contract storage remains the source of truth."""

    def __init__(self, registry: TrustedPolicyRegistry):
        self.registry = registry
        self._lock = threading.RLock()
        self._next_block = registry.from_block
        self._policies: dict[str, dict[str, Any]] = {}
        self._records: dict[str, ChainRecord] = {}
        self._hashes: dict[str, str] = {}
        self._order: list[str] = []
        self._audit_issues: dict[str, dict[str, Any]] = {}
        self._checkpoint_hash: str | None = None

    def _sync(self) -> None:
        with self._lock:
            self.registry._require_connection()
            head = int(self.registry.web3.eth.block_number)
            if self._checkpoint_hash is not None:
                checkpoint_block = self._next_block - 1
                current_hash = (
                    "0x" + bytes(self.registry.web3.eth.get_block(checkpoint_block)["hash"]).hex()
                    if checkpoint_block <= head else None
                )
                if current_hash != self._checkpoint_hash:
                    self._next_block = self.registry.from_block
                    self._policies.clear()
                    self._records.clear()
                    self._hashes.clear()
                    self._order.clear()
                    self._audit_issues.clear()
                    self._checkpoint_hash = None
            while self._next_block <= head:
                last = min(self._next_block + 999, head)
                logs = self._registration_logs(self._next_block, last)
                for log in logs:
                    key = "0x" + bytes(log["args"]["recordKey"]).hex()
                    if key in self._policies or key in self._audit_issues:
                        continue
                    receipt = self.registry.web3.eth.get_transaction_receipt(
                        log["transactionHash"]
                    )
                    record = self.registry._record_from_event(log, receipt)
                    try:
                        self._insert(record)
                    except InvalidChainRecordError as exc:
                        self._remember_audit_issue(record, exc)
                self._next_block = last + 1
            if self._next_block > self.registry.from_block:
                self._checkpoint_hash = "0x" + bytes(
                    self.registry.web3.eth.get_block(self._next_block - 1)["hash"]
                ).hex()
            self._order.sort(
                key=lambda key: (
                    self._records[key].blockNumber,
                    self._records[key].transactionIndex,
                )
            )

    def _registration_logs(self, start: int, end: int) -> list[Any]:
        event = self.registry.contract.events.TrustedPolicyRecordRegistered()
        for retry in range(RATE_LIMIT_RETRIES + 1):
            try:
                return event.get_logs(from_block=start, to_block=end)
            except HTTPError as exc:
                response = exc.response
                if response is None or response.status_code != 429 or retry == RATE_LIMIT_RETRIES:
                    raise
                time.sleep(RATE_LIMIT_INITIAL_DELAY_SECONDS * (2 ** retry))
        raise AssertionError("Unreachable registration log retry state")

    def _insert(self, record: ChainRecord) -> dict[str, Any]:
        key = record.recordKey
        if key in self._policies:
            return self._policies[key]
        content = self.registry.read_on_chain_content(key)
        try:
            self.registry._require_content_matches_record(content, record.data)
        except RuntimeError as exc:
            raise InvalidChainRecordError(str(exc)) from exc
        try:
            metadata = json.loads(content.metadataJson.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidChainRecordError(f"Policy metadata is not valid UTF-8 JSON for {key}") from exc
        if not isinstance(metadata, dict):
            raise InvalidChainRecordError(f"Policy metadata is not an object for {key}")
        expected_fields = {
            "developer": record.data.publisherEntity,
            "publisherEntity": record.data.publisherEntity,
            "applicationName": record.data.serviceName,
            "serviceName": record.data.serviceName,
            "policyVersion": record.data.policyVersion,
            "effectiveDate": record.data.effectiveDate,
        }
        mismatches = [
            name for name, expected in expected_fields.items()
            if metadata.get(name) != expected
        ]
        if mismatches:
            raise InvalidChainRecordError(
                f"Policy metadata differs from the contract for {key}: "
                + ", ".join(mismatches)
            )
        policy_id = metadata.get("policyId")
        try:
            if not isinstance(policy_id, str):
                raise ValueError("policyId is not a string")
            uuid.UUID(policy_id)
        except ValueError as exc:
            raise InvalidChainRecordError(f"Policy metadata has an invalid policyId for {key}") from exc
        hash_code = hashlib.sha256(content.rawFile).hexdigest()
        metadata_document_hash = metadata.get("documentHash")
        if not isinstance(metadata_document_hash, str) or metadata_document_hash.lower().removeprefix("0x") != hash_code:
            raise InvalidChainRecordError(f"Policy metadata documentHash differs from stored content for {key}")
        for count_field in ("wordCount", "sectionCount"):
            count = metadata.get(count_field)
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise InvalidChainRecordError(f"Policy metadata has an invalid {count_field} for {key}")
        policy = {
            "id": key,
            "policyId": policy_id,
            "policyName": record.data.serviceName,
            "policyVersion": record.data.policyVersion,
            "developerName": record.data.publisherEntity,
            "registrant": record.data.registrant,
            "rawFile": content.rawFile.decode("utf-8", errors="replace"),
            "hashCode": hash_code,
            "metadata": metadata,
            "report": generate_report(metadata, hash_code),
            "txHash": record.txHash,
            "metadataHash": record.data.metadataHash.removeprefix("0x"),
            "recordKey": key,
            "blockNumber": record.blockNumber,
            "blockHash": record.blockHash,
            "contractAddress": record.contractAddress,
            "chainId": record.chainId,
            "documentChunkCount": record.data.documentChunkCount,
            "metadataChunkCount": record.data.metadataChunkCount,
            "documentSize": record.data.documentSize,
            "metadataSize": record.data.metadataSize,
            "documentChunkCommitment": record.data.documentChunkCommitment,
            "metadataChunkCommitment": record.data.metadataChunkCommitment,
            "createdAt": datetime.fromtimestamp(record.timestamp, timezone.utc).isoformat(),
        }
        self._policies[key] = policy
        self._records[key] = record
        self._hashes[hash_code] = key
        self._order.append(key)
        return policy

    def get_by_record_key(self, record_key: str) -> dict[str, Any]:
        self._sync()
        with self._lock:
            if record_key in self._policies:
                return self._policies[record_key]
            if record_key in self._audit_issues:
                raise InvalidChainRecordError(self._audit_issues[record_key]["reason"])
            record = self.registry.read_record_by_key(record_key)
            try:
                policy = self._insert(record)
            except InvalidChainRecordError as exc:
                self._remember_audit_issue(record, exc)
                raise
            self._order.sort(
                key=lambda key: (
                    self._records[key].blockNumber,
                    self._records[key].transactionIndex,
                )
            )
            return policy

    def list_policies(self, application_name: str | None = None) -> list[dict[str, Any]]:
        self._sync()
        with self._lock:
            policies = (self._policies[key] for key in reversed(self._order))
            if application_name:
                query = application_name.casefold()
                policies = (p for p in policies if query in p["policyName"].casefold())
            return list(policies)

    def list_chain_records(self) -> list[ChainRecord]:
        self._sync()
        with self._lock:
            return [self._records[key] for key in self._order]

    def list_audit_issues(self) -> list[dict[str, Any]]:
        self._sync()
        with self._lock:
            return list(self._audit_issues.values())

    def _remember_audit_issue(self, record: ChainRecord, exc: InvalidChainRecordError) -> None:
        self._audit_issues[record.recordKey] = {
            "recordKey": record.recordKey,
            "blockNumber": record.blockNumber,
            "txHash": record.txHash,
            "reason": str(exc),
        }

    def list_manageable_policies(self, developer_name: str | None = None) -> list[dict[str, Any]]:
        policies = self.list_policies()
        seen: set[str] = set()
        result = []
        for policy in policies:
            if developer_name and policy["developerName"].casefold() != developer_name.casefold():
                continue
            if policy["policyId"] in seen:
                continue
            seen.add(policy["policyId"])
            result.append(policy)
        return result

    def get_latest(self, policy_id: str, policy_version: str | None = None) -> dict[str, Any] | None:
        for policy in self.list_policies():
            if policy["policyId"] == policy_id and (
                policy_version is None or policy["policyVersion"] == policy_version
            ):
                return policy
        return None

    def get_by_hash(self, hash_code: str) -> dict[str, Any] | None:
        self._sync()
        with self._lock:
            key = self._hashes.get(hash_code)
            return self._policies[key] if key else None

    def get_latest_by_application_name(self, application_name: str) -> dict[str, Any] | None:
        for policy in self.list_policies():
            if policy["policyName"].casefold() == application_name.casefold():
                return policy
        return None
