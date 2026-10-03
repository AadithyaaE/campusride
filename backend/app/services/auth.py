"""Mock login: exchange a seeded user's email for a signed bearer token."""

from __future__ import annotations

from app.core.auth import IssuedToken, MockTokenService, Principal
from app.core.errors import AuthError, NotFoundError, ServiceUnavailableError
from app.models import User
from app.repositories.base import UserRepository


class AuthService:
    def __init__(self, users: UserRepository, mock_tokens: MockTokenService | None) -> None:
        self._users = users
        self._tokens = mock_tokens

    async def mock_login(self, email: str) -> tuple[User, IssuedToken]:
        if self._tokens is None:
            raise ServiceUnavailableError("mock login is disabled (AUTH_MODE is not 'mock')")
        user = await self._users.by_email(email)
        if user is None:
            raise AuthError(f"no seeded user with email {email!r}")
        return user, self._tokens.issue(user)

    async def me(self, principal: Principal) -> User:
        user = await self._users.get(principal.user_id)
        if user is None:
            raise NotFoundError(f"user {principal.user_id} no longer exists")
        return user
