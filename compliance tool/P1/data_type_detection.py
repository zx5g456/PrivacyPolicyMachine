"""Run P1's XR-specific data-type prompt through the OpenAI API."""

from __future__ import annotations

import argparse
from pathlib import Path

from config import DATATYPE_RESULT_DIRECTORY, GPT_MODEL, ROOT_DIRECTORY, SUPPORTED_EXTENSIONS
from src.analyzers.data_type_analyser import analyze_data_types


def detect_data_types(
    in_dir: str | Path = ROOT_DIRECTORY,
    out_dir: str | Path = DATATYPE_RESULT_DIRECTORY,
    model: str = GPT_MODEL,
) -> None:
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
            analysis = analyze_data_types(
                policy_text,
                policy_path.name,
                model=model,
            )
            output_path = output_directory / f"{policy_path.stem}_data_types.txt"
            output_path.write_text(analysis + "\n", encoding="utf-8")
            print(f"[OK] Saved: {output_path}")
        except Exception as exc:
            failures.append(f"{policy_path.name}: {exc}")
            print(f"[ERROR] {policy_path.name}: {exc}")

    if failures:
        raise RuntimeError("P1 data-type analysis failed for: " + "; ".join(failures))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--in_dir",
        default=ROOT_DIRECTORY,
        help="Directory containing privacy policy files",
    )
    parser.add_argument(
        "--out_dir",
        default=DATATYPE_RESULT_DIRECTORY,
        help="Directory to write XR data-type results",
    )
    parser.add_argument("--model", default=GPT_MODEL, help="OpenAI model name")
    args = parser.parse_args()

    detect_data_types(args.in_dir, args.out_dir, args.model)


if __name__ == "__main__":
    main()
