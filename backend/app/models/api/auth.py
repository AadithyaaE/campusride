"""DTOs for authentication (Feature 15)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models import User
from app.models.common import Role


class DevLoginIn(BaseModel):
    """DEVELOPMENT sign-in: a seeded identity's email (AUTH_MODE=dev only)."""

    email: str = Field(
        examples=["student001@campusride.demo", "driver07@campusride.demo", "admin1@campusride.demo"]
    )


MockLoginIn = DevLoginIn  # Features 1–14 name


class PasswordLoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=1, max_length=1024, repr=False)


class AuthConfigOut(BaseModel):
    """What sign-in this backend offers — clients render the matching form."""

    mode: Literal["dev", "password", "oidc"]
    development: bool
    """True for AUTH_MODE=dev: development sign-in, NOT real authentication."""
    dev_login: bool
    password_login: bool
    external_provider: bool
    oidc_issuer: str | None


class MeOut(BaseModel):
    id: str
    role: Role
    name: str
    email: str
    active: bool

    @classmethod
    def of(cls, user: User) -> MeOut:
        return cls(id=user.id, role=user.role, name=user.name, email=user.email, active=user.active)


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    auth_method: Literal["dev", "password"]
    user: MeOut
