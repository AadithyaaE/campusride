import { describe, expect, it } from "vitest";

import type { MyArrivalsOut } from "../../api/types";
import * as fx from "../../test/fixtures";
import * as interim from "./interim";
import {
  backendEtaMin,
  dashboardAlerts,
  otherArrivals,
  PROXIMITY_LABEL,
  STATUS_LABEL,
} from "./interim";

const withArrivals = (patch: Partial<MyArrivalsOut>): MyArrivalsOut => ({
  ...fx.myArrivals,
  ...patch,
});

describe("interim rules on top of the BACKEND ETA", () => {
  it("has no browser-side ETA formula any more", () => {
    expect("etaEstimateMin" in interim).toBe(false);
    expect("INTERIM_MIN_SPEED_MPS" in interim).toBe(false);
    // the only ETA it knows is what the backend returned
    expect(backendEtaMin(fx.myArrivals.my_bus)).toBe(7);
    expect(backendEtaMin(fx.stopBus("BX7", {}))).toBeNull(); // no eta object → nothing invented
  });

  it('no longer decides "Will I make my bus?" in the browser', () => {
    // Feature 7: the decision comes from GET /students/me/commute-decision
    for (const name of ["decide", "assumedWalkMin", "hash", "YES_BUFFER_MIN"]) {
      expect(name in interim).toBe(false);
    }
  });

  it("keeps the backend's ETA order for other buses and no longer recommends in the browser", () => {
    const others = otherArrivals(fx.myArrivals);
    expect(others.map((b) => b.bus_id)).toEqual(["BX8", "BX9"]); // backend order, mine excluded
    expect(otherArrivals(fx.myArrivalsUnassigned)).toEqual([]);
    // Feature 6: recommendations come from GET /students/me/bus-options, not from React
    expect("recommend" in interim).toBe(false);
  });

  it("raises alerts from backend proximity, ETA, delay, occupancy and deviation", () => {
    const a = withArrivals({
      my_bus: fx.arrival(
        "BX7",
        { proximity: "approaching_stop", distance_to_stop_m: 600 },
        fx.eta(2),
        { schedule_status: "delayed", delay_s: 360 },
      ),
      arrivals: [
        fx.arrival("BX8", { proximity: "approaching_stop" }, fx.eta(1), { occupancy: 37 }),
      ],
    });
    const deviated = fx.buses.map((b) =>
      b.id === "BX9" ? { ...b, live: { ...b.live!, status: "deviated" as const } } : b,
    );
    const options = {
      ...fx.myBusOptions,
      options: [
        fx.option(fx.myArrivals.arrivals[2]!, {
          crowding: "Low",
          indicators: ["BEST_ALTERNATIVE"], // chosen by the backend comparison
        }),
      ],
    };
    const alerts = dashboardAlerts(a, fx.commute({ decision: "RISK" }), options, deviated);
    const byKind = Object.fromEntries(alerts.map((x) => [x.kind, x]));
    expect(byKind.approaching?.body).toBe("About 2 min from Test Stop B."); // backend ETA
    expect(byKind.delay?.body).toBe("About 6 min behind the timetable.");
    expect(byKind.capacity?.title).toBe("Bus BX8 is 93% full");
    expect(byKind.deviation?.title).toBe("Bus BX9 is off its usual route");
    expect(byKind.alternative?.title).toBe("Alternative: Bus BX9 (T2)"); // backend BEST_ALTERNATIVE
    expect(byKind.alternative?.body).toContain("low crowding");
    // a YES for the assigned bus raises no alternative alert
    expect(
      dashboardAlerts(a, fx.myCommute, options, fx.buses).some((x) => x.kind === "alternative"),
    ).toBe(false);
    expect(
      dashboardAlerts(a, fx.commute({ decision: "RISK" }), null, fx.buses).some(
        (x) => x.kind === "alternative",
      ),
    ).toBe(false);
    expect(dashboardAlerts(fx.myArrivalsUnassigned, null, null, fx.buses)).toEqual([]);
  });

  it("labels every backend status and proximity", () => {
    expect(Object.keys(STATUS_LABEL)).toHaveLength(7);
    expect(Object.keys(PROXIMITY_LABEL)).toHaveLength(4);
  });
});
