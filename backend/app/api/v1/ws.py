"""``/api/v1/ws`` — real-time push of backend state changes (Feature 14).

Protocol:
1. Client connects, then sends ``{"type": "auth", "token": "<bearer token>"}`` within
   ``WS_AUTH_TIMEOUT_S`` (the same mock/Firebase token as the REST API; first-message auth
   keeps tokens out of URLs and proxy logs). Invalid → close 4401; timeout → 4408.
2. Server answers ``hello`` (user, role, the driver's bus) and then pushes typed envelopes
   (``app/realtime/messages.py``) to this user's audience only.
3. Heartbeat: server sends ``ping`` every ``WS_HEARTBEAT_S``; the client answers ``pong``.
   A socket silent for ``WS_IDLE_TIMEOUT_S`` is closed (4410) and cleaned up.

The socket is receive-only for application data: actions stay on REST (start/stop trip,
QR scan, mark read…). Clients load state over REST first and re-sync over REST after a
reconnect — events are never the only source of truth.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.auth import Principal
from app.core.errors import CampusRideError
from app.models.common import Role
from app.realtime.manager import Connection
from app.realtime.messages import CLOSE_AUTH_TIMEOUT, CLOSE_IDLE, CLOSE_TOO_SLOW, CLOSE_UNAUTHORIZED

router = APIRouter(tags=["realtime"])
log = logging.getLogger(__name__)


async def _authenticate(ws: WebSocket, c) -> Principal | None:
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=c.settings.ws_auth_timeout_s)
    except TimeoutError:
        await ws.close(CLOSE_AUTH_TIMEOUT, "authentication timeout")
        return None
    try:
        msg = json.loads(raw)
        token = msg.get("token") if isinstance(msg, dict) and msg.get("type") == "auth" else None
        if not isinstance(token, str) or not token:
            raise ValueError("first message must be {type: auth, token}")
        return await c.verifier.verify(token)
    except (ValueError, CampusRideError):
        await ws.close(CLOSE_UNAUTHORIZED, "invalid or missing token")
        return None


async def _driver_bus(c, principal: Principal) -> str | None:
    """A driver socket is bound to the bus assigned to THAT driver (never chosen by the client)."""
    if principal.role is not Role.DRIVER:
        return None
    driver = await c.repos.drivers.by_user(principal.user_id)
    if driver is None:
        return None
    return next((b.id for b in await c.repos.buses.list() if b.driver_id == driver.id), None)


@router.websocket("/ws")
async def realtime(ws: WebSocket) -> None:
    c = ws.app.state.container
    hub = c.realtime()
    await ws.accept()
    try:
        principal = await _authenticate(ws, c)
    except WebSocketDisconnect:
        return
    if principal is None:
        return
    conn = hub.manager.connect(principal, await _driver_bus(c, principal))
    hub.ensure_loop()
    conn.offer(hub.hello(conn))
    tasks = [
        asyncio.create_task(_writer(ws, conn), name=f"ws-writer-{conn.id}"),
        asyncio.create_task(_reader(ws, conn), name=f"ws-reader-{conn.id}"),
        asyncio.create_task(_heartbeat(conn, hub, c.settings), name=f"ws-heartbeat-{conn.id}"),
        asyncio.create_task(conn.stop.wait(), name=f"ws-stop-{conn.id}"),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        hub.manager.disconnect(conn)  # no more events are queued for this socket
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        code = {"idle": CLOSE_IDLE, "too_slow": CLOSE_TOO_SLOW}.get(conn.closing or "", 1000)
        with contextlib.suppress(Exception):
            await ws.close(code, conn.closing or "")


async def _writer(ws: WebSocket, conn: Connection) -> None:
    while True:
        text = await conn.queue.get()
        if text is None:
            return
        try:
            await ws.send_text(text)
        except Exception:  # dead socket: stop; the endpoint cleans up
            conn.close("send_failed")
            return


async def _reader(ws: WebSocket, conn: Connection) -> None:
    try:
        while True:
            await ws.receive_text()  # pong (or anything) proves the client is alive
            conn.last_seen = time.monotonic()
    except (WebSocketDisconnect, RuntimeError):
        conn.close("disconnected")


async def _heartbeat(conn: Connection, hub, settings) -> None:
    while True:
        await asyncio.sleep(settings.ws_heartbeat_s)
        if time.monotonic() - conn.last_seen > settings.ws_idle_timeout_s:
            conn.close("idle")
            return
        conn.offer(hub.ping())
