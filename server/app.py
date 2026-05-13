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
from processor import extract_metadata, generate_report, hash_policy
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
                chain_record = registry.read_on_chain_record(policy_id, policy["policy_version"])
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
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Any]:
        metadata = extract_metadata(raw_file, policy_id, policy_version)
        metadata["applicationName"] = policy_name
        metadata["developer"] = developer_name
        report = generate_report(metadata, hash_code)
        chain_record = registry.register_trusted_policy_record(
            OnChainData(
                rawFile=raw_file,
                policyId=policy_id,
                policyVersion=policy_version,
                hashCode=hash_code,
            )
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
        if stored["hash_code"] != submitted_hash:
            self._json(
                {
                    "verified": False,
                    "reason": "Submitted policy content does not match the latest trusted policy for that application.",
                    "submittedHash": submitted_hash,
                    "sqlHash": stored["hash_code"],
                    "stored": stored,
                },
                HTTPStatus.CONFLICT,
            )
            return
        policy_id = stored["policy_id"]
        policy_version = stored["policy_version"]
        chain_record = registry.read_on_chain_record(policy_id, policy_version)
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
        chain_hash = chain_record.data.hashCode or hash_policy(chain_record.data.rawFile)
        comparisons = {
            "sqlMatchesChain": expected_hash == chain_hash,
            "submittedMatchesSql": submitted_hash == expected_hash,
            "rawFileMatchesChain": submitted_raw == chain_record.data.rawFile,
            "policyIdMatches": stored["policy_id"] == chain_record.data.policyId,
            "versionMatches": stored["policy_version"] == chain_record.data.policyVersion,
        }
        verified = all(comparisons.values())
        self._json(
            {
                "verified": verified,
                "comparisons": comparisons,
                "submittedHash": submitted_hash,
                "sqlHash": expected_hash,
                "chainHash": chain_hash,
                "stored": stored,
                "onChain": self._chain_to_dict(chain_record),
                "reason": "Records match." if verified else "At least one record comparison failed.",
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
