"""Deterministic synthetic bus movement model (pure functions, no I/O).

* ``bus_agent``  — per-trip timelines on real route geometry; position at any sim time
* ``traffic``    — road class × time-of-day × per-bus driver speed
* ``passengers`` — synthetic occupancy profile per trip
* ``gps_noise``  — deterministic GPS jitter

The service that runs it (lifecycle, telemetry emission, controls) is
``app.services.bus_simulator``; its only output is telemetry sent through the
same ingestion function as ``POST /api/v1/driver/telemetry``.
"""
