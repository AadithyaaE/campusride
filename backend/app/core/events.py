"""In-process domain event bus.

Modules never call each other's internals; they publish and subscribe to
domain events (catalogue in ``app.models.events``)::

    tracking ──BusStateUpdated──▶ eta, deviation, alerts, realtime

``InProcessEventBus`` awaits handlers sequentially in registration order,
which keeps the pipeline deterministic for the simulator. A failing handler
is logged and isolated — it never breaks the publisher or other handlers.
A Redis-backed bus can implement the same ``EventBus`` protocol later.
"""

from __future__ import annotations

import itertools
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from app.models.events import DomainEvent

E = TypeVar("E", bound=DomainEvent)
Handler = Callable[[E], Awaitable[None]]

log = logging.getLogger(__name__)


class EventBus(Protocol):
    def subscribe(self, event_type: type[E], handler: Handler[E], *, name: str) -> None:
        """Register ``handler`` for ``event_type`` and its subclasses."""
        ...

    async def publish(self, event: DomainEvent) -> None:
        """Deliver ``event`` to every matching handler."""
        ...


@dataclass
class HandlerStats:
    calls: int = 0
    failures: int = 0
    total_s: float = 0.0
    last_error: str | None = None


@dataclass(frozen=True)
class _Subscription:
    order: int
    event_type: type[DomainEvent]
    handler: Handler
    name: str


@dataclass
class InProcessEventBus:
    _subs: list[_Subscription] = field(default_factory=list)
    _counter: itertools.count = field(default_factory=itertools.count)
    stats: dict[str, HandlerStats] = field(default_factory=dict)
    published: int = 0

    def subscribe(self, event_type: type[E], handler: Handler[E], *, name: str) -> None:
        if name in self.stats:
            raise ValueError(f"duplicate event handler name: {name}")
        self._subs.append(_Subscription(next(self._counter), event_type, handler, name))
        self.stats[name] = HandlerStats()

    def handlers_for(self, event: DomainEvent) -> list[str]:
        return [s.name for s in self._subs if isinstance(event, s.event_type)]

    async def publish(self, event: DomainEvent) -> None:
        self.published += 1
        for sub in self._subs:  # already in registration order
            if not isinstance(event, sub.event_type):
                continue
            st = self.stats[sub.name]
            st.calls += 1
            t0 = time.perf_counter()
            try:
                await sub.handler(event)
            except Exception as exc:
                st.failures += 1
                st.last_error = f"{type(exc).__name__}: {exc}"
                log.exception("event handler %s failed on %s", sub.name, event.event_type)
            finally:
                st.total_s += time.perf_counter() - t0
