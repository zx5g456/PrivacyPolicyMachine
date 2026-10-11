#!/usr/bin/env python3
"""Score saved RQ3 responses without making any model calls."""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from rq3.prompts import ALL_FIELDS, CONFIGS, LIST_FIELDS, STATUS_FIELDS
from server.processor import METADATA_OPTIONS


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).with_name("policies.csv")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def canonical_runs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the last attempt per experiment job, retaining failures in the journal."""
    latest: dict[tuple[str, str, int], dict[str, Any]] = {}
    attempts: set[tuple[str, str, int, int]] = set()
    for row in rows:
        key = (row["policy_id"], row["config"], row["repeat"])
        attempt = int(row.get("attempt", 1))
        if attempt < 1 or key + (attempt,) in attempts:
            raise ValueError(f"Duplicate or invalid attempt number: {key}, attempt {attempt}")
        attempts.add(key + (attempt,))
        prior = latest.get(key)
        if prior is not None:
            if prior["status"] in {"ok", "invalid_output"}:
                raise ValueError(f"Attempt logged after a terminal result: {key}")
            if attempt != int(prior.get("attempt", 1)) + 1:
                raise ValueError(f"Nonconsecutive attempt number: {key}, attempt {attempt}")
        latest[key] = row
    return list(latest.values())


def load_sources() -> dict[str, str]:
    with MANIFEST.open(newline="", encoding="utf-8") as file:
        return {r["policy_id"]: (ROOT / r["source_path"]).read_text(encoding="utf-8-sig")
                for r in csv.DictReader(file)}


def valid_fields(response: Any) -> bool:
    if not isinstance(response, dict) or set(response) != {"fields"}:
        return False
    fields = response["fields"]
    if not isinstance(fields, dict) or set(fields) != set(ALL_FIELDS):
        return False
    for name in LIST_FIELDS:
        item = fields[name]
        if not isinstance(item, dict) or set(item) != {"value", "evidence"}:
            return False
        values, evidence = item["value"], item["evidence"]
        if not isinstance(values, list) or not all(isinstance(v, str) and v in METADATA_OPTIONS[name] for v in values):
            return False
        if len(set(values)) != len(values) or not isinstance(evidence, dict):
            return False
        if not all(k in values and isinstance(v, list) and all(isinstance(q, str) for q in v)
                   for k, v in evidence.items()):
            return False
    for name in STATUS_FIELDS:
        item = fields[name]
        if not isinstance(item, dict) or set(item) != {"value", "evidence"}:
            return False
        if not isinstance(item["value"], str) or item["value"] not in {"yes", "no", "unclear"}:
            return False
        if not isinstance(item["evidence"], list) or not all(isinstance(q, str) for q in item["evidence"]):
            return False
    return True


def claims(fields: dict[str, Any]) -> set[tuple[str, str]]:
    facts = set()
    for name in LIST_FIELDS:
        facts.update((name, value) for value in fields[name]["value"])
    for name in STATUS_FIELDS:
        if fields[name]["value"] != "unclear":
            facts.add((name, fields[name]["value"]))
    return facts


def gold_claims(fields: dict[str, Any]) -> set[tuple[str, str]]:
    facts = set()
    for name in LIST_FIELDS:
        facts.update((name, value) for value in fields[name])
    for name in STATUS_FIELDS:
        if fields[name] != "unclear":
            facts.add((name, fields[name]))
    return facts


def quote_stats(fields: dict[str, Any], source: str) -> tuple[int, int, int]:
    """Return asserted values, values with a quote, values with an exact source quote.

    Exact occurrence is a mechanical check, not proof of semantic support.
    """
    assertions = has_quote = exact = 0
    for name, value in claims(fields):
        assertions += 1
        item = fields[name]
        quotes = item["evidence"].get(value, []) if name in LIST_FIELDS else item["evidence"]
        if quotes:
            has_quote += 1
        if any(q.strip() and q in source for q in quotes):
            exact += 1
    return assertions, has_quote, exact


def safe_ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def score_run(row: dict[str, Any], source: str, gold: dict[str, Any] | None) -> dict[str, Any]:
    fields = row.get("final_response")
    valid = valid_fields(fields)
    result = {
        "policy_id": row["policy_id"], "config": row["config"], "repeat": row["repeat"],
        "run_status": row["status"],
        "elapsed_seconds": row["elapsed_seconds"], "model_calls": len(row["calls"]),
        "parse_valid": row["final_response"] is not None, "schema_valid": valid,
        "assertions": 0, "with_quote": 0, "exact_quote": 0,
        "abstentions": 0, "status_fields": len(STATUS_FIELDS),
        "tp": None, "fp": None, "fn": None,
    }
    if not valid:
        result["status_fields"] = 0
        if gold is not None:
            result.update(tp=0, fp=0, fn=len(gold_claims(gold)))
        return result
    values = fields["fields"]
    a, q, e = quote_stats(values, source)
    result.update(assertions=a, with_quote=q, exact_quote=e)
    result["abstentions"] = sum(values[name]["value"] == "unclear" for name in STATUS_FIELDS)
    if gold is not None:
        predicted, reference = claims(values), gold_claims(gold)
        result.update(tp=len(predicted & reference), fp=len(predicted - reference),
                      fn=len(reference - predicted))
    return result


def validate_gold(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    gold = {}
    for row in rows:
        policy_id, fields = row["policy_id"], row["fields"]
        if policy_id in gold or set(fields) != set(ALL_FIELDS):
            raise ValueError(f"Duplicate policy or wrong gold fields: {policy_id}")
        for name in LIST_FIELDS:
            if not isinstance(fields[name], list) or any(v not in METADATA_OPTIONS[name] for v in fields[name]):
                raise ValueError(f"Invalid gold list value: {policy_id} {name}")
        for name in STATUS_FIELDS:
            if not isinstance(fields[name], str) or fields[name] not in {"yes", "no", "unclear"}:
                raise ValueError(f"Invalid gold status: {policy_id} {name}")
        for prefix in ("condition", "negation"):
            tagged = row.get(f"{prefix}_fields", [])
            if (not isinstance(tagged, list) or not all(isinstance(name, str) for name in tagged)
                    or len(set(tagged)) != len(tagged)
                    or any(name not in ALL_FIELDS for name in tagged)):
                raise ValueError(f"Invalid {prefix} field tags: {policy_id}")
        gold[policy_id] = row
    return gold


def validate_reviews(rows: list[dict[str, Any]]) -> dict[tuple[str, str, int], list[dict[str, Any]]]:
    reviews: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    seen = set()
    for row in rows:
        key = (row["policy_id"], row["config"], row["repeat"])
        claim = (row["field"], row["value"])
        if key + claim in seen:
            raise ValueError(f"Duplicate review claim: {key + claim}")
        seen.add(key + claim)
        for name in ("evidence_valid", "assertion_supported"):
            if not isinstance(row.get(name), bool):
                raise ValueError(f"Review requires boolean {name}: {key + claim}")
        reviews[key].append(row)
    return reviews


def apply_reviews(scored: list[dict[str, Any]], runs: list[dict[str, Any]],
                  reviews: dict[tuple[str, str, int], list[dict[str, Any]]],
                  sources: dict[str, str]) -> None:
    for score, run in zip(scored, runs):
        key = (score["policy_id"], score["config"], score["repeat"])
        actual = claims(run["final_response"]["fields"]) if score["schema_valid"] else set()
        reviewed = {(r["field"], r["value"]) for r in reviews.get(key, [])}
        if reviewed != actual:
            raise ValueError(f"Manual review does not cover every assertion for {key}: "
                             f"missing={actual - reviewed}, extra={reviewed - actual}")
        entries = reviews.get(key, [])
        for entry in entries:
            item = run["final_response"]["fields"][entry["field"]]
            quotes = (item["evidence"].get(entry["value"], [])
                      if entry["field"] in LIST_FIELDS else item["evidence"])
            if "evidence" in entry and entry["evidence"] != quotes:
                raise ValueError(f"Manual review quotations differ from saved output: {key}")
            if entry["evidence_valid"] and not any(q.strip() and q in sources[score["policy_id"]] for q in quotes):
                raise ValueError(f"Semantic evidence marked valid without an exact source quote: {key}")
        score["semantically_valid_evidence"] = sum(r["evidence_valid"] for r in entries)
        score["supported_assertions"] = sum(r["assertion_supported"] for r in entries)


def apply_tagged_cases(scored: list[dict[str, Any]], runs: list[dict[str, Any]],
                       gold: dict[str, dict[str, Any]]) -> None:
    for score, run in zip(scored, runs):
        reference = gold.get(score["policy_id"])
        if reference is None:
            continue
        predicted = run["final_response"]["fields"] if score["schema_valid"] else None
        for prefix in ("condition", "negation"):
            tagged = reference.get(f"{prefix}_fields", [])
            score[f"{prefix}_cases"] = len(tagged)
            correct = 0
            for field in tagged:
                if predicted is None:
                    continue
                value = predicted[field]["value"]
                target = reference["fields"][field]
                matches = set(value) == set(target) if field in LIST_FIELDS else value == target
                if matches:
                    correct += 1
            score[f"{prefix}_correct_count"] = correct


def write_review_template(runs: list[dict[str, Any]], out: Path) -> None:
    path = out / "manual_review_template.jsonl"
    lines = []
    for run in runs:
        if not valid_fields(run.get("final_response")):
            continue
        for field, value in sorted(claims(run["final_response"]["fields"])):
            item = run["final_response"]["fields"][field]
            evidence = item["evidence"].get(value, []) if field in LIST_FIELDS else item["evidence"]
            row = {
                "policy_id": run["policy_id"], "config": run["config"],
                "repeat": run["repeat"], "field": field, "value": value,
                "evidence": evidence,
                "evidence_valid": None, "assertion_supported": None,
            }
            lines.append(json.dumps(row, ensure_ascii=False) + "\n")
    write_template(path, "".join(lines))


def write_template(path: Path, content: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") == content:
            return
        alternative = path.with_name(f"{path.stem}.new-{time.time_ns()}{path.suffix}")
        alternative.write_text(content, encoding="utf-8")
        print(f"Preserved {path}; wrote updated template to {alternative}")
    else:
        path.write_text(content, encoding="utf-8")


def write_gold_template(out: Path) -> None:
    path = out / "annotation_template.jsonl"
    lines = []
    with MANIFEST.open(newline="", encoding="utf-8") as file:
        for policy in csv.DictReader(file):
            row = {
                "policy_id": policy["policy_id"],
                "fields": {name: None for name in ALL_FIELDS},
                "condition_fields": [], "negation_fields": [],
            }
            lines.append(json.dumps(row, ensure_ascii=False) + "\n")
    write_template(path, "".join(lines))


def aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_config = defaultdict(list)
    for row in rows:
        by_config[row["config"]].append(row)
    output = []
    for config in CONFIGS:
        group = by_config.get(config, [])
        if not group:
            continue
        total = lambda key: sum(r[key] for r in group if r[key] is not None)
        tp, fp, fn = total("tp"), total("fp"), total("fn")
        has_gold = any(r["tp"] is not None for r in group)
        precision = safe_ratio(tp, tp + fp) if has_gold else None
        recall = safe_ratio(tp, tp + fn) if has_gold else None
        f1 = round(2 * precision * recall / (precision + recall), 4) if precision is not None and recall is not None and precision + recall else None
        reviewed = any("supported_assertions" in r for r in group)
        tagged = any("condition_cases" in r for r in group)
        output.append({
            "config": config, "runs": len(group),
            "precision": precision, "recall": recall, "f1": f1,
            "schema_validity": safe_ratio(total("schema_valid"), len(group)),
            "transport_failure_rate": safe_ratio(sum(r["run_status"] == "failed" for r in group), len(group)),
            "quote_presence_rate": safe_ratio(total("with_quote"), total("assertions")),
            "exact_quote_rate": safe_ratio(total("exact_quote"), total("assertions")),
            "abstention_rate_valid_outputs": safe_ratio(total("abstentions"), total("status_fields")),
            "total_elapsed_seconds": round(total("elapsed_seconds"), 3),
            "mean_elapsed_seconds": round(total("elapsed_seconds") / len(group), 3),
            "total_model_calls": total("model_calls"),
            "unsupported_assertion_rate": safe_ratio(total("assertions") - total("supported_assertions"), total("assertions")) if reviewed else None,
            "semantic_evidence_validity": safe_ratio(total("semantically_valid_evidence"), total("assertions")) if reviewed else None,
            "condition_tagged_field_accuracy": safe_ratio(total("condition_correct_count"), total("condition_cases")) if tagged else None,
            "negation_tagged_field_accuracy": safe_ratio(total("negation_correct_count"), total("negation_cases")) if tagged else None,
        })
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, help="runs.jsonl from rq3.run")
    parser.add_argument("--gold", type=Path, help="Adjudicated human annotation JSONL")
    parser.add_argument("--review", type=Path, help="Completed manual assertion review JSONL")
    parser.add_argument("--out-dir", type=Path, help="Defaults to the runs directory")
    parser.add_argument("--allow-partial", action="store_true", help="Permit incomplete runs with human gold for diagnostics")
    args = parser.parse_args()
    sources = load_sources()
    gold = validate_gold(read_jsonl(args.gold)) if args.gold else {}
    if gold and set(gold) != set(sources):
        raise ValueError("Adjudicated gold must contain all 15 manifest policies")
    journal = read_jsonl(args.runs)
    runs = canonical_runs(journal)
    keys = {(r["policy_id"], r["config"], r["repeat"]) for r in runs}
    if (gold or args.review) and not args.allow_partial:
        expected = {(policy_id, config, repeat) for policy_id in sources
                    for config in CONFIGS for repeat in range(1, 4)}
        if keys != expected:
            raise ValueError(f"Official RQ3 scoring needs all {len(expected)} jobs; "
                             f"found {len(keys)}. Use --allow-partial for diagnostics.")
        failures = [row for row in runs if row["status"] == "failed"]
        if failures:
            raise ValueError(f"{len(failures)} transport failures remain; resume the run before official scoring")
    scored = [score_run(row, sources[row["policy_id"]],
                        gold[row["policy_id"]]["fields"] if row["policy_id"] in gold else None)
              for row in runs]
    if gold:
        apply_tagged_cases(scored, runs, gold)
    if args.review:
        apply_reviews(scored, runs, validate_reviews(read_jsonl(args.review)), sources)
    summary = aggregate(scored)
    out = args.out_dir or args.runs.parent
    out.mkdir(parents=True, exist_ok=True)
    if not args.review:
        write_review_template(runs, out)
    if not args.gold:
        write_gold_template(out)
    with (out / "scores_by_run.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(scored[0]) if scored else [])
        if scored:
            writer.writeheader()
            writer.writerows(scored)
    with (out / "summary.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(summary[0]) if summary else [])
        if summary:
            writer.writeheader()
            writer.writerows(summary)
    print(f"Scored {len(scored)} runs; saved {out / 'summary.csv'}")
    if not gold:
        print("No human gold supplied: precision, recall, F1, and semantic review metrics remain blank.")


if __name__ == "__main__":
    main()
