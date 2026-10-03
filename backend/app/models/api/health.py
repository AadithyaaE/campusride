from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ClockOut(BaseModel):
    mode: Literal["sim", "real"]
    now: datetime
    local_now: datetime
    speed: float
    paused: bool


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    app: str
    env: str
    db: Literal["ok", "down", "not_configured"]
    clock: ClockOut
