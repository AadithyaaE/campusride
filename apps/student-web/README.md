# CampusRide — Student web app

React 19 + Vite + TypeScript + Leaflet/OpenStreetMap. Talks only to the CampusRide
FastAPI backend; it holds **no domain data of its own** (no copies of stops,
routes or buses — everything is fetched).

```bash
npm install
cp .env.example .env      # VITE_API_BASE_URL=http://localhost:8000/api/v1
npm run dev               # http://localhost:5173  (backend must be running)
```

| Script                                        | Does                                                                              |
| --------------------------------------------- | --------------------------------------------------------------------------------- |
| `npm run dev` / `build` / `preview`           | Vite dev server / production build / serve the build                              |
| `npm test`                                    | Vitest + Testing Library (jsdom)                                                  |
| `npm run typecheck` · `lint` · `format:check` | `tsc` · ESLint · Prettier                                                         |
| `npm run gen:api`                             | Regenerate `src/api/schema.gen.ts` from the **running** backend's `/openapi.json` |

## Backend contract (endpoints actually used)

| Endpoint                                                                           | Used for                                                                                                                                                                                                                                                                                 |
| ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /health` (public)                                                             | Header "Backend connected" pill (polled every 15 s)                                                                                                                                                                                                                                      |
| `POST /auth/mock-login`                                                            | Sign-in screen (seeded student accounts)                                                                                                                                                                                                                                                 |
| `GET /me`                                                                          | Restoring the session on every load / refresh                                                                                                                                                                                                                                            |
| `GET /students/me/assignment`                                                      | **My Bus** — the college-assigned bus, route direction and boarding stop (read-only)                                                                                                                                                                                                     |
| `GET /stops`, `GET /stops/nearby`, `GET /stops/{id}/routes`                        | Stop markers, Stops tab, stop cards                                                                                                                                                                                                                                                      |
| `GET /routes`, `GET /routes/{id}`                                                  | Route polylines (geometry) + ordered stops per direction                                                                                                                                                                                                                                 |
| `GET /buses`                                                                       | The fleet **with live state** (position, status, current/next stop, occupancy, delay) — polled every 3 s                                                                                                                                                                                 |
| `GET /students/me/arrivals`                                                        | **Backend ETA + stop matching** for the student: assigned bus and every bus serving the boarding stop (direction-aware), sorted by backend ETA, each with `eta` (minutes, arrival time, confidence, traffic level) — polled every 3 s                                                    |
| `GET /students/me/bus-options`                                                     | **Backend multi-bus comparison** for the boarding stop: per bus occupancy %, crowding, delay, and FASTEST / LEAST CROWDED / ASSIGNED / BEST ALTERNATIVE indicators + trade-off text — polled every 3 s, shown as the Bus options card                                                    |
| `GET /students/me/commute-decision`                                                | **Backend "Will I make my bus?"** for the assigned bus: decision, reason, walking distance/time, bus ETA + arrival time, safety buffer — polled every 3 s                                                                                                                                |
| `GET /students/me/boarding` · `POST /boarding/scan`                                | **QR boarding (prototype)**: scanner state for the assigned bus / current trip, and the ONE boarding endpoint — the simulated scanner sends `{student_id, bus_id, trip_id, timestamp}` built from the backend's data; the backend validates and counts                                   |
| `GET /students/me/recovery-options`                                                | **Backend missed-bus recovery** (at risk / missed / ≥ 5 min late): recommended bus + up to 3 other options serving the SAME assigned stop, with ETA, occupancy, status and reason — polled every 3 s; shown as the recovery card. Suggestions never change the assigned bus              |
| `GET /buses`, `GET /students/me/arrivals` (`route_status`, `deviation_distance_m`) | **Backend route deviation** (Feature 10) of the assigned bus — shown on the My Bus card as On planned route / Minor / Major deviation · N m off route; never measured in the browser                                                                                                     |
| `GET /alerts?limit=20` · `PATCH /alerts/{id}/read`                                 | **Backend in-app notifications** (Feature 11): bus approaching / delayed / capacity / route deviation / missed / alternative available — the student's own alerts only, polled every 3 s; the Notifications panel shows them and marks them read. No alerts are generated in the browser |
| `GET /sim/status`, `POST /sim/start` · `pause` · `reset`, `PUT /sim/speed`         | Dashboard **Demo mode** (dev/demo only; the backend decides who may use them)                                                                                                                                                                                                            |

Types are **generated** from the backend OpenAPI schema (`src/api/schema.gen.ts`,
aliased in `src/api/types.ts`) and responses are checked at runtime
(`src/api/guards.ts`). All HTTP goes through `src/api/client.ts`.

## Student Dashboard (home tab)

My Bus live card · "Will I make my bus?" · quick actions (view boarding stop,
view all buses, **Scan Boarding QR** (simulated scanner → `POST /boarding/scan`), view route — **no
"change stop"**) · alerts · other buses at the boarding stop / all buses ·
live map with every bus (assigned bus highlighted) · Demo mode.

| Data                                                                                                                                                   | Source                                                                                                                                                                         |
| ------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Assigned bus, route direction, boarding stop                                                                                                           | **Backend** `GET /students/me/assignment`                                                                                                                                      |
| Bus positions, status, current/next stop, occupancy, schedule delay, last updated                                                                      | **Backend** synthetic simulator → telemetry → tracking → `GET /buses`                                                                                                          |
| Route geometry, stop positions along routes                                                                                                            | **Backend** `GET /routes/{id}`                                                                                                                                                 |
| Which buses serve my stop, current / previous / next stop, distance, far / approaching / at / passed, **ETA, arrival time, confidence, traffic level** | **Backend** `GET /students/me/arrivals` (F4 matching + F5 ETA)                                                                                                                 |
| ETA countdown between polls                                                                                                                            | Display only — `src/lib/countdown.ts` ticks the backend's `estimated_arrival_time` at the simulation speed (whole minutes, `<1 min`, `Arriving`, `Arrived`)                    |
| Bus comparison: crowding, indicators, best alternative, trade-off                                                                                      | **Backend** `GET /students/me/bus-options` — displayed as given (no score or ranking in React); selecting a card highlights the bus on the map                                 |
| "Will I make my bus?" (YES / RISK / MISSED), walking time, safety buffer                                                                               | **Backend** `GET /students/me/commute-decision` — rule-based, from a **simulated** student location (demo, not GPS); the card only counts the bus down from `bus_arrival_time` |
| Occupancy, % occupied, seats available                                                                                                                 | **Backend** (`occupancy = synthetic baseline + QR boardings`, capped) — shown as given on the My Bus card, bus lists and scan results; never computed in the browser           |
| Alerts                                                                                                                                                 | **Interim rules over backend data** — `src/features/dashboard/interim.ts`; replaced in Phase 6                                                                                 |

**Live updates** (`src/data/liveFleet.ts`): plain polling of `GET /buses` +
`GET /sim/status` every 3 s — no WebSocket yet, and the browser never computes
bus positions (the former browser-only `src/demo/` simulator was removed in
Feature 3). Everything simulated is labelled "Simulated live tracking".

Unassigned students (`status: "unassigned"`) see _"Your bus assignment is not
available yet."_; the fleet still runs on the map but no bus is shown as theirs.

## Still to come from the backend

| Needed                                                              | Phase        |
| ------------------------------------------------------------------- | ------------ |
| WebSocket push of bus state (replaces polling)                      | 2 (realtime) |
| Deviation detection, production alerts, admin assignment management | 6            |

## My Bus = college-assigned bus (read-only)

Students never choose their bus, route or stop. The college/admin assigns
each student a **bus → route direction → boarding stop**; the backend stores it
(`student_assignments`) and `GET /students/me/assignment` returns it:

```json
{ "student_id": "U-S0001", "status": "assigned",
  "assignment": { "bus": {"id": "B05", "reg_no": "TN 00 CR 1005"},
                  "route": {"route_id": "R3", "route_direction_id": "R3", "direction": "to_campus", ...},
                  "boarding_stop": {"stop_id": "S27", "name": "Sholinganallur Junction", "seq": 8, "stop_count": 10, ...},
                  "assigned_at": "2026-06-01T04:30:00Z" } }
```

`status: "unassigned"` (with `assignment: null`) shows _"Your bus assignment is
not available yet."_ Nothing about the assignment is stored in the browser —
only the session token — and the UI has no control to change it.

## Other assumptions

- **Default direction** in route views — To Campus before 12:00, From Campus after,
  using the backend's clock from `/health` (UI default only).
- **Shared stop** — derived from route details: a non-terminal stop served by
  more than one physical route.
- **Dev-only deep link** — `/?login=student042@campusride.demo` signs in
  directly (ignored in production builds); handy for demos and screenshots.
- The typed client lives in this app for now; it moves to `packages/api-client`
  when a second app (admin/driver) needs it. Likewise `src/map/MapView.tsx` is the
  map adapter destined for `packages/web-ui`.

## Structure

```
src/
  api/        client, generated schema, type aliases, runtime guards, React context
  session/    token store, auth context (mock login, /me), sign-in screen
  data/       network loader (stops + routes + geometry), assignment loader
  map/        MapView adapter (only place importing Leaflet; [lng,lat] → [lat,lng])
  features/   live, mybus, stops, routes panels
  shell/      header, layout, URL view state (?tab=&stop=&route=)
  components/ badges, loading / error / empty / Phase-2 states
  test/       fake backend (fetch) + clearly fake fixtures — not seed data
```

View state (tab, selected stop/route) lives in the URL and the session token in
`localStorage`, so a refresh rebuilds everything from the backend.
