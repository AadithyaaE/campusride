import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BusOut, TripBoardingOut } from "./api/client";
import { App } from "./App";
import { POLL_MS } from "./FleetOccupancy";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

class MemoryStorage implements Storage {
  private m = new Map<string, string>();
  get length() {
    return this.m.size;
  }
  clear() {
    this.m.clear();
  }
  getItem(k: string) {
    return this.m.get(k) ?? null;
  }
  key(i: number) {
    return [...this.m.keys()][i] ?? null;
  }
  removeItem(k: string) {
    this.m.delete(k);
  }
  setItem(k: string, v: string) {
    this.m.set(k, v);
  }
}

function bus(
  id: string,
  occupancy: number,
  extra: Partial<NonNullable<BusOut["live"]>> = {},
): BusOut {
  return {
    id,
    reg_no: `TN 00 ${id}`,
    capacity: 50,
    route_id: "R3",
    status: "active",
    source: "sim",
    live: {
      trip_id: `T-${id}`,
      route_id: "R3",
      route_direction_id: "R3",
      direction: "to_campus",
      location: { type: "Point", coordinates: [80.2, 12.9] },
      speed_mps: 8,
      heading_deg: 0,
      status: "en_route",
      schedule_status: "on_time",
      delay_s: 0,
      current_stop_id: "S20",
      next_stop_id: "S21",
      route_progress: 0.4,
      distance_along_m: 4000,
      occupancy,
      available_seats: 50 - occupancy,
      occupancy_percentage: Math.round((100 * occupancy) / 50),
      boarded_count: 0,
      last_updated: "2026-10-05T02:10:00Z",
      stale: false,
      ...extra,
    },
  };
}

const TRIP: TripBoardingOut = {
  trip_id: "T-B05",
  bus_id: "B05",
  route_direction_id: "R3",
  total_boarded: 1,
  visibility: "all",
  events: [
    {
      boarding_id: "BRD-T-B05-U-S0001",
      student_id: "U-S0001",
      bus_id: "B05",
      trip_id: "T-B05",
      stop_id: "S27",
      timestamp: "2026-10-05T02:09:00Z",
      scanner: "simulated",
    },
  ],
};

function backend(role = "admin") {
  let polls = 0;
  const calls: string[] = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    const url = new URL(String(input));
    const key = `${init?.method ?? "GET"} ${url.pathname}`;
    calls.push(key);
    switch (key) {
      case "POST /api/v1/auth/mock-login":
        return json({
          access_token: "mock.t",
          token_type: "bearer",
          expires_at: "2099-01-01T00:00:00Z",
        });
      case "GET /api/v1/me":
        return json({
          id: "U-A1",
          role,
          name: "Transport Office",
          email: "admin1@campusride.demo",
        });
      case "GET /api/v1/buses":
        polls += 1;
        // the second poll reflects a QR scan on B05 (as the backend would report it)
        return json(
          polls === 1
            ? [bus("B05", 38), bus("B06", 20), { ...bus("B09", 0), live: null }]
            : [bus("B05", 39, { boarded_count: 1 }), bus("B06", 20)],
        );
      case "GET /api/v1/trips/T-B05/boarding":
        return json(TRIP);
      default:
        return json({ error: { code: "not_found", message: key } }, 404);
    }
  };
  return { fetchImpl, calls };
}

const flush = () => act(async () => {});

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
});
afterEach(() => vi.useRealTimers());

async function signIn(role = "admin") {
  const b = backend(role);
  render(<App fetchImpl={b.fetchImpl} storage={new MemoryStorage()} />);
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await flush();
  await flush();
  return b;
}

describe("Admin dashboard — live occupancy from the backend", () => {
  it("only admins can sign in", async () => {
    await signIn("student");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This dashboard is for college transport admins only.",
    );
    expect(screen.queryByRole("region", { name: "Fleet occupancy" })).not.toBeInTheDocument();
  });

  it("shows each active bus with the backend's occupancy, %, seats and trip", async () => {
    await signIn();
    const table = await screen.findByRole("region", { name: "Fleet occupancy" });
    const b05 = within(table).getByRole("row", { name: "Bus B05" });
    expect(b05).toHaveTextContent("BUS B05");
    expect(b05).toHaveTextContent("T-B05");
    expect(b05).toHaveTextContent("38 / 50");
    expect(b05).toHaveTextContent("76%");
    expect(b05).toHaveTextContent("12");
    expect(within(table).queryByRole("row", { name: "Bus B09" })).not.toBeInTheDocument(); // no trip
    expect(table).toHaveTextContent("Synthetic baseline + simulated QR scans");
  });

  it("reflects a QR scan on the next poll", async () => {
    const b = await signIn();
    const table = await screen.findByRole("region", { name: "Fleet occupancy" });
    expect(within(table).getByRole("row", { name: "Bus B05" })).toHaveTextContent("38 / 50");
    await act(async () => {
      vi.advanceTimersByTime(POLL_MS);
    });
    await flush();
    const row = within(table).getByRole("row", { name: "Bus B05" });
    expect(row).toHaveTextContent("39 / 50");
    expect(row).toHaveTextContent("78%");
    expect(b.calls.filter((c) => c === "GET /api/v1/buses").length).toBeGreaterThanOrEqual(2);
  });

  it("displays backend numbers as given — no local occupancy maths", async () => {
    const b = backend();
    const odd = bus("B05", 10, { occupancy_percentage: 91, available_seats: 3 });
    const fetchImpl: typeof fetch = async (input, init) =>
      String(input).endsWith("/buses") ? json([odd]) : b.fetchImpl(input, init);
    render(<App fetchImpl={fetchImpl} storage={new MemoryStorage()} />);
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await flush();
    await flush();
    const row = await screen.findByRole("row", { name: "Bus B05" });
    expect(row).toHaveTextContent("10 / 50");
    expect(row).toHaveTextContent("91%");
    expect(row).toHaveTextContent("3");
  });

  it("drills into a trip's boarding events", async () => {
    await signIn();
    fireEvent.click(await screen.findByRole("button", { name: "Boarding for trip T-B05" }));
    await flush();
    const panel = await screen.findByRole("region", { name: "Trip boarding" });
    expect(panel).toHaveTextContent("1 QR boarding on B05 (R3)");
    const events = within(panel).getByRole("list", { name: "Boarding events" });
    expect(events).toHaveTextContent("U-S0001");
    expect(events).toHaveTextContent("at S27");
    expect(events).toHaveTextContent("simulated QR");
  });
});
