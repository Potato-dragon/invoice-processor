"""Shared API pieces: error type, auth, rate limiting, serializers."""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from decimal import Decimal
from typing import Any

from fastapi import Header, Request

from app.config import get_settings
from app.contracts import ErrorCode


class ApiError(Exception):
    def __init__(self, status: int, code: ErrorCode | str, message: str) -> None:
        self.status = status
        self.code = ErrorCode(code).value
        self.message = message


def require_api_key(x_api_key: str | None = Header(default=None)) -> str:
    expected = get_settings().api_key
    if not x_api_key or not hmac.compare_digest(x_api_key.encode(), expected.encode()):
        raise ApiError(401, ErrorCode.UNAUTHORIZED, "missing or wrong X-API-Key header")
    return x_api_key


def _limit(bucket: str) -> int:
    defaults = {"upload": 120, "search": 600}
    return int(os.getenv(f"RATE_LIMIT_{bucket.upper()}_PER_MIN", str(defaults[bucket])))


def rate_limit(bucket: str):  # noqa: ANN201
    """Fixed one-minute window per API key, shared through Redis."""

    def dep(request: Request, x_api_key: str | None = Header(default=None)) -> None:
        from app.jobs import redis_conn

        who = hashlib.sha256((x_api_key or request.client.host if request.client else "anon").encode()).hexdigest()[:16]
        key = f"api_rl:{bucket}:{who}:{int(time.time() // 60)}"
        try:
            pipe = redis_conn().pipeline()
            pipe.incr(key)
            pipe.expire(key, 61)
            count = pipe.execute()[0]
        except Exception:  # noqa: BLE001 - never block the API because Redis blinked
            return
        if count > _limit(bucket):
            raise ApiError(429, ErrorCode.RATE_LIMITED, f"too many {bucket} requests; try again in a minute")

    return dep


def money(value: Any) -> str | None:
    if value is None:
        return None
    d = Decimal(value)
    q = d.quantize(Decimal("0.01"))
    return str(q) if q == d else str(d.normalize())


def iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None
