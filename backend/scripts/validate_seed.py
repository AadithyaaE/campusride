"""Validate the committed seed files without a database.

python scripts/validate_seed.py          # from backend/
"""

from __future__ import annotations

import sys

from app.core.config import get_settings
from app.seed import load_seed, shared_stops, validate_bundle


def main() -> int:
    settings = get_settings()
    bundle = load_seed(settings.seed_data_dir, settings.seed)
    problems = validate_bundle(bundle, settings.tz)
    print(f"seed dir: {settings.seed_data_dir}  (SEED={settings.seed})")
    print(
        f"stops={len(bundle.stops)} routes={len(bundle.routes)} (x2 directions) buses={len(bundle.buses)} "
        f"drivers={len(bundle.drivers)} users={len(bundle.users)} students={len(bundle.student_profiles)}"
    )
    for sid, routes in shared_stops(bundle).items():
        print(f"  shared {sid} {bundle.stop(sid).name:<28} {', '.join(routes)}")
    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nseed OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
