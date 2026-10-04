"""Minimal in-loop ASGI WebSocket client for tests.

Drives the REAL ``/api/v1/ws`` endpoint on the SAME event loop as the simulator and the
``ManualClock`` (Starlette's TestClient would run the app in another thread/loop).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any


class WsClosed(Exception):
    def __init__(self, code: int, reason: str = "") -> None:
        super().__init__(f"closed {code} {reason}")
        self.code = code


class WsTestClient:
    def __init__(self, app, path: str = "/api/v1/ws") -> None:
        self._app = app
        self._path = path
        self._in: asyncio.Queue[dict] = asyncio.Queue()
        self._out: asyncio.Queue[dict] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self.close_code: int | None = None

    async def connect(self) -> WsTestClient:
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "scheme": "ws",
            "http_version": "1.1",
            "path": self._path,
            "raw_path": self._path.encode(),
            "root_path": "",
            "query_string": b"",
            "headers": [(b"host", b"test")],
            "client": ("testclient", 50000),
            "server": ("test", 80),
            "subprotocols": [],
            "state": {},
        }
        await self._in.put({"type": "websocket.connect"})
        self._task = asyncio.create_task(self._app(scope, self._in.get, self._out.put))
        msg = await asyncio.wait_for(self._out.get(), 2)
        assert msg["type"] == "websocket.accept", msg
        return self

    async def send(self, obj: Any) -> None:
        await self._in.put({"type": "websocket.receive", "text": json.dumps(obj)})

    async def auth(self, headers: dict[str, str]) -> dict:
        """Authenticate with a REST bearer header; returns the ``hello`` envelope."""
        await self.send({"type": "auth", "token": headers["Authorization"].removeprefix("Bearer ")})
        hello = await self.recv()
        assert hello["type"] == "hello", hello
        return hello

    async def recv(self, wait_s: float = 2.0) -> dict:
        msg = await asyncio.wait_for(self._out.get(), wait_s)
        if msg["type"] == "websocket.close":
            self.close_code = msg.get("code", 1000)
            raise WsClosed(self.close_code, msg.get("reason", ""))
        return json.loads(msg["text"])

    async def drain(self) -> list[dict]:
        """Everything the server has sent so far (lets queued writer tasks run first)."""
        for _ in range(20):
            await asyncio.sleep(0)
        out: list[dict] = []
        while not self._out.empty():
            msg = self._out.get_nowait()
            if msg["type"] == "websocket.close":
                self.close_code = msg.get("code", 1000)
                break
            out.append(json.loads(msg["text"]))
        return out

    async def close(self) -> None:
        await self._in.put({"type": "websocket.disconnect", "code": 1000})
        if self._task is not None:
            await asyncio.wait_for(self._task, 2)

    async def wait_closed(self, wait_s: float = 2.0) -> int:
        while True:
            msg = await asyncio.wait_for(self._out.get(), wait_s)
            if msg["type"] == "websocket.close":
                self.close_code = msg.get("code", 1000)
                return self.close_code


def types(msgs: list[dict]) -> list[str]:
    return [m["type"] for m in msgs]


def of_type(msgs: list[dict], type_: str) -> list[dict]:
    return [m for m in msgs if m["type"] == type_]
