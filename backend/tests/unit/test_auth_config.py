from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.auth import SessionTokenService, sim_driver_principal
from app.core.config import Settings
from app.core.errors import AuthError, ForbiddenError
from app.deps import require_role
from app.models import User
from app.models.common import Role

USER = User(id="U-S0001", role=Role.STUDENT, name="Test Student", email="Student001@CampusRide.demo")


class FakeNow:
    def __init__(self) -> None:
        self.t = 1_800_000_000.0

    def __call__(self) -> float:
        return self.t


async def test_token_round_trip():
    svc = SessionTokenService("secret", ttl_s=60, mode="dev")
    issued = svc.issue(USER)
    cred = await svc.verify_credential(issued.token)
    # the token names WHO (the user id) — role/email are looked up, never carried
    assert (cred.subject, cred.method, cred.provider) == ("U-S0001", "dev", "campusride")


async def test_tampered_token_rejected():
    svc = SessionTokenService("secret", ttl_s=60, mode="dev")
    token = svc.issue(USER).token
    head, _payload, sig = token.split(".")
    forged = (
        SessionTokenService("other-secret", ttl_s=60, mode="dev")
        .issue(User(id="U-A01", role=Role.ADMIN, name="x", email="a@b.c"))
        .token.split(".")[1]
    )
    with pytest.raises(AuthError):
        await svc.verify_credential(f"{head}.{forged}.{sig}")
    with pytest.raises(AuthError):
        await svc.verify_credential("not-a-token")


async def test_expired_token_rejected():
    now = FakeNow()
    svc = SessionTokenService("secret", ttl_s=60, mode="dev", now=now)
    token = svc.issue(USER).token
    now.t += 61
    with pytest.raises(AuthError, match="expired"):
        await svc.verify_credential(token)


async def test_require_role():
    student = sim_driver_principal("B01", "U-D01").model_copy(update={"role": Role.STUDENT})
    check = require_role(Role.ADMIN)
    with pytest.raises(ForbiddenError):
        await check(student)
    admin = student.model_copy(update={"role": Role.ADMIN})
    assert await check(admin) is admin


def test_sim_driver_principal_is_a_driver_bound_to_a_bus():
    p = sim_driver_principal("B03", "U-D03")
    assert (p.role, p.bus_id, p.source) == (Role.DRIVER, "B03", "sim")


# --------------------------------------------------------------------------- settings


def make(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_defaults_match_spec():
    s = make()
    assert (s.seed, s.sim_speed, s.sim_start_date, s.auth_mode, s.telemetry_ttl_days) == (
        42,
        5,
        "auto",
        "dev",
        30,
    )
    assert s.tz.key == "Asia/Kolkata"


@pytest.mark.parametrize(
    "kw",
    [
        {"sim_speed": 3},
        {"sim_start_date": "05-10-2026"},
        {"auth_mode": "firebase"},
        {"app_env": "prod"},  # development auth not allowed in prod
        {"app_env": "prod", "auth_mode": "password"},  # prod needs a real AUTH_TOKEN_SECRET
        {"auth_mode": "oidc"},  # needs issuer, audience and JWKS URL
        {"campus_timezone": "Mars/Olympus"},
    ],
)
def test_invalid_settings_rejected(kw):
    with pytest.raises(ValidationError):
        make(**kw)


def test_cors_origin_list():
    assert make(cors_origins="http://a, http://b ,").cors_origin_list == ["http://a", "http://b"]
