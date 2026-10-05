# Authentication & identity (Feature 15)

Authentication establishes **who** the caller is. Authorization — unchanged by Feature 15
— decides **what** that identity may do. The backend is authoritative for both.

## Architecture

```
 bearer token (REST "Authorization: Bearer …"  or  WebSocket first message {"type":"auth"})
        │
        ▼
 IdentityVerifier  (app/core/auth.py — THE TokenVerifier for REST and WebSocket)
   1. CredentialVerifier — proves the token, returns provider + subject
        • SessionTokenService  backend HS256 tokens (AUTH_MODE dev | password)
        • OidcTokenVerifier    external RS256 ID tokens via JWKS (AUTH_MODE oidc)
   2. identity — loads the stored User; rejects unknown / inactive identities;
      role, name, email come from the database (never from token claims)
        │
        ▼
 Principal(user_id, role, …)  →  require_role / service-level ownership checks
```

Routers never verify tokens themselves; `deps.get_principal` and `/api/v1/ws` both call
`AppContainer.verifier.verify(token)`. Swapping the identity provider means configuring a
different `CredentialVerifier`; business services are untouched.

## Identity → domain mapping

The `users` collection holds the authentication identity (`app/models/user.py`): stable
`id`, `role` (`student` / `driver` / `admin`), `email`, `active`, `created_at`,
`updated_at`, optional `password_hash` (scrypt, never returned by the API) and, for an
external provider, `auth_provider` + `auth_subject` (unique together).

Domain records keep referencing that same id — no duplicate identities:

| Role | Identity | Domain records |
| --- | --- | --- |
| student | `U-S0001` … `U-S0300` | `student_profiles` / `student_assignments` use the same id |
| driver | `U-D01` … `U-D12` | `drivers.user_id` → driver record → bus via `buses.driver_id` |
| admin | `U-A01`, `U-A02` | role `admin` |

Seeded identities are deterministic (same ids as before Feature 15; timestamps fixed at
`2026-06-01T00:00Z`). Existing MongoDB documents load unchanged (new fields default to
`active=true`, no password, no provider link).

## Modes (`AUTH_MODE`)

| Mode | Sign-in | Token | Use |
| --- | --- | --- | --- |
| `dev` | `POST /auth/dev-login {email}` — **development sign-in, no password** | backend HS256, `amr=["dev"]` | local synthetic demo, tests. Refused when `APP_ENV=prod`. Clients label it "Development sign-in — not real authentication". |
| `password` | `POST /auth/login {email, password}` | backend HS256, `amr=["password"]` | real first-party credentials (scrypt, constant-time verify, one generic error for unknown email / wrong password) |
| `oidc` | at the external provider (e.g. Firebase Auth) | provider's RS256 ID token | production with an external IdP; the backend verifies signature (JWKS), `iss`, `aud`, `exp` |

`GET /auth/config` (public) tells clients which form to show. Only the current mode's
sign-in works; the others answer `404 auth_method_unavailable`. **There is no fallback**: a
`dev` token is rejected in `password` mode (and vice versa) even with the same secret, and
backend tokens are rejected in `oidc` mode. `POST /auth/mock-login` remains as a deprecated
alias of `/auth/dev-login` (dev mode only).

Session tokens carry only `iss`, `aud`, `sub` (user id), `amr`, `iat`, `exp`. The HS256 key
is derived from `AUTH_TOKEN_SECRET`; `APP_ENV=prod` requires a non-default secret of at
least 32 characters. Tokens expire after `AUTH_TOKEN_TTL_S` (default 12 h, wall-clock).

### External provider (`oidc`) configuration

```
AUTH_MODE=oidc
OIDC_ISSUER=https://securetoken.google.com/<firebase-project-id>
OIDC_AUDIENCE=<firebase-project-id>
OIDC_JWKS_URL=https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com
OIDC_LINK_BY_EMAIL=true   # optional: first sign-in links to the seeded user with that VERIFIED email
```

A provider identity is linked to a user by `(auth_provider, auth_subject)`. With
`OIDC_LINK_BY_EMAIL=true`, a first sign-in whose token has `email_verified=true` links to the
not-yet-linked user with that email; already-linked users cannot be re-linked. No service
account or provider secret is needed — only public signing keys.

**Status:** backend verification for `oidc` is implemented and tested with locally generated
keys (signature, issuer, audience, expiry, unknown key, `alg=none`, HS256 key confusion,
linking). The three clients do **not** yet include a provider sign-in UI; in `oidc` mode they
say so. A real Firebase project has not been connected in this repository.

## Inactive identities and roles

`active=false` is checked on every request and on WebSocket authentication: existing tokens
stop working immediately (REST `401`, WebSocket close `4401`), and sign-in is refused. A role
change also applies to the next request, because the role is read from the database.

## REST

Unchanged semantics: no / invalid / expired token or inactive identity → `401
unauthorized`; authenticated but wrong role or not the owner → `403 forbidden` (or `404` where
an endpoint hides foreign resources, e.g. another student's alert).

## WebSocket

`/api/v1/ws` keeps the Feature 14 protocol — first message `{"type":"auth","token":…}`,
invalid → `4401`, no auth in time → `4408` — and uses the SAME `IdentityVerifier`. A
driver's bus is resolved server-side from the authenticated identity; any other field in the
auth message (e.g. `bus_id`, `role`) is ignored. Audience filtering is unchanged.

## Authorization (unchanged rules, now on verified identities)

- **Students** use `/students/me/*`; `/students/{id}/*` is owner-or-admin; a QR scan must be
  for the signed-in student; alerts list only the student's own; another student's alert is
  `404`.
- **Drivers**: authenticated driver → `drivers.user_id` → `buses.driver_id` → bus. Trip
  start/stop/simulate never accept a bus id (one in the body is ignored); telemetry for
  another bus is `403`.
- **Admins**: `/admin/*`, fleet alerts, simulator controls (outside dev). Students and drivers
  get `403`.

## Clients

All three apps follow one pattern: read `GET /auth/config` → development or password form →
keep only the backend token (never the password) → send it as the REST bearer and as the
WebSocket auth message → any REST `401` or WebSocket `4401` signs out.

| App | Session storage |
| --- | --- |
| student-web, admin-web | `sessionStorage` (ends with the tab) |
| driver-app | memory only (nothing persisted on the device; no secure storage needed) |

## Running locally

Development sign-in (default; the full synthetic demo):

```
AUTH_MODE=dev   # .env
python scripts/seed_db.py
uvicorn app.main:app --reload
```

Real email + password sign-in against the seeded world:

```
AUTH_MODE=password
AUTH_TOKEN_SECRET=<32+ random characters>
python scripts/seed_db.py
DEMO_USER_PASSWORD=<choose one> python scripts/manage_users.py set-demo-passwords
python scripts/manage_users.py set-password --email admin1@campusride.demo   # hidden prompt
python scripts/manage_users.py disable --email driver05@campusride.demo
```

Re-seeding replaces users, so set passwords again afterwards. Passwords are never passed as
command-line arguments or logged.

## Limitations

- No sign-in rate limiting / lockout yet.
- Session tokens are stateless: sign-out is client-side; revocation is via `active=false`
  (immediate) — there is no per-token revocation list.
- Web clients keep the token in `sessionStorage` (readable by scripts on the page); httpOnly
  cookie sessions would need CSRF handling and are future work.
- No self-service registration or password reset.
