import { useCallback, useEffect, useState } from "react";

import { useApi } from "../api/ApiContext";
import type { AuthConfig } from "../api/types";
import { config } from "../config";
import { describeError } from "../lib/errors";
import { useAuth } from "./AuthContext";
import { RoleSignIn } from "./RoleSignIn";

const DEFAULT_EMAIL = "student001@campusride.demo";

const errorText = (err: unknown) =>
  err instanceof Error ? describeError(err).detail : String(err);

/**
 * Student sign-in (Feature 15) on the shared CampusRide sign-in page. The backend's
 * `GET /auth/config` decides the form:
 * - AUTH_MODE=dev      → DEVELOPMENT sign-in: a seeded email, no password, clearly labelled;
 * - AUTH_MODE=password → email + password (`POST /auth/login`);
 * - AUTH_MODE=oidc     → external provider sign-in, not available in this app yet.
 * Only student accounts are accepted here (checked against the backend's answer).
 */
export function LoginScreen() {
  const api = useApi();
  const { login } = useAuth();
  const [cfg, setCfg] = useState<AuthConfig | null>(null);
  const [cfgError, setCfgError] = useState<string | null>(null);
  // Dev-only demo deep link: /?login=student042@campusride.demo (development sign-in only).
  const [autoEmail] = useState(() =>
    import.meta.env.DEV ? new URLSearchParams(window.location.search).get("login") : null,
  );
  const [autoBusy, setAutoBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.authConfig().then(
      (c) => {
        if (cancelled) return;
        setCfg(c);
        // the dev deep link signs in only once the backend confirms development sign-in
        if (autoEmail && c.dev_login) {
          setAutoBusy(true);
          login(autoEmail, null).catch((err: unknown) => {
            if (!cancelled) {
              setCfgError(errorText(err));
              setAutoBusy(false);
            }
          });
        }
      },
      (err: unknown) => {
        if (!cancelled) setCfgError(errorText(err));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [api, autoEmail, login]);

  const signIn = useCallback((email: string, pw: string | null) => login(email, pw), [login]);

  return (
    <RoleSignIn
      role="student"
      otherRoleHref={config.adminAppUrl}
      options={cfg}
      optionsError={cfgError}
      defaultEmail={autoEmail ?? DEFAULT_EMAIL}
      onSignIn={signIn}
      errorText={errorText}
      busy={autoBusy}
      demoHint={
        <>
          Demo accounts: <code>student001</code> … <code>student300@campusride.demo</code>
        </>
      }
    />
  );
}
