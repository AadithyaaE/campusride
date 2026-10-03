# admin-web

College transport admin dashboard (React + Vite + TypeScript). **Prototype** — started in
Feature 8 with live occupancy; the rest of the admin scope (assignments, alerts, deviations)
arrives in Phase 6.

## Run

```bash
npm install
npm run dev          # http://localhost:5174 (backend CORS already allows it)
```

Sign in with a mock admin account, e.g. `admin1@campusride.demo` (no password; non-admin
accounts are refused). Backend URL: `VITE_API_BASE_URL` (default `http://localhost:8000/api/v1`).

## What it shows

**Live occupancy** — every bus on an active trip: bus, route direction, trip, occupancy /
capacity, % occupied, seats available, QR boardings on the trip, last update (campus time).
It polls `GET /api/v1/buses` every 3 s — the same backend state the student dashboard reads —
so a QR scan appears on the next poll. Click a trip to see its boarding events
(`GET /api/v1/trips/{trip_id}/boarding`, admins see every event).

Every number is displayed exactly as the backend computed it (`backend/app/services/capacity.py`):

```
occupancy = min(capacity, synthetic simulator headcount + QR boardings on the current trip)
```

Nothing is counted or derived in the browser, and there is no separate frontend state.

**Route deviation** (Feature 10) — a _Route status_ column (Normal / Minor deviation /
Major deviation + metres off route). Select a bus (its number) to open the route monitor:
status, distance, fix time and a Leaflet map of the backend's planned route, the tracked bus
position and the nearest point of the route (`GET /api/v1/buses/{id}/route-status`). The
demo buttons **Normal / Simulate Minor Deviation / Simulate Major Deviation** call
`POST /api/v1/sim/route-deviation` for that bus: the backend simulator moves the bus's
SYNTHETIC GPS sideways — the route remains the planned route. **Active alerts**
(`GET /api/v1/alerts?active=true`) shows the one alert raised when a bus enters a major
deviation; it clears when the bus returns. Nothing is measured or classified in the browser.

## Checks

```bash
npm test             # vitest
npm run typecheck && npm run lint && npm run format:check && npm run build
npm run gen:api      # regenerate src/api/schema.gen.ts from a running backend
```

## Known limitations

- Mock authentication only (as the rest of the prototype).
- The small API client (`src/api/client.ts`) mirrors the student app's client; moving both
  into `packages/api-client` is planned.
- Polling, not WebSockets.
