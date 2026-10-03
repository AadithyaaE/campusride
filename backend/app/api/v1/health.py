from __future__ import annotations

from fastapi import APIRouter

from app.core.clock import SimClock
from app.deps import Container
from app.models.api.health import ClockOut, HealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health(c: Container) -> HealthOut:
    db = "not_configured" if c.database is None else ("ok" if await c.database.ping() else "down")
    clock = c.clock
    return HealthOut(
        status="ok" if db != "down" else "degraded",
        app=c.settings.app_name,
        env=c.settings.app_env,
        db=db,
        clock=ClockOut(
            mode="sim" if isinstance(clock, SimClock) else "real",
            now=clock.now(),
            local_now=clock.local_now(),
            speed=clock.speed,
            paused=isinstance(clock, SimClock) and clock.paused,
        ),
    )
