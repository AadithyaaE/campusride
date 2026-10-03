from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models import User
from app.models.common import Role


class MockLoginIn(BaseModel):
    email: str = Field(
        examples=["student001@campusride.demo", "driver01@campusride.demo", "admin1@campusride.demo"]
    )


class MeOut(BaseModel):
    id: str
    role: Role
    name: str
    email: str

    @classmethod
    def of(cls, user: User) -> MeOut:
        return cls(id=user.id, role=user.role, name=user.name, email=user.email)


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: MeOut
