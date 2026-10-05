import { act, fireEvent, render, screen, waitFor } from "@testing-library/react-native";

import { AppRoot } from "../App";
import { FALLBACK_POLL_MS } from "./state/useDriver";
import { activeDash, dash, errorJson, fakeBackend, json, type Handler } from "./test/fakeBackend";

async function signIn(overrides: Record<string, Handler> = {}) {
  const backend = fakeBackend(overrides);
  await render(<AppRoot fetchImpl={backend.fetchImpl} />);
  await screen.findByText(/Demo sign-in/); // options from GET /auth/config
  await fireEvent.press(screen.getByRole("button", { name: "SIGN IN" }));
  return backend;
}

const startButton = () => screen.findByRole("button", { name: "START TRIP" });

describe("Driver App — backend-driven (Feature 12)", () => {
  it("shows the driver's backend assignment and READY state", async () => {
    await signIn();
    expect(await screen.findByText("Arun Kumar")).toBeTruthy();
    expect(screen.getByText("BUS B07")).toBeTruthy();
    expect(screen.getByText("R4 — To Campus")).toBeTruthy();
    expect(screen.getByText("READY")).toBeTruthy();
    expect(screen.getByLabelText("FIRST STOP: Guindy")).toBeTruthy();
    expect(await startButton()).toBeTruthy();
    expect(screen.queryByRole("button", { name: "STOP TRIP" })).toBeNull();
  });

  it("starts the trip through the backend and shows the ACTIVE state it returns", async () => {
    const backend = await signIn();
    await fireEvent.press(await startButton());
    expect(await screen.findByText("DRIVING")).toBeTruthy();
    expect(backend.calls).toContain("POST /api/v1/driver/trip/start");
    expect(screen.getByLabelText("SPEED: 32 km/h")).toBeTruthy();
    expect(screen.getByLabelText("PASSENGERS: 38 / 50 · 12 seats free")).toBeTruthy();
    expect(screen.getByLabelText("NEXT STOP: Library Gate")).toBeTruthy();
    expect(screen.getByLabelText("GPS: LIVE, simulated")).toBeTruthy();
    expect(screen.getByText("SIMULATED GPS")).toBeTruthy();
    expect(screen.getByRole("button", { name: "STOP TRIP" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "SIMULATE GPS" })).toBeTruthy();
  });

  it("never shows ACTIVE unless the backend confirmed it", async () => {
    await signIn({
      "POST /api/v1/driver/trip/start": () => errorJson(500, "http_error", "boom"),
    });
    await fireEvent.press(await startButton());
    expect(await screen.findByText("Trip could not be started. Please try again.")).toBeTruthy();
    expect(screen.getByText("READY")).toBeTruthy();
    expect(screen.queryByText("DRIVING")).toBeNull();
  });

  it("shows a driver-friendly message for a duplicate start", async () => {
    await signIn({
      "POST /api/v1/driver/trip/start": () => errorJson(409, "trip_already_active"),
    });
    await fireEvent.press(await startButton());
    expect(await screen.findByText("A trip is already active on your bus.")).toBeTruthy();
  });

  it("stops the trip through the backend and returns to READY", async () => {
    let active = true;
    const backend = await signIn({
      "GET /api/v1/driver/me": () => json(active ? activeDash() : dash()),
      "POST /api/v1/driver/trip/stop": () => {
        active = false;
        return json(dash({ next_stop: "Campus" }));
      },
    });
    await fireEvent.press(await screen.findByRole("button", { name: "STOP TRIP" }));
    expect(await screen.findByText("READY")).toBeTruthy();
    expect(backend.calls).toContain("POST /api/v1/driver/trip/stop");
    expect(await startButton()).toBeTruthy();
  });

  it("shows stale and unavailable GPS exactly as the backend reports", async () => {
    await signIn({ "GET /api/v1/driver/me": () => json(activeDash({ gps: "STALE" })) });
    expect(await screen.findByLabelText("GPS: STALE, simulated")).toBeTruthy();
  });

  it("simulate GPS asks the backend (no coordinates are made in the app)", async () => {
    const backend = await signIn({ "GET /api/v1/driver/me": () => json(activeDash()) });
    await fireEvent.press(await screen.findByRole("button", { name: "SIMULATE GPS" }));
    await waitFor(() => expect(backend.calls).toContain("POST /api/v1/driver/simulate-gps"));
  });

  it("without a live socket, polls the backend every 10 s while driving", async () => {
    jest.useFakeTimers();
    try {
      let speed = 32;
      await signIn({
        "GET /api/v1/driver/me": () =>
          json(activeDash({ live: { ...activeDash().live!, speed_kmh: speed } })),
      });
      expect(await screen.findByLabelText("SPEED: 32 km/h")).toBeTruthy();
      speed = 41;
      await act(async () => {
        jest.advanceTimersByTime(FALLBACK_POLL_MS);
      });
      expect(await screen.findByLabelText("SPEED: 41 km/h")).toBeTruthy();
    } finally {
      jest.useRealTimers();
    }
  });

  it("shows the passenger count from the backend occupancy endpoint", async () => {
    const backend = await signIn({ "GET /api/v1/driver/me": () => json(activeDash()) });
    await fireEvent.press(await screen.findByRole("button", { name: "PASSENGERS" }));
    expect(await screen.findByLabelText("PASSENGERS: 38 / 50")).toBeTruthy();
    expect(screen.getByLabelText("AVAILABLE SEATS: 12")).toBeTruthy();
    expect(screen.getByLabelText("OCCUPANCY: 76%")).toBeTruthy();
    expect(await screen.findByLabelText("QR BOARDINGS THIS TRIP: 1")).toBeTruthy();
    expect(backend.calls).toContain("GET /api/v1/buses/B07/occupancy");
  });

  it("shows the route with backend progress", async () => {
    await signIn({ "GET /api/v1/driver/me": () => json(activeDash()) });
    await fireEvent.press(await screen.findByRole("button", { name: "VIEW ROUTE" }));
    expect(await screen.findByLabelText("Stop 3: Library Gate, next")).toBeTruthy();
    expect(screen.getByLabelText("Stop 1: Guindy, passed")).toBeTruthy();
    await fireEvent.press(screen.getByRole("button", { name: "BACK" }));
    expect(await screen.findByText("DRIVING")).toBeTruthy();
  });

  it("handles no assignment", async () => {
    await signIn({
      "GET /api/v1/driver/me": () =>
        json(
          dash({
            bus: null,
            route: null,
            trip: null,
            trip_state: "NO_ASSIGNMENT",
            can_start: false,
            next_stop: null,
            live: null,
            gps: "UNAVAILABLE",
            message: "You have no bus assigned. Please contact the transport office.",
          }),
        ),
    });
    expect(await screen.findByText("NO BUS ASSIGNED")).toBeTruthy();
    expect(
      screen.getByText("You have no bus assigned. Please contact the transport office."),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "START TRIP" })).toBeNull();
  });

  it("refuses non-driver accounts and shows unauthorized / connection errors", async () => {
    await signIn({
      "GET /api/v1/me": () =>
        json({
          id: "U-S0001",
          role: "student",
          name: "Surya",
          email: "student001@campusride.demo",
        }),
    });
    expect(await screen.findByText("This app is for drivers only.")).toBeTruthy();
  });

  it("shows 'Connection unavailable' instead of pretending", async () => {
    await signIn({
      "GET /api/v1/driver/me": () => {
        throw new TypeError("network down");
      },
    });
    expect(await screen.findByText("Connection unavailable")).toBeTruthy();
    expect(screen.queryByText("DRIVING")).toBeNull();
  });

  it("shows a session message on 401", async () => {
    await signIn({ "GET /api/v1/driver/me": () => errorJson(401, "unauthorized") });
    expect(await screen.findByText("Your session has ended. Please sign in again.")).toBeTruthy();
  });
});

describe("prototype boundaries", () => {
  it("uses no device GPS or location permission", () => {
    const pkg = require("../package.json") as { dependencies: Record<string, string> };
    expect(Object.keys(pkg.dependencies)).not.toContain("expo-location");
  });
});
