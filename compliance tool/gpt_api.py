"""Shared OpenAI client configuration for the compliance tools."""

from __future__ import annotations

import os
import shlex
from pathlib import Path

DEFAULT_GPT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "gpt.zshrc"


def _assignment_value(line: str, variable: str) -> str | None:
    candidate = line.strip()
    if candidate.startswith("export "):
        candidate = candidate[7:].strip()
    prefix = f"{variable}="
    if not candidate.startswith(prefix):
        return None
    parts = shlex.split(candidate[len(prefix):], comments=True, posix=True)
    return parts[0] if parts else ""


def load_gpt_api_key(config_path: str | Path | None = None) -> str:
    """Read a bare API key or OPENAI_API_KEY assignment without sourcing shell code."""
    path = Path(
        config_path
        or os.environ.get("GPT_CONFIG_PATH", "")
        or DEFAULT_GPT_CONFIG_PATH
    ).expanduser()
    try:
        lines = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    except OSError as exc:
        raise RuntimeError(f"Cannot read GPT configuration at {path}: {exc}") from exc

    for line in lines:
        value = _assignment_value(line, "OPENAI_API_KEY")
        if value:
            return value

    if len(lines) == 1 and "=" not in lines[0]:
        return lines[0]

    raise RuntimeError(
        f"GPT configuration at {path} must contain a bare key or OPENAI_API_KEY assignment"
    )
