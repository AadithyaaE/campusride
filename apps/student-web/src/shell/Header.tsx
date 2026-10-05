import { useState } from "react";

import type { MeOut } from "../api/types";
import { Icon } from "../components/Icon";
import type { HealthState } from "../hooks/useHealth";
import type { RealtimeStatus } from "../realtime/client";

interface Props {
  me: MeOut;
  health: HealthState;
  /** Live-update connection (Feature 14 WebSocket). */
  realtime: RealtimeStatus;
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

/** One calm status: are we showing live information? */
function connection(health: HealthState, realtime: RealtimeStatus) {
  if (health.reachable === false) return { cls: "pill-bad", text: "Offline" };
  if (realtime === "live") return { cls: "pill-ok", text: "Live" };
  if (realtime === "offline") return { cls: "pill-warn", text: "Reconnecting…" };
  return { cls: "pill-muted", text: "Connecting…" };
}

export function Header({
  me,
  health,
  realtime,
  boardingStopName,
  alertCount,
  onOpenAlerts,
  onLogout,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const live = connection(health, realtime);

  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          <Icon name="bus" size={18} />
        </span>
        <span className="brand-name">CampusRide</span>
      </div>

      {boardingStopName && (
        <span className="stop-chip" title="Your college-assigned boarding stop">
          <Icon name="pin" size={14} />
          <span className="stop-chip-text">{boardingStopName}</span>
        </span>
      )}

      <div className="topbar-status">
        <span
          className={`pill ${live.cls}`}
          role="status"
          aria-label="Connection"
          title="Bus positions are synthetic demo data from the CampusRide simulator"
        >
          <span className="pill-dot" aria-hidden="true" />
          {live.text}
        </span>
      </div>

      <button
        type="button"
        className="icon-btn"
        onClick={onOpenAlerts}
        aria-label={alertCount > 0 ? `Notifications, ${alertCount} unread` : "Notifications"}
      >
        <Icon name="bell" size={19} />
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
          aria-label={`Account: ${me.name}`}
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
