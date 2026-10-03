# CampusRide

Intelligent college bus commute assistant — Smart India Hackathon 2026 prototype.

Students see where their college bus is, whether they can catch it, which other
buses serve their stop, and what to do if they miss it. The prototype runs
entirely on **deterministic synthetic data**: a fictional campus on the real
Chennai road network, simulated buses, simulated GPS, mock auth. No paid APIs,
no Firebase project, no GPS hardware.

Architecture and decisions: [docs/architecture.md](docs/architecture.md).

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Backend skeleton, config, clock, MongoDB, seed data, geometry, tests | ✅ done |
| 1b | Student web app (React + Leaflet) on the real Phase 1 API — routes, stops, college-assigned My Bus | ✅ done |
| F2 | Student Dashboard — My Bus live card, "Will I make my bus?", alternatives, alerts, quick actions, live map | ✅ done |
| F3 | Synthetic live bus tracking — backend simulator → telemetry → tracking → `GET /buses` (polled by the dashboard); dev/demo controls | ✅ done |
| F4 | Stop + route matching — backend decides which buses serve a stop (by route direction), current/previous/next stop, far/approaching/at/passed; `GET /stops/{id}/buses`, `GET /students/me/stop/buses` | ✅ done |
| F5 | Backend ETA prediction + multi-bus arrivals — deterministic ETA (distance, traffic profiles × time of day, timetable average, delay, dwell, stops left), confidence, traffic level; `GET /buses/{id}/eta?stop_id=`, `GET /stops/{id}/arrivals`, `GET /students/me/arrivals`; live countdown in the dashboard | ✅ done |
| F6 | Multi-bus comparison — backend compares the buses serving the student's assigned stop (ETA, occupancy %, crowding, delay, confidence) with FASTEST / LEAST CROWDED / ASSIGNED / BEST ALTERNATIVE indicators; `GET /students/me/bus-options` (+ owner/admin `GET /students/{id}/bus-options`); Bus options card linked to the map | ✅ done |
| F7 | "Will I make my bus?" — deterministic commute decision for the ASSIGNED bus (YES / RISK / MISSED; walk from a synthetic demo location, safety buffer, Feature 5 arrival time, Feature 4 passed/completed); `GET /students/me/commute-decision` (+ owner/admin `GET /students/{id}/commute-decision`) | ✅ done |
| F8 | QR-based live capacity — simulated QR scanner (student app) → `POST /boarding/scan` (assignment + active-trip validation, one boarding per student per trip), occupancy = synthetic baseline + QR boardings, `GET /buses/{id}/occupancy`, `GET /trips/{id}/boarding`; first `admin-web` dashboard (live occupancy) | ✅ done |
| F9 | Missed-bus recovery — when the assigned bus is at risk, missed or ≥ 5 min late, the backend offers other buses serving the SAME assigned stop/direction that the student can still catch (Feature 7 walking rules), ranked catchable → ETA → occupancy → on time → distance; `GET /students/me/recovery-options` (+ owner/admin by id); dashboard recovery card. Suggestions never change the assigned bus | ✅ done |
| F10 | Route deviation detection — shortest distance from each bus's TRACKED position to its PLANNED route geometry → NORMAL (≤ 50 m) / MINOR_DEVIATION / MAJOR_DEVIATION (≥ 150 m); `GET /buses/{id}/route-status`; one alert per MAJOR episode (`GET /alerts`, admin); demo controls `POST /sim/route-deviation` (normal / minor / major); admin route map + student "Route" line. The route remains the planned route; demo deviation changes the synthetic bus position, not the route geometry | ✅ done |
| 2 | Simulator, telemetry ingestion, WebSocket, live buses on the student map | next |
| 3 | Stop selection, matching, baseline ETA, multi-bus arrivals | |
| 4 | "Will I make my bus?", missed-bus recovery | |
| 5 | Driver app, trip start/end, GPS, QR, capacity | |
| 6 | Deviation detection, alerts, admin dashboard, sim controls | |
| 7 | Synthetic history, scikit-learn ETA, Firebase Auth adapter | |

## How the pieces connect

Today (Phase 1):

```
MongoDB (Docker, seeded)  →  FastAPI /api/v1  →  Student React app (Vite, Leaflet + OSM)
                              REST + mock auth      fetches stops, routes, geometry, /me
```

Live bus positions (Feature 3) — synthetic, but through the real pipeline:

```
SimClock → bus simulator ──(same function as POST /driver/telemetry)──▶ telemetry ingestion
        → tracking → BusState (MongoDB) → GET /buses  ◀── polled every 3 s by the Student app
```

The simulator starts with FastAPI (exactly one per process), replays the
morning from 07:15 at 5× and is controlled from the dashboard's **Demo mode**
(start / pause / reset / 1–20×) or `/api/v1/sim/*`. A WebSocket replaces the
polling later.

The frontend never holds domain data of its own: stops, routes, geometry and the
signed-in user all come from FastAPI, which reads MongoDB.

## Run the full demo

Prerequisites: Docker Desktop, Python 3.11+ (3.12 fine locally), Node 20+,
optionally [uv](https://docs.astral.sh/uv/). Commands are for Git Bash on Windows
(use `.venv/bin/...` on macOS/Linux).

```bash
# 1. Start MongoDB
docker compose -f infra/docker-compose.yml up -d

# 2. Backend env + seed the synthetic world (replaces all CampusRide data)
cd backend
uv venv --python 3.12 .venv && uv pip install --python .venv -e ".[dev]"
#   or: python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/python scripts/seed_db.py

# 3. Start FastAPI  → http://localhost:8000/docs   (leave running)
.venv/Scripts/python -m uvicorn app.main:app --reload

# 4. In a second terminal: start the student app  (leave running)
cd apps/student-web
npm install
cp .env.example .env          # VITE_API_BASE_URL=http://localhost:8000/api/v1
npm run dev

# 5. Open http://localhost:5173 and continue as student001@campusride.demo
```

Use `localhost` (not `127.0.0.1`) for the frontend: the backend's CORS allow-list
is `http://localhost:5173,http://localhost:5174` (`CORS_ORIGINS`).

Optional: copy `.env.example` to `.env` (repo root) for backend settings. Defaults work as-is.

Try the API directly:

```bash
curl -X POST localhost:8000/api/v1/auth/mock-login -H "Content-Type: application/json"      -d '{"email":"student001@campusride.demo"}'          # → access_token
curl -H "Authorization: Bearer <token>" localhost:8000/api/v1/stops/S08/routes
```

Demo logins (mock auth): `student001`…`student300@campusride.demo`,
`driver01`…`driver12@campusride.demo`, `admin1` / `admin2@campusride.demo`
(the student app accepts student accounts only).
Every 25th student (`student025`, `student050`, … `student300`) has **no bus
assignment yet**, to demo the unassigned state; all others are assigned a bus
and boarding stop by the (synthetic) college transport office.

## Tests

```bash
# frontend (from apps/student-web)
npm test && npm run typecheck && npm run lint && npm run format:check

# backend (from backend/)
cd backend
.venv/Scripts/python -m pytest                    # unit + API (no DB needed)
.venv/Scripts/python -m pytest -m integration     # MongoDB (Docker must be up)
.venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .
```

## Synthetic world (SEED=42)

* **Campus:** CampusRide Institute of Technology (fictional), Perumbakkam, Chennai — `Asia/Kolkata`.
* **6 physical routes × 2 directions** (`R1`…`R6` to campus, `R1-E`…`R6-E` from campus; evening reuses the geometry reversed), 9.8–17.8 km on real roads (OMR, ECR, Velachery–Tambaram Rd, …).
* **39 stops**, 6 deliberately shared: Medavakkam Koot Road and Sholinganallur Junction (3 routes each); Sembakkam, Thiruvanmiyur, Tidel Park, Thoraipakkam (2 each).
* **12 buses** (2 per route), 12 drivers, 300 generated students, 2 admins.
* **Bus assignments** (college-assigned, read-only for students): 288 students → bus + route direction + boarding stop, balanced per bus within capacity; 12 left unassigned.
* **Schedule:** morning departures 07:15–07:35 (arrive by 08:30), evening 16:30–17:00 (arrive by 18:00).
* **Traffic:** per-road-class hourly profile; arterial roads drop to 0.55× free-flow around 08:00.

Route geometry was authored once with `scripts/author_routes.py` (public OSRM,
OpenStreetMap data) and committed to `backend/data/seed/*.geojson`.
**Running the app never calls OSRM or any other external service.**

## Repository layout

```
backend/            FastAPI app (app/), seed data (data/), scripts, tests
apps/student-web/   React + Vite + TS + Leaflet student app (Phase 1b; live buses in Phase 2)
apps/admin-web/     React + Vite + TS        (live occupancy since F8; rest Phase 6) — :5174
apps/driver-app/    React Native + Expo      (Phase 5)
packages/api-client generated TS client from OpenAPI (Phase 2)
packages/web-ui     shared web components, MapView adapter (Phase 2)
infra/              docker-compose (MongoDB)
scripts/            one-time route authoring (OSRM → GeoJSON)
docs/               architecture and decisions
```

Map data © OpenStreetMap contributors (ODbL).
