"""MongoDB connection (Motor) and index bootstrap.

Motor is isolated to this module and ``app.repositories.mongo``; nothing
else imports it, so swapping the driver later touches only those two places.
"""

from __future__ import annotations

import logging
from datetime import UTC

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, GEOSPHERE, IndexModel
from pymongo.errors import PyMongoError

log = logging.getLogger(__name__)


class Collections:
    CAMPUSES = "campuses"
    STOPS = "stops"
    ROUTES = "routes"
    BUSES = "buses"
    DRIVERS = "drivers"
    TRIPS = "trips"
    TELEMETRY = "telemetry"
    BUS_STATES = "bus_states"
    USERS = "users"
    STUDENT_PROFILES = "student_profiles"
    STUDENT_ASSIGNMENTS = "student_assignments"
    BOARDING_EVENTS = "boarding_events"
    DEVIATIONS = "deviations"
    ALERTS = "alerts"
    TRAFFIC_PROFILES = "traffic_profiles"


INDEXES: dict[str, list[IndexModel]] = {
    Collections.STOPS: [
        IndexModel([("location", GEOSPHERE)], name="location_2dsphere"),
        IndexModel([("campus_id", ASCENDING)], name="campus_id"),
    ],
    Collections.ROUTES: [
        IndexModel([("directions.stops.stop_id", ASCENDING)], name="served_stop"),
        IndexModel([("directions.variant_id", ASCENDING)], name="variant_id"),
    ],
    Collections.TRIPS: [
        IndexModel([("route_id", ASCENDING), ("service_date", ASCENDING)], name="route_date"),
        IndexModel([("bus_id", ASCENDING), ("service_date", ASCENDING)], name="bus_date"),
        IndexModel([("status", ASCENDING), ("scheduled_start", ASCENDING)], name="status_start"),
    ],
    Collections.TELEMETRY: [
        IndexModel([("meta.trip_id", ASCENDING), ("ts", ASCENDING)], name="trip_ts"),
        IndexModel([("meta.bus_id", ASCENDING), ("ts", ASCENDING)], name="bus_ts"),
    ],
    Collections.BUS_STATES: [
        IndexModel([("route_id", ASCENDING)], name="route_id"),
        IndexModel([("variant_id", ASCENDING)], name="variant_id"),
        IndexModel([("location", GEOSPHERE)], name="location_2dsphere"),
    ],
    Collections.USERS: [
        IndexModel([("email", ASCENDING)], name="email_unique", unique=True),
        IndexModel(
            [("firebase_uid", ASCENDING)],
            name="firebase_uid_unique",
            unique=True,
            partialFilterExpression={"firebase_uid": {"$type": "string"}},
        ),
    ],
    Collections.DRIVERS: [IndexModel([("user_id", ASCENDING)], name="user_id", unique=True)],
    Collections.STUDENT_PROFILES: [IndexModel([("home_stop_id", ASCENDING)], name="home_stop_id")],
    Collections.STUDENT_ASSIGNMENTS: [
        IndexModel([("assigned_bus_id", ASCENDING)], name="assigned_bus_id"),
        IndexModel([("boarding_stop_id", ASCENDING)], name="boarding_stop_id"),
    ],
    Collections.BOARDING_EVENTS: [
        IndexModel([("trip_id", ASCENDING), ("ts", ASCENDING)], name="trip_ts"),
        IndexModel([("bus_id", ASCENDING), ("ts", ASCENDING)], name="bus_ts"),
        IndexModel(
            [("student_id", ASCENDING), ("trip_id", ASCENDING)],
            name="student_trip_unique",
            unique=True,
            partialFilterExpression={"student_id": {"$type": "string"}},
        ),
    ],
    Collections.DEVIATIONS: [
        IndexModel([("bus_id", ASCENDING), ("started_at", DESCENDING)], name="bus_started"),
        IndexModel([("status", ASCENDING)], name="status"),
    ],
    Collections.ALERTS: [
        IndexModel([("created_at", DESCENDING)], name="created_at"),
        IndexModel(
            [("audience.user_id", ASCENDING), ("created_at", DESCENDING)], name="recipient_user_created"
        ),
        IndexModel([("audience.role", ASCENDING), ("created_at", DESCENDING)], name="recipient_role_created"),
        IndexModel(
            [("dedup_key", ASCENDING)],
            name="dedup_key_active_unique",
            unique=True,
            partialFilterExpression={"active": True},
        ),
        IndexModel([("dedup_key", ASCENDING), ("episode", ASCENDING)], name="dedup_series"),
        IndexModel(
            [("bus_id", ASCENDING), ("active", ASCENDING), ("type", ASCENDING)], name="bus_active_type"
        ),
        IndexModel([("type", ASCENDING), ("active", ASCENDING)], name="type_active"),
        IndexModel([("read", ASCENDING)], name="read"),
        IndexModel([("resolved_at", ASCENDING)], name="resolved_at"),
        IndexModel([("audience.route_id", ASCENDING)], name="aud_route"),
        IndexModel([("audience.stop_id", ASCENDING)], name="aud_stop"),
        IndexModel([("audience.user_id", ASCENDING)], name="aud_user"),
    ],
}


class Database:
    """Owns the Motor client. Datetimes come back timezone-aware (UTC)."""

    def __init__(self, uri: str, name: str, *, server_selection_timeout_ms: int = 3_000) -> None:
        self.client: AsyncIOMotorClient = AsyncIOMotorClient(
            uri,
            tz_aware=True,
            tzinfo=UTC,
            serverSelectionTimeoutMS=server_selection_timeout_ms,
            uuidRepresentation="standard",
            appname="campusride-backend",
        )
        self.db: AsyncIOMotorDatabase = self.client[name]

    async def ping(self) -> bool:
        try:
            await self.client.admin.command("ping")
            return True
        except PyMongoError:
            return False

    def close(self) -> None:
        self.client.close()


async def ensure_telemetry_collection(db: AsyncIOMotorDatabase, ttl_days: int) -> None:
    """Create the time-series collection, or align its TTL with the setting."""
    ttl_s = ttl_days * 86_400
    existing = {c["name"]: c async for c in await db.list_collections(filter={"name": Collections.TELEMETRY})}
    if Collections.TELEMETRY not in existing:
        await db.create_collection(
            Collections.TELEMETRY,
            timeseries={"timeField": "ts", "metaField": "meta", "granularity": "seconds"},
            expireAfterSeconds=ttl_s,
        )
        log.info("created time-series collection %s (TTL %d days)", Collections.TELEMETRY, ttl_days)
        return
    info = existing[Collections.TELEMETRY]
    if info.get("type") != "timeseries":
        raise RuntimeError(
            f"collection {Collections.TELEMETRY!r} exists but is not time-series; drop it and restart"
        )
    if info.get("options", {}).get("expireAfterSeconds") != ttl_s:
        await db.command({"collMod": Collections.TELEMETRY, "expireAfterSeconds": ttl_s})
        log.info("updated %s TTL to %d days", Collections.TELEMETRY, ttl_days)


async def ensure_indexes(db: AsyncIOMotorDatabase, *, telemetry_ttl_days: int) -> None:
    """Idempotent: safe to run on every startup."""
    await ensure_telemetry_collection(db, telemetry_ttl_days)
    for coll, models in INDEXES.items():
        await db[coll].create_indexes(models)
