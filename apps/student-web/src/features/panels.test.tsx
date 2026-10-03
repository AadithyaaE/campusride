import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildNetwork } from "../data/network";
import * as fx from "../test/fixtures";
import { fakeBackend, json, makeClient, renderWithApi } from "../test/helpers";
import { MyBusPanel } from "./mybus/MyBusPanel";
import { useMyAssignment } from "../data/assignment";
import { RoutesPanel } from "./routes/RoutesPanel";
import { StopsPanel } from "./stops/StopsPanel";

const network = buildNetwork(fx.stops, fx.routeSummaries, fx.routeDetails);
const noop = () => {};

function stopsPanel(selectedStopId: string | null, fetchImpl = fakeBackend().fetchImpl) {
  const onSelectStop = vi.fn();
  renderWithApi(
    <StopsPanel
      network={network}
      selectedStopId={selectedStopId}
      myStopId={null}
      mapCenter={{ lat: 1.1, lng: 10.1 }}
      onSelectStop={onSelectStop}
      onSelectRoute={noop}
    />,
    makeClient(fetchImpl),
  );
  return { onSelectStop };
}

describe("StopsPanel", () => {
  it("lists every stop from the backend and marks shared stops", async () => {
    const { onSelectStop } = stopsPanel(null);
    const list = screen.getByRole("list", { name: "All stops" });
    expect(within(list).getAllByRole("button")).toHaveLength(fx.stops.length);
    const shared = within(list).getByRole("button", { name: /Test Stop B/ });
    expect(within(shared).getByText("Shared · 2 routes")).toBeInTheDocument();
    await userEvent.click(shared);
    expect(onSelectStop).toHaveBeenCalledWith("X2");
  });

  it("filters by search", async () => {
    stopsPanel(null);
    await userEvent.type(screen.getByRole("searchbox", { name: "Search stops" }), "stop c");
    const list = screen.getByRole("list", { name: "All stops" });
    expect(within(list).getAllByRole("button")).toHaveLength(1);
  });

  it("shows loading, then the routes the backend says serve the stop", async () => {
    stopsPanel("X2");
    expect(screen.getByRole("heading", { name: "Test Stop B" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading routes");
    const list = await screen.findByRole("list", { name: "Routes serving this stop" });
    expect(
      within(list)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual([
      expect.stringContaining("T1"),
      expect.stringContaining("T1-E"),
      expect.stringContaining("T2"),
      expect.stringContaining("T2-E"),
    ]);
    expect(screen.getByText("Shared · 2 routes")).toBeInTheDocument();
  });

  it("shows an error with retry when the backend fails", async () => {
    let fail = true;
    const { fetchImpl } = fakeBackend({
      "GET /api/v1/stops/X1/routes": () =>
        fail
          ? json({ error: { code: "boom", message: "database exploded" } }, 500)
          : json(fx.servicesAt("X1")),
    });
    stopsPanel("X1", fetchImpl);
    expect(await screen.findByRole("alert")).toHaveTextContent("database exploded");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByRole("list", { name: "Routes serving this stop" }),
    ).toBeInTheDocument();
  });

  it("asks the backend for stops near the map centre", async () => {
    const backend = fakeBackend({
      "GET /api/v1/stops/nearby": (url) => {
        expect(url.searchParams.get("lat")).toBe("1.1");
        return json([{ ...fx.stops[1], distance_m: 42 }]);
      },
    });
    stopsPanel(null, backend.fetchImpl);
    await userEvent.click(screen.getByRole("button", { name: "Stops near map centre" }));
    const nearby = await screen.findByRole("list", { name: "Nearby stops" });
    expect(nearby).toHaveTextContent("Test Stop A 42 m");
  });

  it("never lets the student pick a stop as their own", async () => {
    stopsPanel("X1");
    await screen.findByRole("list", { name: "Routes serving this stop" });
    expect(screen.queryByRole("button", { name: /my stop|my bus/i })).not.toBeInTheDocument();
  });
});

describe("RoutesPanel", () => {
  it("lists backend routes and shows a route's stops per direction", async () => {
    const onSelectRoute = vi.fn();
    const { rerender } = renderWithApi(
      <RoutesPanel
        network={network}
        selectedRouteId={null}
        myStopId={null}
        defaultDirection="to_campus"
        onSelectRoute={onSelectRoute}
        onSelectStop={noop}
      />,
      makeClient(fakeBackend().fetchImpl),
    );
    await userEvent.click(screen.getByRole("button", { name: /Test Line Two/ }));
    expect(onSelectRoute).toHaveBeenCalledWith("T2");

    rerender(
      <RoutesPanel
        network={network}
        selectedRouteId="T2"
        myStopId="X2"
        defaultDirection="to_campus"
        onSelectRoute={onSelectRoute}
        onSelectStop={noop}
      />,
    );
    const stopsList = screen.getByRole("list", { name: "Stops on T2 — To Campus" });
    expect(
      within(stopsList)
        .getAllByRole("button")
        .map((b) => b.textContent?.split("+")[0]),
    ).toEqual(["Test Stop Cstart", "Test Stop BMy stopShared with T1", "Test Campus"]);
    await userEvent.click(screen.getByRole("tab", { name: "T2-E · From Campus" }));
    expect(screen.getByRole("list", { name: "Stops on T2-E — From Campus" })).toBeInTheDocument();
  });
});

describe("MyBusPanel (college-assigned, read-only)", () => {
  function Harness({ onShowOnMap }: { onShowOnMap: (r: string, s: string) => void }) {
    const assignment = useMyAssignment();
    return <MyBusPanel network={network} assignment={assignment} onShowOnMap={onShowOnMap} />;
  }

  function myBus(overrides: Parameters<typeof fakeBackend>[0] = {}) {
    const onShowOnMap = vi.fn();
    const backend = fakeBackend(overrides);
    renderWithApi(<Harness onShowOnMap={onShowOnMap} />, makeClient(backend.fetchImpl));
    return { onShowOnMap, backend };
  }

  it("shows the assignment returned by the backend", async () => {
    const { onShowOnMap, backend } = myBus();
    expect(screen.getByRole("status")).toHaveTextContent("Loading your bus assignment");
    const card = await screen.findByRole("region", { name: "My bus" });
    expect(card).toHaveTextContent("T2");
    expect(card).toHaveTextContent("Test Line Two");
    expect(card).toHaveTextContent("BusBX7 · TEST 0007");
    expect(card).toHaveTextContent("DirectionTo Campus");
    expect(card).toHaveTextContent("Boarding stopTest Stop B · stop 2 of 3");
    expect(card).toHaveTextContent("+5 min after the route’s first stop");
    expect(card).not.toHaveTextContent(/\bETA\b|arriving|arrives in/);
    expect(backend.calls).toContain("GET /api/v1/students/me/assignment");

    await userEvent.click(within(card).getByRole("button", { name: "Show on map" }));
    expect(onShowOnMap).toHaveBeenCalledWith("T2", "X2");
    const others = await screen.findByRole("list", { name: "Other routes at my stop" });
    expect(within(others).getAllByRole("listitem")).toHaveLength(1); // T1 also serves X2 to campus
    expect(others).toHaveTextContent("T1");
  });

  it("offers no way to choose or change the bus, route or stop", async () => {
    const { backend } = myBus();
    const card = await screen.findByRole("region", { name: "My bus" });
    expect(
      within(card)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["Show on map"]);
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
    expect(card).toHaveTextContent("Assigned by your college transport office");
    expect(backend.calls.every((c) => c.startsWith("GET "))).toBe(true);
  });

  it("tells an unassigned student their assignment is not available yet", async () => {
    myBus({ "GET /api/v1/students/me/assignment": () => json(fx.unassigned) });
    const region = await screen.findByRole("region", { name: "My bus" });
    expect(region).toHaveTextContent("Your bus assignment is not available yet.");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows an error with retry when the assignment cannot be loaded", async () => {
    let fail = true;
    myBus({
      "GET /api/v1/students/me/assignment": () =>
        fail ? json({ error: { code: "boom", message: "db down" } }, 500) : json(fx.assignment),
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("db down");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("region", { name: "My bus" })).toHaveTextContent("BX7");
  });
});
