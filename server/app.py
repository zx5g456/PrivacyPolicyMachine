from __future__ import annotations

import json
import mimetypes
import os
import socket
import sys
import traceback
import uuid
from dataclasses import asdict
from datetime import datetime
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .blockchain import OnChainData, TrustedPolicyRegistry
from .llm_client import DEFAULT_MODEL
from .llm_models import (
    LLMConnectionError,
    LLMProcessorError,
    LLMTimeoutError,
)
from .llm_processor import PolicyLLMProcessor
from .processor import (
    LIST_METADATA_FIELDS,
    RISK_FLAG_DETAILS,
    STATUS_METADATA_FIELDS,
    canonical_metadata_bytes,
    generate_report,
    hash_policy,
    hash_policy_bytes,
    normalize_policy_text,
    require_canonical_metadata_keys,
)
from .storage import PolicyStore


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
STATIC_DIR = ROOT / "web" / "static"
store = PolicyStore(DATA_DIR / "policies.db")
registry = TrustedPolicyRegistry(
    ROOT / "artifacts" / "contracts" / "TrustedPolicyRegistry.sol" / "TrustedPolicyRegistry.json"
)


class AppHandler(BaseHTTPRequestHandler):
    server_version = "PrivacyPolicyMachine/1.0"

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/policies":
                query = parse_qs(parsed.query)
                application_name = self._optional_query(query, "applicationName")
                self._json({"policies": store.list_policies(application_name)})
            elif parsed.path == "/api/policies/manageable":
                query = parse_qs(parsed.query)
                developer_name = self._optional_query(query, "developer")
                self._json({"policies": store.list_manageable_policies(developer_name)})
            elif parsed.path.startswith("/api/policies/"):
                policy_id = unquote(parsed.path.removeprefix("/api/policies/"))
                policy = store.get_latest(policy_id)
                if not policy:
                    self._json({"error": "Policy not found"}, HTTPStatus.NOT_FOUND)
                    return
                chain_record = registry.read_on_chain_record(
                    policy["developerName"],
                    policy["policyName"],
                    policy["policyVersion"],
                )
                self._json({"policy": policy, "onChain": self._chain_to_dict(chain_record)})
            elif parsed.path == "/api/chain":
                self._json({"records": [self._chain_to_dict(item) for item in registry.list_records()]})
            elif parsed.path.startswith("/api/audit/"):
                tx_hash = unquote(parsed.path.removeprefix("/api/audit/"))
                self._json(registry.audit_registration(tx_hash))
            else:
                self._static(parsed.path)
        except Exception as exc:
            self._handle_error(exc)

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            payload = self._read_payload()
            if parsed.path == "/api/policies/reviewed":
                self._register_reviewed_policy(payload)
            elif parsed.path == "/api/policies/update":
                self._update_policy(payload)
            elif parsed.path == "/api/verify":
                self._verify_policy(payload)
            elif parsed.path == "/api/analyze":
                self._analyze_policy_with_llm(payload)
            else:
                self._json({"error": "Route not found"}, HTTPStatus.NOT_FOUND)
        except LLMTimeoutError as exc:
            self._json({"error": str(exc)}, HTTPStatus.GATEWAY_TIMEOUT)
        except (LLMConnectionError, LLMProcessorError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
        except ValueError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._handle_error(exc)

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _update_policy(self, payload: dict[str, Any]) -> None:
        policy_id = self._required(payload, "policyId")
        developer_name = self._developer_name(payload)
        policy_version = self._upload_time()
        raw_file = self._raw_file(payload, required=True)
        raw_bytes = self._raw_file_bytes(payload, raw_file)
        existing = store.get_latest(policy_id)
        if not existing:
            self._json({"error": "Policy ID not found. Create the policy first."}, HTTPStatus.NOT_FOUND)
            return
        if existing.get("developerName", "").lower() != developer_name.lower():
            self._json({"error": "Only the developer who uploaded this application policy can update it."}, HTTPStatus.FORBIDDEN)
            return
        metadata = self._reviewed_metadata(payload)
        hash_code = hash_policy_bytes(raw_bytes)
        duplicate = store.get_by_hash(hash_code)
        if duplicate:
            self._duplicate_hash_response(duplicate, hash_code)
            return
        existing_metadata = existing.get("metadata", {})
        policy, metadata, report, chain_record = self._register_policy_version(
            policy_id=policy_id,
            policy_name=existing["policyName"],
            policy_version=policy_version,
            developer_name=developer_name,
            raw_file=raw_file,
            raw_bytes=raw_bytes,
            hash_code=hash_code,
            policy_url=self._optional_payload(payload, "policyUrl") or existing_metadata.get("policyUrl", ""),
            effective_date=self._optional_payload(payload, "effectiveDate") or existing_metadata.get("effectiveDate", ""),
            change_summary=self._optional_payload(payload, "changeSummary"),
            reviewed_metadata=metadata,
        )
        self._json(
            {
                "policy": policy,
                "metadata": metadata,
                "report": report,
                "onChain": self._chain_to_dict(chain_record),
                "message": "Policy updated, stored, and registered.",
            },
            HTTPStatus.CREATED,
        )

    def _register_policy_version(
        self,
        policy_id: str,
        policy_name: str,
        policy_version: str,
        developer_name: str,
        raw_file: str,
        raw_bytes: bytes,
        hash_code: str,
        policy_url: str,
        effective_date: str,
        change_summary: str,
        reviewed_metadata: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Any]:
        if reviewed_metadata is None:
            raise ValueError("AI-reviewed metadata is required for registration")
        metadata = reviewed_metadata
        require_canonical_metadata_keys(metadata)
        metadata["policyId"] = policy_id
        metadata["policyVersion"] = policy_version
        metadata["applicationName"] = policy_name
        metadata["developer"] = developer_name
        metadata["publisherEntity"] = developer_name
        metadata["policyUrl"] = policy_url
        metadata["serviceName"] = policy_name
        metadata["effectiveDate"] = effective_date
        metadata["documentHash"] = hash_code
        metadata["changeSummary"] = change_summary
        metadata["uploadMethod"] = "ai"
        metadata.setdefault("permittedUsage", [])
        metadata.setdefault("metadataDetails", {})
        metadata_bytes = canonical_metadata_bytes(metadata)
        metadata_hash = hash_policy_bytes(metadata_bytes)
        report = generate_report(metadata, hash_code)
        chain_record = registry.register_trusted_policy_record(
            self._on_chain_data(raw_bytes, metadata_bytes, metadata)
        )
        if chain_record.data.documentHash != "0x" + hash_code:
            raise RuntimeError("Contract document hash does not match the uploaded file")
        if chain_record.data.metadataHash != "0x" + metadata_hash:
            raise RuntimeError("Contract metadata hash does not match the canonical metadata")
        policy = store.create_policy(
            policy_id=policy_id,
            policy_name=policy_name,
            policy_version=policy_version,
            developer_name=developer_name,
            raw_file=raw_file,
            hash_code=hash_code,
            metadata_hash=metadata_hash,
            metadata=metadata,
            report=report,
            tx_hash=chain_record.txHash,
            record_key=chain_record.recordKey,
            block_number=chain_record.blockNumber,
            block_hash=chain_record.blockHash,
            contract_address=chain_record.contractAddress,
            chain_id=chain_record.chainId,
        )
        return policy, metadata, report, chain_record

    def _register_reviewed_policy(self, payload: dict[str, Any]) -> None:
        """Persist AI metadata approved or edited on the review page."""
        raw_file = self._raw_file(payload, required=True)
        raw_bytes = self._raw_file_bytes(payload, raw_file)
        metadata = self._reviewed_metadata(payload)
        policy_id = str(uuid.uuid4())
        policy_version = self._upload_time()
        application_name = self._application_name(payload)
        developer_name = self._developer_name(payload)
        hash_code = hash_policy_bytes(raw_bytes)
        duplicate = store.get_by_hash(hash_code)
        if duplicate:
            self._duplicate_hash_response(duplicate, hash_code)
            return
        policy, metadata, report, chain_record = self._register_policy_version(
            policy_id=policy_id,
            policy_name=application_name,
            policy_version=policy_version,
            developer_name=developer_name,
            raw_file=raw_file,
            raw_bytes=raw_bytes,
            hash_code=hash_code,
            policy_url=self._optional_payload(payload, "policyUrl"),
            effective_date=self._optional_payload(payload, "effectiveDate"),
            change_summary="",
            reviewed_metadata=metadata,
        )
        self._json(
            {
                "policy": policy,
                "metadata": metadata,
                "report": report,
                "onChain": self._chain_to_dict(chain_record),
                "message": "AI-reviewed policy stored and registered.",
            },
            HTTPStatus.CREATED,
        )

    def _reviewed_metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            metadata = json.loads(self._required(payload, "metadataJson"))
        except json.JSONDecodeError as exc:
            raise ValueError("metadataJson must contain valid JSON") from exc
        if not isinstance(metadata, dict) or not isinstance(metadata.get("metadataEvidence"), dict):
            raise ValueError("metadataJson must contain the reviewed policy metadata")
        self._normalize_reviewed_metadata(metadata)
        return metadata

    def _normalize_reviewed_metadata(self, metadata: dict[str, Any]) -> None:
        """Prevent unsupported yes/no findings from being registered."""
        require_canonical_metadata_keys(metadata)
        evidence_by_field = metadata.setdefault("metadataEvidence", {})
        if not isinstance(evidence_by_field, dict):
            evidence_by_field = {}
            metadata["metadataEvidence"] = evidence_by_field
        details_by_field = metadata.setdefault("metadataDetails", {})
        if not isinstance(details_by_field, dict):
            details_by_field = {}
            metadata["metadataDetails"] = details_by_field
        for field_name in (*LIST_METADATA_FIELDS, *STATUS_METADATA_FIELDS, "riskFlags"):
            detail = details_by_field.get(field_name)
            details_by_field[field_name] = detail.strip() if isinstance(detail, str) else ""
        for field_name in STATUS_METADATA_FIELDS:
            evidence = self._evidence_lines(evidence_by_field.get(field_name))
            value = metadata.get(field_name)
            if value in {"yes", "no"} and not evidence:
                metadata[field_name] = "unclear"
            elif value == "mentioned":
                metadata[field_name] = "yes" if evidence else "unclear"
            elif value not in {"yes", "no", "unclear"}:
                metadata[field_name] = "unclear"
            evidence_by_field[field_name] = evidence

    def _evidence_lines(self, evidence: Any) -> list[str]:
        if isinstance(evidence, str):
            return [evidence] if evidence.strip() else []
        if isinstance(evidence, list):
            return [str(item) for item in evidence if str(item).strip()]
        if isinstance(evidence, dict):
            return [
                line
                for value in evidence.values()
                for line in self._evidence_lines(value)
            ]
        return []

    def _preview_policy(self, payload: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
        raw_file = self._raw_file(payload, required=True)
        application_name = self._application_name(payload)
        developer_name = self._developer_name(payload)
        hash_code = hash_policy(raw_file)
        duplicate = store.get_by_hash(hash_code)
        if duplicate:
            self._duplicate_hash_response(duplicate, hash_code)
            return raw_file, {}, hash_code
        metadata = self._empty_ai_metadata(raw_file)
        metadata.update(
            {
                "applicationName": application_name,
                "developer": developer_name,
                "publisherEntity": developer_name,
                "policyUrl": self._optional_payload(payload, "policyUrl"),
                "serviceName": application_name,
                "effectiveDate": self._optional_payload(payload, "effectiveDate"),
                "documentHash": hash_code,
                "changeSummary": "",
                "uploadMethod": "ai",
            }
        )
        return raw_file, metadata, hash_code

    def _empty_ai_metadata(self, raw_file: str) -> dict[str, Any]:
        """Create an unclassified draft for the AI model to populate."""
        metadata: dict[str, Any] = {
            "policyId": "pending-review",
            "policyVersion": None,
            "characterCount": len(raw_file),
            "wordCount": len(raw_file.split()),
            "sectionCount": 0,
            "sections": [],
            "metadataEvidence": {},
            "metadataDetails": {},
            "metadataAssessment": {},
        }
        for field_name in (*LIST_METADATA_FIELDS, "riskFlags"):
            metadata[field_name] = []
            metadata["metadataEvidence"][field_name] = {}
            metadata["metadataDetails"][field_name] = ""
            metadata["metadataAssessment"][field_name] = {}
        for field_name in STATUS_METADATA_FIELDS:
            metadata[field_name] = "unclear"
            metadata["metadataEvidence"][field_name] = []
            metadata["metadataDetails"][field_name] = ""
            metadata["metadataAssessment"][field_name] = {
                "confidence": 0.0,
                "reviewStatus": "needs_review",
            }
        return metadata

    def _verify_policy(self, payload: dict[str, Any]) -> None:
        application_name = self._application_name(payload)
        submitted_bytes, submitted_raw = self._submitted_policy_data(payload)
        submitted_hash = hash_policy_bytes(submitted_bytes)
        stored = store.get_latest_by_application_name(application_name)
        if not stored:
            self._json(
                {
                    "verified": False,
                    "reason": "No trusted policy was found for that application name.",
                    "submittedHash": submitted_hash,
                },
                HTTPStatus.NOT_FOUND,
            )
            return
        policy_version = stored["policyVersion"]
        chain_record = registry.read_on_chain_record(
            stored["developerName"],
            stored["policyName"],
            policy_version,
        )
        if not chain_record:
            self._json(
                {
                    "verified": False,
                    "reason": "A SQL record was found, but no matching on-chain record was found.",
                    "stored": stored,
                    "onChain": self._chain_to_dict(chain_record),
                },
                HTTPStatus.NOT_FOUND,
            )
            return

        expected_hash = stored["hashCode"]
        normalized_submitted = normalize_policy_text(submitted_raw)
        normalized_stored = normalize_policy_text(stored["rawFile"])
        stored_metadata_hash = hash_policy_bytes(canonical_metadata_bytes(stored["metadata"]))
        audit = registry.audit_registration(stored["txHash"])
        comparisons = {
            "submittedTextMatchesSql": normalized_submitted == normalized_stored,
            "submittedHashMatchesSql": submitted_hash == expected_hash,
            "sqlDocumentHashMatchesChain": "0x" + expected_hash == chain_record.data.documentHash,
            "sqlMetadataHashMatchesChain": "0x" + stored_metadata_hash == chain_record.data.metadataHash,
            "storedMetadataHashMatchesSql": stored.get("metadataHash", "") == stored_metadata_hash,
            "calldataDocumentHashMatchesChain": audit["checks"]["documentHashMatchesStorage"],
            "calldataMetadataHashMatchesChain": audit["checks"]["metadataHashMatchesStorage"],
            "transactionSucceeded": audit["checks"]["transactionSucceeded"],
            "transactionTargetsContract": audit["checks"]["transactionTargetsContract"],
            "publisherMatches": stored["developerName"] == chain_record.data.publisherEntity,
            "serviceNameMatches": stored["policyName"] == chain_record.data.serviceName,
            "versionMatches": stored["policyVersion"] == chain_record.data.policyVersion,
            "txHashMatches": stored["txHash"] == chain_record.txHash,
            "recordKeyMatches": stored.get("recordKey", "") == chain_record.recordKey,
            "contractAddressMatches": stored.get("contractAddress", "").lower() == chain_record.contractAddress.lower(),
            "chainIdMatches": stored.get("chainId") == chain_record.chainId,
        }
        verified = all(comparisons.values())
        self._json(
            {
                "verified": verified,
                "comparisons": comparisons,
                "submittedHash": submitted_hash,
                "sqlHash": expected_hash,
                "exactHashesMatch": submitted_hash == expected_hash,
                "audit": audit,
                "normalization": "case, whitespace, and punctuation ignored",
                "stored": stored,
                "onChain": self._chain_to_dict(chain_record),
                "reason": "Policy text matches after normalization." if verified else "At least one normalized text or record identity comparison failed.",
            }
        )

    def _analyze_policy_with_llm(self, payload: dict[str, Any]) -> None:
        """Analyze a policy without writing to SQLite or the blockchain.

        This preview endpoint intentionally stays separate from registration.
        The returned evidence and review flags can be inspected before a later
        workflow decides whether any result is trustworthy enough to persist.
        """
        raw_policy, metadata, hash_code = self._preview_policy(payload)
        if not metadata:
            return
        processor = PolicyLLMProcessor(
            model=os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL),
            timeout_seconds=float(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "90")),
            retries=int(os.environ.get("OLLAMA_RETRIES", "2")),
        )
        analysis = processor.analyze(raw_policy)
        for field_name in (*LIST_METADATA_FIELDS, *STATUS_METADATA_FIELDS):
            field = getattr(analysis.fields, field_name)
            metadata[field_name] = field.value
            metadata["metadataEvidence"][field_name] = field.evidence
            metadata["metadataDetails"][field_name] = field.details
            if field_name in LIST_METADATA_FIELDS:
                metadata["metadataAssessment"][field_name] = {
                    value: {
                        "confidence": 0.5 if field.needs_review else 0.8,
                        "reviewStatus": "needs_review" if field.needs_review else "auto_extracted",
                    }
                    for value in field.value
                }
            else:
                metadata["metadataAssessment"][field_name] = {
                    "value": field.value,
                    "reviewStatus": "needs_review" if field.needs_review else "auto_extracted",
                    "confidence": 0.5 if field.needs_review else 0.8,
                }
        risk_flags = []
        if metadata["retentionPolicy"] == "unclear":
            risk_flags.append("unclear_retention")
        if metadata["downstreamStakeholders"] and metadata["sharingCondition"] == "unclear":
            risk_flags.append("vague_third_party_sharing")
        if metadata["deletionAvailable"] != "yes":
            risk_flags.append("no_deletion_method")
        if any(tag in metadata["dataTypeTags"] for tag in ("location", "voice_recording", "eye_tracking", "payment_info")):
            risk_flags.append("sensitive_data_involved")
        if risk_flags:
            risk_flags.append("review_recommended")
        metadata["riskFlags"] = risk_flags
        metadata["metadataDetails"]["riskFlags"] = " ".join(
            RISK_FLAG_DETAILS[flag] for flag in risk_flags
        )
        metadata["metadataAssessment"]["riskFlags"] = {
            flag: {"confidence": 0.8, "reviewStatus": "needs_review"}
            for flag in risk_flags
        }
        self._json(
            {
                "analysis": analysis.model_dump(),
                "metadata": metadata,
                "report": generate_report(metadata, hash_code),
                "uploadMethod": "ai",
                "requiresReview": True,
                "persisted": False,
                "onChain": False,
                "message": "Policy analyzed locally. No database or blockchain write was performed.",
            }
        )

    def _read_payload(self) -> dict[str, Any]:
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("multipart/form-data"):
            return self._read_multipart(content_type)
        return self._read_json()

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        body = self.rfile.read(length).decode("utf-8")
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _on_chain_data(
        self,
        raw_file: bytes,
        metadata_json: bytes,
        metadata: dict[str, Any],
    ) -> OnChainData:
        return OnChainData(
            rawFile=raw_file,
            metadataJson=metadata_json,
            policyVersion=self._metadata_text(metadata, "policyVersion"),
            publisherEntity=self._metadata_text(metadata, "publisherEntity"),
            serviceName=self._metadata_text(metadata, "serviceName"),
            effectiveDate=self._metadata_text(metadata, "effectiveDate"),
        )

    def _metadata_text(self, metadata: dict[str, Any], key: str) -> str:
        value = metadata.get(key)
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        if value is None:
            return ""
        return str(value)

    def _read_multipart(self, content_type: str) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        message = BytesParser(policy=policy.default).parsebytes(
            b"Content-Type: " + content_type.encode("utf-8") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
        )
        payload: dict[str, Any] = {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            filename = part.get_filename()
            content = part.get_payload(decode=True) or b""
            if filename and content:
                payload[name] = content.decode("utf-8", errors="replace")
                payload[f"{name}Bytes"] = content
                payload[f"{name}Name"] = filename
            elif not filename:
                payload[name] = content.decode(part.get_content_charset() or "utf-8", errors="replace")
        return payload

    def _required(self, payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} is required")
        return value.strip()

    def _optional_payload(self, payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        return value.strip() if isinstance(value, str) else ""

    def _optional_query(self, query: dict[str, list[str]], key: str) -> str | None:
        values = query.get(key) or []
        value = values[0].strip() if values else ""
        return value or None

    def _raw_file(self, payload: dict[str, Any], required: bool) -> str | None:
        value = payload.get("rawFile")
        if isinstance(value, str) and value.strip():
            if not payload.get("rawFileName"):
                raise ValueError("rawFile must be uploaded as a file")
            return value
        if required:
            raise ValueError("rawFile file upload is required")
        return None

    def _raw_file_bytes(self, payload: dict[str, Any], raw_file: str) -> bytes:
        value = payload.get("rawFileBytes")
        return bytes(value) if isinstance(value, bytes) else raw_file.encode("utf-8")

    def _submitted_policy_data(self, payload: dict[str, Any]) -> tuple[bytes, str]:
        raw_file = self._raw_file(payload, required=False)
        if raw_file:
            return self._raw_file_bytes(payload, raw_file), raw_file
        raw_text = payload.get("rawText")
        if isinstance(raw_text, str) and raw_text.strip():
            text = raw_text.strip()
            return text.encode("utf-8"), text
        raise ValueError("Upload a policy file or enter policy text to verify")

    def _submitted_policy(self, payload: dict[str, Any]) -> str:
        return self._submitted_policy_data(payload)[1]

    def _application_name(self, payload: dict[str, Any]) -> str:
        application_name = payload.get("applicationName") or payload.get("policyName")
        if isinstance(application_name, str) and application_name.strip():
            return application_name.strip()
        raise ValueError("applicationName is required")

    def _developer_name(self, payload: dict[str, Any]) -> str:
        developer_name = payload.get("developer") or payload.get("developerName")
        if isinstance(developer_name, str) and developer_name.strip():
            return developer_name.strip()
        raise ValueError("developer is required")

    def _upload_time(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _duplicate_hash_response(self, duplicate: dict[str, Any], hash_code: str) -> None:
        self._json(
            {
                "error": "This file content is already registered. No SQL or on-chain update was performed.",
                "duplicate": {
                    "policyId": duplicate["policyId"],
                    "applicationName": duplicate["policyName"],
                    "uploadTime": duplicate["policyVersion"],
                    "developer": duplicate.get("developerName", ""),
                    "hashCode": hash_code,
                    "createdAt": duplicate["createdAt"],
                },
            },
            HTTPStatus.CONFLICT,
        )

    def _static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        file_path = (STATIC_DIR / path.lstrip("/")).resolve()
        if not str(file_path).startswith(str(STATIC_DIR.resolve())) or not file_path.exists():
            self._json({"error": "Route not found"}, HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        content = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _chain_to_dict(self, record: Any) -> dict[str, Any] | None:
        if record is None:
            return None
        return asdict(record)

    def _handle_error(self, exc: Exception) -> None:
        traceback.print_exc()
        self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)


def main() -> None:
    host = "127.0.0.1"
    port = int(os.environ.get("PORT", "8000"))
    if "PORT" not in os.environ:
        port = _available_port(host, port)
    httpd = ThreadingHTTPServer((host, port), AppHandler)
    print(f"Privacy Policy Machine running at http://{host}:{port}")
    httpd.serve_forever()


def _available_port(host: str, start_port: int) -> int:
    port = start_port
    while port < start_port + 100:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
                return port
            except OSError:
                port += 1
    raise OSError(f"No available port found from {start_port} to {start_port + 99}")


if __name__ == "__main__":
    main()
