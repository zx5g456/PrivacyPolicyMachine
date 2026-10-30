"""P1: classify privacy policies as high-risk or not high-risk."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from config import GPT_MODEL, RISK_RESULT_DIRECTORY, ROOT_DIRECTORY, SUPPORTED_EXTENSIONS
from src.analyzers.high_risk_analyser import analyze_risk


CLASSIFICATION_RE = re.compile(
    r"High-Risk Classification:[ \t]*\[?[ \t]*(Not High-Risk|High-Risk)[ \t]*\]?[ \t]*[.]?",
    re.IGNORECASE,
)
MARKDOWN_PREFIX_RE = re.compile(r"^(?:[-*•]|\d+[.)]|#{1,6})[ \t]+")


def extract_risk_classification(analysis: str) -> str:
    """Extract and normalize the classification required by the P1 prompt."""
    classifications = set()
    for line in analysis.splitlines():
        candidate = MARKDOWN_PREFIX_RE.sub("", line.strip(), count=1)
        candidate = candidate.replace("*", "").replace("_", "").replace("`", "")
        match = CLASSIFICATION_RE.fullmatch(candidate.strip())
        if match:
            classifications.add(
                "Not High-Risk" if match.group(1).lower().startswith("not") else "High-Risk"
            )
    if len(classifications) != 1:
        raise ValueError("P1 response is missing a valid High-Risk Classification")
    return classifications.pop()


def detect_high_risk(
    in_dir: str | Path = ROOT_DIRECTORY,
    out_dir: str | Path = RISK_RESULT_DIRECTORY,
    model: str = GPT_MODEL,
) -> None:
    """Run P1 for every supported policy file in one directory."""
    input_directory = Path(in_dir)
    output_directory = Path(out_dir)
    output_directory.mkdir(parents=True, exist_ok=True)

    if not input_directory.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {input_directory}")

    supported = {extension.lower() for extension in SUPPORTED_EXTENSIONS}
    policy_files = sorted(
        path
        for path in input_directory.iterdir()
        if path.is_file()
        and not path.name.startswith(".")
        and path.suffix.lower() in supported
    )
    if not policy_files:
        print(f"[WARN] No supported policy files found in: {input_directory}")
        return

    failures: list[str] = []
    for policy_path in policy_files:
        try:
            policy_text = policy_path.read_text(encoding="utf-8", errors="ignore")
            analysis = analyze_risk(policy_text, policy_path.name, model=model)
            result = {
                "classification": extract_risk_classification(analysis),
                "analysis": analysis,
                "model": model,
                "policy_file": policy_path.name,
            }
            output_path = output_directory / f"{policy_path.stem}.json"
            output_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"[OK] Saved: {output_path}")
        except Exception as exc:
            failures.append(f"{policy_path.name}: {exc}")
            print(f"[ERROR] {policy_path.name}: {exc}")

    if failures:
        raise RuntimeError("P1 failed for: " + "; ".join(failures))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--in_dir",
        default=ROOT_DIRECTORY,
        help="Directory containing privacy policy files",
    )
    parser.add_argument(
        "--out_dir",
        default=RISK_RESULT_DIRECTORY,
        help="Directory to write P1 JSON results",
    )
    parser.add_argument("--model", default=GPT_MODEL, help="OpenAI model name")
    args = parser.parse_args()

    detect_high_risk(args.in_dir, args.out_dir, args.model)


if __name__ == "__main__":
    main()
