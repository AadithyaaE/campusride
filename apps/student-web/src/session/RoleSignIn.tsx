/**
 * The CampusRide sign-in page shared by the Student and Admin web apps (one platform, two
 * role-based views). This file and `roleSignIn.css` are kept IDENTICAL in both apps.
 *
 * The "Who are you?" choice is navigation only: each app signs in only its own role and
 * the other role is a link to that app's sign-in page. The role a user actually gets is
 * whatever the backend says — the app that signs them in checks it and refuses others.
 * Sign-in options (development / password / external) come from the backend's
 * `GET /auth/config`, exactly as before.
 */
import { useState, type FormEvent, type ReactNode } from "react";

import "./roleSignIn.css";

export type CampusRole = "student" | "admin";

/** The subset of the backend's `GET /auth/config` this page needs. */
export interface SignInOptions {
  development: boolean;
  dev_login: boolean;
  password_login: boolean;
  external_provider: boolean;
}

const ROLE: Record<CampusRole, { label: string; field: string; blurb: string }> = {
  student: {
    label: "Student",
    field: "Student email",
    blurb: "Your bus, your stop, and whether you'll make it.",
  },
  admin: {
    label: "Admin",
    field: "Admin email",
    blurb: "The whole fleet, live, from one control room.",
  },
};

interface Props {
  /** The role this app serves. */
  role: CampusRole;
  /** Where the other role signs in. */
  otherRoleHref: string;
  options: SignInOptions | null;
  /** Sign-in options could not be loaded. */
  optionsError: string | null;
  defaultEmail: string;
  /** `password === null` → development sign-in. Rejects with a user-facing message. */
  onSignIn: (email: string, password: string | null) => Promise<void>;
  errorText: (err: unknown) => string;
  /** e.g. an automatic demo sign-in in progress. */
  busy?: boolean;
  /** Why the user is here again (e.g. their session ended). */
  notice?: string | null;
  /** Extra demo-only help under the form. */
  demoHint?: ReactNode;
}

export function RoleSignIn({
  role,
  otherRoleHref,
  options,
  optionsError,
  defaultEmail,
  onSignIn,
  errorText,
  busy: externalBusy = false,
  notice = null,
  demoHint,
}: Props) {
  const [email, setEmail] = useState(defaultEmail);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const r = ROLE[role];
  const usable = options !== null && (options.dev_login || options.password_login);
  const working = busy || externalBusy;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!options || !usable || working) return;
    setBusy(true);
    setError(null);
    const pw = options.password_login ? password : null;
    setPassword(""); // the password is sent once and never kept
    onSignIn(email.trim(), pw).catch((err: unknown) => {
      setError(errorText(err));
      setBusy(false);
    });
  };

  return (
    <div className="cr-signin">
      <MapBackdrop />
      <main className="cr-signin-main">
        <form
          className="cr-signin-card"
          onSubmit={submit}
          aria-label={`${r.label} sign in`}
          aria-busy={working}
        >
          <header className="cr-signin-head">
            <span className="cr-signin-mark" aria-hidden="true">
              <BusGlyph />
            </span>
            <h1 className="cr-signin-name">CampusRide</h1>
            <p className="cr-signin-sub">Smart College Transportation</p>
            <p className="cr-signin-tag">Real-time. Intelligent. Connected.</p>
          </header>

          <div className="cr-signin-roles" role="group" aria-labelledby="cr-who">
            <span id="cr-who" className="cr-signin-who">
              Who are you?
            </span>
            <div className="cr-signin-seg">
              {(["student", "admin"] as const).map((k) =>
                k === role ? (
                  <span key={k} className="cr-signin-opt is-active" aria-current="true">
                    <RoleGlyph role={k} />
                    {ROLE[k].label}
                  </span>
                ) : (
                  <a key={k} className="cr-signin-opt" href={otherRoleHref}>
                    <RoleGlyph role={k} />
                    {ROLE[k].label}
                  </a>
                ),
              )}
            </div>
            <p className="cr-signin-blurb">{r.blurb}</p>
          </div>

          {notice && (
            <p className="cr-signin-msg is-info" role="status">
              {notice}
            </p>
          )}
          {!options && !optionsError && (
            <p className="cr-signin-wait" role="status">
              <span className="cr-signin-spinner is-dark" aria-hidden="true" /> Getting things
              ready…
            </p>
          )}
          {optionsError && (
            <p className="cr-signin-msg is-error" role="alert">
              {optionsError}
            </p>
          )}
          {options?.development && (
            <p className="cr-signin-msg is-demo" role="note">
              <strong>Demo sign-in</strong> — use any demo {role} account. No password is needed in
              this demo environment.
            </p>
          )}
          {options?.external_provider && (
            <p className="cr-signin-msg is-info" role="note">
              Your college sign-in isn&apos;t available here yet. Please contact your transport
              office.
            </p>
          )}

          {usable && (
            <>
              <label className="cr-signin-field">
                <span>{r.field}</span>
                <input
                  type="email"
                  required
                  autoComplete="username"
                  inputMode="email"
                  spellCheck={false}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </label>
              {options.password_login && (
                <label className="cr-signin-field">
                  <span>Password</span>
                  <input
                    type="password"
                    required
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </label>
              )}
            </>
          )}

          {error && (
            <p className="cr-signin-msg is-error" role="alert">
              {error}
            </p>
          )}

          <button type="submit" className="cr-signin-submit" disabled={working || !usable}>
            {working && <span className="cr-signin-spinner" aria-hidden="true" />}
            {working ? "Signing in…" : "Sign in"}
          </button>

          {options?.development && demoHint && <p className="cr-signin-hint">{demoHint}</p>}

          <p className="cr-signin-foot">
            <LockGlyph />
            {options?.password_login ? "Secure role-based access" : "Role-based access"}
          </p>
        </form>
      </main>
    </div>
  );
}

function BusGlyph() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="26"
      height="26"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="4" y="3" width="16" height="14" rx="3" />
      <path d="M4 10h16M8 17v3M16 17v3" />
      <circle cx="8" cy="13.5" r="0.9" fill="currentColor" />
      <circle cx="16" cy="13.5" r="0.9" fill="currentColor" />
    </svg>
  );
}

function RoleGlyph({ role }: { role: CampusRole }) {
  return role === "student" ? (
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M3 9l9-4 9 4-9 4-9-4z" />
      <path d="M7 11v4c0 1.5 2.2 3 5 3s5-1.5 5-3v-4" />
    </svg>
  ) : (
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4M7 12l3-3 2 2 4-4" />
    </svg>
  );
}

function LockGlyph() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="14"
      height="14"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="5" y="11" width="14" height="9" rx="2" />
      <path d="M8 11V8a4 4 0 0 1 8 0v3" />
    </svg>
  );
}

/** Decorative, static map: a faint street grid with three bus routes and their stops. */
function MapBackdrop() {
  const routes = [
    {
      d: "M-20 640 C 180 600, 260 470, 420 450 S 700 380, 820 250 S 1080 120, 1460 90",
      c: "#0284c7",
    },
    {
      d: "M-20 180 C 160 230, 300 300, 470 300 S 760 420, 930 520 S 1220 700, 1460 720",
      c: "#7c3aed",
    },
    {
      d: "M300 900 C 340 720, 420 640, 560 600 S 840 560, 980 430 S 1180 260, 1240 -20",
      c: "#ea580c",
    },
  ];
  const stops = [
    [420, 450],
    [820, 250],
    [1180, 118],
    [470, 300],
    [930, 520],
    [1240, 690],
    [560, 600],
    [980, 430],
    [160, 612],
  ];
  return (
    <svg
      className="cr-signin-map"
      viewBox="0 0 1440 900"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <pattern id="cr-grid" width="72" height="72" patternUnits="userSpaceOnUse">
          <path d="M72 0H0V72" fill="none" stroke="#c9d6e3" strokeWidth="1" />
        </pattern>
      </defs>
      <rect width="1440" height="900" fill="url(#cr-grid)" />
      <path
        d="M-20 380 L 1460 300 M 640 -20 L 700 920 M -20 820 L 1460 760"
        stroke="#d5e0ea"
        strokeWidth="10"
        fill="none"
      />
      {routes.map((r) => (
        <path
          key={r.c}
          d={r.d}
          stroke={r.c}
          strokeWidth="5"
          strokeLinecap="round"
          fill="none"
          opacity="0.35"
        />
      ))}
      {stops.map(([x, y]) => (
        <circle
          key={`${x}-${y}`}
          cx={x}
          cy={y}
          r="7"
          fill="#fff"
          stroke="#0f3d5e"
          strokeWidth="3"
          opacity="0.5"
        />
      ))}
    </svg>
  );
}
