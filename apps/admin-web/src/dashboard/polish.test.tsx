import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminApi } from "../api/client";
import { fakeBackend } from "../test/backend";
import { ControlRoom } from "./ControlRoom";

vi.mock("./FleetMap", () => ({ default: () => <div data-testid="fleet-map" /> }));
vi.mock("../RouteMap", () => ({ default: () => <div data-testid="route-map" /> }));

const settle = async () => {
  for (let i = 0; i < 4; i++) await act(() => new Promise((r) => setTimeout(r, 0)));
};

function setup() {
  const b = fakeBackend();
  const api = new AdminApi({
    baseUrl: "http://b.test/api/v1",
    getToken: () => "t",
    fetchImpl: b.fetchImpl,
  });
  render(<ControlRoom api={api} />);
  return b;
}

beforeEach(() => vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] }));
afterEach(() => vi.useRealTimers());

describe("Control room polish (Feature 16.5)", () => {
  it("shows fleet status from the backend statuses and filters the table on click", async () => {
    setup();
    await settle();
    const status = screen.getByRole("region", { name: "Fleet status" });
    expect(status).toHaveTextContent("2 need attention"); // B05 off route + B15 delayed
    fireEvent.click(within(status).getByRole("button", { name: /1 Off route/ }));
    const table = screen.getByRole("table", { name: "Fleet table" });
    expect(within(table).getAllByRole("row")).toHaveLength(2); // header + B05
    expect(within(table).getByRole("row", { name: "Bus B05" })).toHaveTextContent("Off route");
  });

  it("fleet rows show the driver and active alerts instead of raw GPS fields", async () => {
    setup();
    await settle();
    const b15 = screen.getByRole("row", { name: "Bus B15" });
    expect(b15).toHaveTextContent("Driver B15");
    expect(within(b15).getByLabelText("1 active alert")).toBeInTheDocument();
    expect(b15).not.toHaveTextContent("LIVE");
  });

  it("demo controls are collapsed and call the real simulator API", async () => {
    const b = setup();
    await settle();
    const panel = screen.getByRole("region", { name: "Demo controls" });
    expect(within(panel).queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: /Demo controls/ }));
    await settle();
    expect(b.calls.map((c) => c.key)).toContain("GET /api/v1/sim/status");
    fireEvent.click(within(panel).getByRole("button", { name: "Pause" }));
    await settle();
    expect(b.calls.map((c) => c.key)).toContain("POST /api/v1/sim/pause");
    fireEvent.click(within(panel).getByRole("radio", { name: "20×" }));
    await settle();
    expect(b.calls.find((c) => c.key === "PUT /api/v1/sim/speed")?.body).toEqual({ speed: 20 });
    fireEvent.click(within(panel).getByRole("button", { name: "Send off route" }));
    await settle();
    expect(b.calls.find((c) => c.key === "POST /api/v1/sim/route-deviation")?.body).toEqual({
      mode: "major",
      bus_id: "B07",
    });
    fireEvent.click(within(panel).getByRole("button", { name: "Reset to start of day" }));
    await settle();
    expect(b.calls.map((c) => c.key)).toContain("POST /api/v1/sim/reset");
    expect(panel).toHaveTextContent("Driver app");
  });

  it("KPIs put active alerts up front and label status as Off route", async () => {
    setup();
    await settle();
    const kpis = screen.getByRole("region", { name: "Key figures" });
    expect(within(kpis).getByRole("group", { name: "Active alerts" })).toHaveTextContent("3");
    expect(screen.getByRole("row", { name: "Bus B05" })).toHaveTextContent("Off route");
  });
});
