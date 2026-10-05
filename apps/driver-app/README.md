# driver-app

CampusRide **Driver App** (Feature 12) — React Native + Expo + TypeScript.

A deliberately simple control surface for the **existing** backend: the driver signs in,
sees their assigned bus and route, presses **START TRIP**, drives, and presses
**STOP TRIP**. Everything shown comes from the backend; the app never simulates a bus,
never makes coordinates and never decides anything.

> **Feature 12 uses synthetic GPS. Actual device GPS is not implemented yet.**
> The app requests no location permission and does not use `expo-location`. "GPS: LIVE ·
> SIMULATED GPS" means fresh telemetry from the backend simulator.

## Run

```bash
# 1. backend (MongoDB + API) — see the root README
# 2. this app
npm install
npx expo start            # press a (Android emulator) / i (iOS) or scan with Expo Go
```

Set the backend URL in `.env` (see `.env.example`):

```
EXPO_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1   # Android emulator: http://10.0.2.2:8000/api/v1
                                                        # phone (Expo Go): http://<PC LAN IP>:8000/api/v1
```

**Demo account** (development sign-in, no password, `AUTH_MODE=dev`; email + password with `AUTH_MODE=password`): `driver07@campusride.demo` → **Arun Kumar**,
**Bus B07**, route **R4 Guindy – Taramani**. B07 is the driver-controlled bus by default
(`SIM_DRIVER_CONTROLLED_BUSES=B07` on the backend). Other seeded drivers
(`driver01…12@campusride.demo`) can sign in too; their buses follow the automatic demo
schedule, so their trips are shown read-only.

## How it works

```
Driver App ──POST /driver/trip/start──▶ BusSimulator (existing) ──synthetic GPS──▶
TelemetryIngestService (same path as POST /driver/telemetry) ──▶ tracking ──▶ BusState
        ▲                                                                  │
        └──────────── GET /driver/me every 3 s (driving screen only) ◀─────┘
                       (Student and Admin dashboards read the SAME BusState)
```

| Screen                   | Backend                                                                                    |
| ------------------------ | ------------------------------------------------------------------------------------------ |
| Sign in                  | `GET /auth/config`, `POST /auth/dev-login` or `POST /auth/login`, `GET /me` (drivers only) |
| Driving (READY / ACTIVE) | `GET /driver/me` — profile, bus, route, trip, speed, GPS freshness, passengers, next stop  |
| START TRIP               | `POST /driver/trip/start` — the backend starts the driver's own next trip                  |
| STOP TRIP                | `POST /driver/trip/stop` — the trip is finalized where the bus is; telemetry stops         |
| SIMULATE GPS             | `POST /driver/simulate-gps` — the backend simulator emits one extra fix now                |
| View route               | `GET /driver/route` — ordered stops, passed / current / next                               |
| Passengers               | `GET /buses/{id}/occupancy` (Feature 8) + `GET /trips/{id}/boarding` (count)               |

- The UI changes only after the backend confirms an action; on failure it shows a short
  message ("Trip could not be started. Please try again.") and re-reads the real state.
- If the backend is unreachable it shows **Connection unavailable** — it never pretends a
  trip is active. There is no offline mode.
- The session token is kept in memory only; nothing about trips, positions, speed or
  occupancy is stored on the device.
- The driver never picks a bus, route, trip or student — all come from the backend.

## Checks

```bash
npm test                 # jest-expo + React Native Testing Library
npm run typecheck        # tsc --noEmit
npm run lint             # expo lint (eslint-config-expo)
npm run format:check
npm run build            # expo export (Android JS bundle) as a production build check
npm run gen:api          # regenerate src/api/schema.gen.ts from a running backend
```

## Limitations / future

- Synthetic GPS only. Real phone GPS (`expo-location`, background location, batching to
  `POST /driver/telemetry`) is a future feature — the backend ingestion path already exists.
- Polling (3 s) instead of WebSockets.
- External-provider (OIDC) sign-in has no UI in the app yet; the token is kept in memory only (re-sign-in after an app restart).
- No map in the app (a stop list is enough for the driver); the web apps draw the map.
