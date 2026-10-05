"""Sign-in and identity (Feature 15). See ``app/core/auth.py`` for the boundary.

``GET /auth/config`` tells clients which sign-in to show. Exactly one backend sign-in
endpoint works per AUTH_MODE; the others answer 404 ``auth_method_unavailable``.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import Container, CurrentPrincipal
from app.models.api.auth import AuthConfigOut, DevLoginIn, MeOut, PasswordLoginIn, TokenOut
from app.services.auth import AuthService

router = APIRouter(tags=["auth"])


def _svc(c) -> AuthService:
    return AuthService(c.repos.users, c.session_tokens, c.settings.auth_mode)


@router.get("/auth/config", response_model=AuthConfigOut)
async def auth_config(c: Container) -> AuthConfigOut:
    mode = c.settings.auth_mode
    return AuthConfigOut(
        mode=mode,
        development=mode == "dev",
        dev_login=mode == "dev",
        password_login=mode == "password",
        external_provider=mode == "oidc",
        oidc_issuer=c.settings.oidc_issuer or None if mode == "oidc" else None,
    )


@router.post("/auth/dev-login", response_model=TokenOut)
async def dev_login(body: DevLoginIn, c: Container) -> TokenOut:
    """DEVELOPMENT sign-in (AUTH_MODE=dev): seeded email, no password. Not real authentication."""
    user, issued = await _svc(c).dev_login(body.email)
    return TokenOut(
        access_token=issued.token, expires_at=issued.expires_at, auth_method="dev", user=MeOut.of(user)
    )


@router.post("/auth/mock-login", response_model=TokenOut, deprecated=True)
async def mock_login(body: DevLoginIn, c: Container) -> TokenOut:
    """Deprecated alias of ``/auth/dev-login`` (Features 1–14 clients and scripts)."""
    return await dev_login(body, c)


@router.post("/auth/login", response_model=TokenOut)
async def password_login(body: PasswordLoginIn, c: Container) -> TokenOut:
    """Email + password sign-in (AUTH_MODE=password)."""
    user, issued = await _svc(c).password_login(body.email, body.password)
    return TokenOut(
        access_token=issued.token, expires_at=issued.expires_at, auth_method="password", user=MeOut.of(user)
    )


@router.get("/me", response_model=MeOut)
async def me(principal: CurrentPrincipal, c: Container) -> MeOut:
    return MeOut.of(await _svc(c).me(principal))
