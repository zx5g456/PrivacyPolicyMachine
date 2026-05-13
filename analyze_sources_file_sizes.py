#!/usr/bin/env python3
"""
Standalone file-size analysis for the local sources directory.

It scans files under sources/, writes a CSV with per-file sizes, prints summary
statistics, and generates a PNG chart comparing size distributions.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SOURCE_DIR = Path("sources")
DEFAULT_OUTPUT_DIR = Path("source_size_analysis")


@dataclass(frozen=True)
class FileRecord:
    path: Path
    relative_path: Path
    group: str
    extension: str
    size_bytes: int

    @property
    def size_kib(self) -> float:
        return self.size_bytes / 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze file sizes under sources/ and generate a comparison chart."
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="Directory to scan. Default: sources",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for CSV and chart outputs. Default: source_size_analysis",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Include hidden files such as .DS_Store. Hidden files are skipped by default.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=20,
        help="Number of largest files to show in the chart. Default: 20",
    )
    return parser.parse_args()


def is_hidden(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def detect_group(relative_path: Path) -> str:
    parts = relative_path.parts
    if len(parts) >= 2 and parts[0] == "dataset":
        return parts[1]
    if len(parts) >= 1:
        return parts[0]
    return "(root)"


def collect_files(source_dir: Path, include_hidden: bool) -> list[FileRecord]:
    records: list[FileRecord] = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue

        relative_path = path.relative_to(source_dir)
        if not include_hidden and is_hidden(relative_path):
            continue

        stat = path.stat()
        records.append(
            FileRecord(
                path=path,
                relative_path=relative_path,
                group=detect_group(relative_path),
                extension=path.suffix.lower() or "(none)",
                size_bytes=stat.st_size,
            )
        )
    return records


def percentile(sorted_values: list[int], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])

    position = (len(sorted_values) - 1) * pct
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])

    lower_value = sorted_values[lower]
    upper_value = sorted_values[upper]
    return lower_value + (upper_value - lower_value) * (position - lower)


def summarize_sizes(records: list[FileRecord]) -> dict[str, float]:
    sizes = sorted(record.size_bytes for record in records)
    if not sizes:
        return {}

    return {
        "count": len(sizes),
        "total_bytes": sum(sizes),
        "min_bytes": min(sizes),
        "p25_bytes": percentile(sizes, 0.25),
        "median_bytes": statistics.median(sizes),
        "mean_bytes": statistics.mean(sizes),
        "p75_bytes": percentile(sizes, 0.75),
        "p90_bytes": percentile(sizes, 0.90),
        "p95_bytes": percentile(sizes, 0.95),
        "max_bytes": max(sizes),
    }


def human_size(num_bytes: float) -> str:
    units = ["B", "KiB", "MiB", "GiB"]
    value = float(num_bytes)
    for unit in units:
        if abs(value) < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{value:.0f} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} GiB"


def write_csv(records: list[FileRecord], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "relative_path",
                "group",
                "extension",
                "size_bytes",
                "size_kib",
            ],
        )
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "relative_path": record.relative_path.as_posix(),
                    "group": record.group,
                    "extension": record.extension,
                    "size_bytes": record.size_bytes,
                    "size_kib": f"{record.size_kib:.3f}",
                }
            )


def group_records(records: list[FileRecord]) -> dict[str, list[FileRecord]]:
    groups: dict[str, list[FileRecord]] = defaultdict(list)
    for record in records:
        groups[record.group].append(record)
    return dict(sorted(groups.items()))


def print_summary(records: list[FileRecord], csv_path: Path, chart_path: Path) -> None:
    summary = summarize_sizes(records)
    if not summary:
        print("No files found.")
        return

    print("Overall file-size summary")
    print(f"- Files: {int(summary['count'])}")
    print(f"- Total size: {human_size(summary['total_bytes'])}")
    print(f"- Min / median / mean / max:")
    print(
        "  "
        f"{human_size(summary['min_bytes'])} / "
        f"{human_size(summary['median_bytes'])} / "
        f"{human_size(summary['mean_bytes'])} / "
        f"{human_size(summary['max_bytes'])}"
    )
    print(
        "- P25 / P75 / P90 / P95: "
        f"{human_size(summary['p25_bytes'])} / "
        f"{human_size(summary['p75_bytes'])} / "
        f"{human_size(summary['p90_bytes'])} / "
        f"{human_size(summary['p95_bytes'])}"
    )

    print("\nBy group")
    for group, grouped in group_records(records).items():
        grouped_summary = summarize_sizes(grouped)
        print(
            f"- {group}: {len(grouped)} files, "
            f"total {human_size(grouped_summary['total_bytes'])}, "
            f"median {human_size(grouped_summary['median_bytes'])}, "
            f"max {human_size(grouped_summary['max_bytes'])}"
        )

    print(f"\nCSV written to: {csv_path}")
    print(f"Chart written to: {chart_path}")


def make_chart(records: list[FileRecord], chart_path: Path, top_n: int) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(chart_path.parent / ".matplotlib-cache"))

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    groups = group_records(records)
    group_names = list(groups)
    group_total_kib = [sum(record.size_kib for record in groups[name]) for name in group_names]
    group_median_kib = [
        statistics.median(record.size_kib for record in groups[name]) for name in group_names
    ]

    all_sizes_kib = [record.size_kib for record in records]
    largest = sorted(records, key=lambda record: record.size_bytes, reverse=True)[:top_n]
    largest_labels = [record.relative_path.as_posix() for record in largest]
    largest_sizes = [record.size_kib for record in largest]

    fig, axes = plt.subplots(2, 2, figsize=(16, 11))
    fig.suptitle("sources/ file size analysis", fontsize=16, fontweight="bold")

    axes[0][0].hist(all_sizes_kib, bins=30, color="#3b82f6", edgecolor="white")
    axes[0][0].set_title("Distribution of file sizes")
    axes[0][0].set_xlabel("Size (KiB)")
    axes[0][0].set_ylabel("File count")

    axes[0][1].bar(group_names, group_total_kib, color=["#10b981", "#f59e0b", "#6366f1"])
    axes[0][1].set_title("Total size by group")
    axes[0][1].set_ylabel("Total size (KiB)")
    axes[0][1].tick_params(axis="x", rotation=20)

    axes[1][0].bar(group_names, group_median_kib, color=["#14b8a6", "#ef4444", "#8b5cf6"])
    axes[1][0].set_title("Median file size by group")
    axes[1][0].set_ylabel("Median size (KiB)")
    axes[1][0].tick_params(axis="x", rotation=20)

    axes[1][1].barh(range(len(largest)), largest_sizes, color="#64748b")
    axes[1][1].set_title(f"Top {len(largest)} largest files")
    axes[1][1].set_xlabel("Size (KiB)")
    axes[1][1].set_yticks(range(len(largest)))
    axes[1][1].set_yticklabels(largest_labels, fontsize=7)
    axes[1][1].invert_yaxis()

    for axis in axes.flat:
        axis.grid(axis="y", alpha=0.25)

    fig.tight_layout(rect=(0, 0, 1, 0.96))
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(chart_path, dpi=180)
    plt.close(fig)


def main() -> int:
    args = parse_args()
    source_dir = args.source_dir.resolve()
    output_dir = args.output_dir.resolve()

    if not source_dir.exists():
        print(f"Source directory does not exist: {source_dir}")
        return 1
    if not source_dir.is_dir():
        print(f"Source path is not a directory: {source_dir}")
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    records = collect_files(source_dir, include_hidden=args.include_hidden)

    csv_path = output_dir / "file_sizes.csv"
    chart_path = output_dir / "file_size_analysis.png"

    write_csv(records, csv_path)
    if records:
        make_chart(records, chart_path, top_n=max(1, args.top_n))

    print_summary(records, csv_path, chart_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
