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
from .chain_store import ChainPolicyStore
from .compliance_bundle import read_compliance_bundle
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
    hash_policy_bytes,
    normalize_policy_text,
    require_canonical_metadata_keys,
)


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "web" / "static"
MAX_HTTP_BODY_BYTES = 2 * 1024 * 1024
registry = TrustedPolicyRegistry(
    ROOT / "artifacts" / "contracts" / "TrustedPolicyRegistry.sol" / "TrustedPolicyRegistry.json"
)
store = ChainPolicyStore(registry)


class AppHandler(BaseHTTPRequestHandler):
    server_version = "PrivacyPolicyMachine/1.0"

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/config":
                publishers = json.loads(os.environ.get("PUBLISHER_WALLETS_JSON", "{}"))
                if not isinstance(publishers, dict):
                    raise RuntimeError("PUBLISHER_WALLETS_JSON must be a JSON object")
                self._json({
                    "chainId": 8453,
                    "contractAddress": registry.contract.address,
                    "rpcUrl": "https://mainnet.base.org",
                    "publisherWallets": publishers,
                })
            elif parsed.path == "/api/policies":
                query = parse_qs(parsed.query)
                application_name = self._optional_query(query, "applicationName")
                self._json({"policies": store.list_policies(application_name)})
            elif parsed.path == "/api/policies/manageable":
                query = parse_qs(parsed.query)
                developer_name = self._optional_query(query, "developer")
                self._json({"policies": store.list_manageable_policies(developer_name)})
            elif parsed.path.startswith("/api/records/") and parsed.path.endswith("/raw"):
                record_key = unquote(parsed.path[len("/api/records/"):-len("/raw")])
                content = registry.read_on_chain_content(record_key)
                record = registry.read_record_by_key(record_key)
                registry._require_content_matches_record(content, record.data)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="policy-{record.recordKey[2:]}.bin"',
                )
                self.send_header("Content-Length", str(len(content.rawFile)))
                self.end_headers()
                self.wfile.write(content.rawFile)
            elif parsed.path.startswith("/api/policies/"):
                policy_id = unquote(parsed.path.removeprefix("/api/policies/"))
                policy = store.get_latest(policy_id)
                if not policy:
                    self._json({"error": "Policy not found"}, HTTPStatus.NOT_FOUND)
                    return
                chain_record = registry.read_record_by_key(policy["recordKey"])
                self._json({"policy": policy, "onChain": self._chain_to_dict(chain_record)})
            elif parsed.path == "/api/chain":
                self._json({
                    "records": [self._chain_to_dict(item) for item in store.list_chain_records()],
                    "auditIssues": store.list_audit_issues(),
                })
            elif parsed.path.startswith("/api/audit/"):
                tx_hash = unquote(parsed.path.removeprefix("/api/audit/"))
                self._json(registry.audit_registration(tx_hash))
            elif parsed.path.startswith("/api/compliance/"):
                resource = unquote(parsed.path.removeprefix("/api/compliance/"))
                if resource.endswith("/download"):
                    record_key = resource.removesuffix("/download")
                    self._download_compliance_bundle(record_key)
                else:
                    self._compliance_detail(resource)
            else:
                self._static(parsed.path)
        except Exception as exc:
            self._handle_error(exc)

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            payload = self._read_payload()
            if parsed.path == "/api/policies/prepare":
                self._prepare_policy(payload)
            elif parsed.path == "/api/policies/complete":
                self._complete_policy(payload)
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

    def _prepare_policy(self, payload: dict[str, Any]) -> None:
        """Prepare contract calls for the connected developer wallet to pay and sign."""
        workflow = self._required(payload, "workflow")
        if workflow not in {"create", "update"}:
            raise ValueError("workflow must be create or update")
        raw_file = self._raw_file(payload, required=True)
        raw_bytes = self._raw_file_bytes(payload, raw_file)
        metadata = self._reviewed_metadata(payload)
        policy_id, policy_version = self._review_registration_identity(metadata)
        developer_name = self._developer_name(payload)
        wallet_address = self._required(payload, "walletAddress")
        hash_code = hash_policy_bytes(raw_bytes)
        existing = store.get_latest(policy_id)
        if workflow == "update":
            if not existing:
                raise ValueError("Policy ID not found on Base Mainnet")
            if self._required(payload, "policyId") != policy_id:
                raise ValueError("Reviewed metadata does not belong to the selected policy")
            if existing["developerName"].casefold() != developer_name.casefold():
                raise ValueError("Only the original developer may update this policy")
            policy_name = existing["policyName"]
            existing_metadata = existing["metadata"]
            policy_url = self._optional_payload(payload, "policyUrl") or existing_metadata.get("policyUrl", "")
            effective_date = self._optional_payload(payload, "effectiveDate") or existing_metadata.get("effectiveDate", "")
            change_summary = self._optional_payload(payload, "changeSummary")
        else:
            requested_name = self._application_name(payload)
            if existing and (
                existing["policyVersion"] != policy_version
                or existing["developerName"].casefold() != developer_name.casefold()
                or existing["policyName"] != requested_name
            ):
                raise ValueError("Reviewed policy ID belongs to another registration")
            for policy in store.list_policies(requested_name):
                if (
                    policy["developerName"].casefold() == developer_name.casefold()
                    and policy["policyName"].casefold() == requested_name.casefold()
                    and policy["policyId"] != policy_id
                ):
                    raise ValueError("This developer already has a policy for the application; use Update Policy")
            policy_name = requested_name
            policy_url = self._optional_payload(payload, "policyUrl")
            effective_date = self._optional_payload(payload, "effectiveDate")
            change_summary = ""

        duplicate = store.get_by_hash(hash_code)
        if duplicate and not (
            duplicate["policyId"] == policy_id
            and duplicate["policyVersion"] == policy_version
        ):
            self._duplicate_hash_response(duplicate, hash_code)
            return
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
        plan = registry.prepare_policy_transactions(
            self._on_chain_data(raw_bytes, metadata_bytes, metadata), wallet_address
        )
        self._json({
            **plan,
            "report": generate_report(metadata, hash_code),
            "policyPreview": {
                "policyId": policy_id,
                "policyName": policy_name,
                "policyVersion": policy_version,
                "developerName": developer_name,
                "hashCode": hash_code,
            },
        })

    def _complete_policy(self, payload: dict[str, Any]) -> None:
        record_key = self._required(payload, "recordKey")
        if len(record_key) != 66 or not record_key.startswith("0x"):
            raise ValueError("recordKey must be a 32-byte hex value")
        try:
            key_bytes = bytes.fromhex(record_key[2:])
        except ValueError as exc:
            raise ValueError("recordKey must be a 32-byte hex value") from exc
        registry._require_connection()
        if not registry.contract.functions.hasRecord(key_bytes).call():
            self._json({"error": "Registration is not finalized on Base Mainnet"}, HTTPStatus.CONFLICT)
            return
        policy = store.get_by_record_key(record_key)
        chain_record = registry.read_record_by_key(record_key)
        self._json({
            "policy": policy,
            "metadata": policy["metadata"],
            "report": policy["report"],
            "onChain": self._chain_to_dict(chain_record),
            "message": "Policy finalized on Base Mainnet.",
        })

    def _reviewed_metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            metadata = json.loads(self._required(payload, "metadataJson"))
        except json.JSONDecodeError as exc:
            raise ValueError("metadataJson must contain valid JSON") from exc
        if not isinstance(metadata, dict) or not isinstance(metadata.get("metadataEvidence"), dict):
            raise ValueError("metadataJson must contain the reviewed policy metadata")
        self._normalize_reviewed_metadata(metadata)
        return metadata

    def _review_registration_identity(self, metadata: dict[str, Any]) -> tuple[str, str]:
        policy_id = metadata.get("policyId")
        policy_version = metadata.get("policyVersion")
        if not isinstance(policy_id, str):
            raise ValueError("Reviewed metadata is missing its policyId")
        try:
            uuid.UUID(policy_id)
        except ValueError as exc:
            raise ValueError("Reviewed metadata contains an invalid policyId") from exc
        if not isinstance(policy_version, str):
            raise ValueError("Reviewed metadata is missing its policyVersion")
        try:
            datetime.fromisoformat(policy_version)
        except ValueError as exc:
            raise ValueError("Reviewed metadata contains an invalid policyVersion") from exc
        return policy_id, policy_version

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
        raw_bytes = self._raw_file_bytes(payload, raw_file)
        document_limit = int(registry.contract.functions.MAX_DOCUMENT_BYTES().call())
        if len(raw_bytes) > document_limit:
            raise ValueError(f"Policy file exceeds the {document_limit}-byte Base contract limit")
        application_name = self._application_name(payload)
        developer_name = self._developer_name(payload)
        hash_code = hash_policy_bytes(raw_bytes)
        duplicate = store.get_by_hash(hash_code)
        if duplicate:
            self._duplicate_hash_response(duplicate, hash_code)
            return raw_file, {}, hash_code
        metadata = self._empty_ai_metadata(raw_file)
        requested_policy_id = self._optional_payload(payload, "policyId")
        if requested_policy_id:
            try:
                uuid.UUID(requested_policy_id)
            except ValueError as exc:
                raise ValueError("policyId must be a UUID") from exc
        else:
            for policy in store.list_policies(application_name):
                if (
                    policy["developerName"].casefold() == developer_name.casefold()
                    and policy["policyName"].casefold() == application_name.casefold()
                ):
                    raise ValueError("This developer already has a policy for the application; use Update Policy")
            requested_policy_id = str(uuid.uuid4())
        metadata.update(
            {
                "policyId": requested_policy_id,
                "policyVersion": self._upload_time(),
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
            self._json({
                "verified": False,
                "reason": "No Base Mainnet policy was found for that application name.",
                "submittedHash": submitted_hash,
            }, HTTPStatus.NOT_FOUND)
            return
        chain_record = registry.read_record_by_key(stored["recordKey"])
        content = registry.read_on_chain_content(stored["recordKey"])
        audit = registry.audit_registration(stored["recordKey"])
        comparisons = {
            "submittedHashMatchesOnChain": "0x" + submitted_hash == chain_record.data.documentHash,
            "onChainDocumentHashValid": content.document_hash == chain_record.data.documentHash,
            "onChainMetadataHashValid": content.metadata_hash == chain_record.data.metadataHash,
            "onChainDocumentCommitmentValid": content.document_commitment == chain_record.data.documentChunkCommitment,
            "onChainMetadataCommitmentValid": content.metadata_commitment == chain_record.data.metadataChunkCommitment,
            "publisherMatches": stored["developerName"] == chain_record.data.publisherEntity,
            "serviceNameMatches": stored["policyName"] == chain_record.data.serviceName,
            "versionMatches": stored["policyVersion"] == chain_record.data.policyVersion,
            "receiptMatches": stored["txHash"] == chain_record.txHash,
            "contractAddressMatches": stored["contractAddress"].lower() == chain_record.contractAddress.lower(),
            "chainIdMatches": stored["chainId"] == chain_record.chainId == 8453,
            **audit["checks"],
        }
        verified = all(comparisons.values())
        self._json({
            "verified": verified,
            "comparisons": comparisons,
            "submittedHash": submitted_hash,
            "exactHashesMatch": "0x" + submitted_hash == chain_record.data.documentHash,
            "normalizedTextMatches": normalize_policy_text(submitted_raw) == normalize_policy_text(stored["rawFile"]),
            "audit": audit,
            "normalization": "case, whitespace, and punctuation ignored for the informational text comparison",
            "stored": stored,
            "onChain": self._chain_to_dict(chain_record),
            "reason": "Exact policy bytes match the verified Base record." if verified else "The submitted file or an on-chain audit check did not match.",
        })

    def _analyze_policy_with_llm(self, payload: dict[str, Any]) -> None:
        """Analyze a policy without writing to the blockchain.

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
                "message": "Policy analyzed locally. No Base Mainnet transaction was sent.",
            }
        )

    def _read_payload(self) -> dict[str, Any]:
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("multipart/form-data"):
            return self._read_multipart(content_type)
        return self._read_json()

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > MAX_HTTP_BODY_BYTES:
            raise ValueError("Request body exceeds the upload limit")
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
        if length < 0 or length > MAX_HTTP_BODY_BYTES:
            raise ValueError("Request body exceeds the upload limit")
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
                "error": "This file content is already registered on Base Mainnet.",
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

    def _compliance_detail(self, record_key: str) -> None:
        status = registry.read_compliance_status(record_key)
        if status["status"] != "finalized":
            self._json({"compliance": status})
            return

        content, bundle, comparisons = self._verified_compliance_bundle(record_key)
        files = [
            {
                **entry,
                "content": bundle.files[entry["name"]].decode(
                    "utf-8", errors="replace"
                ),
            }
            for entry in bundle.manifest["files"]
        ]
        self._json(
            {
                "compliance": status,
                "verified": True,
                "comparisons": comparisons,
                "manifest": bundle.manifest,
                "files": files,
                "downloadUrl": f"/api/compliance/{record_key}/download",
            }
        )

    def _download_compliance_bundle(self, record_key: str) -> None:
        content, _, _ = self._verified_compliance_bundle(record_key)
        filename = f"compliance-{record_key.lower()}.zip"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{filename}"',
        )
        self.send_header("Content-Length", str(len(content.bundle)))
        self.end_headers()
        self.wfile.write(content.bundle)

    def _verified_compliance_bundle(self, record_key: str) -> tuple[Any, Any, dict[str, bool]]:
        content = registry.read_compliance_content(record_key)
        bundle = read_compliance_bundle(content.bundle)
        comparisons = {
            "bundleHashMatchesContract": (
                bundle.manifest["bundleHash"] == content.result.bundleHash
            ),
            "sourceDocumentHashMatchesContract": (
                bundle.manifest["sourceDocumentHash"]
                == content.result.sourceDocumentHash
            ),
            "pipelineVersionHashMatchesContract": (
                bundle.manifest["pipelineVersionHash"]
                == content.result.pipelineVersionHash
            ),
            "recordKeyMatchesContract": (
                bundle.manifest["recordKey"].lower()
                == content.result.recordKey.lower()
            ),
        }
        failures = [name for name, valid in comparisons.items() if not valid]
        if failures:
            raise RuntimeError(
                "Compliance manifest failed contract validation: "
                + ", ".join(failures)
            )
        return content, bundle, comparisons

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
        payload = asdict(record)
        payload["compliance"] = registry.read_compliance_status(record.recordKey)
        return payload

    def _handle_error(self, exc: Exception) -> None:
        traceback.print_exc()
        self._json(
            {"error": "Server failed to process the Base Mainnet request. Check server logs."},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )


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
