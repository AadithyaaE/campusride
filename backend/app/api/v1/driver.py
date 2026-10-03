"""Driver endpoints. Telemetry from a real driver phone enters here; the
simulator calls the SAME ``TelemetryIngestService.ingest`` in-process."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.v1.buses import BusLiveOut
from app.core.auth import Principal
from app.deps import Container, require_role
from app.models.common import Role
from app.models.telemetry_in import TelemetryBatchIn

router = APIRouter(tags=["driver"])

Driver = Annotated[Principal, Depends(require_role(Role.DRIVER))]


@router.post("/driver/telemetry", response_model=BusLiveOut, status_code=202)
async def post_telemetry(batch: TelemetryBatchIn, principal: Driver, c: Container) -> BusLiveOut:
    """Ingest GPS fixes for the driver's own bus; returns the derived bus state."""
    state = await c.telemetry_ingest().ingest(batch, principal)
    return BusLiveOut.of(state, c.clock, c.settings.bus_stale_after_s)
