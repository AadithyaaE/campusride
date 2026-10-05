import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { useApi } from "../api/ApiContext";
import { UnauthorizedError } from "../api/client";
import type { MeOut } from "../api/types";
import type { SessionStore } from "./sessionStore";

export type AuthState =
  | { status: "checking" }
  | { status: "signedOut" }
  | { status: "signedIn"; me: MeOut }
  | { status: "unreachable"; error: Error };

interface AuthApi {
  state: AuthState;
  /** `password === null` → development sign-in (AUTH_MODE=dev). */
  login: (email: string, password: string | null) => Promise<void>;
  logout: () => void;
  retry: () => void;
}

const AuthContext = createContext<AuthApi | null>(null);

export const STUDENT_ONLY_MESSAGE =
  "This isn't a student account. Transport staff can sign in by choosing Admin above.";

/**
 * Session lifecycle. On startup (and on every refresh) the stored token is
 * validated with `GET /me`; the user shown is always the backend's answer.
 */
export function AuthProvider({ store, children }: { store: SessionStore; children: ReactNode }) {
  const api = useApi();
  const [state, setState] = useState<AuthState>(() =>
    store.get() ? { status: "checking" } : { status: "signedOut" },
  );
  const [attempt, setAttempt] = useState(0);

  // Validate the stored session against the backend.
  useEffect(() => {
    if (!store.get()) return; // initial state is already "signedOut"
    let cancelled = false;
    api.me().then(
      (me) => {
        if (cancelled) return;
        if (me.role !== "student") {
          store.clear();
          setState({ status: "signedOut" });
          return;
        }
        setState({ status: "signedIn", me });
      },
      (err: unknown) => {
        if (cancelled) return;
        if (err instanceof UnauthorizedError) {
          store.clear();
          setState({ status: "signedOut" });
        } else {
          setState({
            status: "unreachable",
            error: err instanceof Error ? err : new Error(String(err)),
          });
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [api, store, attempt]);

  // A 401 anywhere (or sign-out in another tab) clears the session.
  useEffect(
    () =>
      store.subscribe(() => {
        if (!store.get()) setState({ status: "signedOut" });
      }),
    [store],
  );

  const login = useCallback(
    async (email: string, password: string | null) => {
      const res =
        password === null
          ? await api.devLogin(email.trim())
          : await api.passwordLogin(email.trim(), password);
      if (res.user.role !== "student") throw new Error(STUDENT_ONLY_MESSAGE);
      store.set({ token: res.access_token, expiresAt: res.expires_at, userId: res.user.id });
      setState({ status: "signedIn", me: res.user });
    },
    [api, store],
  );

  const logout = useCallback(() => store.clear(), [store]);
  const retry = useCallback(() => {
    setState(store.get() ? { status: "checking" } : { status: "signedOut" });
    setAttempt((n) => n + 1);
  }, [store]);

  const value = useMemo(() => ({ state, login, logout, retry }), [state, login, logout, retry]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthApi {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
