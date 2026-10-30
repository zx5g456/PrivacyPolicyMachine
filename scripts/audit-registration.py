#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Independently recover and audit chunked policy content from contract storage."
    )
    parser.add_argument(
        "identifier",
        help="Finalization transaction hash or finalized on-chain record key",
    )
    parser.add_argument("--rpc-url", required=True)
    parser.add_argument("--contract-address", required=True)
    parser.add_argument("--deployment-block", required=True, type=int)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    os.environ["RPC_URL"] = args.rpc_url
    os.environ["CONTRACT_ADDRESS"] = args.contract_address
    os.environ["CONTRACT_DEPLOYMENT_BLOCK"] = str(args.deployment_block)
    os.environ["EXPECTED_CHAIN_ID"] = "8453"

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from server.blockchain import TrustedPolicyRegistry

    artifact = root / "artifacts/contracts/TrustedPolicyRegistry.sol/TrustedPolicyRegistry.json"
    registry = TrustedPolicyRegistry(artifact)
    audit = registry.audit_registration(args.identifier)

    if args.output_dir:
        recovered = registry.read_on_chain_content(audit["recordKey"])
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
