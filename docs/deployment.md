# Deployment — first cloud deployment

| Part | Host | Source |
|---|---|---|
| Backend (FastAPI + WebSockets) | Render Web Service | `backend/` · `render.yaml` |
| Database | MongoDB Atlas | — |
| Student Web | Vercel project #1 | `apps/student-web` |
| Admin Web | Vercel project #2 | `apps/admin-web` |
| Driver app | Expo EAS (Android) | `apps/driver-app` · `eas.json` |

Order: **Atlas → Render → Vercel (both) → update Render `CORS_ORIGINS` → EAS.**
Secrets live only in the provider dashboards, never in git. The variable names below are the
backend's real ones (`backend/app/core/config.py`); a full template is in `backend/.env.production.example`.

## A. MongoDB Atlas
1. https://cloud.mongodb.com → create a project → **Create cluster** (the free M0 tier is fine for the SIH demo).
   Pick a region close to the Render region (e.g. Singapore / Mumbai).
2. **Database Access → Add new database user**: password authentication, a generated password,
   role *Read and write to any database* (or restrict it to the `campusride` database).
3. **Network Access → Add IP address**. Render's free instances have no fixed outbound IP, so for the
   demo use `0.0.0.0/0`. Access is then protected by the user and password. On a paid Render plan,
   add only its static outbound IPs instead.
4. **Connect → Drivers → Python**. Copy the `mongodb+srv://<user>:<password>@<cluster>/…` string and put
   the password in it. This string is the secret value of **`MONGO_URI`** (Render only).
5. Database name: **`MONGO_DB=campusride`**.
6. **Load the data once** (from your PC, never on server start):
   ```bash
   cd backend
   # PowerShell: $env:MONGO_URI="<atlas uri>"; $env:MONGO_DB="campusride"
   MONGO_URI="<atlas uri>" MONGO_DB=campusride .venv/Scripts/python scripts/seed_db.py
   MONGO_URI="<atlas uri>" MONGO_DB=campusride DEMO_USER_PASSWORD="<choose one>" \
     .venv/Scripts/python scripts/manage_users.py set-demo-passwords
   ```
   `seed_db.py` **replaces** the demo data (users included), so run it only to (re)initialise the database.
   Real accounts should instead get individual passwords with `manage_users.py set-password --email …`.
7. Verify: after Render is up, `GET https://<render-app>.onrender.com/api/v1/health` → `"db":"ok"`.

## B. Render (backend)
https://dashboard.render.com → **New → Blueprint** → select the GitHub repo (it reads `render.yaml`), or create a
**Web Service** by hand with:

| Setting | Value |
|---|---|
| Root Directory | `backend` |
| Runtime | Python |
| Build Command | `pip install uv && uv sync --frozen --no-dev` |
| Start Command | `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*'` |
| Health Check Path | `/api/v1/health` |

Environment variables:

| Name | Value | Secret? |
|---|---|---|
| `PYTHON_VERSION` | `3.12.8` | no |
| `APP_ENV` | `prod` | no |
| `AUTH_MODE` | `password` | no |
| `AUTH_TOKEN_SECRET` | ≥ 32 random characters. The Blueprint generates one; by hand use `python -c "import secrets; print(secrets.token_urlsafe(48))"` | **yes** |
| `MONGO_URI` | the Atlas string from A.4 | **yes** |
| `MONGO_DB` | `campusride` | no |
| `CORS_ORIGINS` | `https://<student>.vercel.app,https://<admin>.vercel.app` (exact origins, no trailing `/`; set after C/D) | no |
| `CLOCK_MODE`, `SIM_ENABLED`, `SIM_AUTOSTART` | see "Simulator policy" | no |

The backend **refuses to start** with `APP_ENV=prod` plus `AUTH_MODE=dev`, or with a missing or short
`AUTH_TOKEN_SECRET`. A database error is logged with the credentials hidden (`mongodb+srv://***@…`).
WebSockets (`wss://<render-app>.onrender.com/api/v1/ws`) work on Render web services with no extra setting.
Free instances sleep after ~15 min idle (the first request then takes ~1 min), so open the apps a minute
before a demo.

### Simulator policy
| Mode | Variables | Result |
|---|---|---|
| **Default (safe)** | `CLOCK_MODE=real`, `SIM_ENABLED=false`, `SIM_AUTOSTART=false` | No simulated buses. Data, sign-in and dashboards work, but nothing moves, and the Driver app's *Start Trip* answers "trip system unavailable". In this prototype, trips run through the simulator, because GPS is synthetic. |
| **SIH public demo (opt-in)** | `CLOCK_MODE=sim`, `SIM_ENABLED=true`, `SIM_AUTOSTART=true` (optional `SIM_SPEED=5`, `SIM_DRIVER_CONTROLLED_BUSES=B07`) | The synthetic fleet runs and the Driver app starts trips. Only **admins** can pause, speed up, reset or trigger route deviation (`APP_ENV=prod`). |

In demo mode, **every backend start resets the demo day's runtime data for simulated buses**: positions,
telemetry, and that day's boardings and alerts. Users, routes and seed data are never touched on start.

## C. Vercel — CampusRide Student
https://vercel.com/new → import the repo → **Root Directory `apps/student-web`**. Vite is detected
automatically: build `npm run build`, output `dist`, install `npm install`. Environment variables
(Production), all **public** (they are compiled into the browser bundle, so never put secrets in `VITE_*`):

| Name | Value |
|---|---|
| `VITE_API_BASE_URL` | `https://<render-app>.onrender.com/api/v1` |
| `VITE_ADMIN_APP_URL` | `https://<admin>.vercel.app/` |

The real-time URL is derived automatically (`https` → `wss`). Redeploy after changing a variable.

## D. Vercel — CampusRide Admin
A second Vercel project from the same repo → **Root Directory `apps/admin-web`**. Same build defaults.

| Name | Value |
|---|---|
| `VITE_API_BASE_URL` | `https://<render-app>.onrender.com/api/v1` |
| `VITE_STUDENT_APP_URL` | `https://<student>.vercel.app/` |

Then put both Vercel origins into Render's `CORS_ORIGINS`, and redeploy the student app if its
`VITE_ADMIN_APP_URL` changed.

## E. Expo EAS (Driver app, Android)
Android package: `com.campusride.driver` (`app.json`). Profiles are in `eas.json`: `preview` builds an
**APK** to install directly, and `production` builds an **AAB** for Google Play (not submitted automatically).
```bash
cd apps/driver-app
npm install -g eas-cli          # once
eas login                       # your Expo account
eas init                        # links the project (writes the projectId into app.json — commit that)
eas env:create --name EXPO_PUBLIC_API_BASE_URL --value https://<render-app>.onrender.com/api/v1 \
  --environment preview --environment production --visibility plaintext
eas build -p android --profile preview      # test APK
eas build -p android --profile production   # Play Store AAB
```
`EXPO_PUBLIC_API_BASE_URL` is compiled into the app, so it is public by design (no secrets). The driver
signs in with their own email and password; the backend decides which bus they drive.

## Verify a deployment
1. `https://<render-app>.onrender.com/api/v1/health` → `status: ok`, `db: ok`, `env: prod`.
2. Student app: sign in → Today's Commute loads, and the header shows **Live** (WebSocket connected).
3. Admin app: sign in → Control Room, Live. A student account is refused on the admin sign-in.
4. Driver APK: sign in as the driver → their assigned bus. In demo mode, *Start Trip* moves it on both web apps.
