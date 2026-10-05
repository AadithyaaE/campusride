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

from app.core.auth import Principal, SessionTokenService, TokenVerifier
from app.core.clock import Clock
from app.core.config import Settings
from app.core.db import Database
from app.core.errors import AuthError, ForbiddenError
from app.core.events import EventBus
from app.models.common import Role
from app.models.events import BusStateUpdated
from app.realtime.hub import RealtimeHub
from app.repositories import Repositories
from app.services.admin_service import AdminService
from app.services.alert_monitor import AlertMonitor
from app.services.alert_service import AlertService
from app.services.boarding_service import BoardingService
from app.services.bus_comparison_service import BusComparisonService
from app.services.bus_simulator import BusSimulator
from app.services.commute_decision_service import CommuteDecisionService
from app.services.eta_service import EtaService
from app.services.matching import MatchingService
from app.services.missed_bus_service import MissedBusService
from app.services.ridership import RidershipLedger
from app.services.route_anomaly_service import RouteAnomalyService
from app.services.student_commute_service import StudentCommuteService
from app.services.student_location import StudentLocationSource
from app.services.tracking import TelemetryIngestService


@dataclass
class AppContainer:
    settings: Settings
    clock: Clock
    events: EventBus
    repos: Repositories
    verifier: TokenVerifier
    session_tokens: SessionTokenService | None = None
    """Backend session-token issuer (AUTH_MODE dev / password); None for oidc."""
    database: Database | None = None
    ingest: TelemetryIngestService | None = None
    """The ONE telemetry ingestion path (driver API + simulator)."""
    simulator: BusSimulator | None = None
    """Synthetic bus simulator (None when SIM_ENABLED=false or CLOCK_MODE=real)."""
    matching_service: MatchingService | None = None
    eta_service: EtaService | None = None
    comparison_service: BusComparisonService | None = None
    commute_service: CommuteDecisionService | None = None
    boarding_service: BoardingService | None = None
    recovery_service: MissedBusService | None = None
    alert_monitor_service: AlertMonitor | None = None
    ridership_ledger: RidershipLedger | None = None
    """Feature 13 — per-trip peak load, fed by the ingest pipeline's BusStateUpdated events."""
    admin_service: AdminService | None = None
    realtime_hub: RealtimeHub | None = None
    """Feature 14 — EventBus → WebSocket push (subscribed when the container is created)."""

    def __post_init__(self) -> None:
        # Subscribe before anything publishes, so no state change is missed by live clients.
        self.realtime()

    def realtime(self) -> RealtimeHub:
        if self.realtime_hub is None:
            self.realtime_hub = RealtimeHub(self)
            self.realtime_hub.attach()
        return self.realtime_hub

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

    def commute(self) -> CommuteDecisionService:
        """ "Will I make my bus?" on top of comparison / ETA / matching (+ synthetic location)."""
        if self.commute_service is None:
            self.commute_service = CommuteDecisionService(
                self.comparison(),
                self.repos,
                self.settings,
                self.clock,
                StudentLocationSource(self.settings),
            )
        return self.commute_service

    def recovery(self) -> MissedBusService:
        """Missed-bus recovery on top of the commute decision (→ comparison → ETA → matching)."""
        if self.recovery_service is None:
            self.recovery_service = MissedBusService(self.commute(), self.settings, self.clock)
        return self.recovery_service

    def boarding(self) -> BoardingService:
        """QR boarding + live occupancy; shares the ONE ingest service (occupancy writes)."""
        if self.boarding_service is None:
            self.boarding_service = BoardingService(
                self.repos, self.clock, self.events, self.matching(), self.telemetry_ingest()
            )
        return self.boarding_service

    def alerts(self) -> AlertService:
        """Feature 11 — the ONE alert service (shared with the telemetry pipeline)."""
        return self.telemetry_ingest().alerts

    def alert_monitor(self) -> AlertMonitor:
        """Feature 11 — periodic student-alert sweep (approaching / missed / alternative)."""
        if self.alert_monitor_service is None:
            self.alert_monitor_service = AlertMonitor(
                self.alerts(), self.recovery(), self.repos, self.clock, self.settings
            )
        return self.alert_monitor_service

    def route_anomaly(self) -> RouteAnomalyService:
        """Feature 10 — the SAME instance the telemetry pipeline uses for transitions."""
        return self.telemetry_ingest().anomaly

    def telemetry_ingest(self) -> TelemetryIngestService:
        if self.ingest is None:
            self.ingest = TelemetryIngestService(self.repos, self.events, self.clock, self.settings)
            self.ridership_ledger = RidershipLedger()
            self.events.subscribe(
                BusStateUpdated, self.ridership_ledger.on_bus_state, name=f"ridership.bus_state.{id(self)}"
            )
        return self.ingest

    def ridership(self) -> RidershipLedger:
        self.telemetry_ingest()
        assert self.ridership_ledger is not None
        return self.ridership_ledger

    def student_commute(self) -> StudentCommuteService:
        """Feature 16 — today's commute + history over the existing student services."""
        return StudentCommuteService(self.repos, self.clock, self.recovery(), self.boarding(), self.alerts())

    def admin(self) -> AdminService:
        """Feature 13 — admin dashboard read models over the existing services."""
        if self.admin_service is None:
            self.admin_service = AdminService(
                self.repos,
                self.settings,
                self.clock,
                self.matching(),
                self.eta(),
                self.alerts(),
                self.ridership(),
                self.simulator,
            )
        return self.admin_service


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
