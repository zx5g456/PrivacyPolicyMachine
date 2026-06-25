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

from blockchain import OnChainData, TrustedPolicyRegistry
from processor import extract_metadata, generate_report, hash_policy, normalize_policy_text
from storage import PolicyStore


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
STATIC_DIR = ROOT / "web" / "static"
store = PolicyStore(DATA_DIR / "policies.db")
registry = TrustedPolicyRegistry(DATA_DIR / "chain.json")


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
                    policy["developer_name"],
                    policy["policy_name"],
                    policy["policy_version"],
                )
                self._json({"policy": policy, "onChain": self._chain_to_dict(chain_record)})
            elif parsed.path == "/api/chain":
                self._json({"records": [self._chain_to_dict(item) for item in registry.list_records()]})
            else:
                self._static(parsed.path)
        except Exception as exc:
            self._handle_error(exc)

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            payload = self._read_payload()
            if parsed.path == "/api/policies":
                self._create_policy(payload)
            elif parsed.path == "/api/policies/update":
                self._update_policy(payload)
            elif parsed.path == "/api/verify":
                self._verify_policy(payload)
            else:
                self._json({"error": "Route not found"}, HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._handle_error(exc)

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _create_policy(self, payload: dict[str, Any]) -> None:
        raw_file = self._raw_file(payload, required=True)
        policy_id = str(uuid.uuid4())
        application_name = self._application_name(payload)
        developer_name = self._developer_name(payload)
        policy_version = self._upload_time()
        hash_code = hash_policy(raw_file)
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
            hash_code=hash_code,
            policy_url=self._optional_payload(payload, "policyUrl"),
            effective_date=self._optional_payload(payload, "effectiveDate"),
            change_summary="",
        )
        self._json(
            {
                "policy": policy,
                "metadata": metadata,
                "report": report,
                "onChain": self._chain_to_dict(chain_record),
                "message": "Policy processed, stored, and registered.",
            },
            HTTPStatus.CREATED,
        )

    def _update_policy(self, payload: dict[str, Any]) -> None:
        policy_id = self._required(payload, "policyId")
        developer_name = self._developer_name(payload)
        policy_version = self._upload_time()
        raw_file = self._raw_file(payload, required=True)
        existing = store.get_latest(policy_id)
        if not existing:
            self._json({"error": "Policy ID not found. Create the policy first."}, HTTPStatus.NOT_FOUND)
            return
        if existing.get("developer_name", "").lower() != developer_name.lower():
            self._json({"error": "Only the developer who uploaded this application policy can update it."}, HTTPStatus.FORBIDDEN)
            return
        hash_code = hash_policy(raw_file)
        duplicate = store.get_by_hash(hash_code)
        if duplicate:
            self._duplicate_hash_response(duplicate, hash_code)
            return
        policy, metadata, report, chain_record = self._register_policy_version(
            policy_id=policy_id,
            policy_name=existing["policy_name"],
            policy_version=policy_version,
            developer_name=developer_name,
            raw_file=raw_file,
            hash_code=hash_code,
            policy_url=self._optional_payload(payload, "policyUrl"),
            effective_date=self._optional_payload(payload, "effectiveDate"),
            change_summary=self._optional_payload(payload, "changeSummary"),
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
        hash_code: str,
        policy_url: str,
        effective_date: str,
        change_summary: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Any]:
        metadata = extract_metadata(raw_file, policy_id, policy_version)
        metadata["applicationName"] = policy_name
        metadata["developer"] = developer_name
        metadata["publisher_entity"] = developer_name
        metadata["policy_url"] = policy_url
        metadata["service_name"] = policy_name
        metadata["effective_date"] = effective_date
        metadata["document_hash"] = hash_code
        metadata["change_summary"] = change_summary
        report = generate_report(metadata, hash_code)
        chain_record = registry.register_trusted_policy_record(
            self._on_chain_data(raw_file, metadata)
        )
        policy = store.create_policy(
            policy_id=policy_id,
            policy_name=policy_name,
            policy_version=policy_version,
            developer_name=developer_name,
            raw_file=raw_file,
            hash_code=hash_code,
            metadata=metadata,
            report=report,
            tx_hash=chain_record.txHash,
        )
        return policy, metadata, report, chain_record

    def _verify_policy(self, payload: dict[str, Any]) -> None:
        application_name = self._application_name(payload)
        submitted_raw = self._submitted_policy(payload)
        submitted_hash = hash_policy(submitted_raw)
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
        policy_version = stored["policy_version"]
        chain_record = registry.read_on_chain_record(
            stored["developer_name"],
            stored["policy_name"],
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

        expected_hash = stored["hash_code"]
        normalized_submitted = normalize_policy_text(submitted_raw)
        normalized_stored = normalize_policy_text(stored["raw_file"])
        normalized_chain = normalize_policy_text(chain_record.data.rawFile)
        comparisons = {
            "submittedTextMatchesSql": normalized_submitted == normalized_stored,
            "sqlTextMatchesChain": normalized_stored == normalized_chain,
            "publisherMatches": stored["developer_name"] == chain_record.data.publisherEntity,
            "serviceNameMatches": stored["policy_name"] == chain_record.data.serviceName,
            "versionMatches": stored["policy_version"] == chain_record.data.policyVersion,
        }
        verified = all(comparisons.values())
        self._json(
            {
                "verified": verified,
                "comparisons": comparisons,
                "submittedHash": submitted_hash,
                "sqlHash": expected_hash,
                "exactHashesMatch": submitted_hash == expected_hash,
                "normalization": "case, whitespace, and punctuation ignored",
                "stored": stored,
                "onChain": self._chain_to_dict(chain_record),
                "reason": "Policy text matches after normalization." if verified else "At least one normalized text or record identity comparison failed.",
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

    def _on_chain_data(self, raw_file: str, metadata: dict[str, Any]) -> OnChainData:
        return OnChainData(
            rawFile=raw_file,
            policyVersion=self._metadata_text(metadata, "policy_version"),
            publisherEntity=self._metadata_text(metadata, "publisher_entity"),
            policyUrl=self._metadata_text(metadata, "policy_url"),
            serviceName=self._metadata_text(metadata, "service_name"),
            effectiveDate=self._metadata_text(metadata, "effective_date"),
            dataTypeTags=self._metadata_text(metadata, "data_type_tags"),
            dataSourceTypes=self._metadata_text(metadata, "data_source_types"),
            collectionContext=self._metadata_text(metadata, "collection_context"),
            processingPurpose=self._metadata_text(metadata, "processing_purpose"),
            permittedUsage=self._metadata_text(metadata, "permitted_usage"),
            thirdPartySources=self._metadata_text(metadata, "third_party_sources"),
            downstreamStakeholders=self._metadata_text(metadata, "downstream_stakeholders"),
            thirdPartyPurpose=self._metadata_text(metadata, "third_party_purpose"),
            sharingCondition=self._metadata_text(metadata, "sharing_condition"),
            consentRequired=self._metadata_text(metadata, "consent_required"),
            optOutAvailable=self._metadata_text(metadata, "opt_out_available"),
            deletionAvailable=self._metadata_text(metadata, "deletion_available"),
            requestChannel=self._metadata_text(metadata, "request_channel"),
            retentionPolicy=self._metadata_text(metadata, "retention_policy"),
            encryptionApplied=self._metadata_text(metadata, "encryption_applied"),
            anonymisation=self._metadata_text(metadata, "anonymisation"),
            regulatoryFramework=self._metadata_text(metadata, "regulatory_framework"),
            crossBorderTransfer=self._metadata_text(metadata, "cross_border_transfer"),
            childDataInvolved=self._metadata_text(metadata, "child_data_involved"),
            changeSummary=self._metadata_text(metadata, "change_summary"),
            contactChannel=self._metadata_text(metadata, "contact_channel"),
            riskFlags=self._metadata_text(metadata, "risk_flags"),
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

    def _submitted_policy(self, payload: dict[str, Any]) -> str:
        raw_file = self._raw_file(payload, required=False)
        if raw_file:
            return raw_file
        raw_text = payload.get("rawText")
        if isinstance(raw_text, str) and raw_text.strip():
            return raw_text.strip()
        raise ValueError("Upload a policy file or enter policy text to verify")

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
                    "policyId": duplicate["policy_id"],
                    "applicationName": duplicate["policy_name"],
                    "uploadTime": duplicate["policy_version"],
                    "developer": duplicate.get("developer_name", ""),
                    "hashCode": hash_code,
                    "createdAt": duplicate["created_at"],
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
