/** Jest setup: no real sockets — tests drive a fake WebSocket "server" explicitly. */
import { FakeWebSocket } from "./fakeSocket";

(globalThis as { WebSocket: unknown }).WebSocket = FakeWebSocket;
beforeEach(() => FakeWebSocket.reset());
