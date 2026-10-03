"""QR boarding: POST /boarding/scan, GET /trips/{id}/boarding (Feature 8). Rules live in the service."""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import Container, CurrentPrincipal
from app.models.api.boarding import (
    BoardingEventOut,
    BoardingScanIn,
    BoardingScanOut,
    OccupancyOut,
    TripBoardingOut,
)
from app.services.boarding_service import QrPayload

router = APIRouter(tags=["boarding"])

MESSAGES = {
    "boarded": "Boarding recorded.",
    "already_boarded": "You have already boarded this trip.",
}


@router.post("/boarding/scan", response_model=BoardingScanOut)
async def scan(body: BoardingScanIn, principal: CurrentPrincipal, c: Container) -> BoardingScanOut:
    """Record a QR boarding for the signed-in student (PROTOTYPE: unsigned, simulated QR).

    Validated against the college assignment and the bus's current trip. A repeat
    scan returns ``already_boarded`` and changes nothing.
    """
    result = await c.boarding().scan(
        principal,
        QrPayload(
            student_id=body.student_id,
            bus_id=body.bus_id,
            trip_id=body.trip_id,
            timestamp=body.timestamp,
            stop_id=body.stop_id,
            scanner=body.scanner,
        ),
    )
    e = result.event
    return BoardingScanOut(
        **OccupancyOut.of(result.occupancy).model_dump(),
        status=result.status,
        boarding_id=e.id,
        student_id=e.student_id or body.student_id,
        stop_id=e.stop_id,
        timestamp=e.ts,
        message=MESSAGES[result.status],
    )


@router.get("/trips/{trip_id}/boarding", response_model=TripBoardingOut)
async def trip_boarding(trip_id: str, principal: CurrentPrincipal, c: Container) -> TripBoardingOut:
    """Boarding events of a trip. Admins: all; students: only their own; others: count only."""
    tb = await c.boarding().trip_boarding(trip_id, principal)
    return TripBoardingOut(
        trip_id=tb.trip.id,
        bus_id=tb.trip.bus_id,
        route_direction_id=tb.trip.variant_id,
        total_boarded=tb.total_boarded,
        visibility=tb.visibility,
        events=[BoardingEventOut.of(e) for e in tb.events],
    )
