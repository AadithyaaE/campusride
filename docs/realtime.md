# Real-time updates (Feature 14)

CampusRide pushes backend state changes to the Student, Driver and Admin apps over one
WebSocket. The socket **distributes** backend facts; it never computes them.

```
Simulator / Driver phone
        │  POST /driver/telemetry  (or the simulator, in-process — same call)
        ▼
TelemetryIngestService → tracking → BusState (MongoDB)        AlertService · BoardingService
        │                                                       │
        └──── publish ────▶  InProcessEventBus  ◀─── publish ───┘   (the ONE existing bus)
                                   │
                                   ▼
                       RealtimeHub (subscriber)  app/realtime/hub.py
                                   │  audience · change detection · coalescing
                                   ▼
                       ConnectionManager          app/realtime/manager.py
                                   │  per-socket bounded queue + writer task
                                   ▼
                       /api/v1/ws  ──▶  Student · Driver · Admin
```

## Endpoint and authentication

`ws://<host>/api/v1/ws` (`wss://` behind TLS).

1. Connect, then send `{"type": "auth", "token": "<bearer token>"}` as the **first
   message** within `WS_AUTH_TIMEOUT_S` (10 s). It is the same token the REST API accepts
   (mock token today, Firebase later), verified by the same `TokenVerifier`. First-message
   auth keeps tokens out of URLs and proxy logs.
2. The server answers `hello` (`user_id`, `role`, the driver's `bus_id`, heartbeat).
3. Invalid / missing token → close `4401`; no auth in time → `4408`.

The socket is receive-only for application data. Actions stay on REST (start/stop trip,
simulate GPS, QR scan, mark alert read, simulator controls).

## Envelope

Every server message (`app/realtime/messages.py`, Pydantic):

```json
{ "id": "evt-…", "type": "bus.state.updated", "seq": 42,
  "ts": "2026-10-05T01:52:05Z", "sent_at": "…", "scope": "fleet", "data": { … } }
```

`id` is unique (clients drop duplicates), `seq` increases per process (clients drop
anything not newer), `ts` is when the fact happened (simulation time).

## Event types and audiences

| Type | Source (existing) | `data` | Audience |
| --- | --- | --- | --- |
| `bus.state.updated` | `BusStateUpdated` (tracking) | `{bus}` = the `GET /buses` item | admins, students, the bus's driver |
| `fleet.bus.updated` | `BusStateUpdated` | `{bus}` = the `GET /admin/fleet` row (incl. Feature 5 ETA) | admins |
| `driver.state.updated` | `BusStateUpdated` | the `GET /driver/me` answer | that bus's driver only |
| `occupancy.updated` | BusState occupancy changed (Feature 8) | bus, trip, passengers, capacity, seats, % , QR boarded | admins, students, the bus's driver |
| `eta.updated` | Feature 5 ETA to the next stop changed | bus, trip, next stop, minutes, status, confidence | admins, students, the bus's driver |
| `route.deviation` | BusState route status entered/changed/left a deviation (Feature 10) | bus, trip, status, previous status, distance | admins, students, the bus's driver |
| `trip.started` / `trip.completed` | `TripStarted` / `TripEnded` | trip, bus, route, direction | admins, students, the bus's driver |
| `boarding.updated` | `BoardingRecorded` (Feature 8) | trip, bus, stop, `student_id` | admins + the student who boarded; the driver without `student_id` |
| `alert.created` / `.updated` / `.resolved` | `AlertCreated/Updated/Resolved` (Feature 11) | the `AlertOut` | admin alerts → admins; a student's alert → that student |
| `alert.read` | `AlertRead` | alert id | admin alert → every admin (shared flag); student alert → that student |
| `admin.overview.updated` | something changed (≤ 1 per 2 s) | the `GET /admin/overview` answer | admins |
| `sim.reset` | `POST /sim/reset` publishes `SimReset` | — | everyone (re-sync over REST) |
| `hello`, `ping` | connection | — | that socket |

Rules: students never receive another student's alert or boarding; drivers never receive
another bus's updates (their bus is resolved server-side from the signed-in driver, as in
Feature 12); alerts without a recipient are never sent. `GET /buses` is already readable by
every signed-in user, so fleet movement is not private.

## Throughput

The simulator awaits event handlers, so hub handlers only record the latest state per bus.
A flush loop (every `WS_FLUSH_INTERVAL_S` = 1 s) pushes each changed bus **once** (latest
state wins, older states are dropped). `occupancy.updated`, `eta.updated` and
`route.deviation` are only sent when the backend value differs from the last one pushed for
that bus. 12 buses at 20× ⇒ at most ~12 bus updates per second per client. Payload DTOs
(admin row with ETA, driver dashboard) are built only when a client of that audience is
connected; with no clients a flush does no work. Trip, boarding and alert events are pushed
immediately.

## Connection health

- Server `ping` every `WS_HEARTBEAT_S` (20 s); clients answer `pong`.
- A socket silent for `WS_IDLE_TIMEOUT_S` (60 s) is closed (`4410`) and removed.
- Each socket has a bounded queue (`WS_QUEUE_SIZE` = 500). A client that falls behind is
  closed (`4429`); a failed send closes that socket. Neither ever blocks or crashes the
  simulator or an API request.
- Clients close and reconnect a socket that sent nothing for 2.5 × heartbeat + 5 s.

## Client behaviour (all three apps — `src/realtime/client.ts`)

1. Load the current state over REST.
2. Open the socket, authenticate, apply events.
3. After **every** (re)connection, fetch the REST state once (closes the load/connect race
   and covers events missed while disconnected).
4. Reconnect with backoff 1 → 2 → 4 → 8 → 16 → 30 s (capped). A refused token stops retrying.
5. Socket live → REST only re-syncs every 60 s. Socket down → REST polling every 10 s
   (never both at full speed).
6. Duplicates (id), stale envelopes (seq) and older bus fixes (`last_updated`) are ignored.

- **Admin**: applies `fleet.bus.updated` (map, table, panels, bus detail),
  `admin.overview.updated` (KPIs) and `alert.*`; trip events refresh routes/schedule.
- **Student**: applies `bus.state.updated` (map/cards) and its own `alert.*`; relevant
  `eta.updated` / `occupancy.updated` / `route.deviation` / `trip.*` and its own
  `boarding.updated` re-fetch the student-specific backend answers (arrivals, comparison and
  — Feature 16 — today's commute) at most once per 1.5 s; Recent Commutes re-fetch only when
  today's phase / trip / boarding changes.
- **Driver**: applies `driver.state.updated` (speed, GPS, passengers, next stop, trip and
  route status); trip events re-fetch `/driver/me`.

## Single-process limitation and scaling

The event bus and the connection manager are **in process**, matching the prototype's
single-worker design (one simulator per process). Nothing about connections is stored in
MongoDB; persistent state is unchanged. With several workers or hosts, each would only
reach its own sockets. Production scaling needs a shared broker — e.g. an `EventBus`
implementation on Redis pub/sub (or NATS) that every worker subscribes to, with sticky or
stateless sockets behind the load balancer — plus moving the simulator to its own process.

## Testing

- Backend: `pytest tests/api/test_ws_api.py` drives the real endpoint with an in-loop ASGI
  WebSocket client (`tests/wsclient.py`) on the same event loop as the simulator; tests
  call `RealtimeHub.flush()` for determinism. Covers auth, audiences, the
  driver → admin/student end-to-end flow, change detection, ordering, slow/failed clients,
  heartbeat and cleanup.
- Frontends: a scriptable `FakeWebSocket` (`src/test/fakeSocket.ts`) is installed
  globally; `realtime.test.tsx` in each app covers connect/auth, events, duplicates,
  reconnect + re-sync and fallback polling.
- Manually: sign in to the Admin, Student and Driver apps; the Admin status bar shows
  "Live · real-time", the Student demo panel "Live · real-time updates", the Driver header
  "● LIVE". Start B07 in the Driver app and watch the Admin row change within ~1 s.
