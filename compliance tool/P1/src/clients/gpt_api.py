"""OpenAI API client used by the P1 analyzers."""

from __future__ import annotations

import time

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError

from config import BASE_DELAY, GPT_MAX_TOKENS, GPT_MODEL, GPT_TEMPERATURE, MAX_RETRIES


RETRYABLE_ERRORS = (RateLimitError, APITimeoutError, APIConnectionError)


def get_gpt_response(
    prompt_message: str,
    filename: str,
    model: str = GPT_MODEL,
) -> str:
    """Send one P1 prompt through the same public OpenAI API used by P2/P3."""
    client = OpenAI()

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=GPT_TEMPERATURE,
                max_tokens=GPT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt_message}],
            )
            content = response.choices[0].message.content
            if not content or not content.strip():
                raise RuntimeError(f"GPT returned an empty response for {filename}")
            return content.strip()
        except RETRYABLE_ERRORS:
            if attempt == MAX_RETRIES - 1:
                raise
            retry_delay = min(BASE_DELAY * (2**attempt), 60)
            print(
                f"  Retrying GPT request {attempt + 2}/{MAX_RETRIES} for "
                f"{filename} in {retry_delay}s..."
            )
            time.sleep(retry_delay)

    raise RuntimeError(f"GPT request failed for {filename}")
