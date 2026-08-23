#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Independently recover and audit a policy registration from transaction calldata."
    )
    parser.add_argument("tx_hash")
    parser.add_argument("--rpc-url", required=True)
    parser.add_argument("--contract-address", required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    os.environ["RPC_URL"] = args.rpc_url
    os.environ["CONTRACT_ADDRESS"] = args.contract_address

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from server.blockchain import TrustedPolicyRegistry

    artifact = root / "artifacts/contracts/TrustedPolicyRegistry.sol/TrustedPolicyRegistry.json"
    registry = TrustedPolicyRegistry(artifact)
    audit = registry.audit_registration(args.tx_hash)

    if args.output_dir:
        recovered = registry.recover_registration(args.tx_hash)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "raw-file.bin").write_bytes(recovered.rawFile)
        (args.output_dir / "metadata.json").write_bytes(recovered.metadataJson)
        audit["recoveredFiles"] = {
            "rawFile": str(args.output_dir / "raw-file.bin"),
            "metadata": str(args.output_dir / "metadata.json"),
        }

    print(json.dumps(audit, ensure_ascii=False, indent=2))
    raise SystemExit(0 if audit["valid"] else 1)


if __name__ == "__main__":
    main()
