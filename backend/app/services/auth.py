"""Sign-in flows (Feature 15). Each is available only in its own AUTH_MODE.

* ``dev_login``      — DEVELOPMENT sign-in (AUTH_MODE=dev): a seeded identity by email, no
                       password. For the local synthetic demo only; refused in prod config.
* ``password_login`` — first-party sign-in (AUTH_MODE=password): email + password checked
                       against the stored scrypt hash (constant time, generic error).
* AUTH_MODE=oidc     — no sign-in here: clients obtain an ID token from the external
                       provider and send it as the bearer token.

Both backend flows issue a session token from ``SessionTokenService`` that is valid only
for the mode that issued it, and both reject inactive identities.
"""

from __future__ import annotations

from app.core.auth import IssuedToken, Principal, SessionTokenService
from app.core.errors import AuthError, CodedError, NotFoundError
from app.core.passwords import verify_password
from app.models import User
from app.repositories.base import UserRepository


class AuthMethodUnavailable(CodedError):
    def __init__(self, method: str, mode: str) -> None:
        super().__init__(
            "auth_method_unavailable", f"{method} sign-in is not available (AUTH_MODE={mode})", 404
        )


class AuthService:
    def __init__(self, users: UserRepository, tokens: SessionTokenService | None, mode: str) -> None:
        self._users = users
        self._tokens = tokens
        self._mode = mode

    def _issuer(self, method: str) -> SessionTokenService:
        if self._tokens is None or self._tokens.mode != method:
            raise AuthMethodUnavailable(method, self._mode)
        return self._tokens

    async def dev_login(self, email: str) -> tuple[User, IssuedToken]:
        tokens = self._issuer("dev")
        user = await self._users.by_email(email)
        if user is None:
            raise AuthError(f"no seeded user with email {email!r}")
        if not user.active:
            raise AuthError("account is disabled")
        return user, tokens.issue(user)

    async def password_login(self, email: str, password: str) -> tuple[User, IssuedToken]:
        tokens = self._issuer("password")
        user = await self._users.by_email(email)
        ok = verify_password(password, user.password_hash if user else None)
        if user is None or not ok:
            raise AuthError("invalid email or password")
        if not user.active:
            raise AuthError("account is disabled")
        return user, tokens.issue(user)

    async def me(self, principal: Principal) -> User:
        user = await self._users.get(principal.user_id)
        if user is None:
            raise NotFoundError(f"user {principal.user_id} no longer exists")
        return user
