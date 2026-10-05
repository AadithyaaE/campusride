"""Authentication boundary (Feature 15): who is calling, verified, and with which role.

Routers and the WebSocket only ever see a ``Principal``, produced by ONE ``TokenVerifier``
(``AppContainer.verifier``). Verification has two stages, so the identity provider can
change without touching business services:

1. **Credential** — a ``CredentialVerifier`` proves the bearer token and returns WHO it
   names (``VerifiedCredential``): provider + subject.
   * ``SessionTokenService`` — HS256 tokens issued by this backend after a development
     sign-in (AUTH_MODE=dev) or an email + password sign-in (AUTH_MODE=password). Each
     token records the mode that issued it; a token from another mode is rejected (no
     silent fallback from real to development authentication).
   * ``OidcTokenVerifier`` — RS256 ID tokens from an external OpenID Connect provider
     (AUTH_MODE=oidc, e.g. Firebase Auth), checked against the provider's JWKS, issuer,
     audience and expiry.
2. **Identity** — ``IdentityVerifier`` maps the credential to the stored ``User`` (the
   auth identity; students / drivers / admins hang off its id) and enforces ``active``.
   Role, name and email always come from the database, never from token claims, so
   deactivation or a role change takes effect on the next request.

The simulator acts as a driver through ``sim_driver_principal(bus)`` and goes through the
same authorisation checks as a real driver's phone.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal, Protocol

import jwt
from pydantic import BaseModel

from app.core.errors import AuthError
from app.models import User
from app.models.common import Role

SESSION_ISSUER = "campusride"
SESSION_AUDIENCE = "campusride-api"
SessionMode = Literal["dev", "password"]


class Principal(BaseModel):
    user_id: str
    role: Role
    name: str = ""
    email: str | None = None
    bus_id: str | None = None
    """Set for simulator principals (the bus this "driver" drives)."""
    source: Literal["user", "sim"] = "user"
    auth_method: str | None = None
    """How the caller authenticated: ``dev``, ``password``, ``oidc`` (None for the simulator)."""


class TokenVerifier(Protocol):
    """THE boundary used by REST (``deps.get_principal``) and the WebSocket (``/ws``)."""

    async def verify(self, token: str) -> Principal: ...


@dataclass(frozen=True)
class VerifiedCredential:
    provider: str
    """``campusride`` for backend session tokens, else the OIDC issuer."""
    subject: str
    """The user id (session tokens) or the provider's subject (OIDC)."""
    method: str
    email: str | None = None
    email_verified: bool = False


class CredentialVerifier(Protocol):
    async def verify_credential(self, token: str) -> VerifiedCredential: ...


class UserLookup(Protocol):
    async def get(self, id: str) -> User | None: ...

    async def by_email(self, email: str) -> User | None: ...

    async def by_auth_subject(self, provider: str, subject: str) -> User | None: ...

    async def upsert(self, item: User) -> User: ...


class IssuedToken(BaseModel):
    token: str
    expires_at: datetime


# ============================================================================ session tokens


class SessionTokenService:
    """Issues and verifies backend session tokens (HS256 JWT, constant-time signature check).

    Claims: ``iss``/``aud`` (this API), ``sub`` = user id, ``amr`` = [mode], ``iat``, ``exp``.
    Nothing else is trusted: role/name/email are looked up per request. Expiry uses real
    wall-clock time — a fast-forwarded simulation never expires a login.
    """

    def __init__(
        self, secret: str, ttl_s: int, mode: SessionMode, now: Callable[[], float] = time.time
    ) -> None:
        if not secret:
            raise ValueError("session token secret must not be empty")
        # 256-bit HS256 key derived from the configured secret (prod requires >= 32 chars of it)
        self._key = hashlib.sha256(f"campusride-session-v1:{secret}".encode()).digest()
        self._ttl_s = ttl_s
        self.mode: SessionMode = mode
        self._now = now

    def issue(self, user: User) -> IssuedToken:
        now = int(self._now())
        exp = now + self._ttl_s
        claims = {
            "iss": SESSION_ISSUER,
            "aud": SESSION_AUDIENCE,
            "sub": user.id,
            "amr": [self.mode],
            "iat": now,
            "exp": exp,
        }
        return IssuedToken(
            token=jwt.encode(claims, self._key, algorithm="HS256"),
            expires_at=datetime.fromtimestamp(exp, UTC),
        )

    async def verify_credential(self, token: str) -> VerifiedCredential:
        try:
            claims = jwt.decode(
                token,
                self._key,
                algorithms=["HS256"],
                audience=SESSION_AUDIENCE,
                issuer=SESSION_ISSUER,
                options={"require": ["exp", "iat", "sub", "aud", "iss"], "verify_iat": False},
                leeway=0,
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("token expired") from exc
        except jwt.PyJWTError as exc:
            raise AuthError("invalid token") from exc
        if int(claims["exp"]) < self._now():  # injected clock (tests) — PyJWT uses real time
            raise AuthError("token expired")
        if claims.get("amr") != [self.mode]:
            raise AuthError(f"token was not issued by {self.mode} sign-in")
        return VerifiedCredential(provider=SESSION_ISSUER, subject=str(claims["sub"]), method=self.mode)


# ============================================================================ external OIDC provider


class OidcTokenVerifier:
    """RS256 ID tokens from an OpenID Connect provider (Firebase Auth, Auth0, Keycloak, …).

    ``jwks`` (a JWK set dict) is for tests/offline use; otherwise keys are fetched from
    ``jwks_url`` and cached by PyJWT's ``PyJWKClient``. Only asymmetric RS256 is accepted
    (no ``none``, no HS256 key-confusion).
    """

    ALGORITHMS: ClassVar[list[str]] = ["RS256"]

    def __init__(
        self, *, issuer: str, audience: str, jwks_url: str = "", jwks: dict[str, Any] | None = None
    ) -> None:
        if not issuer or not audience or not (jwks_url or jwks):
            raise ValueError("OIDC needs an issuer, an audience and a JWKS")
        self.issuer = issuer
        self._audience = audience
        self._keys = jwt.PyJWKSet.from_dict(jwks) if jwks is not None else None
        self._client = jwt.PyJWKClient(jwks_url, cache_keys=True) if jwks is None else None

    def _signing_key(self, token: str) -> Any:
        if self._client is not None:
            return self._client.get_signing_key_from_jwt(token).key
        kid = jwt.get_unverified_header(token).get("kid")
        assert self._keys is not None
        for k in self._keys.keys:
            if k.key_id == kid:
                return k.key
        raise AuthError("unknown signing key")

    async def verify_credential(self, token: str) -> VerifiedCredential:
        try:
            claims = jwt.decode(
                token,
                self._signing_key(token),
                algorithms=self.ALGORITHMS,
                audience=self._audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("token expired") from exc
        except (jwt.PyJWTError, ValueError) as exc:
            raise AuthError("invalid token") from exc
        return VerifiedCredential(
            provider=self.issuer,
            subject=str(claims["sub"]),
            method="oidc",
            email=claims.get("email"),
            email_verified=bool(claims.get("email_verified")),
        )


# ============================================================================ identity


class IdentityVerifier:
    """Credential → stored ``User`` → ``Principal``. The single ``TokenVerifier`` of the app."""

    def __init__(
        self, credentials: CredentialVerifier, users: UserLookup, *, link_by_email: bool = False
    ) -> None:
        self._credentials = credentials
        self._users = users
        self._link_by_email = link_by_email

    async def _resolve(self, cred: VerifiedCredential) -> User | None:
        if cred.provider == SESSION_ISSUER:
            return await self._users.get(cred.subject)
        user = await self._users.by_auth_subject(cred.provider, cred.subject)
        if user is None and self._link_by_email and cred.email and cred.email_verified:
            candidate = await self._users.by_email(cred.email)
            if candidate is not None and candidate.auth_subject is None:
                user = await self._users.upsert(
                    candidate.model_copy(
                        update={
                            "auth_provider": cred.provider,
                            "auth_subject": cred.subject,
                            "updated_at": datetime.now(UTC),
                        }
                    )
                )
        return user

    async def verify(self, token: str) -> Principal:
        cred = await self._credentials.verify_credential(token)
        user = await self._resolve(cred)
        if user is None:
            raise AuthError("unknown identity")
        if not user.active:
            raise AuthError("account is disabled")
        return principal_of(user, cred.method)


def principal_of(user: User, method: str | None = None) -> Principal:
    return Principal(user_id=user.id, role=user.role, name=user.name, email=user.email, auth_method=method)


def sim_driver_principal(bus_id: str, driver_user_id: str) -> Principal:
    """Principal the simulator uses when it acts as the driver of ``bus_id``."""
    return Principal(
        user_id=driver_user_id, role=Role.DRIVER, name=f"sim:{bus_id}", bus_id=bus_id, source="sim"
    )
