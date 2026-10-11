#!/usr/bin/env python3
"""Run the frozen RQ3 prompt comparison; preserve raw responses and timings."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import sys
import time
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

if os.name == "nt":
    import msvcrt
else:
    import fcntl

# Also support `python rq3/run.py` from a checkout without PYTHONPATH.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.llm_processor import chunk_policy
from rq3.prompts import CONFIGS, extraction_prompt, merge_prompt


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).with_name("policies.csv")
LOCAL_TIME = ZoneInfo("Australia/Brisbane")


def now() -> str:
    return datetime.now(LOCAL_TIME).isoformat(timespec="seconds")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    """Replace a checkpoint only after its new contents reach disk."""
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


@contextmanager
def exclusive_run_lock(path: Path) -> Iterator[None]:
    """Keep one runner per output directory on Windows and Unix."""
    with path.open("a+b") as lock:
        if os.name == "nt":
            # msvcrt locks a byte at the current file position. Keep byte 0
            # available even when this is a newly created lock file.
            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
        try:
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(f"Another runner is already using {path.parent}") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def read_journal(path: Path) -> list[dict[str, Any]]:
    """Read complete rows; preserve and remove only a torn final JSONL row."""
    if not path.exists():
        return []
    rows = []
    with path.open("rb+") as file:
        while True:
            start = file.tell()
            raw = file.readline()
            if not raw:
                break
            try:
                row = json.loads(raw)
                if not isinstance(row, dict):
                    raise ValueError("result row is not an object")
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                if raw.endswith(b"\n") or file.read(1):
                    raise ValueError(f"Corrupt results journal at byte {start}") from exc
                backup = path.with_name(path.name + f".incomplete-{time.time_ns()}.bin")
                backup.write_bytes(raw)
                file.truncate(start)
                file.flush()
                os.fsync(file.fileno())
                print(f"Preserved torn final row in {backup}; rerunning that job", flush=True)
                break
            rows.append(row)
            if not raw.endswith(b"\n"):
                file.write(b"\n")
                file.flush()
                os.fsync(file.fileno())
    return rows


def load_policies() -> list[dict[str, Any]]:
    with MANIFEST.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    if len(rows) != 15 or len({r["policy_id"] for r in rows}) != 15:
        raise ValueError("RQ3 manifest must contain 15 unique policy IDs")
    for row in rows:
        path = ROOT / row["source_path"]
        if not path.resolve().is_relative_to((ROOT / "sources" / "dataset").resolve()):
            raise ValueError(f"Source path escapes the policy dataset: {path}")
        raw = path.read_bytes()
        if sha256(raw) != row["sha256"]:
            raise ValueError(f"Policy source changed since selection: {path}")
        row["text"] = raw.decode("utf-8-sig")
    return rows


def model_identity(args: argparse.Namespace) -> dict[str, Any]:
    """Pin the local Ollama model digest across interrupted sessions."""
    if args.backend != "ollama":
        return {"name": args.model, "digest": None}
    parts = urlsplit(args.ollama_url)
    if not parts.path.endswith("/api/chat"):
        raise ValueError("Ollama URL must end in /api/chat for model verification")
    tags_url = urlunsplit((parts.scheme, parts.netloc,
                           parts.path[:-len("/api/chat")] + "/api/tags", "", ""))
    with urllib.request.urlopen(tags_url, timeout=min(args.timeout, 15)) as response:
        body = json.load(response)
    for item in body.get("models", []):
        if item.get("name") == args.model or item.get("model") == args.model:
            digest = item.get("digest")
            if not isinstance(digest, str) or not digest:
                raise ValueError(f"Ollama did not provide a digest for {args.model}")
            return {"name": args.model, "digest": digest}
    raise ValueError(f"Ollama model {args.model!r} is not installed")


def request_model(
    *, backend: str, model: str, prompt: str, temperature: float,
    timeout: float, ollama_url: str,
) -> tuple[str, dict[str, Any]]:
    if backend == "ollama":
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "format": "json",  # Identical JSON mode across all five arms.
            "stream": False,
            "think": False,
            "options": {"temperature": temperature, "num_ctx": 8192, "num_predict": 4096},
        }
        req = urllib.request.Request(
            ollama_url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = json.load(response)
        return body["message"]["content"], {
            key: body.get(key) for key in ("prompt_eval_count", "eval_count", "total_duration")
            if key in body
        }
    if backend == "openai":
        from openai import OpenAI

        response = OpenAI(timeout=timeout).chat.completions.create(
            model=model,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or "", (
            response.usage.model_dump() if response.usage else {}
        )
    raise ValueError(f"Unsupported backend: {backend}")


def model_call(args: argparse.Namespace, prompt: str, stage: str, index: int | None) -> dict[str, Any]:
    started = now()
    tick = time.perf_counter()
    record: dict[str, Any] = {
        "stage": stage, "chunk_index": index, "started_at": started,
        "prompt_sha256": sha256(prompt.encode("utf-8")), "prompt": prompt,
    }
    try:
        raw, usage = request_model(
            backend=args.backend, model=args.model, prompt=prompt,
            temperature=args.temperature, timeout=args.timeout,
            ollama_url=args.ollama_url,
        )
        record["raw_response"] = raw
        record["usage"] = usage
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("JSON root is not an object")
            record["parsed_response"] = parsed
            record["parse_valid"] = True
        except (json.JSONDecodeError, ValueError) as exc:
            record["parsed_response"] = None
            record["parse_valid"] = False
            record["error_kind"] = "invalid_output"
            record["error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        record["raw_response"] = None
        record["parsed_response"] = None
        record["parse_valid"] = False
        record["error_kind"] = "transport"
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["ended_at"] = now()
    record["elapsed_seconds"] = round(time.perf_counter() - tick, 4)
    return record


def run_job(
    args: argparse.Namespace, policy: dict[str, Any], config: str, repeat: int,
    *, previous: dict[str, Any] | None = None,
    checkpoint: Any = None,
) -> dict[str, Any]:
    chunks = chunk_policy(policy["text"], max_chars=args.chunk_chars, overlap_chars=args.overlap_chars)
    tick = time.perf_counter()
    chunk_records = [{"index": c.index, "start": c.start, "end": c.end,
                      "sha256": sha256(c.text.encode("utf-8"))} for c in chunks]
    if previous is None:
        result: dict[str, Any] = {
            "policy_id": policy["policy_id"], "source_path": policy["source_path"],
            "policy_sha256": policy["sha256"], "config": config, "repeat": repeat,
            "model": args.model, "backend": args.backend, "started_at": now(),
            "chunk_count": len(chunks), "chunks": chunk_records, "calls": [],
        }
    else:
        result = previous
        if (result["policy_id"], result["config"], result["repeat"]) != (policy["policy_id"], config, repeat):
            raise ValueError("Pending checkpoint is for a different job")
        if result["policy_sha256"] != policy["sha256"] or result["chunks"] != chunk_records:
            raise ValueError("Pending checkpoint has different policy content or chunk boundaries")
        if result["model"] != args.model or result["backend"] != args.backend:
            raise ValueError("Pending checkpoint has different model settings")
    elapsed_before = float(result.get("elapsed_seconds", 0))
    saved_calls = list(result["calls"])
    cursor = 0

    def get_call(prompt: str, stage: str, index: int | None) -> dict[str, Any]:
        nonlocal cursor
        expected_hash = sha256(prompt.encode("utf-8"))
        if cursor < len(saved_calls):
            call = saved_calls[cursor]
            if (call["stage"], call["chunk_index"], call["prompt_sha256"]) != (stage, index, expected_hash):
                raise ValueError("Pending checkpoint prompt or call order differs from current code")
            if call.get("error_kind") == "transport":
                if cursor != len(saved_calls) - 1:
                    raise ValueError("Pending checkpoint has calls after a transport failure")
                saved_calls.pop()
                result["calls"].pop()
                call = model_call(args, prompt, stage, index)
                result["calls"].append(call)
                result["elapsed_seconds"] = round(elapsed_before + time.perf_counter() - tick, 4)
                if checkpoint is not None:
                    checkpoint(result)
        else:
            call = model_call(args, prompt, stage, index)
            result["calls"].append(call)
            result["elapsed_seconds"] = round(elapsed_before + time.perf_counter() - tick, 4)
            if checkpoint is not None:
                checkpoint(result)
        cursor += 1
        return call

    parsed_chunks: list[dict[str, Any]] = []
    for chunk in chunks:
        call = get_call(extraction_prompt(config, chunk.text, chunk.index, len(chunks)),
                        "extraction", chunk.index)
        if not call["parse_valid"]:
            break
        parsed_chunks.append({
            "chunk_index": chunk.index, "source_chunk": chunk.text,
            "fields": call["parsed_response"].get("fields"),
        })
    if len(parsed_chunks) == len(chunks):
        if len(chunks) == 1:
            result["final_response"] = result["calls"][0]["parsed_response"]
        else:
            call = get_call(merge_prompt(config, parsed_chunks), "merge", None)
            result["final_response"] = call["parsed_response"] if call["parse_valid"] else None
    else:
        result["final_response"] = None
    if result["final_response"] is not None:
        result["status"] = "ok"
    elif any(call.get("error_kind") == "invalid_output" for call in result["calls"]):
        result["status"] = "invalid_output"
    else:
        result["status"] = "failed"
    result["ended_at"] = now()
    result["elapsed_seconds"] = round(elapsed_before + time.perf_counter() - tick, 4)
    return result


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("ollama", "openai"), default="ollama")
    parser.add_argument("--model", default="qwen3.5:9b")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=7841, help="Fixed random order of jobs")
    parser.add_argument("--chunk-chars", type=int, default=3000)
    parser.add_argument("--overlap-chars", type=int, default=200)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434/api/chat")
    parser.add_argument("--configs", nargs="+", choices=CONFIGS, default=CONFIGS)
    parser.add_argument("--policy-ids", nargs="+", help="Optional policy subset for a smoke run")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "rq3" / "results" / datetime.now(LOCAL_TIME).strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--dry-run", action="store_true", help="Show plan without calling the model")
    parser.add_argument("--resume", action="store_true", help="Continue an interrupted output directory")
    args = parser.parse_args()
    if args.repeats < 1 or args.chunk_chars < 500 or not 0 <= args.overlap_chars < args.chunk_chars:
        parser.error("repeats, chunk-chars, or overlap-chars are invalid")
    if len(set(args.configs)) != len(args.configs):
        parser.error("--configs must not contain duplicates")
    return args


def main() -> None:
    args = arguments()
    if len(set(args.configs)) != len(args.configs):
        raise ValueError("Configuration list contains duplicates")
    policies = load_policies()
    if args.policy_ids:
        wanted = set(args.policy_ids)
        policies = [p for p in policies if p["policy_id"] in wanted]
        if {p["policy_id"] for p in policies} != wanted:
            raise ValueError("Unknown policy ID in --policy-ids")
    jobs = [(p, config, repeat) for p in policies for config in args.configs
            for repeat in range(1, args.repeats + 1)]
    random.Random(args.seed).shuffle(jobs)
    calls = sum((len(chunk_policy(p["text"], max_chars=args.chunk_chars,
                                  overlap_chars=args.overlap_chars)) * 1 +
                 (len(chunk_policy(p["text"], max_chars=args.chunk_chars,
                                   overlap_chars=args.overlap_chars)) > 1))
                for p, _, _ in jobs)
    print(f"Plan: {len(policies)} policies, {len(jobs)} jobs, "
          f"up to {calls} model calls before retries", flush=True)
    if args.dry_run:
        return

    out = args.out_dir.resolve()
    if args.resume and not (out / "run_metadata.json").is_file():
        raise FileNotFoundError("--resume requires an existing run_metadata.json in --out-dir")
    if not args.resume and out.exists() and any(
        p.name not in {"run.lock", "run_metadata.json.tmp"} for p in out.iterdir()
    ):
        raise FileExistsError("Output directory is not empty; use --resume or a new --out-dir")
    out.mkdir(parents=True, exist_ok=True)
    with exclusive_run_lock(out / "run.lock"):
        metadata_path = out / "run_metadata.json"
        results_path = out / "runs.jsonl"
        pending_path = out / "pending_job.json"
        if not args.resume and metadata_path.exists():
            raise FileExistsError("Run metadata was created by another process")
        metadata = {
            "created_at": now(), "backend": args.backend, "model": args.model,
            "model_identity": model_identity(args),
            "temperature": args.temperature, "repeats": args.repeats,
            "seed": args.seed, "timeout": args.timeout,
            "ollama_url": args.ollama_url if args.backend == "ollama" else None,
            "chunk_chars": args.chunk_chars, "overlap_chars": args.overlap_chars,
            "policy_ids": [p["policy_id"] for p in policies], "configs": list(args.configs),
            "manifest_sha256": sha256(MANIFEST.read_bytes()),
            "prompts_sha256": sha256(Path(__file__).with_name("prompts.py").read_bytes()),
            "runner_sha256": sha256(Path(__file__).read_bytes()),
            "chunker_sha256": sha256((ROOT / "server" / "llm_processor.py").read_bytes()),
            "fields_sha256": sha256((ROOT / "server" / "processor.py").read_bytes()),
        }
        if args.resume:
            old = json.loads(metadata_path.read_text(encoding="utf-8"))
            if {k: v for k, v in old.items() if k != "created_at"} != {k: v for k, v in metadata.items() if k != "created_at"}:
                raise ValueError("Resume settings or experiment code differ from saved run metadata")
        else:
            atomic_json(metadata_path, metadata)

        prior_rows = read_journal(results_path)
        job_map = {(p["policy_id"], c, r): (p, c, r) for p, c, r in jobs}
        succeeded: set[tuple[str, str, int]] = set()
        attempts: dict[tuple[str, str, int], int] = {}
        for row in prior_rows:
            key = (row["policy_id"], row["config"], row["repeat"])
            if key not in job_map:
                raise ValueError(f"Results journal contains an unexpected job: {key}")
            attempts[key] = max(attempts.get(key, 0), int(row.get("attempt", 1)))
            if row["status"] in {"ok", "invalid_output"}:
                succeeded.add(key)

        pending = json.loads(pending_path.read_text(encoding="utf-8")) if pending_path.exists() else None
        if pending is not None:
            pending_key = (pending["policy_id"], pending["config"], pending["repeat"])
            if pending_key not in job_map:
                raise ValueError(f"Pending checkpoint contains an unexpected job: {pending_key}")
            if pending_key in succeeded:
                pending_path.unlink()  # The complete result was already committed.
                pending = None
            else:
                jobs = [job_map[pending_key]] + [job for job in jobs
                         if (job[0]["policy_id"], job[1], job[2]) != pending_key]
        remaining = len(jobs) - len(succeeded)
        print(f"Resume state: {len(succeeded)} completed, {remaining} pending; "
              f"{sum(key not in succeeded for key in attempts)} failed attempts to retry", flush=True)
        started = time.perf_counter()
        completed_now = 0
        with results_path.open("a", encoding="utf-8") as file:
            for number, (policy, config, repeat) in enumerate(jobs, 1):
                key = (policy["policy_id"], config, repeat)
                if key in succeeded:
                    continue
                previous = pending if pending is not None and key == pending_key else None
                attempt = previous.get("attempt", attempts.get(key, 0) + 1) if previous else attempts.get(key, 0) + 1

                def save_checkpoint(value: dict[str, Any]) -> None:
                    value["attempt"] = attempt
                    atomic_json(pending_path, value)

                row = run_job(args, policy, config, repeat,
                              previous=previous, checkpoint=save_checkpoint)
                row["attempt"] = attempt
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
                file.flush()
                os.fsync(file.fileno())
                pending_path.unlink(missing_ok=True)
                pending = None
                completed_now += 1
                elapsed = time.perf_counter() - started
                eta = elapsed / completed_now * (remaining - completed_now)
                print(f"{number}/{len(jobs)} {policy['policy_id']} {config} run {repeat}: "
                      f"{row['status']} in {row['elapsed_seconds']:.1f}s; "
                      f"session {elapsed:.1f}s; ETA {eta:.1f}s", flush=True)
                if row["status"] == "failed":
                    raise RuntimeError(
                        f"Model call failed for {key}; result saved. Fix the connection "
                        f"and resume with --out-dir {out} --resume"
                    )
        print(f"Saved: {results_path}")


if __name__ == "__main__":
    main()
