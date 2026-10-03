from __future__ import annotations

from pydantic import field_validator

from app.models.common import Document, Role


class User(Document):
    role: Role
    name: str
    email: str
    firebase_uid: str | None = None

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v:
            raise ValueError("invalid email")
        return v
