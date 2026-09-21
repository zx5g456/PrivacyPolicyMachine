from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


COMPLIANCE_FILE_TYPES = {
    "p1-risk.json": "application/json",
    "p2-extraction.json": "application/json",
    "p3-checklist.json": "application/json",
    "p3-checklist.md": "text/markdown",
}
BUNDLE_FILENAME = "compliance-bundle.zip"
MANIFEST_FILENAME = "compliance-manifest.json"
INTERNAL_MANIFEST_FILENAME = "manifest.json"
BUNDLE_SCHEMA_VERSION = "1"
_FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class ComplianceBundle:
    data: bytes
    manifest: dict[str, Any]
    files: dict[str, bytes]


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return "0x" + hashlib.sha256(value).hexdigest()


def build_compliance_bundle(
    files: Mapping[str, bytes],
    *,
    record_key: str,
    source_document_hash: str,
    model: str,
    p3_mode: str,
    pipeline_version: str,
) -> ComplianceBundle:
    normalized_files = _validate_files(files)
    internal_manifest = {
        "schemaVersion": BUNDLE_SCHEMA_VERSION,
        "recordKey": _normalize_hash(record_key, "recordKey"),
        "sourceDocumentHash": _normalize_hash(
            source_document_hash, "sourceDocumentHash"
        ),
        "model": model,
        "p3Mode": p3_mode,
        "pipelineVersion": pipeline_version,
        "pipelineVersionHash": sha256_hex(pipeline_version.encode("utf-8")),
        "files": [
            {
                "name": name,
                "mediaType": COMPLIANCE_FILE_TYPES[name],
                "size": len(normalized_files[name]),
                "sha256": sha256_hex(normalized_files[name]),
            }
            for name in COMPLIANCE_FILE_TYPES
        ],
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        _write_zip_entry(
            archive,
            INTERNAL_MANIFEST_FILENAME,
            canonical_json_bytes(internal_manifest),
        )
        for name in COMPLIANCE_FILE_TYPES:
            _write_zip_entry(archive, name, normalized_files[name])

    data = buffer.getvalue()
    manifest = {
        **internal_manifest,
        "bundleFile": BUNDLE_FILENAME,
        "bundleSize": len(data),
        "bundleHash": sha256_hex(data),
        "compression": "zip-deflate",
    }
    return ComplianceBundle(data=data, manifest=manifest, files=normalized_files)


def read_compliance_bundle(data: bytes) -> ComplianceBundle:
    if not data:
        raise ValueError("Compliance bundle is empty")
    try:
        with zipfile.ZipFile(io.BytesIO(data), mode="r") as archive:
            names = archive.namelist()
            expected = [INTERNAL_MANIFEST_FILENAME, *COMPLIANCE_FILE_TYPES]
            if names != expected:
                raise ValueError(
                    "Compliance bundle entries do not match the required deterministic order"
                )
            manifest = json.loads(archive.read(INTERNAL_MANIFEST_FILENAME))
            files = {name: archive.read(name) for name in COMPLIANCE_FILE_TYPES}
    except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise ValueError("Invalid compliance bundle") from exc

    _validate_internal_manifest(manifest, files)
    external_manifest = {
        **manifest,
        "bundleFile": BUNDLE_FILENAME,
        "bundleSize": len(data),
        "bundleHash": sha256_hex(data),
        "compression": "zip-deflate",
    }
    return ComplianceBundle(data=data, manifest=external_manifest, files=files)


def write_compliance_bundle(
    output_dir: Path,
    *,
    record_key: str,
    source_document_hash: str,
    model: str,
    p3_mode: str,
    pipeline_version: str,
) -> ComplianceBundle:
    files = {
        name: (output_dir / name).read_bytes()
        for name in COMPLIANCE_FILE_TYPES
    }
    bundle = build_compliance_bundle(
        files,
        record_key=record_key,
        source_document_hash=source_document_hash,
        model=model,
        p3_mode=p3_mode,
        pipeline_version=pipeline_version,
    )
    _atomic_write(output_dir / BUNDLE_FILENAME, bundle.data)
    _atomic_write(
        output_dir / MANIFEST_FILENAME,
        json.dumps(bundle.manifest, ensure_ascii=False, indent=2).encode("utf-8")
        + b"\n",
    )
    return bundle


def restore_compliance_bundle(output_dir: Path, data: bytes) -> ComplianceBundle:
    """Restore every local artifact from an already verified on-chain ZIP bundle."""
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = read_compliance_bundle(data)
    _atomic_write(output_dir / BUNDLE_FILENAME, bundle.data)
    _atomic_write(
        output_dir / MANIFEST_FILENAME,
        json.dumps(bundle.manifest, ensure_ascii=False, indent=2).encode("utf-8")
        + b"\n",
    )
    for name, content in bundle.files.items():
        _atomic_write(output_dir / name, content)
    return bundle


def read_local_compliance_bundle(
    output_dir: Path,
    *,
    record_key: str,
    source_document_hash: str,
) -> ComplianceBundle | None:
    bundle_path = output_dir / BUNDLE_FILENAME
    manifest_path = output_dir / MANIFEST_FILENAME
    if not bundle_path.is_file() or not manifest_path.is_file():
        return None

    try:
        stored_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        bundle = read_compliance_bundle(bundle_path.read_bytes())
    except (OSError, ValueError, json.JSONDecodeError):
        return None

    expected_record_key = _normalize_hash(record_key, "recordKey")
    expected_document_hash = _normalize_hash(
        source_document_hash, "sourceDocumentHash"
    )
    if bundle.manifest != stored_manifest:
        return None
    if bundle.manifest.get("recordKey") != expected_record_key:
        return None
    if bundle.manifest.get("sourceDocumentHash") != expected_document_hash:
        return None
    return bundle


def _validate_files(files: Mapping[str, bytes]) -> dict[str, bytes]:
    expected = set(COMPLIANCE_FILE_TYPES)
    if set(files) != expected:
        missing = sorted(expected - set(files))
        extra = sorted(set(files) - expected)
        raise ValueError(f"Compliance files mismatch; missing={missing}, extra={extra}")
    normalized = {name: bytes(files[name]) for name in COMPLIANCE_FILE_TYPES}
    empty = [name for name, value in normalized.items() if not value]
    if empty:
        raise ValueError("Compliance files must not be empty: " + ", ".join(empty))
    return normalized


def _validate_internal_manifest(
    manifest: dict[str, Any], files: Mapping[str, bytes]
) -> None:
    if manifest.get("schemaVersion") != BUNDLE_SCHEMA_VERSION:
        raise ValueError("Unsupported compliance bundle schema")
    _normalize_hash(str(manifest.get("recordKey", "")), "recordKey")
    _normalize_hash(
        str(manifest.get("sourceDocumentHash", "")), "sourceDocumentHash"
    )
    pipeline_version = manifest.get("pipelineVersion")
    if not isinstance(pipeline_version, str) or not pipeline_version:
        raise ValueError("Compliance bundle is missing pipelineVersion")
    if manifest.get("pipelineVersionHash") != sha256_hex(
        pipeline_version.encode("utf-8")
    ):
        raise ValueError("Compliance pipeline version hash does not match")

    expected_entries = [
        {
            "name": name,
            "mediaType": COMPLIANCE_FILE_TYPES[name],
            "size": len(files[name]),
            "sha256": sha256_hex(files[name]),
        }
        for name in COMPLIANCE_FILE_TYPES
    ]
    if manifest.get("files") != expected_entries:
        raise ValueError("Compliance file manifest does not match bundle content")


def _normalize_hash(value: str, label: str) -> str:
    normalized = value.lower()
    if len(normalized) != 66 or not normalized.startswith("0x"):
        raise ValueError(f"{label} must be a 32-byte 0x-prefixed hash")
    try:
        bytes.fromhex(normalized[2:])
    except ValueError as exc:
        raise ValueError(f"{label} must be hexadecimal") from exc
    return normalized


def _write_zip_entry(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
