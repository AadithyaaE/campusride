/**
 * Persists the mock-auth session (bearer token) across browser refreshes.
 *
 * Only the token and its expiry are stored. Who the user is always comes
 * from `GET /me` on startup, so a refresh reconstructs state from the backend.
 */

export interface Session {
  token: string;
  expiresAt: string;
  userId: string;
}

const KEY = "campusride.session";

/** localStorage when usable (it can throw in private mode / sandboxes). */
export function browserStorage(): Storage | null {
  try {
    const s = window.localStorage;
    const probe = "__campusride_probe__";
    s.setItem(probe, "1");
    s.removeItem(probe);
    return s;
  } catch {
    return null;
  }
}

export class SessionStore {
  private memory: Session | null = null;
  private readonly listeners = new Set<() => void>();
  private readonly storage: Storage | null;
  private readonly now: () => number;

  constructor(storage: Storage | null, now: () => number = Date.now) {
    this.storage = storage;
    this.now = now;
  }

  get(): Session | null {
    const s = this.memory ?? this.read();
    if (!s) return null;
    if (Date.parse(s.expiresAt) <= this.now()) {
      this.clear();
      return null;
    }
    return s;
  }

  set(session: Session): void {
    this.memory = session;
    try {
      this.storage?.setItem(KEY, JSON.stringify(session));
    } catch {
      /* storage full/blocked: keep the in-memory session */
    }
    this.emit();
  }

  clear(): void {
    const had = this.memory !== null || this.read() !== null;
    this.memory = null;
    try {
      this.storage?.removeItem(KEY);
    } catch {
      /* ignore */
    }
    if (had) this.emit();
  }

  subscribe(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private read(): Session | null {
    try {
      const raw = this.storage?.getItem(KEY);
      if (!raw) return null;
      const s = JSON.parse(raw) as Partial<Session>;
      if (
        typeof s.token === "string" &&
        typeof s.expiresAt === "string" &&
        typeof s.userId === "string"
      ) {
        return s as Session;
      }
    } catch {
      /* corrupted entry */
    }
    return null;
  }

  private emit(): void {
    for (const fn of this.listeners) fn();
  }
}
