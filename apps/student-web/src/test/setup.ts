import "@testing-library/jest-dom/vitest";
import { beforeEach, vi } from "vitest";

import { FakeWebSocket } from "./fakeSocket";

// No real sockets in tests: each test drives the fake "server" explicitly.
vi.stubGlobal("WebSocket", FakeWebSocket);
beforeEach(() => FakeWebSocket.reset());
