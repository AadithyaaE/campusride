from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, datetime

import httpx
import pytest

from app.core.auth import MockTokenService
from app.core.clock import DEFAULT_TZ, ManualClock
from app.core.config import BACKEND_DIR, Settings
from app.core.events import InProcessEventBus
from app.deps import AppContainer
from app.main import create_app
from app.repositories.memory import memory_repositories
from app.seed import SeedBundle, load_seed, persist_seed

SEED = 42
SERVICE_DATE = date(2026, 10, 5)  # a Monday
SIM_START = datetime(2026, 10, 5, 7, 15, tzinfo=DEFAULT_TZ)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(_env_file=None, app_env="test", seed=SEED, mock_token_secret="test-secret")


@pytest.fixture(scope="session")
def bundle() -> SeedBundle:
    return load_seed(BACKEND_DIR / "data" / "seed", SEED)


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(SIM_START, seed=SEED)


@pytest.fixture
async def container(settings: Settings, bundle: SeedBundle, clock: ManualClock) -> AppContainer:
    repos = memory_repositories()
    await persist_seed(repos, bundle, SERVICE_DATE, DEFAULT_TZ)
    tokens = MockTokenService(settings.mock_token_secret, settings.mock_token_ttl_s)
    return AppContainer(
        settings=settings,
        clock=clock,
        events=InProcessEventBus(),
        repos=repos,
        verifier=tokens,
        mock_tokens=tokens,
    )


@pytest.fixture
async def client(container: AppContainer) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(container=container)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as c:
        yield c


async def login(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    resp = await client.post("/auth/mock-login", json={"email": email})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def student_headers(client: httpx.AsyncClient) -> dict[str, str]:
    return await login(client, "student001@campusride.demo")


@pytest.fixture
async def live_client(container: AppContainer) -> AsyncIterator[tuple[httpx.AsyncClient, AppContainer]]:
    """App with the synthetic simulator attached and prepared (as the lifespan would)."""
    from app.main import attach_simulator

    attach_simulator(container)
    assert container.simulator is not None
    await container.simulator.reset()
    app = create_app(container=container)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1") as c:
        yield c, container
    await container.simulator.shutdown()


async def advance(container: AppContainer, seconds: int) -> None:
    """Advance the ManualClock in 5 s steps, emitting telemetry like the real loop."""
    for _ in range(seconds // 5):
        container.clock.advance(5)
        await container.simulator.step_until(container.clock.now())
