# CampusRide

Intelligent college bus commute assistant — Smart India Hackathon 2026 prototype.

Students see where their college bus is, whether they can catch it, which other
buses serve their stop, and what to do if they miss it. The prototype runs
entirely on **deterministic synthetic data**: a fictional campus on the real
Chennai road network, simulated buses, simulated GPS, development sign-in by default (real password / OIDC authentication configurable). No paid APIs,
no Firebase project, no GPS hardware.

Architecture and decisions: [docs/architecture.md](docs/architecture.md). Cloud deployment (Render · MongoDB Atlas · Vercel · Expo EAS): [docs/deployment.md](docs/deployment.md).


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
curl -X POST localhost:8000/api/v1/auth/dev-login -H "Content-Type: application/json"      -d '{"email":"student001@campusride.demo"}'          # → access_token
curl -H "Authorization: Bearer <token>" localhost:8000/api/v1/stops/S08/routes
```

Demo logins (development sign-in, `AUTH_MODE=dev`; for real email + password sign-in see `docs/authentication.md`): `student001`…`student300@campusride.demo`,
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
apps/driver-app/    React Native + Expo      (Driver App since F12; `npx expo start`)
packages/api-client generated TS client from OpenAPI (Phase 2)
packages/web-ui     shared web components, MapView adapter (Phase 2)
infra/              docker-compose (MongoDB)
scripts/            one-time route authoring (OSRM → GeoJSON)
docs/               architecture and decisions
```

Map data © OpenStreetMap contributors (ODbL).
