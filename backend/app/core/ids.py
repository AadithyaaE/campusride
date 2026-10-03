"""Identifier formats.

Reference data uses human-readable codes as ``_id`` so WebSocket topics and
seed files can refer to them directly (``route:R1``, ``stop:S07``, ``bus:B03``).
High-volume records (telemetry, boardings, alerts, …) use generated ids.
"""

from __future__ import annotations

import re
from datetime import date
from datetime import time as dtime

from bson import ObjectId

from app.models.common import Direction

STOP_ID = re.compile(r"^S\d{2}$")
ROUTE_ID = re.compile(r"^R\d+$")
VARIANT_ID = re.compile(r"^R\d+(-E)?$")
BUS_ID = re.compile(r"^B\d{2}$")
DRIVER_ID = re.compile(r"^D\d{2}$")
CAMPUS_ID = re.compile(r"^C\d{2}$")

EVENING_SUFFIX = "-E"


def new_id() -> str:
    """Generated id for high-volume documents (sortable by creation time)."""
    return str(ObjectId())


def variant_id(route_id: str, direction: Direction) -> str:
    """``R1`` + TO_CAMPUS → ``R1``; ``R1`` + FROM_CAMPUS → ``R1-E``."""
    return route_id if direction is Direction.TO_CAMPUS else f"{route_id}{EVENING_SUFFIX}"


def split_variant_id(vid: str) -> tuple[str, Direction]:
    """``R1-E`` → (``R1``, FROM_CAMPUS)."""
    if not VARIANT_ID.match(vid):
        raise ValueError(f"not a route variant id: {vid!r}")
    if vid.endswith(EVENING_SUFFIX):
        return vid[: -len(EVENING_SUFFIX)], Direction.FROM_CAMPUS
    return vid, Direction.TO_CAMPUS


def trip_id(service_date: date, vid: str, departure: dtime) -> str:
    """``T-20261005-R1-0715``."""
    return f"T-{service_date:%Y%m%d}-{vid}-{departure:%H%M}"
