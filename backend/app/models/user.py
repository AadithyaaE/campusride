"""The authentication identity (Feature 15) — one per person who can sign in.

The ``User`` id is the stable identity every domain record already references:
students (``StudentProfile`` / ``StudentAssignment`` use the same id), drivers
(``Driver.user_id``) and admins (role ``admin``). Role, name, email and ``active`` are
authoritative here and read on every request (never trusted from a token).
"""

from __future__ import annotations

from pydantic import AwareDatetime, Field, field_validator

from app.models.common import Document, Role


class User(Document):
    role: Role
    name: str
    email: str
    active: bool = True
    """Inactive identities are rejected at authentication (REST 401, WebSocket 4401)."""
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
    auth_provider: str | None = None
    """External identity provider (OIDC issuer) this user is linked to, if any."""
    auth_subject: str | None = None
    """The provider's stable subject (``sub``) for this user — unique per provider."""
    password_hash: str | None = Field(default=None, repr=False)
    """scrypt hash for AUTH_MODE=password (``app/core/passwords.py``). Never returned by the API."""
    firebase_uid: str | None = None
    """Legacy (pre-Feature 15, always null); superseded by ``auth_provider`` / ``auth_subject``."""

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v:
            raise ValueError("invalid email")
        return v
