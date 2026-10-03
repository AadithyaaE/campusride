from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.core.events import InProcessEventBus
from app.models.common import Direction
from app.models.events import DomainEvent, SimReset, TripEnded, TripStarted

NOW = datetime(2026, 10, 5, 1, 45, tzinfo=UTC)


def started() -> TripStarted:
    return TripStarted(
        ts=NOW, trip_id="T1", bus_id="B01", route_id="R1", variant_id="R1", direction=Direction.TO_CAMPUS
    )


async def test_handlers_run_in_registration_order():
    bus = InProcessEventBus()
    calls: list[str] = []

    async def a(_):
        calls.append("a")

    async def b(_):
        calls.append("b")

    bus.subscribe(TripStarted, b, name="b")
    bus.subscribe(TripStarted, a, name="a")
    await bus.publish(started())
    assert calls == ["b", "a"]


async def test_subscription_is_by_type_including_base_class():
    bus = InProcessEventBus()
    seen: list[str] = []

    async def any_event(e: DomainEvent):
        seen.append(f"any:{e.event_type}")

    async def only_started(e: TripStarted):
        seen.append("started")

    bus.subscribe(DomainEvent, any_event, name="audit")
    bus.subscribe(TripStarted, only_started, name="tracking")
    await bus.publish(started())
    await bus.publish(TripEnded(ts=NOW, trip_id="T1", bus_id="B01", variant_id="R1"))
    assert seen == ["any:trip.started", "started", "any:trip.ended"]


async def test_failing_handler_is_isolated():
    bus = InProcessEventBus()
    ran: list[str] = []

    async def boom(_):
        raise RuntimeError("bad handler")

    async def fine(_):
        ran.append("fine")

    bus.subscribe(SimReset, boom, name="boom")
    bus.subscribe(SimReset, fine, name="fine")
    await bus.publish(SimReset(ts=NOW))
    assert ran == ["fine"]
    assert bus.stats["boom"].failures == 1
    assert "bad handler" in (bus.stats["boom"].last_error or "")
    assert bus.stats["fine"].calls == 1


async def test_nested_publish_is_depth_first():
    bus = InProcessEventBus()
    order: list[str] = []

    async def on_start(e):
        order.append("start")
        await bus.publish(TripEnded(ts=e.ts, trip_id=e.trip_id, bus_id=e.bus_id, variant_id=e.variant_id))
        order.append("start-done")

    async def on_end(_):
        order.append("end")

    bus.subscribe(TripStarted, on_start, name="s")
    bus.subscribe(TripEnded, on_end, name="e")
    await bus.publish(started())
    assert order == ["start", "end", "start-done"]


def test_duplicate_handler_name_rejected():
    bus = InProcessEventBus()

    async def h(_): ...

    bus.subscribe(SimReset, h, name="x")
    with pytest.raises(ValueError):
        bus.subscribe(SimReset, h, name="x")


def test_events_are_immutable_and_have_ids():
    e = started()
    assert e.event_id and e.event_type == "trip.started"
    with pytest.raises(ValidationError):
        e.bus_id = "B02"  # type: ignore[misc]
