"""Adapter between on-chain raw policy bytes and the P1/P2/P3 CLIs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gpt_api import load_gpt_api_key
from server.compliance_bundle import (
    BUNDLE_FILENAME,
    COMPLIANCE_FILE_TYPES,
    read_local_compliance_bundle,
    write_compliance_bundle,
)


TOOL_ROOT = Path(__file__).resolve().parent
P1_SCRIPT = TOOL_ROOT / "P1" / "high_risk_detection.py"
P2_SCRIPT = TOOL_ROOT / "P2" / "information_extract.py"
P3_SCRIPT = TOOL_ROOT / "P3" / "evaluate_checklist.py"
PIPELINE_VERSION_FILES = (
    P1_SCRIPT,
    TOOL_ROOT / "P1" / "src" / "prompts" / "risk_prompt.py",
    P2_SCRIPT,
    P3_SCRIPT,
)


def run_stage(label: str, command: list[str], environment: dict[str, str]) -> None:
    completed = subprocess.run(
        command,
        cwd=TOOL_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.stdout.strip():
        print(completed.stdout.strip())
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"{label} failed: {details or f'exit {completed.returncode}'}")


def require_output(label: str, path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(f"{label} did not create its expected output: {path.name}")


def p1_checklist_mode(result_path: Path) -> str:
    """Map P1's validated classification to the P3 CLI flag."""
    try:
        classification = json.loads(result_path.read_text(encoding="utf-8"))[
            "classification"
        ]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read P1 classification from {result_path}") from exc

    if classification == "High-Risk":
        return "yes"
    if classification == "Not High-Risk":
        return "no"
    raise RuntimeError(f"Unsupported P1 classification: {classification!r}")


def pipeline_version() -> str:
    digest = hashlib.sha256()
    for path in PIPELINE_VERSION_FILES:
        digest.update(path.relative_to(TOOL_ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"p1-p2-p3-openai-v1:{digest.hexdigest()}"


def _restore_local_files(output_dir: Path, files: dict[str, bytes]) -> None:
    for name, content in files.items():
        path = output_dir / name
        if not path.is_file() or path.read_bytes() != content:
            temporary = output_dir / f".{name}.tmp"
            temporary.write_bytes(content)
            temporary.replace(path)


def _write_bundle(
    output_dir: Path,
    *,
    record_key: str,
    document_hash: str,
    model: str,
    p3_mode: str,
) -> None:
    bundle = write_compliance_bundle(
        output_dir,
        record_key=record_key,
        source_document_hash=document_hash,
        model=model,
        p3_mode=p3_mode,
        pipeline_version=pipeline_version(),
    )
    print(
        f"Compliance bundle ready: {BUNDLE_FILENAME} "
        f"({bundle.manifest['bundleSize']} bytes, {bundle.manifest['bundleHash']})"
    )


def run_compliance(
    raw_file: bytes,
    output_dir: Path,
    model: str,
    high_risk: str,
    record_key: str,
    document_hash: str,
) -> None:
    if not raw_file:
        raise ValueError("rawFile is empty")
    actual_document_hash = "0x" + hashlib.sha256(raw_file).hexdigest()
    if actual_document_hash.lower() != document_hash.lower():
        raise ValueError("rawFile does not match the supplied document hash")

    output_dir.mkdir(parents=True, exist_ok=True)
    existing_bundle = read_local_compliance_bundle(
        output_dir,
        record_key=record_key,
        source_document_hash=document_hash,
    )
    if existing_bundle is not None:
        _restore_local_files(output_dir, existing_bundle.files)
        print(
            f"Reusing existing local compliance bundle "
            f"{existing_bundle.manifest['bundleHash']}; GPT stages were skipped"
        )
        return

    existing_outputs = all(
        (output_dir / name).is_file() and (output_dir / name).stat().st_size > 0
        for name in COMPLIANCE_FILE_TYPES
    )
    if existing_outputs:
        p3_mode = (
            p1_checklist_mode(output_dir / "p1-risk.json")
            if high_risk == "auto"
            else high_risk
        )
        _write_bundle(
            output_dir,
            record_key=record_key,
            document_hash=document_hash,
            model=model,
            p3_mode=p3_mode,
        )
        print("Reused existing P1/P2/P3 files; GPT stages were skipped")
        return

    environment = {
        **os.environ,
        "OPENAI_API_KEY": load_gpt_api_key(),
    }

    with tempfile.TemporaryDirectory(prefix="compliance-", dir=output_dir) as temporary:
        work_dir = Path(temporary)
        policy_dir = work_dir / "policy"
        p1_dir = work_dir / "p1"
        p2_dir = work_dir / "p2"
        p3_dir = work_dir / "p3"
        policy_dir.mkdir()
        policy_path = policy_dir / "policy.txt"
        policy_path.write_bytes(raw_file)

        run_stage(
            "P1 high-risk classification",
            [
                sys.executable,
                str(P1_SCRIPT),
                "--in_dir",
                str(policy_dir),
                "--out_dir",
                str(p1_dir),
                "--model",
                model,
            ],
            environment,
        )
        p1_result = p1_dir / "policy.json"
        require_output("P1 high-risk classification", p1_result)
        p3_high_risk = (
            p1_checklist_mode(p1_result) if high_risk == "auto" else high_risk
        )
        print(f"P3 checklist mode: {p3_high_risk} (configured: {high_risk})")

        run_stage(
            "P2 information extraction",
            [
                sys.executable,
                str(P2_SCRIPT),
                "--in_dir",
                str(policy_dir),
                "--out_dir",
                str(p2_dir),
                "--model",
                model,
            ],
            environment,
        )
        p2_result = p2_dir / "policy.json"
        require_output("P2 information extraction", p2_result)

        run_stage(
            "P3 checklist evaluation",
            [
                sys.executable,
                str(P3_SCRIPT),
                "--report_dir",
                str(p2_dir),
                "--policy_dir",
                str(policy_dir),
                "--out_dir",
                str(p3_dir),
                "--high_risk",
                p3_high_risk,
                "--model",
                model,
            ],
            environment,
        )
        p3_json_result = p3_dir / "policy.json"
        p3_markdown_result = p3_dir / "policy.md"
        require_output("P3 checklist evaluation", p3_json_result)
        require_output("P3 checklist evaluation", p3_markdown_result)

        p1_result.replace(output_dir / "p1-risk.json")
        p2_result.replace(output_dir / "p2-extraction.json")
        p3_json_result.replace(output_dir / "p3-checklist.json")
        p3_markdown_result.replace(output_dir / "p3-checklist.md")
        _write_bundle(
            output_dir,
            record_key=record_key,
            document_hash=document_hash,
            model=model,
            p3_mode=p3_high_risk,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--record-key", required=True)
    parser.add_argument("--document-hash", required=True)
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument(
        "--high-risk",
        choices=["auto", "yes", "no"],
        default="auto",
        help="Use P1 classification by default, or explicitly override the P3 checklist",
    )
    args = parser.parse_args()

    run_compliance(
        raw_file=sys.stdin.buffer.read(),
        output_dir=Path(args.output_dir),
        model=args.model,
        high_risk=args.high_risk,
        record_key=args.record_key,
        document_hash=args.document_hash,
    )
    print(f"Compliance outputs saved locally in {Path(args.output_dir).resolve()}")


if __name__ == "__main__":
    main()
