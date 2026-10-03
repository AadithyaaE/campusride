# CampusRide architecture

This document is the source of truth. Changes to it are deliberate decisions,
recorded in the decision log at the end.

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11 (`>=3.11,<3.15`), FastAPI, Pydantic v2, Motor/MongoDB, pytest |
| Student web / Admin web | React + Vite + TypeScript |
| Driver app | React Native + Expo |
| Shared | `packages/api-client` (generated from OpenAPI), `packages/web-ui` |
| Map | Leaflet + OpenStreetMap tiles behind a `MapView` adapter (Google Maps later) |
| Auth | `AUTH_MODE=mock` (HMAC tokens for seeded users) → Firebase Auth in Phase 7 |
| Real-time | REST for commands/queries, WebSocket `/api/v1/ws` with topic subscriptions |
| Database | MongoDB 7 in Docker |

## Principles

1. **The simulator acts like a real driver.** Synthetic buses produce telemetry
   that goes through the *same* ingestion function as `POST /driver/telemetry`,
   authenticated as a driver principal bound to the bus. Switching a bus from
   synthetic to a real phone is `Bus.source = "device"` — nothing downstream changes.
2. **Linear referencing.** Every route is a polyline with cumulative distances;
   every stop and every bus has a distance along it. ETA, "has it passed?",
   matching, deviation and recovery are arithmetic on those distances.
3. **Intelligence only sees telemetry / BusState**, never simulator internals.
4. **One clock.** `Clock` protocol → `RealClock`, `SimClock` (1/2/5/10/20×,
   pause, fast-forward, reset), `ManualClock` (tests). Nothing else calls `datetime.now()`.
5. **No paid or runtime-external services.** Route geometry is pre-authored and committed.
6. **Backend is the source of truth.** Routers are thin; logic lives in services;
   persistence only via repositories; modules communicate via domain events.

## Backend layout

```
app/
  main.py            app factory + lifespan (Mongo, indexes, clock, event bus)
  deps.py            AppContainer + FastAPI dependencies (repos, clock, principal, roles)
  core/              config, clock, events, auth, db, ids, errors
  models/            domain documents, events.py (event catalogue), api/ (DTOs)
  repositories/      base.py (protocols), mongo/, memory/ (same behaviour, for tests)
  geo/               distance, local frame, polyline, projection
  seed/              load / validate / persist the synthetic world
  services/          reference (P1); tracking, matching, eta_service, bus_comparison_service, commute_decision_service, student_location,
                     capacity, recovery, deviation, alerts (later phases)
  api/v1/            health, auth, stops, routes (P1); more per phase
  realtime/ simulator/ ml/   (later phases)
```

## Student transport assignment

```
College/admin assigns → student_assignments {student, bus, route direction, boarding stop}
Student signs in → GET /students/me/assignment → My Bus (read-only)
Phase 2+: live tracking follows that specific assigned bus
```

Students never select or edit their bus, route or stop.

## Routes and directions

A **physical route** (`R1`) stores its geometry once, in the TO_CAMPUS
orientation, plus two **directions**:

| variant | direction | label | geometry |
|---|---|---|---|
| `R1` | `to_campus` | R1 — To Campus | stored path |
| `R1-E` | `from_campus` | R1-E — From Campus | same path reversed |

Each direction lists its stops in travel order, with `distance_along_m` in its
own frame: `d_from_campus = length_m − d_to_campus` (exact). Trips reference
`route_id`, `direction` and `variant_id`.

## Time

* Timestamps are stored as timezone-aware **UTC**.
* Schedules, the simulation clock, UI, alerts and student-facing ETAs use **Asia/Kolkata**.
* `SIM_START_DATE=auto` → the next weekday after today, at `SIM_START_TIME` (07:15).
  `YYYY-MM-DD` overrides it.
* Randomness comes from `clock.rng(*scope)` = f(SEED, scope). Scopes use
  scenario / bus / time-of-day — never the calendar date — so a scenario
  behaves identically whichever day it runs.
* Telemetry is a time-series collection with a 30-day TTL.

## Data flow (target, Phases 2–6)

```
SimClock tick → BusAgent (speed = base × traffic(t) × driver noise) → noisy GPS
  → TelemetryIngestService.ingest()      ◄── same function as POST /driver/telemetry
  → telemetry (time series) + TelemetryReceived
  → tracking: windowed projection → BusState (distance_along, off_route, next stop, stale)
  → BusStateUpdated / StopArrived / StopDeparted
  → eta → EtaUpdated │ deviation → Deviation* │ capacity → OccupancyChanged │ alerts → AlertCreated
  → realtime: topic fan-out → WS envelope {type, topic, ts, data}
  → student-web (route:R1, stop:S07, user:me) · admin-web (admin:fleet) · driver-app (bus:B03)
Matching / comparison / decision / recovery are request-time services over BusState + routes + ETA.
```

## Synthetic data

Committed under `backend/data/seed/`:

| File | Origin |
|---|---|
| `stops.geojson`, `routes.geojson` | authored once by `scripts/author_routes.py` from `scripts/route_spec.json` via public OSRM |
| `campus.json`, `buses.json`, `drivers.json`, `admins.json`, `schedules.json`, `traffic_profiles.json` | hand-written |
| `students.json` | generator config; 300 students are generated from SEED |

`app.seed.validate` enforces the integrity rules: counts, unique ids,
stops within 50 m of every route serving them, monotonic stop distances,
exact evening reversal, 5–6 shared stops (at least one with 3 routes),
≥2 buses per route, trips inside the 07:00–08:30 and 16:30–18:00 windows,
no overlapping trips per bus.

## Decision log

| # | Decision |
|---|---|
| Q1 | Repository root is `sih_travel_app/`; app name CampusRide. |
| Q2 | Fictional campus on the real Chennai road network; geometry authored once via public OSRM and committed; runtime is offline. |
| Q3 | `requires-python >=3.11,<3.15`; Docker image `python:3.11-slim`; no 3.12+-only features; uv optional. |
| Q4 | `SIM_START_DATE=auto` = next weekday, 07:15 IST; randomness independent of calendar date; 30-day telemetry TTL. |
| Q5 | Evening trips from day one: `R1-E`…`R6-E` reuse morning geometry reversed (12 directions, 6 physical routes). |
| Q6 | Physical route identity (`R1`) is separate from direction (`to_campus` / `from_campus`). |
| Q7 | Store UTC; present Asia/Kolkata. |
| Q8 | No runtime routing/geocoding; the map must degrade gracefully if tiles are unavailable. |
| Q9 | Campus, stops, routes, buses, drivers, students and schedules are fictional. |
| Q10 | 12 buses, 2 per physical route, so students see "my bus" + "other buses on my route". |
| Q11 | ~6 shared stops, some by 2 routes and some by 3. |
| Q12 | Sim speeds 1/2/5/10/20×, default 5×; sim time independent of wall-clock. |
| Q13 | Default scenario MORNING_RUSH (07:15 departures, 07:40–08:10 peak, delays, multiple buses at shared stops) — Phase 2. |
| P1-a | Road classes: OSRM's demo profile reports similar speeds for trunk and primary roads, so speed separates arterial/local and highway spans (OMR, ECR) are declared per route in `route_spec.json`. |
| P1-b | `Route.segment_classes` and `TrafficProfile.free_flow_kmph` added so the traffic model can be keyed by road class. |
| P1-c | Reference-data codes are document ids (`S08`, `R1`, `B03`, `D03`, users `U-S0001`/`U-D01`/`U-A01`); trip ids `T-YYYYMMDD-<variant>-HHMM`. |
| P1-d | Shared stops for routes that approach a junction from different roads were placed where every serving route passes (e.g. Medavakkam stop sits just east of the junction). |
| F1-a | Student web app built on the real Phase 1 API before the simulator; types generated from the backend OpenAPI schema (`npm run gen:api`) and validated at runtime. |
| F1-b | Typed client and MapView adapter live in `apps/student-web` until a second app needs them, then move to `packages/api-client` / `packages/web-ui`. |
| F1-c | ~~Student-selected stop/route~~ — **superseded by F1-e.** |
| F1-e | **College-assigned bus is the only transport model.** `StudentAssignment` (`student_assignments`, `_id` = student id): `assigned_bus_id`, `assigned_route_direction_id`, `boarding_stop_id`, `assigned_by`, `assigned_at`. Validated: bus active and on that route (`Bus.default_route_id`), stop served by the direction and not its final stop. Students read it via `GET /students/me/assignment` (student-only, GET-only); creation/changes are admin-side (later). Seed assigns 288/300 deterministically. `PUT /students/me/stop` from the original plan is dropped; `StudentProfile.preferred_route_ids`/`home_stop_id` remain only as seed inputs (unused by the API) and are candidates for removal. |
| F1-d | TypeScript pinned to 5.9 (typescript-eslint and openapi-typescript do not support TS 6/7 yet). |
| F2-a | `GET /api/v1/buses` (fleet reference data: id, reg_no, capacity, route_id, status — no secrets, no live state) added early so the dashboard shows real bus numbers/capacities. Live state stays `GET /buses/{id}/state` (Phase 2). |
| F2-b | ~~Frontend-only demo simulator~~ — **superseded by F3-a.** Originally: dashboard live values came from a deterministic, frontend-only demo simulator (`apps/student-web/src/demo`) using real route geometry + the real fleet + the real assignment; refreshed by local polling (3 s), clearly labelled "Simulated". It is deleted when Phase 2–6 provide the real data (WebSocket, ETA, decision, QR occupancy, deviation, alerts). |
| F3-a | **Backend synthetic simulator is the single source of live bus state.** `app/simulator/` (pure, deterministic per-trip timelines on real geometry: road-class × time-of-day traffic × seeded per-bus driver factor, route dwell times, seeded "hold" delays, seeded occupancy) + `app/services/bus_simulator.py` (lifecycle, emission on a fixed sim-time grid, controls). Its only output is telemetry through `TelemetryIngestService.ingest` — the same function as `POST /driver/telemetry`. The browser simulator was deleted. |
| F3-b | Tracking derives `BusState` from fixes only: windowed projection (window grows with the gap between fixes), current/next stop, DWELLING within `STOP_ARRIVAL_RADIUS_M`, trip ACTIVE/COMPLETED, `delay_s` vs. the timetable. Status values reuse `BusStatus` (at_depot/en_route/dwelling/completed…); "DELAYED" is `schedule_status` (≥ 5 min late) and "PAUSED" is the simulation clock state — no duplicate enums. |
| F3-c | One simulator per process: created with the app container, prepared + started by the FastAPI lifespan, refuses a second running instance in the process, cancelled on shutdown. Reset/startup replays the service day from `SIM_START_TIME` and clears only *simulated* buses' state/telemetry. Run the API with a single worker. `SIM_AUTOSTART` now defaults to `true`. |
| F3-d | Telemetry may carry an optional driver-reported `occupancy` headcount (synthetic in the simulator) until QR boarding (Phase 5). A finished trip sends one final fix, then its "phone" stays silent until the next trip's pre-departure window. |
| F3-e | `/api/v1/sim/*` controls are dev/demo: any signed-in user when `APP_ENV` is dev/test, admins otherwise. The dashboard polls `GET /buses` every 3 s until the WebSocket feed exists. |
| F4-a | **Stop + route matching is a backend service** (`app/services/matching.py`) over the tracked `BusState` (route direction + distance along it) and each direction's ordered stops — no geometry scans, no lat/lng proximity. A bus serves a stop ⇔ its CURRENT route direction (`R2` ≠ `R2-E`) contains it. `stops_around` is shared with tracking so current/next stop has one definition. |
| F4-b | Proximity to a stop is `StopProximity` (far_from_stop / approaching_stop / at_stop / passed_stop), orthogonal to `BusStatus`. Thresholds: at ≤ `STOP_ARRIVAL_RADIUS_M` (40 m) along the route, approaching ≤ `STOP_APPROACHING_M` (1 km) ahead; a completed trip has passed every stop but its last. |
| F4-c | `GET /stops/{id}/buses[?direction=]` and `GET /students/me/stop/buses` (student-only, read-only; explicit `unassigned` response). "Other buses" for a student = same direction as their assignment, information only — the assignment never changes. The dashboard displays these results; only ETA/decision/recommendations/alerts remain interim estimates in the browser. |
| F5-a | **ETA is a deterministic backend service** (`app/services/eta_service.py`, no ML) on top of F4 matching. Model time = Σ over road classes of remaining distance / (free-flow speed × traffic-profile factor at the current sim time of day). Effective speed blends the bus's current speed (weight 0.5 within 1.5 km, 0.25 further, 0 when stopped) with the model speed, clamped to 2.5–22 m/s. Plus dwell at intermediate stops (and half the current stop's dwell while dwelling). |
| F5-b | "Historical average" = the **timetable's** planned stop-to-stop time (`scheduled_offset_at`) — a planned, not observed, average; no history store yet. Delay is applied ONCE, only to the timetable term: `delay_factor = clamp(1 + delay_s / max(scheduled_elapsed, 600 s), 0.8, 1.5)`. Combined = 0.65 × (travel + dwell) + 0.35 × timetable × delay_factor (model only when there is no timetable). A bus still at the depot adds the wait until its scheduled departure. |
| F5-c | Output: `eta_seconds`, `eta_minutes` (integer, `ceil`, 0 under 60 s), `estimated_arrival_time` (UTC, sim clock), `computed_at`, status predicted/at_stop/passed/completed, confidence high/medium/low (a **prototype heuristic score**, not a calibrated probability), traffic level Low (≤ 1.15) / Moderate (≤ 1.5) / High, `traffic_factor`, `delay_factor`, and a breakdown. |
| F5-d | Endpoints: `GET /buses/{id}/eta?stop_id=` (404 unknown bus/stop, 409 no live state or stop not on the bus's current direction), `GET /stops/{id}/arrivals[?direction=]`, `GET /students/me/arrivals` (student-only, assignment-derived stop + direction, explicit unassigned response). Arrivals are sorted at_stop → predicted (by ETA) → completed → passed. The dashboard polls `/students/me/arrivals`; `/students/me/stop/buses` stays for matching-only clients. |
| F5-e | The browser computes **no** ETA: it shows the backend's `estimated_arrival_time` as a whole-minute countdown, advancing sim time from the poll's `computed_at` at the simulation speed (frozen when paused); labels `N min` / `<1 min` / `Arriving` / `Arrived` / `Passed` / `Completed`. "Will I make my bus?", the walk time and alerts remain interim rules over the backend ETA. |
| F6-a | **Multi-bus comparison is a backend layer on top of F4 + F5** (`app/services/bus_comparison_service.py`): it takes `EtaService.student_arrivals` (assignment → F4 matching → F5 ETA) and adds only occupancy %, crowding, an internal cost and indicators. No matching, distance or ETA is recomputed; no new bus-state representation (each option is the F5 `ArrivalOut` + comparison fields). Replaces the empty `services/comparison.py` placeholder. |
| F6-b | Options = buses whose F5 status is `predicted`/`at_stop`; `passed`/`completed` are listed under `excluded`. Stale (> `BUS_STALE_AFTER_S`) and broken-down buses are listed but not *comparable* (no FASTEST / LEAST_CROWDED / BEST_ALTERNATIVE). Those three need ≥ 2 comparable options. Options keep F5 arrival order — there is no overall ranking. Occupancy % = occupancy / capacity × 100 (capacity 0 → `Unknown`); crowding Low < 60 % ≤ Medium < 80 % ≤ High (the frontend occupancy bar uses the same bands). |
| F6-c | Internal cost (minute-equivalents, lower is better, never exposed): ETA min + 0.20 per occupancy point above 50 % + 30 if full (≥ 100 %) + 5 if capacity unknown + 0.25 per minute of delay (> 0; a reliability risk — the ETA already contains expected lateness) + 0/1/3 for high/medium/low ETA confidence − 2 for the assigned bus. FASTEST = lowest ETA; LEAST_CROWDED = lowest occupancy %; ASSIGNED = the college-assigned bus; **BEST_ALTERNATIVE = lowest cost among comparable, not-full buses other than the fastest, only if within 15 of the fastest's cost** (so it is never just "the second-fastest", may be the assigned bus, and may be absent). Ties → ETA, then bus id. `trade_off` text compares each option to the fastest ("+3 min vs B07 · 22 more seats free"). Prototype decision support, not ML. |
| F6-d | `GET /students/me/bus-options` (student-only; explicit `unassigned`; `assigned_bus_note` explains a passed/finished/between-trips assigned bus). `GET /students/{id}/bus-options`: the student themself or an admin; another student gets 403 whether or not the id exists (no probing); admin → 404 for unknown/non-student ids. |
| F6-e | Student web: "Bus options" card (ETA countdown, occupancy + crowding, indicator badges, traffic / stops away / delay, trade-off line) polled with the other live data. React computes no score and does not re-rank. Selecting a card only rings and centres that bus on the map. The interim browser `recommend()` rule is removed; the interim "alternative" alert now uses the backend BEST_ALTERNATIVE. |
| F7-a | **Commute decision is a backend rule engine** (`app/services/commute_decision_service.py`, pure `evaluate_commute` + service) for the ASSIGNED bus at the ASSIGNED stop. It consumes Feature 6 `for_student` (→ F5 arrivals → F4 matching) — no matching / ETA / occupancy recomputed. No ML, no probability. Replaces the empty `services/decision.py` placeholder and the browser's interim `decide()` / `assumedWalkMin`. |
| F7-b | Student location: **synthetic only** (`app/services/student_location.py`): a fixed point 60–800 m from the boarding stop, from `derive_seed(SEED, "student-location", student_id)`, always `source="synthetic"` and labelled "demo, not GPS". `STUDENT_LOCATION_MODE=off` → `LOCATION_UNAVAILABLE` (never assumed at the stop). Walking distance = existing `geo.walking_distance_m` (straight line × 1.3 street-detour factor; no pedestrian routing). Walking speed = the student's seeded profile `walk_speed_mps` (1.1–1.5), else `WALKING_SPEED_MPS` (1.4). |
| F7-c | Rules, first match wins, on absolute timestamps: no live bus → UNKNOWN; not serving the stop in the assigned direction / F5 `passed` / `completed` / predicted arrival already elapsed → **MISSED** (overrides timing); no ETA → UNKNOWN; no location → LOCATION_UNAVAILABLE; speed ≤ 0 → UNKNOWN; else `student_arrival = now + walk`, `required_arrival = bus_arrival − COMMUTE_SAFETY_BUFFER_S` (120 s): **YES iff student_arrival < required_arrival**, otherwise **RISK** (exact equality = RISK; a walk longer than the ETA is RISK, not MISSED — the bus has not passed). A YES is downgraded to RISK for stale telemetry (`BUS_STALE_AFTER_S`, shared `tracking.is_stale`), breakdown or deviation. Delay is NOT added again (already in the F5 ETA); exposed for explanation only. |
| F7-d | `GET /students/me/commute-decision` (student-only; no bus/stop parameters; explicit `unassigned`) and `GET /students/{id}/commute-decision` (self or admin; other student 403 even for unknown ids; admin 404 for unknown). Authorization shared with F6 (`_authorize_student_view`). Minutes are whole: walk and ETA rounded up, `0` = "<1 min". `alternatives_available` counts F6 options — the decision never switches buses (recovery is Feature 8). |
| F7-e | Student web: the existing "Will I make my bus?" card renders the backend decision as given (YES ✓ / RISK ⚠ / MISSED ✕ / Location unavailable / Can't tell yet), "Bus arrives in" ticks from the backend arrival timestamp (`countdown.ts`), walking time, safety buffer, reason, "Simulated location" label, and a "See bus options" link when RISK/MISSED. The interim alternative alert now keys off the backend decision. |

