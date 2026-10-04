/** Scriptable stand-in for the browser WebSocket (installed globally in test setup). */
let seq = 0;
let ids = 0;

export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static reset() {
    FakeWebSocket.instances = [];
  }
  static get last(): FakeWebSocket {
    const s = FakeWebSocket.instances.at(-1);
    if (!s) throw new Error("no WebSocket was opened");
    return s;
  }

  readonly url: string;
  readyState = 0;
  sent: Record<string, unknown>[] = [];
  onopen: ((e: unknown) => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(text: string) {
    this.sent.push(JSON.parse(text) as Record<string, unknown>);
  }

  close(code = 1000) {
    if (this.readyState === 3) return;
    this.readyState = 3;
    this.onclose?.({ code });
  }

  // ------------------------------------------------------------ test controls (the "server")

  /** Accept the socket and answer the client's auth with `hello`. */
  accept(data: Record<string, unknown> = { role: "admin", heartbeat_s: 20 }) {
    this.readyState = 1;
    this.onopen?.({});
    this.emit("hello", data);
  }

  emit(type: string, data: unknown, over: { id?: string; seq?: number } = {}) {
    seq = over.seq ?? seq + 1;
    const env = {
      id: over.id ?? `evt-${++ids}`,
      type,
      seq,
      ts: "2026-10-05T02:10:00Z",
      sent_at: "2026-10-05T02:10:00Z",
      scope: "fleet",
      data,
    };
    this.onmessage?.({ data: JSON.stringify(env) });
    return env;
  }

  /** The server/network drops the connection. */
  drop(code = 1006) {
    this.close(code);
  }
}
