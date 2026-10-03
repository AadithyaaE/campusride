import { useState } from "react";

import type { MeOut } from "../api/types";
import type { HealthState } from "../hooks/useHealth";

interface Props {
  me: MeOut;
  health: HealthState;
  /** College-assigned boarding stop (null while loading / unassigned). */
  boardingStopName: string | null;
  alertCount: number;
  onOpenAlerts: () => void;
  onLogout: () => void;
}

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join("");

export function Header({
  me,
  health,
  boardingStopName,
  alertCount,
  onOpenAlerts,
  onLogout,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const backend =
    health.reachable === null
      ? { cls: "pill-muted", text: "Checking backend…", short: "Checking" }
      : health.reachable
        ? { cls: "pill-ok", text: "Backend connected", short: "Online" }
        : { cls: "pill-bad", text: "Backend unreachable", short: "Offline" };

  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          CR
        </span>
        <span className="brand-name">CampusRide</span>
      </div>

      {boardingStopName && (
        <span className="stop-chip" title="Your college-assigned boarding stop">
          <span aria-hidden="true">📍</span>
          <span className="label-long">Boarding stop: </span>
          {boardingStopName}
        </span>
      )}

      <div className="topbar-status">
        <span className={`pill ${backend.cls}`} role="status">
          <span className="pill-dot" aria-hidden="true" />
          <span className="label-long">{backend.text}</span>
          <span className="label-short" aria-hidden="true">
            {backend.short}
          </span>
        </span>
        <span
          className="pill pill-muted"
          title="Bus positions come from the backend's synthetic simulator — not real GPS"
        >
          <span className="pill-dot" aria-hidden="true" />
          Simulated live tracking
        </span>
      </div>

      <button
        type="button"
        className="icon-btn"
        onClick={onOpenAlerts}
        aria-label={`Notifications (${alertCount})`}
      >
        <span aria-hidden="true">🔔</span>
        {alertCount > 0 && (
          <span className="icon-badge" aria-hidden="true">
            {alertCount}
          </span>
        )}
      </button>

      <div className="profile">
        <button
          type="button"
          className="avatar"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          aria-label={`Profile: ${me.name}`}
          onClick={() => setMenuOpen((o) => !o)}
        >
          {initials(me.name)}
        </button>
        <span className="user-name">{me.name}</span>
        {menuOpen && (
          <div className="menu" role="menu">
            <p className="menu-head">
              <strong>{me.name}</strong>
              <span>{me.email}</span>
              <span>Student</span>
            </p>
            <button type="button" role="menuitem" className="menu-item" onClick={onLogout}>
              Sign out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
