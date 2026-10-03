import { useEffect, useState, type FormEvent } from "react";

import { describeError } from "../lib/errors";
import { useAuth } from "./AuthContext";

const DEFAULT_EMAIL = "student001@campusride.demo";

/**
 * Mock sign-in (AUTH_MODE=mock): exchanges a seeded account's email for a
 * token via `POST /auth/mock-login`. Firebase replaces this in Phase 7.
 */
export function LoginScreen() {
  const { login } = useAuth();
  // Dev-only demo deep link: /?login=student042@campusride.demo signs in directly.
  const [autoEmail] = useState(() =>
    import.meta.env.DEV ? new URLSearchParams(window.location.search).get("login") : null,
  );
  const [email, setEmail] = useState(autoEmail ?? DEFAULT_EMAIL);
  const [busy, setBusy] = useState(autoEmail !== null);
  const [error, setError] = useState<string | null>(null);

  const submit = async (value: string) => {
    setBusy(true);
    setError(null);
    try {
      await login(value);
    } catch (err) {
      setError(err instanceof Error ? describeError(err).detail : String(err));
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!autoEmail) return;
    login(autoEmail).catch((err: unknown) => {
      setError(err instanceof Error ? describeError(err).detail : String(err));
      setBusy(false);
    });
  }, [autoEmail, login]);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void submit(email);
  };

  return (
    <div className="login">
      <form className="login-card" onSubmit={onSubmit} aria-labelledby="login-title">
        <div className="brand brand-lg">
          <span className="brand-mark" aria-hidden="true">
            CR
          </span>
          <span className="brand-name">CampusRide</span>
        </div>
        <h1 id="login-title">Sign in</h1>
        <p className="muted">
          Prototype sign-in with a seeded demo account. No password — the backend runs in mock-auth
          mode.
        </p>
        <label className="field">
          <span>Student email</span>
          <input
            className="input"
            type="email"
            required
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
          {busy ? "Signing in…" : "Continue"}
        </button>
        <p className="footnote">
          Demo accounts: <code>student001</code> … <code>student300@campusride.demo</code>
        </p>
      </form>
    </div>
  );
}
