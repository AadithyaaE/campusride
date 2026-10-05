"""Password hashing for first-party credentials (AUTH_MODE=password). Standard library only.

Format: ``scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>`` — memory-hard scrypt with a random
16-byte salt per password. Verification is constant time (``hmac.compare_digest``), and
``verify_password`` against ``None`` still does the work (no user-enumeration timing).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

N, R, P, DKLEN = 2**14, 8, 1, 32
MIN_LENGTH = 8
_DUMMY = None


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=DKLEN, maxmem=64 * 1024 * 1024)


def hash_password(password: str) -> str:
    if len(password) < MIN_LENGTH:
        raise ValueError(f"password must be at least {MIN_LENGTH} characters")
    salt = os.urandom(16)
    return f"scrypt${N}${R}${P}${_b64e(salt)}${_b64e(_derive(password, salt, N, R, P))}"


def verify_password(password: str, encoded: str | None) -> bool:
    global _DUMMY
    if encoded is None:  # unknown user / no password set: same cost, always False
        if _DUMMY is None:
            _DUMMY = hash_password("dummy-password-for-timing")
        verify_password(password, _DUMMY)
        return False
    try:
        algo, n, r, p, salt, expected = encoded.split("$")
        if algo != "scrypt":
            return False
        got = _derive(password, base64.b64decode(salt), int(n), int(r), int(p))
        return hmac.compare_digest(got, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False
