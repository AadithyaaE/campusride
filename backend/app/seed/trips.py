"""Expand the daily schedule into concrete ``Trip`` documents for a service date."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.core.ids import trip_id, variant_id
from app.models import Bus, Trip
from app.seed.loader import Schedule


def build_trips(schedule: Schedule, buses: list[Bus], service_date: date, tz: ZoneInfo) -> list[Trip]:
    drivers = {b.id: b.driver_id for b in buses}
    trips: list[Trip] = []
    for st in schedule.trips:
        vid = variant_id(st.route_id, st.direction)
        start_local = datetime.combine(service_date, st.departure, tzinfo=tz)
        trips.append(
            Trip(
                id=trip_id(service_date, vid, st.departure),
                route_id=st.route_id,
                direction=st.direction,
                variant_id=vid,
                bus_id=st.bus_id,
                driver_id=drivers.get(st.bus_id),
                service_date=service_date,
                scheduled_start=start_local.astimezone(UTC),
            )
        )
    trips.sort(key=lambda t: (t.scheduled_start, t.id))
    return trips
