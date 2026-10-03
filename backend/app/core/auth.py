"""Authentication: who is calling, and with which role.

Routers only ever see a ``Principal``. Where it came from is hidden behind
``TokenVerifier``:

* ``MockTokenService`` (AUTH_MODE=mock) — HMAC-signed tokens issued by
  ``POST /auth/mock-login`` for seeded users. No Firebase project needed.
* ``FirebaseVerifier`` (AUTH_MODE=firebase) — Phase 7.

The simulator authenticates as ``sim_driver_principal(bus)`` — a driver
principal bound to one bus — and goes through the same authorisation checks
as a real driver's phone.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel

from app.core.errors import AuthError
from app.models import User
from app.models.common import Role

MOCK_TOKEN_PREFIX = "mock"


class Principal(BaseModel):
    user_id: str
    role: Role
    name: str = ""
    email: str | None = None
    bus_id: str | None = None
    """Set for simulator principals (the bus this "driver" drives)."""
    source: Literal["user", "sim"] = "user"


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> Principal: ...


class IssuedToken(BaseModel):
    token: str
    expires_at: datetime


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class MockTokenService:
    """Issues and verifies ``mock.<payload>.<signature>`` bearer tokens.

    Expiry uses real wall-clock time (``now``), not simulated time: a login
    must not expire because the demo was fast-forwarded.
    """

    def __init__(self, secret: str, ttl_s: int, now: Callable[[], float] = time.time) -> None:
        if not secret:
            raise ValueError("mock token secret must not be empty")
        self._key = secret.encode()
        self._ttl_s = ttl_s
        self._now = now

    def _sign(self, payload_b64: str) -> str:
        mac = hmac.new(self._key, f"{MOCK_TOKEN_PREFIX}.{payload_b64}".encode(), hashlib.sha256)
        return _b64e(mac.digest())

    def issue(self, user: User) -> IssuedToken:
        exp = int(self._now()) + self._ttl_s
        payload = {
            "sub": user.id,
            "role": user.role.value,
            "name": user.name,
            "email": user.email,
            "exp": exp,
        }
        payload_b64 = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
        token = f"{MOCK_TOKEN_PREFIX}.{payload_b64}.{self._sign(payload_b64)}"
        return IssuedToken(token=token, expires_at=datetime.fromtimestamp(exp, UTC))

    async def verify(self, token: str) -> Principal:
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != MOCK_TOKEN_PREFIX:
            raise AuthError("malformed token")
        _, payload_b64, sig = parts
        if not hmac.compare_digest(sig, self._sign(payload_b64)):
            raise AuthError("invalid token signature")
        try:
            payload = json.loads(_b64d(payload_b64))
        except (ValueError, json.JSONDecodeError) as exc:
            raise AuthError("malformed token payload") from exc
        if int(payload.get("exp", 0)) < self._now():
            raise AuthError("token expired")
        return Principal(
            user_id=payload["sub"],
            role=Role(payload["role"]),
            name=payload.get("name", ""),
            email=payload.get("email"),
        )


class FirebaseVerifier:
    """Verifies Firebase ID tokens. Implemented in Phase 7."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id

    async def verify(self, token: str) -> Principal:
        raise AuthError("AUTH_MODE=firebase is not implemented yet (Phase 7)")


def sim_driver_principal(bus_id: str, driver_user_id: str) -> Principal:
    """Principal the simulator uses when it acts as the driver of ``bus_id``."""
    return Principal(
        user_id=driver_user_id, role=Role.DRIVER, name=f"sim:{bus_id}", bus_id=bus_id, source="sim"
    )
