"""LLM client for Gemini/Gemma API.

Design:
- Plain httpx (no big SDK).
- Models from LLM_PRIMARY_MODEL / LLM_FALLBACK_MODEL env vars.
- Key from GEMINI_API_KEY in x-goog-api-key header (never logged).
- LLM_FAKE=true returns deterministic fake output; no network call.
- Client is injectable for tests.
- Parses JSON from the last complete JSON object in Gemma response text
  (Gemma 4 may emit reasoning/thinking tokens before the JSON).
- Thinking set to its lowest budget (0 tokens budget) via thinkingConfig.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Protocol, runtime_checkable

import httpx

from app.contracts import ErrorCode, PipelineError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fake / deterministic output for tests
# ---------------------------------------------------------------------------

_FAKE_RESPONSE: dict[str, Any] = {
    "invoice_number": {"value": "FAKE-001", "evidence": "Invoice No: FAKE-001", "page": 1},
    "invoice_date": {"value": "2026-01-01", "evidence": "Date: 2026-01-01", "page": 1},
    "supplier_name": {"value": "Fake Supplier Ltd", "evidence": "Fake Supplier Ltd", "page": 1},
    "customer_name": {"value": None, "evidence": None, "page": None},
    "subtotal": {"value": None, "evidence": None, "page": None},
    "tax": {"value": None, "evidence": None, "page": None},
    "total": {"value": "100.00", "evidence": "Total: 100.00", "page": 1},
    "currency": {"value": None, "evidence": None, "page": None},
    "line_items": [],
}


# ---------------------------------------------------------------------------
# Protocol for injectable client
# ---------------------------------------------------------------------------

@runtime_checkable
class LLMClient(Protocol):
    def complete(self, model: str, prompt: str) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# JSON extraction from Gemma response text
# ---------------------------------------------------------------------------

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def extract_json_from_text(text: str) -> dict[str, Any]:
    """Parse JSON from Gemma response text.

    Gemma 4 may prefix its answer with chain-of-thought/reasoning tokens.
    We strip code fences, then find the *last* complete JSON object.
    """
    # Try code-fence blocks first (last one wins)
    blocks = _JSON_BLOCK_RE.findall(text)
    candidates = list(blocks) + [text]

    last_json: dict[str, Any] | None = None
    for candidate in candidates:
        # Find all {...} blocks in the candidate, take last
        depth = 0
        start = -1
        for i, ch in enumerate(candidate):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start != -1:
                    chunk = candidate[start: i + 1]
                    try:
                        obj = json.loads(chunk)
                        if isinstance(obj, dict):
                            last_json = obj
                    except json.JSONDecodeError:
                        pass

    if last_json is not None:
        return last_json
    raise PipelineError(ErrorCode.LLM_INVALID_OUTPUT, "No valid JSON object found in LLM response")


# ---------------------------------------------------------------------------
# Real HTTP client
# ---------------------------------------------------------------------------

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiHTTPClient:
    """Thin httpx wrapper for the Gemini generateContent REST endpoint."""

    def __init__(self, api_key: str, timeout: float = 60.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    def complete(self, model: str, prompt: str) -> dict[str, Any]:
        url = _BASE_URL.format(model=model)
        headers = {"x-goog-api-key": self._api_key, "Content-Type": "application/json"}
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            # Keep thinking at lowest budget (Gemma 4)
            "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
        }
        try:
            resp = httpx.post(url, headers=headers, json=payload, timeout=self._timeout)
        except httpx.TimeoutException as exc:
            raise PipelineError(ErrorCode.LLM_UNAVAILABLE, f"Request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise PipelineError(ErrorCode.LLM_UNAVAILABLE, f"Network error: {exc}") from exc

        if resp.status_code == 429:
            raise PipelineError(ErrorCode.LLM_RATE_LIMITED, "HTTP 429 from LLM API")
        if resp.status_code >= 500:
            raise PipelineError(ErrorCode.LLM_UNAVAILABLE, f"HTTP {resp.status_code} from LLM API")
        if not resp.is_success:
            raise PipelineError(ErrorCode.LLM_UNAVAILABLE, f"HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise PipelineError(ErrorCode.LLM_INVALID_OUTPUT, f"Unexpected LLM response shape: {exc}") from exc

        return extract_json_from_text(text)


# ---------------------------------------------------------------------------
# Fake client
# ---------------------------------------------------------------------------

class FakeLLMClient:
    """Deterministic fake for testing — no network, no quota."""

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self._response = response or _FAKE_RESPONSE

    def complete(self, model: str, prompt: str) -> dict[str, Any]:  # noqa: ARG002
        return dict(self._response)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_llm_client() -> LLMClient:
    """Return FakeLLMClient if LLM_FAKE=true, else GeminiHTTPClient."""
    if os.getenv("LLM_FAKE", "").lower() in ("1", "true", "yes"):
        return FakeLLMClient()
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise PipelineError(ErrorCode.LLM_UNAVAILABLE, "GEMINI_API_KEY not set")
    return GeminiHTTPClient(api_key=api_key)
