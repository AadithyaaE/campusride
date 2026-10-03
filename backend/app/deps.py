"""Application container and FastAPI dependency providers.

Everything a router needs comes through here, so tests can swap the whole
container (memory repositories, ``ManualClock``) without touching routers.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth import MockTokenService, Principal, TokenVerifier
from app.core.clock import Clock
from app.core.config import Settings
from app.core.db import Database
from app.core.errors import AuthError, ForbiddenError
from app.core.events import EventBus
from app.models.common import Role
from app.repositories import Repositories
from app.services.bus_comparison_service import BusComparisonService
from app.services.bus_simulator import BusSimulator
from app.services.eta_service import EtaService
from app.services.matching import MatchingService
from app.services.tracking import TelemetryIngestService


@dataclass
class AppContainer:
    settings: Settings
    clock: Clock
    events: EventBus
    repos: Repositories
    verifier: TokenVerifier
    mock_tokens: MockTokenService | None = None
    database: Database | None = None
    ingest: TelemetryIngestService | None = None
    """The ONE telemetry ingestion path (driver API + simulator)."""
    simulator: BusSimulator | None = None
    """Synthetic bus simulator (None when SIM_ENABLED=false or CLOCK_MODE=real)."""
    matching_service: MatchingService | None = None
    eta_service: EtaService | None = None
    comparison_service: BusComparisonService | None = None

    def matching(self) -> MatchingService:
        """Stop ↔ bus matching (caches static route data for the app's lifetime)."""
        if self.matching_service is None:
            self.matching_service = MatchingService(self.repos, self.settings)
        return self.matching_service

    def eta(self) -> EtaService:
        """Backend ETA prediction on top of matching (caches traffic profiles / road-class tables)."""
        if self.eta_service is None:
            self.eta_service = EtaService(self.repos, self.settings, self.clock, self.matching())
        return self.eta_service

    def comparison(self) -> BusComparisonService:
        """Multi-bus comparison on top of ETA (+ matching) — no state of its own."""
        if self.comparison_service is None:
            self.comparison_service = BusComparisonService(self.eta(), self.settings, self.clock)
        return self.comparison_service

    def telemetry_ingest(self) -> TelemetryIngestService:
        if self.ingest is None:
            self.ingest = TelemetryIngestService(self.repos, self.events, self.clock, self.settings)
        return self.ingest


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


Container = Annotated[AppContainer, Depends(get_container)]


def get_repos(c: Container) -> Repositories:
    return c.repos


def get_clock(c: Container) -> Clock:
    return c.clock


Repos = Annotated[Repositories, Depends(get_repos)]
AppClock = Annotated[Clock, Depends(get_clock)]

_bearer = HTTPBearer(auto_error=False, description="Mock token from POST /api/v1/auth/mock-login")


async def get_principal(
    c: Container,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if creds is None or not creds.credentials:
        raise AuthError("missing bearer token")
    return await c.verifier.verify(creds.credentials)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_role(*roles: Role) -> Callable[[Principal], Awaitable[Principal]]:
    """Dependency factory: ``Depends(require_role(Role.ADMIN))``."""

    async def _check(principal: CurrentPrincipal) -> Principal:
        if principal.role not in roles:
            raise ForbiddenError(f"requires role: {', '.join(r.value for r in roles)}")
        return principal

    return _check
