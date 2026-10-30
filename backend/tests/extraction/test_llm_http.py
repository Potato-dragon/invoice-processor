"""GeminiHTTPClient request shape, retries and response parsing (no network)."""
import os
from unittest.mock import patch

import httpx
import pytest

from app.contracts import ErrorCode, PipelineError
from app.extraction.llm import GeminiHTTPClient

URL = "https://example.test"


def _ok(parts):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": parts}}]}, request=httpx.Request("POST", URL))


def _status(code):
    return httpx.Response(code, json={"error": {}}, request=httpx.Request("POST", URL))


@pytest.fixture(autouse=True)
def no_sleep():
    with patch("app.extraction.llm.time.sleep"), patch.dict(os.environ, {"LLM_RETRIES": "3"}):
        yield


def test_payload_has_no_thinking_budget():
    with patch("httpx.post", return_value=_ok([{"text": '{"a": 1}'}])) as post:
        GeminiHTTPClient("k").complete("gemma-4-31b-it", "p")
    payload = post.call_args.kwargs["json"]
    assert "thinkingConfig" not in payload.get("generationConfig", {})
    assert post.call_args.kwargs["headers"]["x-goog-api-key"] == "k"


def test_retries_5xx_then_succeeds():
    with patch("httpx.post", side_effect=[_status(500), _status(503), _ok([{"text": '{"a": 1}'}])]) as post:
        assert GeminiHTTPClient("k").complete("m", "p") == {"a": 1}
    assert post.call_count == 3


def test_gives_up_after_retries():
    with patch("httpx.post", return_value=_status(500)):
        with pytest.raises(PipelineError) as exc:
            GeminiHTTPClient("k").complete("m", "p")
    assert exc.value.code == ErrorCode.LLM_UNAVAILABLE


def test_400_and_429_not_retried():
    for code, expected in ((400, ErrorCode.LLM_UNAVAILABLE), (429, ErrorCode.LLM_RATE_LIMITED)):
        with patch("httpx.post", return_value=_status(code)) as post:
            with pytest.raises(PipelineError) as exc:
                GeminiHTTPClient("k").complete("m", "p")
        assert exc.value.code == expected
        assert post.call_count == 1


def test_thought_parts_are_skipped():
    parts = [{"text": '{"draft": true}', "thought": True}, {"text": '{"final": true}'}]
    with patch("httpx.post", return_value=_ok(parts)):
        assert GeminiHTTPClient("k").complete("m", "p") == {"final": True}
