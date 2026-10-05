import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Alert } from "../../api/types";
import * as fx from "../../test/fixtures";
import { AlertsList } from "./AlertsList";

const NOW = "2030-01-07T01:50:00Z"; // simulation time

function show(alerts: Alert[] = fx.myAlerts, onMarkRead = vi.fn()) {
  render(<AlertsList alerts={alerts} nowIso={NOW} onMarkRead={onMarkRead} />);
  return { panel: screen.getByRole("region", { name: "Notifications" }), onMarkRead };
}

const ALL: [Alert["type"], string, string][] = [
  ["BUS_APPROACHING", "🚌", "Bus BX7 reaches your stop (Test Stop B) in 3 minutes."],
  ["BUS_DELAYED", "⏱", "Bus BX7 is running 8 minutes late."],
  ["CAPACITY_WARNING", "👥", "Bus BX7 is 84% full with 8 seats remaining."],
  ["ROUTE_DEVIATION", "🛣", "Your bus BX7 is currently 303 m from its planned route."],
  ["MISSED_BUS", "⏰", "You missed your assigned bus BX7."],
  [
    "ALTERNATIVE_BUS_AVAILABLE",
    "🔄",
    "Bus BX8 serves your stop and gives you a 5-minute safety buffer.",
  ],
];

describe("Student notifications panel (backend Feature 11 alerts, displayed as given)", () => {
  it("renders the backend alerts with an unread count", () => {
    const { panel } = show();
    expect(within(panel).getByLabelText("2 unread")).toHaveTextContent("2");
    const items = within(panel).getAllByRole("listitem");
    expect(items.map((i) => i.getAttribute("aria-label"))).toEqual([
      "Your bus is approaching (unread)",
      "Your bus is delayed (unread)",
      "Another bus can get you there",
    ]);
    expect(items[0]).toHaveClass("is-unread");
    expect(items[2]).toHaveClass("is-read");
  });

  it("shows every alert type with icon, title, message, severity text and time", () => {
    show(
      ALL.map(([type, , message], i) =>
        fx.alert(type, message, {
          alert_id: `A${i}`,
          severity: type === "ROUTE_DEVIATION" ? "critical" : "warning",
          timestamp: "2030-01-07T01:47:00Z",
        }),
      ),
    );
    const items = screen.getAllByRole("listitem");
    ALL.forEach(([, , message], i) => {
      expect(items[i]!.querySelector("svg.icon")).not.toBeNull(); // one consistent icon set
      expect(items[i]).toHaveTextContent(message); // exactly the backend message
      expect(items[i]).toHaveTextContent("3 min ago");
    });
    // severity is shown as text, not only by colour/icon
    expect(items[3]).toHaveTextContent("Critical");
    expect(items[3]).toHaveClass("alert-critical");
    expect(items[1]).toHaveTextContent("Warning");
  });

  it("marks resolved alerts as resolved", () => {
    show([fx.alert("BUS_DELAYED", "Bus BX7 is running 8 minutes late.", { active: false })]);
    expect(screen.getByRole("listitem")).toHaveTextContent("Resolved");
  });

  it("asks the backend to mark an alert read; read ones have no button", () => {
    const { onMarkRead } = show();
    const buttons = screen.getAllByRole("button", { name: /^Mark .* read$/ });
    expect(buttons).toHaveLength(2);
    fireEvent.click(buttons[0]!);
    expect(onMarkRead).toHaveBeenCalledWith(fx.myAlerts[0]!.alert_id);
  });

  it("shows an empty state", () => {
    show([]);
    expect(screen.getByText("You're all caught up")).toBeInTheDocument();
  });

  it("generates nothing itself — shows only what the backend returned", async () => {
    show([fx.alert("BUS_APPROACHING", "Anything the backend says.")]);
    await act(async () => {});
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByRole("listitem")).toHaveTextContent("Anything the backend says.");
  });
});
