from __future__ import annotations

from fastapi import APIRouter

from app.deps import Container, CurrentPrincipal
from app.models.api.auth import MeOut, MockLoginIn, TokenOut
from app.services.auth import AuthService

router = APIRouter(tags=["auth"])


@router.post("/auth/mock-login", response_model=TokenOut)
async def mock_login(body: MockLoginIn, c: Container) -> TokenOut:
    user, issued = await AuthService(c.repos.users, c.mock_tokens).mock_login(body.email)
    return TokenOut(access_token=issued.token, expires_at=issued.expires_at, user=MeOut.of(user))


@router.get("/me", response_model=MeOut)
async def me(principal: CurrentPrincipal, c: Container) -> MeOut:
    return MeOut.of(await AuthService(c.repos.users, c.mock_tokens).me(principal))
