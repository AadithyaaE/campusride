import { describe, expect, it, vi } from "vitest";

import * as fx from "../test/fixtures";
import { fakeBackend, json, makeClient } from "../test/helpers";
import {
  ApiClient,
  ApiError,
  BackendUnavailableError,
  MalformedResponseError,
  UnauthorizedError,
} from "./client";

describe("ApiClient", () => {
  it("prefixes the base URL and sends the bearer token", async () => {
    const fetchImpl = vi.fn(async () => json(fx.stops));
    const api = makeClient(fetchImpl as unknown as typeof fetch, "tok-123");
    const stops = await api.listStops();
    expect(stops).toHaveLength(fx.stops.length);
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://backend.test/api/v1/stops");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-123");
  });

  it("strips trailing slashes from the base URL", async () => {
    const fetchImpl = vi.fn(async () => json(fx.health));
    const api = new ApiClient({
      baseUrl: "http://x.test/api/v1///",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    await api.health();
    expect((fetchImpl.mock.calls[0] as unknown as [string])[0]).toBe("http://x.test/api/v1/health");
  });

  it("does not send a token to public endpoints", async () => {
    const fetchImpl = vi.fn(async () => json(fx.token));
    const api = makeClient(fetchImpl as unknown as typeof fetch, "tok");
    await api.mockLogin("t1@example.test");
    const init = (fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ email: "t1@example.test" });
  });

  it("encodes query parameters for nearby stops", async () => {
    const fetchImpl = vi.fn(async () => json([{ ...fx.stops[1], distance_m: 12.5 }]));
    const api = makeClient(fetchImpl as unknown as typeof fetch);
    const res = await api.nearbyStops({ lat: 1.1, lng: 10.1, radiusM: 2000, limit: 5 });
    expect(res[0]!.distance_m).toBe(12.5);
    const url = new URL((fetchImpl.mock.calls[0] as unknown as [string])[0]);
    expect(Object.fromEntries(url.searchParams)).toEqual({
      lat: "1.1",
      lng: "10.1",
      radius_m: "2000",
      limit: "5",
    });
  });

  it("maps the backend error envelope to ApiError", async () => {
    const api = makeClient(async () =>
      json({ error: { code: "not_found", message: "stop S99 not found" } }, 404),
    );
    await expect(api.getStop("S99")).rejects.toMatchObject({
      status: 404,
      code: "not_found",
      message: "stop S99 not found",
    });
  });

  it("maps FastAPI 422 validation errors", async () => {
    const body = {
      detail: [{ loc: ["query", "lat"], msg: "Input should be less than or equal to 90" }],
    };
    const api = makeClient(async () => json(body, 422));
    const err = await api.nearbyStops({ lat: 999, lng: 1 }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({
      code: "validation_error",
      message: "lat: Input should be less than or equal to 90",
    });
  });

  it("raises UnauthorizedError on 401 and notifies the session", async () => {
    const onUnauthorized = vi.fn();
    const api = new ApiClient({
      baseUrl: "http://b.test",
      getToken: () => "expired",
      onUnauthorized,
      fetchImpl: async () =>
        json({ error: { code: "unauthorized", message: "token expired" } }, 401),
    });
    await expect(api.me()).rejects.toBeInstanceOf(UnauthorizedError);
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("refuses authenticated calls without a token, without hitting the network", async () => {
    const fetchImpl = vi.fn();
    const api = makeClient(fetchImpl as unknown as typeof fetch, null);
    await expect(api.listRoutes()).rejects.toBeInstanceOf(UnauthorizedError);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("reports an unreachable backend", async () => {
    const api = makeClient(async () => {
      throw new TypeError("Failed to fetch");
    });
    const err = await api.listStops().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(BackendUnavailableError);
    expect((err as Error).message).toContain("http://backend.test/api/v1");
  });

  it("treats gateway errors as backend unavailable", async () => {
    const api = makeClient(async () => new Response("Bad Gateway", { status: 502 }));
    await expect(api.listStops()).rejects.toBeInstanceOf(BackendUnavailableError);
  });

  it("rejects malformed responses", async () => {
    const wrongShape = makeClient(async () => json([{ id: "X1", name: "no location" }]));
    await expect(wrongShape.listStops()).rejects.toBeInstanceOf(MalformedResponseError);
    const notJson = makeClient(async () => new Response("<html>oops</html>", { status: 200 }));
    await expect(notJson.listRoutes()).rejects.toBeInstanceOf(MalformedResponseError);
    const swapped = makeClient(async () =>
      json({ ...fx.stops[1], location: { type: "Point", coordinates: [1.1, 210.0] } }),
    );
    await expect(swapped.getStop("X1")).rejects.toBeInstanceOf(MalformedResponseError);
  });

  it("accepts every Phase 1 response shape from the fake backend", async () => {
    const api = makeClient(fakeBackend().fetchImpl);
    await expect(api.health()).resolves.toMatchObject({ status: "ok" });
    await expect(api.me()).resolves.toEqual(fx.me);
    await expect(api.listRoutes()).resolves.toHaveLength(2);
    await expect(api.getRoute("T1")).resolves.toMatchObject({ id: "T1" });
    await expect(api.stopRoutes("X2")).resolves.toHaveLength(4);
    await expect(api.myAssignment()).resolves.toMatchObject({ status: "assigned" });
  });

  it("reads the college assignment, assigned or not, and rejects inconsistent ones", async () => {
    await expect(makeClient(async () => json(fx.unassigned)).myAssignment()).resolves.toEqual(
      fx.unassigned,
    );
    const broken = { ...fx.assignment, assignment: null }; // "assigned" without data
    await expect(makeClient(async () => json(broken)).myAssignment()).rejects.toBeInstanceOf(
      MalformedResponseError,
    );
    const fetchImpl = vi.fn(async () => json(fx.assignment));
    await makeClient(fetchImpl as unknown as typeof fetch).myAssignment();
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://backend.test/api/v1/students/me/assignment");
    expect(init.method).toBe("GET"); // read-only: the client has no way to change it
  });

  it("reads live bus state and bus detail", async () => {
    const api = makeClient(fakeBackend().fetchImpl);
    const buses = await api.listBuses();
    expect(buses.find((b) => b.id === "BX7")?.live?.route_direction_id).toBe("T2");
    const detail = {
      ...fx.buses[0],
      current_stop: { id: "X3", name: "Test Stop C" },
      next_stop: { id: "X2", name: "Test Stop B" },
      simulation_paused: false,
    };
    const one = makeClient(async () => json(detail));
    await expect(one.getBus("BX7")).resolves.toMatchObject({ next_stop: { id: "X2" } });
  });

  it("rejects malformed live state", async () => {
    const broken = [{ ...fx.buses[0], live: { status: "en_route" } }]; // no location etc.
    await expect(makeClient(async () => json(broken)).listBuses()).rejects.toBeInstanceOf(
      MalformedResponseError,
    );
  });

  it("calls the backend simulator controls with the right methods", async () => {
    const backend = fakeBackend();
    const api = makeClient(backend.fetchImpl);
    await expect(api.simStatus()).resolves.toMatchObject({ enabled: true, paused: false });
    await expect(api.simPause()).resolves.toMatchObject({ paused: true });
    await expect(api.simStart()).resolves.toMatchObject({ paused: false });
    await expect(api.simSetSpeed(10)).resolves.toMatchObject({ speed: 10 });
    await api.simReset();
    expect(backend.calls).toEqual([
      "GET /api/v1/sim/status",
      "POST /api/v1/sim/pause",
      "POST /api/v1/sim/start",
      "PUT /api/v1/sim/speed",
      "POST /api/v1/sim/reset",
    ]);
  });

  it("surfaces a forbidden simulator control as an ApiError", async () => {
    const api = makeClient(async () =>
      json({ error: { code: "forbidden", message: "simulator controls are admin-only" } }, 403),
    );
    await expect(api.simPause()).rejects.toMatchObject({ status: 403, code: "forbidden" });
  });

  it("reads backend stop matching for the student and for any stop", async () => {
    const backend = fakeBackend({
      "GET /api/v1/stops/X2/buses": (url) => {
        expect(url.searchParams.get("direction")).toBe("to_campus");
        return json({ stop: { id: "X2", name: "Test Stop B" }, buses: fx.myStopBuses.other_buses });
      },
    });
    const api = makeClient(backend.fetchImpl);
    const mine = await api.myStopBuses();
    expect(mine.my_bus?.bus_id).toBe("BX7");
    expect(mine.other_buses.map((b) => b.bus_id)).toEqual(["BX8", "BX9"]);
    const stop = await api.stopBuses("X2", "to_campus");
    expect(stop.buses).toHaveLength(2);
  });

  it("rejects an 'unassigned' matching response that still carries buses", async () => {
    const bogus = { ...fx.myStopUnassigned, other_buses: fx.myStopBuses.other_buses };
    await expect(makeClient(async () => json(bogus)).myStopBuses()).rejects.toBeInstanceOf(
      MalformedResponseError,
    );
  });

  it("reads backend ETAs and arrivals", async () => {
    const backend = fakeBackend({
      "GET /api/v1/buses/BX7/eta": (url) => {
        expect(url.searchParams.get("stop_id")).toBe("X2");
        return json({
          ...fx.eta(7),
          bus_id: "BX7",
          bus_number: "BX7",
          reg_no: "TEST 0007",
          stop_id: "X2",
          stop_name: "Test Stop B",
          route_id: "T2",
          route_direction_id: "T2",
          direction: "to_campus",
          proximity: "far_from_stop",
          distance_to_stop_m: 3200,
          stops_away: 1,
          delay_s: 30,
        });
      },
      "GET /api/v1/stops/X2/arrivals": () =>
        json({ stop: { id: "X2", name: "Test Stop B" }, arrivals: fx.myArrivals.arrivals }),
    });
    const api = makeClient(backend.fetchImpl);
    const e = await api.busEta("BX7", "X2");
    expect(e.eta_minutes).toBe(7);
    const s = await api.stopArrivals("X2");
    expect(s.arrivals.map((a) => a.bus_id)).toEqual(["BX8", "BX7", "BX9"]);
    const mine = await api.myArrivals();
    expect(mine.my_bus?.bus_id).toBe("BX7");
  });

  it("validates QR boarding and occupancy responses (Feature 8)", async () => {
    const backend = fakeBackend({
      "POST /api/v1/boarding/scan": () => json(fx.scanResult()),
      "GET /api/v1/buses/BX7/occupancy": () => json(fx.occupancy()),
      "GET /api/v1/trips/T-TEST-T2/boarding": () =>
        json({
          trip_id: "T-TEST-T2",
          bus_id: "BX7",
          route_direction_id: "T2",
          total_boarded: 1,
          visibility: "own",
          events: [
            {
              boarding_id: "BRD-T-TEST-T2-" + fx.me.id,
              student_id: fx.me.id,
              bus_id: "BX7",
              trip_id: "T-TEST-T2",
              stop_id: "X2",
              timestamp: "2030-01-07T01:50:00Z",
              scanner: "simulated",
            },
          ],
        }),
    });
    const api = makeClient(backend.fetchImpl);
    const payload = {
      student_id: fx.me.id,
      bus_id: "BX7",
      trip_id: "T-TEST-T2",
      timestamp: "2030-01-07T01:50:00Z",
    };
    expect((await api.scanBoarding(payload)).status).toBe("boarded");
    expect((await api.busOccupancy("BX7")).available_seats).toBe(12);
    expect((await api.tripBoarding("T-TEST-T2")).total_boarded).toBe(1);
    expect((await api.myBoarding()).trip_id).toBe("T-TEST-T2");
    const fractional = makeClient(async () => json(fx.occupancy({ occupancy_percentage: 76.4 })));
    await expect(fractional.busOccupancy("BX7")).rejects.toBeInstanceOf(MalformedResponseError);
    const full = makeClient(async () =>
      json({ error: { code: "bus_full", message: "Bus BX7 is full" } }, 409),
    );
    await expect(full.scanBoarding(payload)).rejects.toMatchObject({
      status: 409,
      code: "bus_full",
    });
  });

  it("validates the backend commute decision (Feature 7)", async () => {
    const ok = await makeClient(async () => json(fx.myCommute)).myCommuteDecision();
    expect(ok.decision).toBe("YES");
    const none = await makeClient(async () => json(fx.myCommuteUnassigned)).myCommuteDecision();
    expect(none.decision).toBeNull();
    for (const bad of [
      fx.commute({ decision: "PROBABLY" as never }),
      fx.commute({ walking_time_minutes: 3.7 }),
      fx.commute({
        student_location: { ...fx.myCommute.student_location!, source: "gps" as never },
      }),
    ]) {
      await expect(makeClient(async () => json(bad)).myCommuteDecision()).rejects.toBeInstanceOf(
        MalformedResponseError,
      );
    }
  });

  it("validates the backend bus comparison (Feature 6)", async () => {
    const ok = await makeClient(async () => json(fx.myBusOptions)).myBusOptions();
    expect(ok.options.map((o) => o.indicators)).toEqual([
      ["FASTEST"],
      ["ASSIGNED", "BEST_ALTERNATIVE"],
      ["LEAST_CROWDED"],
    ]);
    const unknownBadge = {
      ...fx.myBusOptions,
      options: [{ ...fx.myBusOptions.options[0], indicators: ["SMARTEST"] }],
    };
    await expect(makeClient(async () => json(unknownBadge)).myBusOptions()).rejects.toBeInstanceOf(
      MalformedResponseError,
    );
    const fractionalPct = {
      ...fx.myBusOptions,
      options: [{ ...fx.myBusOptions.options[0], occupancy_percentage: 92.4 }],
    };
    await expect(makeClient(async () => json(fractionalPct)).myBusOptions()).rejects.toBeInstanceOf(
      MalformedResponseError,
    );
    const none = await makeClient(async () => json(fx.myBusOptionsUnassigned)).myBusOptions();
    expect(none.status).toBe("unassigned");
  });

  it("surfaces 'bus does not serve this stop' (409) and rejects fractional minutes", async () => {
    const conflict = makeClient(async () =>
      json(
        {
          error: {
            code: "conflict",
            message: "bus BX8 is running T1, which does not serve stop X3",
          },
        },
        409,
      ),
    );
    await expect(conflict.busEta("BX8", "X3")).rejects.toMatchObject({
      status: 409,
      code: "conflict",
    });
    const fractional = {
      ...fx.myArrivals,
      arrivals: [{ ...fx.myArrivals.arrivals[0], eta: { ...fx.eta(2), eta_minutes: 2.4 } }],
    };
    await expect(makeClient(async () => json(fractional)).myArrivals()).rejects.toBeInstanceOf(
      MalformedResponseError,
    );
  });
});
