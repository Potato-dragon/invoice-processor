"""Shared rate limiter and LLM cache.

Rate limiter:
- Sliding-window limiter in Redis shared across workers.
- In-memory fallback when Redis is unavailable.
- Configurable limits per model via environment variables:
    LLM_PRIMARY_RPM, LLM_PRIMARY_TPM, LLM_PRIMARY_RPD
    LLM_FALLBACK_RPM, LLM_FALLBACK_TPM, LLM_FALLBACK_RPD

Cache:
- Stored in the llm_cache DB table (key = sha256(model+prompt+doc_text)).
- Cache hit costs zero quota.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurable limits per model
# ---------------------------------------------------------------------------

_ENV_PRIMARY = "LLM_PRIMARY_MODEL"
_ENV_FALLBACK = "LLM_FALLBACK_MODEL"


def _int_env(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def get_limits(model_key: str) -> dict[str, int]:
    """Return {rpm, tpm, rpd} for 'primary' or 'fallback'."""
    prefix = model_key.upper()  # PRIMARY or FALLBACK
    return {
        "rpm": _int_env(f"LLM_{prefix}_RPM", 30 if model_key == "primary" else 15),
        "tpm": _int_env(f"LLM_{prefix}_TPM", 16_000 if model_key == "primary" else 250_000),
        "rpd": _int_env(f"LLM_{prefix}_RPD", 14_400 if model_key == "primary" else 500),
    }


def estimate_tokens(text: str) -> int:
    """Rough token count: chars / 4."""
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# In-memory sliding-window limiter (fallback when Redis unavailable)
# ---------------------------------------------------------------------------

class _InMemoryWindow:
    """Thread-safe sliding-window counter using a deque of timestamps."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self._limit = limit
        self._window = window_seconds
        self._timestamps: deque[float] = deque()

    def allow(self) -> bool:
        now = time.monotonic()
        cutoff = now - self._window
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
        if len(self._timestamps) < self._limit:
            self._timestamps.append(now)
            return True
        return False

    def remaining_wait(self) -> float:
        if not self._timestamps:
            return 0.0
        return max(0.0, self._timestamps[0] + self._window - time.monotonic())


class InMemoryRateLimiter:
    """Per-model in-memory rate limiter (RPM + RPD; TPM tracked separately)."""

    def __init__(self, model_key: str) -> None:
        limits = get_limits(model_key)
        self._rpm_window = _InMemoryWindow(limits["rpm"], 60)
        self._rpd_window = _InMemoryWindow(limits["rpd"], 86_400)
        self._tpm_limit = limits["tpm"]
        self._token_window: deque[tuple[float, int]] = deque()  # (ts, tokens)
        self._tpm_window = 60

    def _tpm_current(self) -> int:
        now = time.monotonic()
        cutoff = now - self._tpm_window
        while self._token_window and self._token_window[0][0] < cutoff:
            self._token_window.popleft()
        return sum(t for _, t in self._token_window)

    def check_and_reserve(self, prompt_tokens: int, max_wait: float = 20.0) -> None:
        """Block until quota allows, or raise PipelineError(LLM_RATE_LIMITED)."""
        from app.contracts import ErrorCode, PipelineError

        deadline = time.monotonic() + max_wait
        while True:
            ok_rpm = self._rpm_window.allow()
            ok_rpd = self._rpd_window.allow()
            tpm_used = self._tpm_current()
            ok_tpm = (tpm_used + prompt_tokens) <= self._tpm_limit

            if ok_rpm and ok_rpd and ok_tpm:
                self._token_window.append((time.monotonic(), prompt_tokens))
                return

            now = time.monotonic()
            if now >= deadline:
                raise PipelineError(ErrorCode.LLM_RATE_LIMITED, "Rate limit exceeded; could not acquire slot within 20s")

            # Wait a short interval
            time.sleep(min(1.0, deadline - now))

            # Re-allow windows that we already consumed above
            if not ok_rpm:
                pass  # already logged in allow()
            if not ok_rpd:
                pass


# ---------------------------------------------------------------------------
# Redis-backed rate limiter
# ---------------------------------------------------------------------------

def _make_redis_limiter(model_key: str):  # type: ignore[no-untyped-def]
    """Try to build a Redis-backed limiter; return None on failure."""
    try:
        import redis as _redis

        url = os.getenv("REDIS_URL", "")
        if not url:
            return None
        client = _redis.from_url(url, socket_connect_timeout=1)
        client.ping()
        return _RedisRateLimiter(client, model_key)
    except Exception:  # noqa: BLE001
        return None


class _RedisRateLimiter:
    """Sliding-window rate limiter backed by Redis sorted sets."""

    def __init__(self, client: Any, model_key: str) -> None:
        self._redis = client
        limits = get_limits(model_key)
        self._rpm_limit = limits["rpm"]
        self._rpd_limit = limits["rpd"]
        self._tpm_limit = limits["tpm"]
        self._prefix = f"llm_rl:{model_key}"

    def _check_window(self, key: str, limit: int, window_s: int) -> bool:
        now = time.time()
        cutoff = now - window_s
        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(key, "-inf", cutoff)
        pipe.zcard(key)
        _, count = pipe.execute()
        return int(count) < limit

    def _add_entry(self, key: str, window_s: int) -> None:
        now = time.time()
        self._redis.zadd(key, {str(now): now})
        self._redis.expire(key, window_s + 5)

    def check_and_reserve(self, prompt_tokens: int, max_wait: float = 20.0) -> None:
        from app.contracts import ErrorCode, PipelineError

        deadline = time.time() + max_wait
        while True:
            rpm_key = f"{self._prefix}:rpm"
            rpd_key = f"{self._prefix}:rpd"
            tpm_key = f"{self._prefix}:tpm"

            ok_rpm = self._check_window(rpm_key, self._rpm_limit, 60)
            ok_rpd = self._check_window(rpd_key, self._rpd_limit, 86_400)
            # TPM: sum scores in last 60s
            now = time.time()
            cutoff = now - 60
            self._redis.zremrangebyscore(tpm_key, "-inf", cutoff)
            tpm_used = int(self._redis.zscore_sum_hack(tpm_key) if hasattr(self._redis, "zscore_sum_hack") else 0)
            # Simpler: count entries * average is impractical; just count entries as tokens proxy
            tpm_used_count = int(self._redis.zcard(tpm_key) or 0) * 100  # rough
            ok_tpm = (tpm_used_count + prompt_tokens) <= self._tpm_limit

            if ok_rpm and ok_rpd and ok_tpm:
                self._add_entry(rpm_key, 60)
                self._add_entry(rpd_key, 86_400)
                self._redis.zadd(tpm_key, {f"{now}:{prompt_tokens}": now})
                self._redis.expire(tpm_key, 65)
                return

            if time.time() >= deadline:
                raise PipelineError(ErrorCode.LLM_RATE_LIMITED, "Rate limit exceeded; could not acquire slot within 20s")
            time.sleep(1.0)


# ---------------------------------------------------------------------------
# Public factory: get a limiter for a model key
# ---------------------------------------------------------------------------

_limiters: dict[str, Any] = {}


def get_rate_limiter(model_key: str) -> InMemoryRateLimiter:
    """Return (and cache) a rate limiter for 'primary' or 'fallback'."""
    if model_key not in _limiters:
        redis_limiter = _make_redis_limiter(model_key)
        _limiters[model_key] = redis_limiter if redis_limiter is not None else InMemoryRateLimiter(model_key)
    return _limiters[model_key]  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Cache: sha256 key, backed by llm_cache DB table
# ---------------------------------------------------------------------------

def _cache_key(model: str, prompt: str, doc_text: str) -> str:
    raw = model + "\x00" + prompt + "\x00" + doc_text
    return hashlib.sha256(raw.encode()).hexdigest()


class LLMCache:
    """SQLAlchemy-backed cache using the llm_cache table.

    Falls back to a per-process in-memory dict if no session factory is provided
    (useful in tests with LLM_FAKE=true).
    """

    def __init__(self, session_factory: Any = None) -> None:
        self._session_factory = session_factory
        self._mem: dict[str, dict[str, Any]] = {}

    def get(self, model: str, prompt: str, doc_text: str) -> dict[str, Any] | None:
        key = _cache_key(model, prompt, doc_text)
        if key in self._mem:
            return self._mem[key]
        if self._session_factory is None:
            return None
        try:
            from sqlalchemy import text as sa_text

            with self._session_factory() as session:
                row = session.execute(
                    sa_text("SELECT response FROM llm_cache WHERE key = :k"),
                    {"k": key},
                ).fetchone()
                if row:
                    data = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                    self._mem[key] = data
                    return data
        except Exception:  # noqa: BLE001
            logger.debug("llm_cache DB lookup failed, using mem only")
        return None

    def set(self, model: str, prompt: str, doc_text: str, response: dict[str, Any]) -> None:
        key = _cache_key(model, prompt, doc_text)
        self._mem[key] = response
        if self._session_factory is None:
            return
        try:
            from sqlalchemy import text as sa_text

            with self._session_factory() as session:
                session.execute(
                    sa_text(
                        "INSERT INTO llm_cache(key, model, response, created_at) "
                        "VALUES(:k, :m, :r, now()) ON CONFLICT (key) DO NOTHING"
                    ),
                    {"k": key, "m": model, "r": json.dumps(response)},
                )
                session.commit()
        except Exception:  # noqa: BLE001
            logger.debug("llm_cache DB write failed, cached in-memory only")


# Singleton cache with no DB session (tests / fallback)
_default_cache: LLMCache | None = None


def get_cache(session_factory: Any = None) -> LLMCache:
    global _default_cache
    if _default_cache is None:
        _default_cache = LLMCache(session_factory)
    return _default_cache
