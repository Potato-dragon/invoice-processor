"""The LLM limiter must be shared through Redis whenever REDIS_URL is set."""
import os
import uuid
from unittest.mock import patch

import pytest

from app.contracts import ErrorCode, PipelineError
from app.extraction import limiter as limiter_mod


def _redis_client():
    redis = pytest.importorskip("redis")
    url = os.getenv("REDIS_URL", "")
    if not url:
        pytest.skip("REDIS_URL not set")
    client = redis.from_url(url, socket_connect_timeout=1)
    try:
        client.ping()
    except Exception:
        pytest.skip("Redis not reachable")
    return client


def test_factory_uses_redis_when_url_set():
    _redis_client()
    limiter_mod._limiters.clear()
    try:
        assert isinstance(limiter_mod.get_rate_limiter("primary"), limiter_mod.RedisRateLimiter)
    finally:
        limiter_mod._limiters.clear()


def test_factory_uses_memory_without_redis_url():
    limiter_mod._limiters.clear()
    try:
        with patch.dict(os.environ, {"REDIS_URL": ""}):
            assert isinstance(limiter_mod.get_rate_limiter("primary"), limiter_mod.InMemoryRateLimiter)
    finally:
        limiter_mod._limiters.clear()


def test_two_limiters_share_one_quota():
    client = _redis_client()
    key = f"test_{uuid.uuid4().hex[:8]}"
    env = {f"LLM_{key.upper()}_RPM": "2", f"LLM_{key.upper()}_RPD": "100", f"LLM_{key.upper()}_TPM": "100000"}
    with patch.dict(os.environ, env):
        a = limiter_mod.RedisRateLimiter(client, key)
        b = limiter_mod.RedisRateLimiter(client, key)  # a second "worker"
    try:
        a.check_and_reserve(10, max_wait=0)
        b.check_and_reserve(10, max_wait=0)
        with pytest.raises(PipelineError) as exc:
            a.check_and_reserve(10, max_wait=0)
        assert exc.value.code == ErrorCode.LLM_RATE_LIMITED
    finally:
        client.delete(*(f"llm_rl:{key}:{w}" for w in ("rpm", "rpd", "tpm")))


def test_token_budget_is_exact_sum():
    client = _redis_client()
    key = f"test_{uuid.uuid4().hex[:8]}"
    env = {f"LLM_{key.upper()}_RPM": "100", f"LLM_{key.upper()}_RPD": "100", f"LLM_{key.upper()}_TPM": "1000"}
    with patch.dict(os.environ, env):
        lim = limiter_mod.RedisRateLimiter(client, key)
    try:
        lim.check_and_reserve(600, max_wait=0)
        lim.check_and_reserve(400, max_wait=0)  # exactly at the cap
        with pytest.raises(PipelineError):
            lim.check_and_reserve(1, max_wait=0)
    finally:
        client.delete(*(f"llm_rl:{key}:{w}" for w in ("rpm", "rpd", "tpm")))
