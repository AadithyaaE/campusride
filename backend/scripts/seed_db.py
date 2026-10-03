"""Load the deterministic synthetic world into MongoDB.

    python scripts/seed_db.py                 # trips for the resolved SIM_START_DATE
    python scripts/seed_db.py --date 2026-10-05
    python scripts/seed_db.py --dry-run       # validate only, touch nothing

WARNING: replaces ALL CampusRide data in MONGO_DB (idempotent re-seed).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date

from app.core.clock import resolve_sim_start
from app.core.config import get_settings
from app.core.db import Database, ensure_indexes
from app.repositories.mongo import mongo_repositories
from app.seed import load_seed, persist_seed, validate_bundle


async def run(service_date: date | None, dry_run: bool) -> int:
    settings = get_settings()
    bundle = load_seed(settings.seed_data_dir, settings.seed)
    problems = validate_bundle(bundle, settings.tz)
    if problems:
        print("seed validation failed:")
        for p in problems:
            print(f"  - {p}")
        return 1

    if service_date is None:
        service_date = resolve_sim_start(settings.sim_start_date, settings.sim_start_time, settings.tz).date()
    if dry_run:
        print(
            f"seed valid; would load into {settings.mongo_uri}/{settings.mongo_db} "
            f"for service date {service_date}"
        )
        return 0

    database = Database(settings.mongo_uri, settings.mongo_db)
    try:
        if not await database.ping():
            print(
                f"MongoDB not reachable at {settings.mongo_uri}. "
                "Start it: docker compose -f infra/docker-compose.yml up -d"
            )
            return 2
        await ensure_indexes(database.db, telemetry_ttl_days=settings.telemetry_ttl_days)
        counts = await persist_seed(mongo_repositories(database.db), bundle, service_date, settings.tz)
    finally:
        database.close()

    print(f"seeded {settings.mongo_db} for service date {service_date} (SEED={settings.seed}):")
    for k, v in counts.items():
        print(f"  {k:<18} {v}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--date", type=date.fromisoformat, help="service date YYYY-MM-DD (default: SIM_START_DATE)"
    )
    parser.add_argument("--dry-run", action="store_true", help="validate only")
    args = parser.parse_args()
    return asyncio.run(run(args.date, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
