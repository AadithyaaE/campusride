"""Domain event catalogue — the contracts between modules.

Producers publish these on the ``EventBus``; consumers subscribe by type.
Events are immutable facts about something that already happened.

=========================  ===========================  ==================================
Event                      Produced by                  Typical consumers
=========================  ===========================  ==================================
TelemetryReceived          telemetry ingestion          tracking
BusStateUpdated            tracking                     eta, deviation, alerts, realtime
StopArrived/StopDeparted   tracking (from telemetry)    eta, capacity, alerts, realtime
TripStarted/TripEnded      driver API / ingestion       tracking, realtime, admin
EtaUpdated                 eta                          alerts, realtime
BoardingRecorded           capacity                     realtime, analytics
OccupancyChanged           capacity                     alerts, realtime
DeviationStarted/Ended     deviation                    alerts, realtime
BreakdownReported          driver report                alerts, realtime
DelayReported              driver report                alerts, realtime
AlertCreated               alerts                       realtime
SimReset                   sim control                  every stateful module
=========================  ===========================  ==================================
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.core.ids import new_id
from app.models.alert import Alert
from app.models.bus_state import BusState
from app.models.common import BoardingType, Direction


class DomainEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_type: ClassVar[str] = "domain.event"
    event_id: str = Field(default_factory=new_id)
    ts: AwareDatetime
    """When it happened, from the Clock (sim time while simulating)."""


class TelemetryReceived(DomainEvent):
    event_type: ClassVar[str] = "telemetry.received"
    bus_id: str
    trip_id: str | None
    count: int


class BusStateUpdated(DomainEvent):
    event_type: ClassVar[str] = "bus.state"
    state: BusState


class StopArrived(DomainEvent):
    event_type: ClassVar[str] = "stop.arrived"
    bus_id: str
    trip_id: str
    variant_id: str
    stop_id: str
    seq: int


class StopDeparted(DomainEvent):
    event_type: ClassVar[str] = "stop.departed"
    bus_id: str
    trip_id: str
    variant_id: str
    stop_id: str
    seq: int


class TripStarted(DomainEvent):
    event_type: ClassVar[str] = "trip.started"
    trip_id: str
    bus_id: str
    route_id: str
    variant_id: str
    direction: Direction


class TripEnded(DomainEvent):
    event_type: ClassVar[str] = "trip.ended"
    trip_id: str
    bus_id: str
    variant_id: str


class StopEta(BaseModel):
    """Predicted arrival at one stop (computed, never stored as domain state)."""

    stop_id: str
    seq: int
    eta: AwareDatetime
    p10: AwareDatetime
    p90: AwareDatetime


class EtaUpdated(DomainEvent):
    event_type: ClassVar[str] = "eta.update"
    trip_id: str
    bus_id: str
    variant_id: str
    model_version: str
    stops: list[StopEta]


class BoardingRecorded(DomainEvent):
    event_type: ClassVar[str] = "boarding.recorded"
    trip_id: str
    bus_id: str
    stop_id: str
    type: BoardingType
    student_id: str | None = None


class OccupancyChanged(DomainEvent):
    event_type: ClassVar[str] = "occupancy"
    bus_id: str
    trip_id: str
    occupancy: int
    capacity: int


class DeviationStarted(DomainEvent):
    event_type: ClassVar[str] = "deviation.started"
    deviation_id: str
    bus_id: str
    trip_id: str
    off_route_m: float


class DeviationEnded(DomainEvent):
    event_type: ClassVar[str] = "deviation.ended"
    deviation_id: str
    bus_id: str
    trip_id: str
    max_off_route_m: float


class BreakdownReported(DomainEvent):
    event_type: ClassVar[str] = "breakdown.reported"
    bus_id: str
    trip_id: str
    note: str | None = None


class DelayReported(DomainEvent):
    event_type: ClassVar[str] = "delay.reported"
    bus_id: str
    trip_id: str
    delay_min: int
    note: str | None = None


class AlertCreated(DomainEvent):
    event_type: ClassVar[str] = "alert"
    alert: Alert


class SimReset(DomainEvent):
    event_type: ClassVar[str] = "sim.reset"
    scenario: str | None = None
