"""Shared rate limiter and LLM cache.

Rate limiter:
- Sliding-window limiter in Redis shared across workers (whenever REDIS_URL is set).
- In-memory limiter only when REDIS_URL is not set (unit tests, local scripts).
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
import threading
import time
import uuid
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
# In-memory sliding-window limiter (only when REDIS_URL is not set)
# ---------------------------------------------------------------------------

def _max_wait() -> float:
    try:
        return float(os.getenv("LLM_MAX_WAIT_S", "60"))
    except ValueError:
        return 60.0


class _InMemoryWindow:
    """Sliding-window counter using a deque of timestamps."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self._limit = limit
        self._window = window_seconds
        self._timestamps: deque[float] = deque()

    def _prune(self) -> None:
        cutoff = time.monotonic() - self._window
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    def has_room(self) -> bool:
        self._prune()
        return len(self._timestamps) < self._limit

    def record(self) -> None:
        self._timestamps.append(time.monotonic())

    def allow(self) -> bool:
        if self.has_room():
            self.record()
            return True
        return False


class InMemoryRateLimiter:
    """Per-process limiter (RPM, RPD and TPM). Used only without Redis."""

    def __init__(self, model_key: str) -> None:
        limits = get_limits(model_key)
        self._lock = threading.Lock()
        self._rpm_window = _InMemoryWindow(limits["rpm"], 60)
        self._rpd_window = _InMemoryWindow(limits["rpd"], 86_400)
        self._tpm_limit = limits["tpm"]
        self._token_window: deque[tuple[float, int]] = deque()  # (ts, tokens)

    def _tpm_current(self) -> int:
        cutoff = time.monotonic() - 60
        while self._token_window and self._token_window[0][0] < cutoff:
            self._token_window.popleft()
        return sum(t for _, t in self._token_window)

    def try_reserve(self, prompt_tokens: int) -> bool:
        # Check every window first and only then record, so a refused call
        # never uses up a slot in another window.
        with self._lock:
            ok = (
                self._rpm_window.has_room()
                and self._rpd_window.has_room()
                and self._tpm_current() + prompt_tokens <= self._tpm_limit
            )
            if ok:
                self._rpm_window.record()
                self._rpd_window.record()
                self._token_window.append((time.monotonic(), prompt_tokens))
            return ok

    def check_and_reserve(self, prompt_tokens: int, max_wait: float | None = None) -> None:
        """Block until quota allows, or raise PipelineError(LLM_RATE_LIMITED)."""
        _wait_for_slot(self.try_reserve, prompt_tokens, _max_wait() if max_wait is None else max_wait)


def _wait_for_slot(try_reserve: Any, prompt_tokens: int, max_wait: float) -> None:
    from app.contracts import ErrorCode, PipelineError

    deadline = time.monotonic() + max_wait
    while True:
        if try_reserve(prompt_tokens):
            return
        now = time.monotonic()
        if now >= deadline:
            raise PipelineError(ErrorCode.LLM_RATE_LIMITED, f"LLM rate limit: no free slot within {max_wait:.0f}s")
        time.sleep(min(1.0, deadline - now))


# ---------------------------------------------------------------------------
# Redis-backed rate limiter (shared by every API and worker process)
# ---------------------------------------------------------------------------

# One atomic script: prune old entries, check RPM, RPD and TPM together, and
# record the call only if all three have room. Token counts are kept in the
# member name ("<uuid>:<tokens>") so TPM is an exact sum, not an estimate.
_RESERVE_LUA = """
local now = tonumber(ARGV[1])
local tokens = tonumber(ARGV[2])
local rpm, rpd, tpm = tonumber(ARGV[3]), tonumber(ARGV[4]), tonumber(ARGV[5])
local id = ARGV[6]
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - 60)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now - 86400)
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', now - 60)
if redis.call('ZCARD', KEYS[1]) >= rpm then return 0 end
if redis.call('ZCARD', KEYS[2]) >= rpd then return 0 end
local used = 0
for _, m in ipairs(redis.call('ZRANGE', KEYS[3], 0, -1)) do
  used = used + tonumber(string.match(m, ':(%d+)$'))
end
if used + tokens > tpm then return 0 end
redis.call('ZADD', KEYS[1], now, id)
redis.call('ZADD', KEYS[2], now, id)
redis.call('ZADD', KEYS[3], now, id .. ':' .. tokens)
redis.call('EXPIRE', KEYS[1], 70)
redis.call('EXPIRE', KEYS[2], 86410)
redis.call('EXPIRE', KEYS[3], 70)
return 1
"""


class RedisRateLimiter:
    """Sliding-window limiter in Redis sorted sets, atomic via a Lua script."""

    def __init__(self, client: Any, model_key: str) -> None:
        self._redis = client
        self._limits = get_limits(model_key)
        prefix = f"llm_rl:{model_key}"
        self._keys = [f"{prefix}:rpm", f"{prefix}:rpd", f"{prefix}:tpm"]
        self._script = client.register_script(_RESERVE_LUA)

    def try_reserve(self, prompt_tokens: int) -> bool:
        args = [time.time(), prompt_tokens, self._limits["rpm"], self._limits["rpd"], self._limits["tpm"], uuid.uuid4().hex]
        return bool(self._script(keys=self._keys, args=args))

    def check_and_reserve(self, prompt_tokens: int, max_wait: float | None = None) -> None:
        _wait_for_slot(self.try_reserve, prompt_tokens, _max_wait() if max_wait is None else max_wait)


# ---------------------------------------------------------------------------
# Public factory: get a limiter for a model key
# ---------------------------------------------------------------------------

_limiters: dict[str, Any] = {}


def get_rate_limiter(model_key: str) -> InMemoryRateLimiter | RedisRateLimiter:
    """Return the limiter for 'primary' or 'fallback'.

    Redis is used whenever REDIS_URL is set, so every worker shares one quota.
    In-memory is only for runs without Redis (unit tests, local scripts).
    """
    if model_key not in _limiters:
        url = os.getenv("REDIS_URL", "")
        if url:
            import redis as _redis

            _limiters[model_key] = RedisRateLimiter(_redis.from_url(url, socket_connect_timeout=2), model_key)
        else:
            logger.warning("REDIS_URL not set: LLM rate limiter is per-process only")
            _limiters[model_key] = InMemoryRateLimiter(model_key)
    return _limiters[model_key]


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
    elif session_factory is not None and _default_cache._session_factory is None:
        _default_cache._session_factory = session_factory
    return _default_cache
