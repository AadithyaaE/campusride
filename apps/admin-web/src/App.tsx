/**
 * CampusRide admin dashboard. Sign-in (Feature 15: development or email + password, as the
 * backend's `/auth/config` says) → admins only → transport control room (Feature 13).
 * The session (backend token + expiry, never a password) lives in sessionStorage: it ends
 * with the tab, and any 401 / WebSocket 4401 signs out. Everything shown comes from the
 * backend; this app keeps no transport state of its own.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { AdminApi, ApiError, type AuthConfig, type MeOut, type TokenOut } from "./api/client";
import { config } from "./config";
import { ControlRoom } from "./dashboard/ControlRoom";
import { RoleSignIn } from "./signin/RoleSignIn";

const SESSION_KEY = "campusride.admin.session";
const ADMIN_ONLY_MESSAGE =
  "This isn't an admin account. Students can sign in by choosing Student above.";

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

export function App({ fetchImpl, storage = window.sessionStorage }: Props) {
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

  const login = async (email: string, password: string | null) => {
    const t: TokenOut =
      password === null ? await api.devLogin(email) : await api.passwordLogin(email, password);
    const probe = new AdminApi({
      baseUrl: config.apiBaseUrl,
      getToken: () => t.access_token,
      fetchImpl,
    });
    const me: MeOut = await probe.me();
    if (me.role !== "admin") {
      throw new ApiError(403, "forbidden", ADMIN_ONLY_MESSAGE);
    }
    const s = { token: t.access_token, expiresAt: t.expires_at, name: me.name };
    try {
      storage.setItem(SESSION_KEY, JSON.stringify(s));
    } catch {
      /* session simply won't survive a reload */
    }
    setSession(s);
  };

  if (!session) return <Login api={api} onLogin={login} />;
  return (
    <div className="app">
      <header className="topbar">
        <strong className="brand">
          <span className="brand-mark" aria-hidden="true">
            <svg
              viewBox="0 0 24 24"
              width="18"
              height="18"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.9"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="4" y="3" width="16" height="14" rx="3" />
              <path d="M4 10h16M8 17v3M16 17v3" />
            </svg>
          </span>
          CampusRide <span className="brand-sub">Transport Control</span>
        </strong>
        <span className="who">
          {session.name}{" "}
          <button type="button" className="btn btn-ghost" onClick={logout}>
            Sign out
          </button>
        </span>
      </header>
      <main className="main main-wide">
        <ControlRoom api={api} />
      </main>
    </div>
  );
}

const errorText = (err: unknown) => (err instanceof Error ? err.message : String(err));

/** Admin sign-in on the shared CampusRide sign-in page. Only admin accounts get in. */
function Login({
  api,
  onLogin,
}: {
  api: AdminApi;
  onLogin: (email: string, password: string | null) => Promise<void>;
}) {
  const [cfg, setCfg] = useState<AuthConfig | null>(null);
  const [cfgError, setCfgError] = useState<string | null>(null);
  useEffect(() => {
    api.authConfig().then(setCfg, (e: unknown) => setCfgError(errorText(e)));
  }, [api]);
  return (
    <RoleSignIn
      role="admin"
      otherRoleHref={config.studentAppUrl}
      options={cfg}
      optionsError={cfgError}
      defaultEmail="admin1@campusride.demo"
      onSignIn={onLogin}
      errorText={errorText}
    />
  );
}
