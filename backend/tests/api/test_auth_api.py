"""Feature 15 — authentication & identity through ONE boundary (REST + WebSocket).

Modes: ``dev`` (development sign-in, default for tests), ``password`` (first-party
credentials) and ``oidc`` (external provider ID tokens, verified against a local JWKS here —
no network, no production credentials).
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.auth import IdentityVerifier, OidcTokenVerifier, SessionTokenService
from app.core.config import Settings
from app.core.passwords import hash_password, verify_password
from app.main import create_app
from app.models.common import AlertType, Role
from app.services.alert_service import AlertSpec, Recipient
from tests.conftest import SEED, login
from tests.wsclient import WsClosed, WsTestClient

STUDENT, OTHER_STUDENT = "student001@campusride.demo", "student002@campusride.demo"
DRIVER07, DRIVER05 = "driver07@campusride.demo", "driver05@campusride.demo"
ADMIN = "admin1@campusride.demo"
PASSWORD = "correct horse battery staple"
ADMIN_ENDPOINTS = ["/admin/overview", "/admin/fleet", "/admin/routes", "/admin/schedule", "/admin/analytics"]


def _settings(**kw) -> Settings:
    base = {
        "_env_file": None,
        "app_env": "test",
        "seed": SEED,
        "mock_token_secret": "test-secret",
        "sim_driver_controlled_buses": "B07",
        "ws_auth_timeout_s": 0.3,
        "ws_flush_interval_s": 3600,
    }
    return Settings(**(base | kw))


@pytest.fixture
def settings() -> Settings:
    return _settings()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def ws_open(container, token: str | None):
    """Open the REAL /ws endpoint and authenticate (returns the socket and hello or close code)."""
    sock = await WsTestClient(create_app(container=container)).connect()
    if token is None:
        return sock, await sock.wait_closed(wait_s=2)
    await sock.send({"type": "auth", "token": token})
    try:
        return sock, await sock.recv()
    except WsClosed as e:
        return sock, e.code


async def _set_user(container, email: str, **update):
    user = await container.repos.users.by_email(email)
    return await container.repos.users.upsert(user.model_copy(update=update))


# ============================================================================ passwords (unit)


def test_password_hashing():
    h = hash_password(PASSWORD)
    assert h.startswith("scrypt$") and PASSWORD not in h
    assert verify_password(PASSWORD, h) and not verify_password("wrong password", h)
    assert hash_password(PASSWORD) != h  # random salt
    assert not verify_password(PASSWORD, None) and not verify_password(PASSWORD, "garbage$x")
    with pytest.raises(ValueError):
        hash_password("short")


# ============================================================================ development mode


async def test_dev_mode_is_explicit_and_labelled(client):
    cfg = (await client.get("/auth/config")).json()
    assert cfg == {
        "mode": "dev",
        "development": True,
        "dev_login": True,
        "password_login": False,
        "external_provider": False,
        "oidc_issuer": None,
    }
    r = await client.post("/auth/dev-login", json={"email": STUDENT})
    assert r.status_code == 200 and r.json()["auth_method"] == "dev"
    assert r.json()["user"] == {
        "id": "U-S0001",
        "role": "student",
        "name": r.json()["user"]["name"],
        "email": STUDENT,
        "active": True,
    }
    assert (await client.post("/auth/mock-login", json={"email": STUDENT})).status_code == 200  # alias
    off = await client.post("/auth/login", json={"email": STUDENT, "password": PASSWORD})
    assert off.status_code == 404 and off.json()["error"]["code"] == "auth_method_unavailable"


async def test_missing_invalid_tampered_and_expired_tokens(client, container):
    assert (await client.get("/me")).status_code == 401
    for bad in ("garbage", "mock.garbage.sig", "a.b.c"):
        assert (await client.get("/me", headers=bearer(bad))).status_code == 401
    user = await container.repos.users.by_email(STUDENT)
    forged = SessionTokenService("not-the-server-secret", 60, "dev").issue(user).token
    assert (await client.get("/me", headers=bearer(forged))).status_code == 401
    expired = SessionTokenService("test-secret", 60, "dev", now=lambda: time.time() - 3600).issue(user)
    r = await client.get("/me", headers=bearer(expired.token))
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


async def test_inactive_identity_is_rejected_everywhere(client, container):
    headers = await login(client, STUDENT)
    assert (await client.get("/students/me/assignment", headers=headers)).status_code == 200
    await _set_user(container, STUDENT, active=False)
    r = await client.get("/students/me/assignment", headers=headers)  # existing token stops working
    assert r.status_code == 401 and r.json()["error"]["message"] == "account is disabled"
    assert (await client.post("/auth/dev-login", json={"email": STUDENT})).status_code == 401
    _, code = await ws_open(container, headers["Authorization"].removeprefix("Bearer "))
    assert code == 4401
    await container.realtime().shutdown()


async def test_role_comes_from_the_identity_record_not_the_token(client, container):
    headers = await login(client, ADMIN)
    assert (await client.get("/admin/overview", headers=headers)).status_code == 200
    await _set_user(container, ADMIN, role=Role.STUDENT)  # demoted: takes effect immediately
    assert (await client.get("/admin/overview", headers=headers)).status_code == 403


# ============================================================================ roles & isolation


async def test_roles_on_student_driver_and_admin_endpoints(live_client):
    client, _ = live_client
    s, d, a = await login(client, STUDENT), await login(client, DRIVER07), await login(client, ADMIN)
    assert (await client.get("/students/me/assignment", headers=s)).status_code == 200
    assert (await client.get("/driver/me", headers=d)).status_code == 200
    for path in ADMIN_ENDPOINTS:
        assert (await client.get(path, headers=a)).status_code == 200
        assert (await client.get(path, headers=s)).status_code == 403
        assert (await client.get(path, headers=d)).status_code == 403
    assert (await client.get("/driver/me", headers=s)).status_code == 403
    assert (await client.get("/driver/me", headers=a)).status_code == 403
    assert (await client.get("/students/me/assignment", headers=d)).status_code == 403


async def test_student_cannot_reach_another_students_data(live_client):
    client, container = live_client
    s1 = await login(client, STUDENT)
    for path in ("commute-decision", "recovery-options", "bus-options"):
        assert (await client.get(f"/students/U-S0002/{path}", headers=s1)).status_code == 403
        assert (await client.get(f"/students/U-S0001/{path}", headers=s1)).status_code == 200
    forged = {"student_id": "U-S0002", "bus_id": "B05", "trip_id": "T-x", "timestamp": "2026-10-05T01:50:00Z"}
    r = await client.post("/boarding/scan", json=forged, headers=s1)
    assert r.status_code == 403 and r.json()["error"]["code"] == "invalid_student"
    theirs = await container.alerts().create_alert(
        AlertSpec(
            AlertType.MISSED_BUS,
            Recipient("U-S0002"),
            "You missed your assigned bus B06.",
            container.clock.now(),
            "B06",
            "T2",
            "R3",
        )
    )
    mine = (await client.get("/alerts", headers=s1)).json()
    assert all(a["student_id"] == "U-S0001" for a in mine) and theirs.id not in {a["alert_id"] for a in mine}
    assert (await client.patch(f"/alerts/{theirs.id}/read", headers=s1)).status_code == 404


async def test_driver_operates_only_the_server_resolved_own_bus(live_client):
    client, container = live_client
    d07, d05 = await login(client, DRIVER07), await login(client, DRIVER05)
    # a client-supplied bus id is ignored: the server resolves driver → driver record → bus
    r = await client.post("/driver/trip/start", json={"bus_id": "B05"}, headers=d07)
    assert r.status_code == 200 and r.json()["bus"]["id"] == "B07" and r.json()["trip_state"] == "ACTIVE"
    b05_trip = (await container.repos.bus_states.get("B05")).trip_id
    assert (await container.repos.trips.get(b05_trip)).status.value == "scheduled"  # untouched
    # driver 05 cannot stop driver 07's trip (stop acts on driver 05's own bus only)
    assert (await client.post("/driver/trip/stop", json={"bus_id": "B07"}, headers=d05)).status_code == 409
    assert (await container.repos.trips.get(r.json()["trip"]["id"])).status.value == "active"
    tele = {
        "bus_id": "B07",
        "trip_id": None,
        "points": [{"ts": "2026-10-05T01:50:00Z", "lng": 80.2, "lat": 12.9}],
    }
    assert (await client.post("/driver/telemetry", json=tele, headers=d05)).status_code == 403


# ============================================================================ WebSocket (same boundary)


async def test_websocket_uses_the_same_identity_boundary(live_client):
    client, container = live_client
    tokens = {
        e: (await login(client, e))["Authorization"].removeprefix("Bearer ")
        for e in (STUDENT, DRIVER07, ADMIN)
    }
    try:
        for email, role in ((STUDENT, "student"), (DRIVER07, "driver"), (ADMIN, "admin")):
            _, hello = await ws_open(container, tokens[email])
            assert hello["type"] == "hello" and hello["data"]["role"] == role
        # a driver cannot claim another bus: extra fields in the auth message are ignored
        sock = await WsTestClient(create_app(container=container)).connect()
        await sock.send({"type": "auth", "token": tokens[DRIVER07], "bus_id": "B05", "role": "admin"})
        hello = await sock.recv()
        assert (hello["data"]["role"], hello["data"]["bus_id"]) == ("driver", "B07")
        _, code = await ws_open(container, "invalid.token.value")
        assert code == 4401
        _, code = await ws_open(container, None)  # never authenticates
        assert code == 4408
        # audience scoping still applies: a student never receives an admin alert
        s_sock, _ = await ws_open(container, tokens[STUDENT])
        await container.alerts().create_alert(
            AlertSpec(
                AlertType.CAPACITY_WARNING,
                Recipient(),
                "Bus B07 is 88% full.",
                container.clock.now(),
                "B07",
                "T7",
                "R4",
            )
        )
        assert [m for m in await s_sock.drain() if m["type"] == "alert.created"] == []
    finally:
        await container.realtime().shutdown()


# ============================================================================ password mode


class TestPasswordMode:
    @pytest.fixture
    def settings(self) -> Settings:
        return _settings(auth_mode="password")

    @pytest.fixture
    async def with_passwords(self, container):
        digest = hash_password(PASSWORD)
        for email in (STUDENT, DRIVER07, ADMIN):
            await _set_user(container, email, password_hash=digest)
        return container

    async def test_config_and_no_development_sign_in(self, client, with_passwords):
        cfg = (await client.get("/auth/config")).json()
        assert (cfg["mode"], cfg["development"], cfg["password_login"], cfg["dev_login"]) == (
            "password",
            False,
            True,
            False,
        )
        for path in ("/auth/dev-login", "/auth/mock-login"):
            r = await client.post(path, json={"email": ADMIN})
            assert r.status_code == 404 and r.json()["error"]["code"] == "auth_method_unavailable"

    async def test_password_sign_in(self, client, with_passwords):
        r = await client.post("/auth/login", json={"email": "ADMIN1@campusride.demo", "password": PASSWORD})
        assert r.status_code == 200 and r.json()["auth_method"] == "password"
        token = r.json()["access_token"]
        assert (await client.get("/admin/overview", headers=bearer(token))).status_code == 200
        wrong = await client.post("/auth/login", json={"email": ADMIN, "password": "nope-nope-nope"})
        unknown = await client.post(
            "/auth/login", json={"email": "ghost@campusride.demo", "password": PASSWORD}
        )
        no_pw = await client.post("/auth/login", json={"email": OTHER_STUDENT, "password": PASSWORD})
        for resp in (wrong, unknown, no_pw):  # one generic answer: no account enumeration
            assert resp.status_code == 401 and resp.json()["error"]["message"] == "invalid email or password"

    async def test_no_silent_fallback_to_development_tokens(self, client, with_passwords, container):
        user = await container.repos.users.by_email(ADMIN)
        dev_token = SessionTokenService("test-secret", 3600, "dev").issue(user).token  # same secret
        r = await client.get("/me", headers=bearer(dev_token))
        assert r.status_code == 401 and "not issued by password sign-in" in r.json()["error"]["message"]
        _, code = await ws_open(container, dev_token)
        assert code == 4401
        await container.realtime().shutdown()

    async def test_inactive_with_correct_password_and_websocket(self, client, with_passwords, container):
        r = await client.post("/auth/login", json={"email": DRIVER07, "password": PASSWORD})
        token = r.json()["access_token"]
        _, hello = await ws_open(container, token)
        assert hello["data"]["role"] == "driver" and hello["data"]["bus_id"] == "B07"
        await _set_user(container, DRIVER07, active=False)
        r = await client.post("/auth/login", json={"email": DRIVER07, "password": PASSWORD})
        assert r.status_code == 401 and r.json()["error"]["message"] == "account is disabled"
        assert (await client.get("/driver/me", headers=bearer(token))).status_code == 401
        await container.realtime().shutdown()


# ============================================================================ external OIDC provider


ISSUER, AUDIENCE = "https://securetoken.example.test/campusride-demo", "campusride-demo"


def _rsa():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def keys():
    good, other = _rsa(), _rsa()
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(good.public_key(), as_dict=True) | {"kid": "k1", "use": "sig"}
    return {"good": good, "other": other, "jwks": {"keys": [jwk]}}


def id_token(key, *, sub="uid-admin-1", kid="k1", iss=ISSUER, aud=AUDIENCE, exp_in=600, **extra):
    now = int(time.time())
    claims = {"iss": iss, "aud": aud, "sub": sub, "iat": now, "exp": now + exp_in} | extra
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


class TestOidcMode:
    @pytest.fixture
    def settings(self) -> Settings:
        return _settings(
            auth_mode="oidc",
            oidc_issuer=ISSUER,
            oidc_audience=AUDIENCE,
            oidc_jwks_url="https://unused.test/jwks",
        )

    @pytest.fixture
    async def oidc(self, container, keys):
        # same IdentityVerifier, with the provider's JWKS supplied locally (no network in tests)
        verifier = OidcTokenVerifier(issuer=ISSUER, audience=AUDIENCE, jwks=keys["jwks"])
        container.verifier = IdentityVerifier(verifier, container.repos.users, link_by_email=True)
        await _set_user(container, ADMIN, auth_provider=ISSUER, auth_subject="uid-admin-1")
        return container

    async def test_valid_external_token(self, client, oidc, keys):
        r = await client.get("/me", headers=bearer(id_token(keys["good"])))
        assert r.status_code == 200 and r.json()["id"] == "U-A01" and r.json()["role"] == "admin"
        assert (
            await client.get("/admin/overview", headers=bearer(id_token(keys["good"])))
        ).status_code == 200
        cfg = (await client.get("/auth/config")).json()
        assert cfg["external_provider"] is True and cfg["oidc_issuer"] == ISSUER and not cfg["development"]
        assert (await client.post("/auth/dev-login", json={"email": ADMIN})).status_code == 404

    async def test_rejected_external_tokens(self, client, oidc, keys):
        bad = [
            id_token(keys["other"]),  # signed by a key the provider never published
            id_token(keys["good"], iss="https://evil.test"),
            id_token(keys["good"], aud="someone-else"),
            id_token(keys["good"], exp_in=-60),
            id_token(keys["good"], kid="unknown"),
            id_token(keys["good"], sub="uid-not-linked"),
            jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "sub": "uid-admin-1"}, key="", algorithm="none"),
            jwt.encode(  # HS256 "signed" with the public key: algorithm confusion
                {"iss": ISSUER, "aud": AUDIENCE, "sub": "uid-admin-1", "iat": 0, "exp": 2**31},
                key="x" * 32,
                algorithm="HS256",
                headers={"kid": "k1"},
            ),
        ]
        for token in bad:
            assert (await client.get("/me", headers=bearer(token))).status_code == 401, token[:40]
        session = (
            SessionTokenService("test-secret", 600, "dev").issue(await oidc.repos.users.by_email(ADMIN)).token
        )
        assert (await client.get("/me", headers=bearer(session))).status_code == 401  # no fallback

    async def test_first_sign_in_links_by_verified_email_only(self, client, oidc, keys):
        unverified = id_token(keys["good"], sub="uid-s2", email=OTHER_STUDENT, email_verified=False)
        assert (await client.get("/me", headers=bearer(unverified))).status_code == 401
        verified = id_token(keys["good"], sub="uid-s2", email=OTHER_STUDENT, email_verified=True)
        r = await client.get("/me", headers=bearer(verified))
        assert r.status_code == 200 and r.json()["id"] == "U-S0002"
        linked = await oidc.repos.users.by_email(OTHER_STUDENT)
        assert (linked.auth_provider, linked.auth_subject) == (ISSUER, "uid-s2")
        # an already-linked account can't be re-linked to another subject
        hijack = id_token(keys["good"], sub="uid-attacker", email=OTHER_STUDENT, email_verified=True)
        assert (await client.get("/me", headers=bearer(hijack))).status_code == 401

    async def test_websocket_with_external_token(self, oidc, keys):
        try:
            _, hello = await ws_open(oidc, id_token(keys["good"]))
            assert hello["type"] == "hello" and hello["data"]["role"] == "admin"
            _, code = await ws_open(oidc, id_token(keys["other"]))
            assert code == 4401
        finally:
            await oidc.realtime().shutdown()
