"""WebSocket connection manager (Feature 14) — process-local, in memory.

Each authenticated socket is a ``Connection`` with its own bounded send queue; a writer
task (owned by the endpoint) drains it to the socket. ``send`` therefore never awaits the
network: the simulator / API request that published an event can't be slowed down or
crashed by a slow or dead client. A client whose queue overflows is marked for closing.

Audience rules are evaluated here from the authenticated principal only:

* ``roles``      — every connection with one of these roles (e.g. all admins);
* ``users``      — these user ids only (a student's own alerts, one driver);
* ``driver_bus`` — driver connections bound to this bus (the driver's OWN bus).

LIMITATION: state lives in this process. With several workers each would hold its own
connections; a shared broker (e.g. Redis pub/sub) would be needed — see docs.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from dataclasses import dataclass, field

from app.core.auth import Principal
from app.models.common import Role

log = logging.getLogger(__name__)

_ids = itertools.count(1)


@dataclass(frozen=True)
class Audience:
    roles: frozenset[Role] = frozenset()
    users: frozenset[str] = frozenset()
    driver_bus: str | None = None

    @classmethod
    def fleet(cls, bus_id: str | None) -> Audience:
        """Fleet-level bus facts: all admins and students (``GET /buses`` is open to them) +
        the driver of THAT bus. Other drivers never receive another bus's updates."""
        return cls(roles=frozenset({Role.ADMIN, Role.STUDENT}), driver_bus=bus_id)

    @classmethod
    def admins(cls) -> Audience:
        return cls(roles=frozenset({Role.ADMIN}))

    @classmethod
    def user(cls, user_id: str) -> Audience:
        return cls(users=frozenset({user_id}))

    @classmethod
    def everyone(cls) -> Audience:
        return cls(roles=frozenset(Role))


@dataclass
class Connection:
    principal: Principal
    bus_id: str | None
    """Drivers: the bus they are assigned to (private updates); None otherwise."""
    queue: asyncio.Queue[str | None]
    id: int = field(default_factory=lambda: next(_ids))
    last_seen: float = field(default_factory=time.monotonic)
    closing: str | None = None
    """Set when the manager wants the endpoint to close this socket (reason)."""
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    """Signals the endpoint to close the socket now (``closing`` says why)."""

    def close(self, reason: str) -> None:
        if not self.closing:
            self.closing = reason
        self.stop.set()

    def matches(self, a: Audience) -> bool:
        p = self.principal
        if p.role in a.roles:
            return True
        if p.user_id in a.users:
            return True
        return a.driver_bus is not None and p.role is Role.DRIVER and self.bus_id == a.driver_bus

    def offer(self, text: str) -> bool:
        if self.closing:
            return False
        try:
            self.queue.put_nowait(text)
            return True
        except asyncio.QueueFull:
            self.close("too_slow")
            log.warning("ws %s (%s) fell behind; disconnecting", self.id, self.principal.user_id)
            return False


class ConnectionManager:
    def __init__(self, queue_size: int) -> None:
        self._queue_size = queue_size
        self._conns: dict[int, Connection] = {}

    def connect(self, principal: Principal, bus_id: str | None) -> Connection:
        conn = Connection(principal=principal, bus_id=bus_id, queue=asyncio.Queue(self._queue_size))
        self._conns[conn.id] = conn
        return conn

    def disconnect(self, conn: Connection) -> None:
        self._conns.pop(conn.id, None)

    def __len__(self) -> int:
        return len(self._conns)

    @property
    def connections(self) -> list[Connection]:
        return list(self._conns.values())

    def has_role(self, role: Role) -> bool:
        return any(c.principal.role is role for c in self._conns.values())

    def drivers_of(self, bus_id: str) -> list[Connection]:
        return [c for c in self._conns.values() if c.principal.role is Role.DRIVER and c.bus_id == bus_id]

    def send(self, text: str, audience: Audience) -> int:
        """Queue ``text`` for every matching connection; returns how many accepted it."""
        return sum(c.offer(text) for c in list(self._conns.values()) if c.matches(audience))

    def send_to(self, conn: Connection, text: str) -> bool:
        return conn.offer(text)
