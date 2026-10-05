"""FastAPI application factory.

    uvicorn app.main:app --reload          # from backend/

``create_app(container=...)`` lets tests inject an in-memory container; in
normal runs the lifespan builds the real one (MongoDB, clock, event bus).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.auth import IdentityVerifier, OidcTokenVerifier, SessionTokenService, TokenVerifier, UserLookup
from app.core.clock import Clock, RealClock, SimClock, resolve_sim_start
from app.core.config import Settings, get_settings
from app.core.db import Database, ensure_indexes
from app.core.errors import install_exception_handlers
from app.core.events import InProcessEventBus
from app.deps import AppContainer
from app.repositories.mongo import mongo_repositories
from app.services.bus_simulator import BusSimulator

log = logging.getLogger("campusride")


def build_clock(settings: Settings) -> Clock:
    if settings.clock_mode == "real":
        return RealClock(settings.tz)
    start = resolve_sim_start(settings.sim_start_date, settings.sim_start_time, settings.tz)
    return SimClock(
        start,
        speed=settings.sim_speed,
        seed=settings.seed,
        tz=settings.tz,
        paused=not settings.sim_autostart,
    )


def build_auth(settings: Settings, users: UserLookup) -> tuple[TokenVerifier, SessionTokenService | None]:
    """THE authentication boundary for REST and WebSocket (Feature 15), per AUTH_MODE.

    Returns the identity verifier and, for dev / password modes, the session-token issuer.
    There is no fallback: each mode accepts only its own credentials.
    """
    if settings.auth_mode == "oidc":
        oidc = OidcTokenVerifier(
            issuer=settings.oidc_issuer, audience=settings.oidc_audience, jwks_url=settings.oidc_jwks_url
        )
        return IdentityVerifier(oidc, users, link_by_email=settings.oidc_link_by_email), None
    tokens = SessionTokenService(settings.auth_token_secret, settings.auth_token_ttl_s, settings.auth_mode)
    if settings.auth_mode == "dev":
        log.warning("AUTH_MODE=dev — DEVELOPMENT sign-in (no passwords). Never use this in production.")
    return IdentityVerifier(tokens, users), tokens


async def build_container(settings: Settings) -> AppContainer:
    database = Database(settings.mongo_uri, settings.mongo_db)
    if not await database.ping():
        database.close()
        raise RuntimeError(
            f"MongoDB is not reachable at {settings.mongo_uri}. "
            "Start it with: docker compose -f infra/docker-compose.yml up -d"
        )
    await ensure_indexes(database.db, telemetry_ttl_days=settings.telemetry_ttl_days)
    repos = mongo_repositories(database.db)
    verifier, session_tokens = build_auth(settings, repos.users)
    container = AppContainer(
        settings=settings,
        clock=build_clock(settings),
        events=InProcessEventBus(),
        repos=repos,
        verifier=verifier,
        session_tokens=session_tokens,
        database=database,
    )
    attach_simulator(container)
    return container


def attach_simulator(c: AppContainer) -> None:
    """Create the (single) simulator for this app when enabled and the clock is simulated."""
    if c.settings.sim_enabled and isinstance(c.clock, SimClock) and c.simulator is None:
        c.simulator = BusSimulator(c.repos, c.clock, c.telemetry_ingest(), c.settings)


def create_app(settings: Settings | None = None, container: AppContainer | None = None) -> FastAPI:
    settings = container.settings if container else (settings or get_settings())
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = False
        if getattr(app.state, "container", None) is None:
            app.state.container = await build_container(settings)
            owned = True
        c: AppContainer = app.state.container
        if c.simulator is not None:
            # Lifespan owns the simulator: prepare once, ONE loop task, stopped on shutdown.
            await c.simulator.reset()
            c.simulator.ensure_loop()
        c.alert_monitor().ensure_loop()  # Feature 11: student alert sweep on the sim clock
        c.realtime().ensure_loop()  # Feature 14: coalesced WebSocket push
        log.info(
            "CampusRide up — clock %s (%s), auth=%s",
            c.clock.local_now().isoformat(),
            settings.clock_mode,
            settings.auth_mode,
        )
        try:
            yield
        finally:
            await c.realtime().shutdown()
            await c.alert_monitor().shutdown()
            if c.simulator is not None:
                await c.simulator.shutdown()
            if owned and c.database is not None:
                c.database.close()

    app = FastAPI(
        title="CampusRide API",
        version="0.1.0",
        description="Intelligent college bus commute assistant — synthetic-data prototype.",
        lifespan=lifespan,
    )
    app.state.container = container
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
