"""DTOs for the transport admin dashboard (Feature 13) — ``/admin/*``.

Every live value here is read from the existing backend state (``BusState``, trips,
alerts) and the existing services (Feature 5 ETA, Feature 8 occupancy, Feature 10
route status, tracking's delay rule). Synthetic historical analytics are returned in a
separate, explicitly labelled block — never mixed with live values.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.models.api.route_status import LatLonOut
from app.models.common import BusSource, BusStatus, Direction, FleetStatus, RouteStatus, Severity, TripStatus

OperationalStatus = Literal[
    "active", "delayed", "deviated", "breakdown", "waiting", "completed", "idle", "out_of_service"
]
"""One control-room status per bus, derived in the backend (see ``admin_service.operational_status``)."""

Crowding = Literal["Low", "Medium", "High", "Unknown"]
GpsFreshness = Literal["LIVE", "STALE", "UNAVAILABLE"]
EtaStatusOut = Literal["predicted", "at_stop", "passed", "completed"]


class NamedRefOut(BaseModel):
    id: str
    name: str


class AlertRefOut(BaseModel):
    alert_id: str
    type: str
    severity: Severity
    title: str
    message: str


# ----------------------------------------------------------------------------- fleet


class AdminFleetBusOut(BaseModel):
    """One bus row for the control room (table, map, active buses, occupancy, delays, deviations)."""

    bus_id: str
    reg_no: str
    source: BusSource
    fleet_status: FleetStatus
    route_id: str
    """Physical route the bus is assigned to (both directions)."""
    route_name: str
    route_color: str
    driver: NamedRefOut | None
    operational_status: OperationalStatus
    bus_status: BusStatus | None
    """Live driving state from tracking (null: no telemetry yet)."""
    trip_id: str | None
    trip_status: TripStatus | None
    route_direction_id: str | None
    direction: Direction | None
    direction_label: str | None
    location: LatLonOut | None
    heading_deg: float | None
    speed_kmh: int | None
    current_stop: NamedRefOut | None
    next_stop: NamedRefOut | None
    eta_next_stop_min: int | None
    """Feature 5 ETA to ``next_stop`` in whole minutes (0 = under a minute)."""
    eta_status: EtaStatusOut | None
    eta_confidence: Literal["high", "medium", "low"] | None
    delay_s: int | None
    delay_min: int | None
    is_delayed: bool
    """Tracking's delay rule (``DELAYED_AFTER_S`` while moving or dwelling)."""
    occupancy: int | None
    capacity: int
    available_seats: int | None
    occupancy_percentage: int | None
    crowding: Crowding
    """Feature 6/8 crowding band: <60 % Low · 60–79 % Medium · ≥80 % High."""
    boarded_count: int
    route_status: RouteStatus | None
    deviation_distance_m: float | None
    route_progress: float | None
    gps: GpsFreshness
    gps_age_s: int | None
    last_updated: datetime | None
    active_alerts: list[AlertRefOut]


class FilterOptionOut(BaseModel):
    value: str
    label: str


class FleetFilterOptionsOut(BaseModel):
    routes: list[FilterOptionOut]
    buses: list[FilterOptionOut]
    statuses: list[FilterOptionOut]


class AdminFleetOut(BaseModel):
    generated_at: datetime
    sim_time: datetime
    filters: dict[str, str | None]
    """The filters applied to ``buses`` (echoed)."""
    total: int
    """Buses before filtering."""
    buses: list[AdminFleetBusOut]
    options: FleetFilterOptionsOut
    """Everything the filters can select (from the unfiltered fleet)."""


# ----------------------------------------------------------------------------- overview


class TripCountsOut(BaseModel):
    total: int
    scheduled: int
    active: int
    completed: int
    cancelled: int


class AlertCountsOut(BaseModel):
    active: int
    unread: int
    critical: int
    warning: int
    info: int


class AdminOverviewOut(BaseModel):
    generated_at: datetime
    sim_time: datetime
    service_date: date
    simulation_paused: bool | None
    total_buses: int
    buses_in_service: int
    """Buses whose fleet status is ``active`` (not in maintenance / retired)."""
    buses_on_trip: int
    active_trips: int
    trips_today: TripCountsOut
    students: int
    assigned_students: int
    passengers_today: int
    """Σ peak on-board load of every trip started today (Feature 8 occupancy)."""
    passengers_method: str
    qr_boardings_today: int
    delayed_buses: int
    deviated_buses: int
    """Buses currently in MINOR or MAJOR deviation (Feature 10)."""
    major_deviations: int
    alerts: AlertCountsOut


# ----------------------------------------------------------------------------- routes & schedule


class AdminRouteDirectionOut(BaseModel):
    variant_id: str
    direction: Direction
    label: str
    stop_count: int
    first_stop: NamedRefOut
    last_stop: NamedRefOut
    scheduled_duration_min: int
    """Timetable: first stop → last stop (from ``scheduled_offset_s``)."""


class AdminRouteOut(BaseModel):
    id: str
    name: str
    color: str
    length_km: float
    directions: list[AdminRouteDirectionOut]
    assigned_buses: list[str]
    active_buses: list[str]
    trips_today: TripCountsOut
    delayed_buses: list[str]
    deviated_buses: list[str]
    avg_occupancy_percentage: int | None
    """Mean of the backend occupancy % of buses on a trip of this route now."""
    passengers_today: int


class ScheduleTripOut(BaseModel):
    trip_id: str
    route_id: str
    route_name: str
    route_color: str
    route_direction_id: str
    direction: Direction
    direction_label: str
    first_stop: str
    last_stop: str
    scheduled_departure: datetime
    scheduled_arrival: datetime
    actual_start: datetime | None
    actual_end: datetime | None
    bus_id: str
    reg_no: str
    driver: NamedRefOut | None
    status: TripStatus
    delay_min: int | None
    """Live delay of the bus while this trip is running (tracking)."""


class AdminScheduleOut(BaseModel):
    service_date: date
    generated_at: datetime
    trips: list[ScheduleTripOut]


# ----------------------------------------------------------------------------- analytics


class LabelValueOut(BaseModel):
    label: str
    value: float
    key: str | None = None
    color: str | None = None


class OccupancyBarOut(BaseModel):
    bus_id: str
    route_id: str
    occupancy: int
    capacity: int
    occupancy_percentage: int | None
    crowding: Crowding


class DelaySummaryOut(BaseModel):
    buses_measured: int
    fleet_avg_delay_min: float | None
    by_route: list[LabelValueOut]


class LiveAnalyticsOut(BaseModel):
    """Computed from today's backend state (live / real)."""

    passengers_per_route: list[LabelValueOut]
    occupancy_by_bus: list[OccupancyBarOut]
    trips_today: TripCountsOut
    trips_by_departure_hour: list[LabelValueOut]
    average_delay: DelaySummaryOut
    qr_boardings_by_slot: list[LabelValueOut]
    """QR boarding events today in 30-minute slots (campus-local)."""


class SyntheticAnalyticsOut(BaseModel):
    """Deterministic demo history (no history is stored yet). NEVER live data."""

    synthetic: Literal[True] = True
    label: Literal["Synthetic demo data"] = "Synthetic demo data"
    method: str
    seed: int
    daily_passengers: list[LabelValueOut]
    average_delay_by_day: list[LabelValueOut]
    peak_boarding_by_hour: list[LabelValueOut]
    passengers_per_route_weekly_avg: list[LabelValueOut]


class AdminAnalyticsOut(BaseModel):
    generated_at: datetime
    service_date: date
    live: LiveAnalyticsOut
    synthetic: SyntheticAnalyticsOut
