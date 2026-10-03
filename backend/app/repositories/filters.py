"""Helpers shared by both repository implementations."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from app.models import Trip
from app.models.common import TripStatus


def date_key(d: date) -> str:
    """Dates are stored as ISO strings (BSON has no plain date type)."""
    return d.isoformat()


def trip_with_status(trip: Trip, status: TripStatus, at: datetime) -> Trip:
    update: dict[str, Any] = {"status": status}
    if status is TripStatus.ACTIVE and trip.actual_start is None:
        update["actual_start"] = at
    if status in (TripStatus.COMPLETED, TripStatus.CANCELLED):
        update["actual_end"] = at
    return trip.model_copy(update=update)


def _resolve(value: Any, parts: list[str]) -> list[Any]:
    """All values at a dotted path, flattening arrays like MongoDB does."""
    if not parts:
        return value if isinstance(value, list) else [value]
    if isinstance(value, list):
        out: list[Any] = []
        for v in value:
            out.extend(_resolve(v, parts))
        return out
    if isinstance(value, Mapping) and parts[0] in value:
        return _resolve(value[parts[0]], parts[1:])
    return []


def matches(doc: Mapping[str, Any], flt: Mapping[str, Any] | None) -> bool:
    """Subset of MongoDB query semantics: equality and ``$in`` on (dotted) paths."""
    if not flt:
        return True
    for key, cond in flt.items():
        values = _resolve(doc, key.split("."))
        if isinstance(cond, Mapping):
            unsupported = set(cond) - {"$in"}
            if unsupported:
                raise NotImplementedError(f"memory filter does not support {unsupported}")
            if not any(v in cond["$in"] for v in values):
                return False
        elif cond not in values:
            return False
    return True
