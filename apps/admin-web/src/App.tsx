/**
 * CampusRide admin dashboard (prototype). Mock login → admins only → transport control
 * room (Feature 13). Everything shown comes from the backend; this app keeps no transport
 * state of its own.
 */
import { useCallback, useMemo, useState, type FormEvent } from "react";

import { AdminApi, ApiError, type MeOut } from "./api/client";
import { config } from "./config";
import { ControlRoom } from "./dashboard/ControlRoom";

const SESSION_KEY = "campusride.admin.session";

interface Session {
  token: string;
  expiresAt: string;
  name: string;
}

function readSession(storage: Storage): Session | null {
  try {
    const raw = storage.getItem(SESSION_KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as Partial<Session>;
    if (!s.token || !s.expiresAt || Date.parse(s.expiresAt) <= Date.now()) return null;
    return { token: s.token, expiresAt: s.expiresAt, name: s.name ?? "Admin" };
  } catch {
    return null;
  }
}

interface Props {
  fetchImpl?: typeof fetch;
  storage?: Storage;
}

export function App({ fetchImpl, storage = window.localStorage }: Props) {
  const [session, setSession] = useState<Session | null>(() => readSession(storage));
  const logout = useCallback(() => {
    try {
      storage.removeItem(SESSION_KEY);
    } catch {
      /* storage unavailable: nothing to clear */
    }
    setSession(null);
  }, [storage]);
  const api = useMemo(
    () =>
      new AdminApi({
        baseUrl: config.apiBaseUrl,
        getToken: () => session?.token ?? null,
        onUnauthorized: logout,
        fetchImpl,
      }),
    [session, logout, fetchImpl],
  );

  const login = async (email: string) => {
    const t = await api.mockLogin(email);
    const probe = new AdminApi({
      baseUrl: config.apiBaseUrl,
      getToken: () => t.access_token,
      fetchImpl,
    });
    const me: MeOut = await probe.me();
    if (me.role !== "admin") {
      throw new ApiError(403, "forbidden", "This dashboard is for college transport admins only.");
    }
    const s = { token: t.access_token, expiresAt: t.expires_at, name: me.name };
    try {
      storage.setItem(SESSION_KEY, JSON.stringify(s));
    } catch {
      /* session simply won't survive a reload */
    }
    setSession(s);
  };

  return (
    <div className="app">
      <header className="topbar">
        <strong className="brand">
          CampusRide <span className="brand-sub">Transport Control</span>
        </strong>
        {session && (
          <span className="who">
            {session.name}{" "}
            <button type="button" className="btn btn-ghost" onClick={logout}>
              Sign out
            </button>
          </span>
        )}
      </header>
      <main className={session ? "main main-wide" : "main"}>
        {session ? <ControlRoom api={api} /> : <Login onLogin={login} />}
      </main>
    </div>
  );
}

function Login({ onLogin }: { onLogin: (email: string) => Promise<void> }) {
  const [email, setEmail] = useState("admin1@campusride.demo");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    onLogin(email.trim())
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setBusy(false));
  };
  return (
    <form className="card login" onSubmit={submit} aria-label="Admin sign in">
      <h1>Admin sign in</h1>
      <p className="muted">Mock authentication (prototype) — no password.</p>
      <label>
        Email
        <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" className="btn btn-primary" disabled={busy}>
        {busy ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
