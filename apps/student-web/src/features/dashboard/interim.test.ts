import { describe, expect, it } from "vitest";

import * as fx from "../../test/fixtures";
import * as interim from "./interim";
import { backendEtaMin, otherArrivals, PROXIMITY_LABEL, STATUS_LABEL } from "./interim";

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

  it("generates no alerts in the browser (Feature 11: backend AlertService only)", () => {
    for (const name of ["dashboardAlerts", "CAPACITY_WARN_PCT", "DashboardAlert"]) {
      expect(name in interim).toBe(false);
    }
  });

  it("labels every backend status and proximity", () => {
    expect(Object.keys(STATUS_LABEL)).toHaveLength(7);
    expect(Object.keys(PROXIMITY_LABEL)).toHaveLength(4);
  });
});
