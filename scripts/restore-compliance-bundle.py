from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.compliance_bundle import restore_compliance_bundle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    bundle_path = Path(args.bundle)
    output_dir = Path(args.output_dir)
    restored = restore_compliance_bundle(output_dir, bundle_path.read_bytes())
    print(
        f"Restored {len(restored.files)} compliance files from "
        f"{restored.manifest['bundleHash']}"
    )


if __name__ == "__main__":
    main()
