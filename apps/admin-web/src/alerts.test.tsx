import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminApi, type AlertOut } from "./api/client";
import { POLL_MS } from "./polling";
import { AlertsPanel } from "./dashboard/Alerts";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function alert(type: string, message: string, over: Partial<AlertOut> = {}): AlertOut {
  const id = over.alert_id ?? `ALT-${type}-ADMIN-B05-T1-1`;
  return {
    alert_id: id,
    id,
    type: type as AlertOut["type"],
    title: type.replace(/_/g, " "),
    message,
    body: message,
    bus_id: "B05",
    trip_id: "T1",
    route_id: "R3",
    student_id: null,
    admin_id: null,
    recipient: "admin",
    severity: "warning",
    timestamp: "2026-10-05T02:10:00Z",
    created_at: "2026-10-05T02:10:00Z",
    updated_at: null,
    read: false,
    resolved_at: null,
    active: true,
    payload: {},
    ...over,
  };
}

const FLEET = [
  alert("ROUTE_DEVIATION", "BUS B05 is 303 m off its planned route.", { severity: "critical" }),
  alert("BUS_DELAYED", "Bus B07 is running 8 minutes late (R4).", { bus_id: "B07" }),
  alert("CAPACITY_WARNING", "Bus B11 is 88% full with 6 seats remaining.", { bus_id: "B11" }),
];

function setup(pages: AlertOut[][] = [FLEET]) {
  const calls: string[] = [];
  let n = 0;
  const fetchImpl: typeof fetch = async (input, init) => {
    const u = new URL(String(input));
    const key = `${init?.method ?? "GET"} ${u.pathname}${u.search}`;
    calls.push(key);
    if (key === "GET /api/v1/alerts?active=true") {
      const page = pages[Math.min(n, pages.length - 1)]!;
      n += 1;
      return json(page);
    }
    if (init?.method === "PATCH") return json({ ...FLEET[0], read: true });
    return json({ error: { code: "not_found", message: key } }, 404);
  };
  render(
    <AlertsPanel
      api={new AdminApi({ baseUrl: "http://b.test/api/v1", getToken: () => "t", fetchImpl })}
    />,
  );
  return calls;
}

const flush = async () => {
  for (let i = 0; i < 4; i++) await act(() => new Promise((r) => setTimeout(r, 0)));
};

beforeEach(() => vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] }));
afterEach(() => vi.useRealTimers());

describe("Admin active alerts (backend Feature 11 fleet alerts)", () => {
  it("shows deviation, delay and capacity alerts with severity text and unread count", async () => {
    setup();
    await flush();
    const panel = screen.getByRole("region", { name: "Active alerts" });
    expect(within(panel).getByLabelText("3 unread")).toBeInTheDocument();
    const items = within(panel).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("ROUTE DEVIATION");
    expect(items[0]).toHaveTextContent("BUS B05 is 303 m off its planned route.");
    expect(items[0]).toHaveTextContent("Critical");
    expect(items[0]).toHaveClass("alert-critical");
    expect(items[1]).toHaveTextContent("Bus B07 is running 8 minutes late (R4).");
    expect(items[2]).toHaveTextContent("Bus B11 is 88% full with 6 seats remaining.");
    expect(items[2]).toHaveTextContent("Warning");
  });

  it("marks an alert read through the backend", async () => {
    const calls = setup();
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Mark ROUTE DEVIATION for B05 read" }));
    await flush();
    expect(calls).toContain(`PATCH /api/v1/alerts/${FLEET[0]!.alert_id}/read`);
    expect(screen.getByLabelText("2 unread")).toBeInTheDocument();
  });

  it("follows the backend on every poll (new and resolved alerts)", async () => {
    setup([[FLEET[0]!], FLEET, []]);
    await flush();
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    await act(async () => {
      vi.advanceTimersByTime(POLL_MS);
    });
    await flush();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    await act(async () => {
      vi.advanceTimersByTime(POLL_MS);
    });
    await flush();
    expect(screen.getByText("No active alerts.")).toBeInTheDocument();
  });

  it("never shows a student's personal alert in the fleet view", async () => {
    setup([
      [
        ...FLEET,
        alert("MISSED_BUS", "You missed your assigned bus B05.", {
          recipient: "student",
          student_id: "U-S0001",
          alert_id: "S1",
        }),
      ],
    ]);
    await flush();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.queryByText("You missed your assigned bus B05.")).not.toBeInTheDocument();
  });
});
