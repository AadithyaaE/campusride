import { describe, expect, it } from "vitest";

import { buildNetwork } from "../data/network";
import { boundsOf, toLatLng } from "../map/geo";
import { SessionStore } from "../session/sessionStore";
import { parseView, serializeView } from "../shell/urlState";
import * as fx from "../test/fixtures";
import { MemoryStorage } from "../test/helpers";
import { formatKm, formatOffset, localClock, localHour, suggestedDirection } from "./format";

const network = () => buildNetwork(fx.stops, fx.routeSummaries, fx.routeDetails);

describe("buildNetwork (derived only from backend responses)", () => {
  it("indexes routes serving each stop and finds shared stops", () => {
    const n = network();
    expect(n.servingRoutes.get("X2")).toEqual(["T1", "T2"]);
    expect(n.servingRoutes.get("X1")).toEqual(["T1"]);
    expect([...n.sharedStopIds]).toEqual(["X2"]); // campus terminal X0 is not "shared"
    expect(n.routeById.get("T2")?.name).toBe("Test Line Two");
  });

  it("handles an empty backend", () => {
    const n = buildNetwork([], [], []);
    expect(n.stops).toEqual([]);
    expect(n.sharedStopIds.size).toBe(0);
  });
});

describe("geo adapter", () => {
  it("converts backend [lng, lat] to Leaflet [lat, lng]", () => {
    expect(toLatLng([80.2, 12.9])).toEqual([12.9, 80.2]);
  });

  it("computes bounds in Leaflet order", () => {
    expect(
      boundsOf([
        [10, 1],
        [12, 3],
        [11, 0],
      ]),
    ).toEqual([
      [0, 10],
      [3, 12],
    ]);
    expect(boundsOf([])).toBeNull();
  });
});

describe("suggestedDirection", () => {
  it("suggests a route-view direction from the backend clock hour", () => {
    expect(suggestedDirection(7)).toBe("to_campus");
    expect(suggestedDirection(16)).toBe("from_campus");
    expect(suggestedDirection(null)).toBe("to_campus");
  });
});

describe("SessionStore", () => {
  it("persists, expires and notifies", () => {
    let now = Date.parse("2030-01-01T00:00:00Z");
    const storage = new MemoryStorage();
    const store = new SessionStore(storage, () => now);
    let events = 0;
    store.subscribe(() => events++);
    store.set({ token: "t", expiresAt: "2030-01-01T01:00:00Z", userId: "U-T1" });
    expect(new SessionStore(storage, () => now).get()?.token).toBe("t"); // survives "refresh"
    now += 2 * 3600_000;
    expect(store.get()).toBeNull();
    expect(events).toBe(2); // set + expiry clear
  });
});

describe("URL view state", () => {
  it("parses and serializes tab/stop/route", () => {
    expect(parseView("?tab=stops&stop=X2")).toEqual({ tab: "stops", stop: "X2", route: null });
    expect(parseView("?tab=bogus")).toEqual({ tab: "dashboard", stop: null, route: null });
    expect(serializeView({ tab: "routes", stop: null, route: "T1" }, "?stop=X1&login=a")).toBe(
      "?login=a&tab=routes&route=T1",
    );
  });
});

describe("format", () => {
  it("formats distances, timetable offsets and backend clock times", () => {
    expect(formatKm(10127)).toBe("10.1 km");
    expect(formatOffset(0)).toBe("start");
    expect(formatOffset(1457)).toBe("+24 min");
    expect(localClock("2030-01-07T07:15:00+05:30")).toBe("07:15");
    expect(localHour("2030-01-07T16:40:00+05:30")).toBe(16);
  });
});
