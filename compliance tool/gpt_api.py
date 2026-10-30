"""Shared OpenAI client configuration for the compliance tools."""

from __future__ import annotations

import os


def load_gpt_api_key() -> str:
    """Read the API key injected by the Base Mainnet launcher."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is required for compliance analysis")
    return key
