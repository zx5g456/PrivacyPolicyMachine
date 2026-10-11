#!/usr/bin/env python3
"""Freeze a short, content-distinct RQ3 sample from the existing source corpus."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(__file__).with_name("policies.csv")

# Chosen by reading the shortest plausible, independent privacy notices. The
# 3,000-character chunk setting makes most policies exercise aggregation.
SOURCES = (
    ("Oberon Technologies", "high_risk_pp/www.oberontech.com.txt"),
    ("Taanga Studios", "high_risk_pp/www.taangastudios.com.txt"),
    ("Pillow", "high_risk_pp/www.pillow.social.txt"),
    ("Medicalholodeck", "high_risk_pp/www.medicalholodeck.com.txt"),
    ("Simodont Dental Trainer", "high_risk_pp/www.simodontdentaltrainer.com.txt"),
    ("Court Time Tennis", "high_risk_pp/courttimetennis.com.txt"),
    ("Gun Raiders", "ai-xr-oculus/3982869578392875_privacy_policy.txt"),
    ("Quill", "high_risk_pp/quill.art.txt"),
    ("Blue Duck Studios", "ai-xr-oculus/5934280436582748_privacy_policy.txt"),
    ("Commuter Games", "ai-xr-oculus/3927222113966481_privacy_policy.txt"),
    ("Dance Dance Dance", "ai-xr-oculus/7969053893147948_privacy_policy.txt"),
    ("Uptale", "high_risk_pp/www.uptale.io.txt"),
    ("Aim XR", "ai-xr-oculus/4245506092131005_privacy_policy.txt"),
    ("Vermillion", "high_risk_pp/vermillion-vr.com.txt"),
    ("Cubism", "ai-xr-oculus/2264524423619421_privacy_policy.txt"),
)


def main() -> None:
    from server.llm_processor import chunk_policy

    rows = []
    hashes = set()
    for index, (name, relative) in enumerate(SOURCES, 1):
        path = ROOT / "sources" / "dataset" / relative
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        digest = hashlib.sha256(raw).hexdigest()
        if digest in hashes:
            raise ValueError(f"Duplicate policy content: {path}")
        hashes.add(digest)
        rows.append({
            "policy_id": f"P{index:02d}",
            "policy_name": name,
            "source_path": str(path.relative_to(ROOT)),
            "sha256": digest,
            "bytes": len(raw),
            "words": len(text.split()),
            "characters": len(text),
            "chunks_at_3000": len(chunk_policy(text, max_chars=3000, overlap_chars=200)),
        })
    with OUTPUT.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"Selected {len(rows)} policies; manifest: {OUTPUT}")
    for row in rows:
        print(row["policy_id"], row["policy_name"], row["characters"], row["chunks_at_3000"])


if __name__ == "__main__":
    main()
