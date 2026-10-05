import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BoardingScanIn } from "../../api/types";
import * as fx from "../../test/fixtures";
import { fakeBackend, json, makeClient, renderWithApi } from "../../test/helpers";
import { ScanBoarding } from "./ScanBoarding";
import { simulatedPayload } from "./scanner";

const SIM_NOW = "2030-01-07T01:51:00Z";

function show(overrides: Parameters<typeof fakeBackend>[0] = {}) {
  const sent: BoardingScanIn[] = [];
  const backend = fakeBackend({
    "POST /api/v1/boarding/scan": async (_url, init) => {
      sent.push(JSON.parse(String(init.body)) as BoardingScanIn);
      return json(fx.scanResult());
    },
    ...overrides,
  });
  let boarded = 0;
  renderWithApi(
    <ScanBoarding simNowIso={SIM_NOW} onBoarded={() => (boarded += 1)} />,
    makeClient(backend.fetchImpl),
  );
  return { backend, sent, boardedCalls: () => boarded };
}

const simulate = async () =>
  fireEvent.click(await screen.findByRole("button", { name: "Simulate Scan" }));

describe("Scan Boarding QR (simulated scanner → POST /boarding/scan)", () => {
  it("shows the assigned bus, stop, trip and a clearly simulated scanner", async () => {
    show();
    const scanner = await screen.findByRole("region", { name: "Simulated QR scanner" });
    expect(scanner).toHaveTextContent("Demo scanner — simulates scanning the QR code on your bus");
    expect(scanner).toHaveTextContent("Assigned busBUS BX7");
    expect(scanner).toHaveTextContent("Boarding stopTest Stop B");
    expect(scanner).toHaveTextContent("TripT-TEST-T2");
    expect(within(scanner).getByRole("status")).toHaveTextContent("Ready to scan");
    expect(within(scanner).getByRole("button", { name: "Simulate Scan" })).toBeEnabled();
  });

  it("builds the payload from the backend's assignment + current trip only", async () => {
    const { sent, backend } = show();
    await simulate();
    await screen.findByRole("alert");
    expect(sent).toEqual([
      {
        student_id: fx.me.id,
        bus_id: "BX7",
        trip_id: "T-TEST-T2",
        timestamp: SIM_NOW,
        scanner: "simulated",
      },
    ]);
    expect(backend.calls).toContain("POST /api/v1/boarding/scan"); // the one real endpoint
  });

  it("confirms the boarding with the backend's occupancy numbers", async () => {
    const { boardedCalls } = show();
    await simulate();
    const result = await screen.findByRole("alert");
    expect(result).toHaveTextContent("Boarding recorded");
    expect(result).toHaveTextContent("BUS BX7");
    expect(result).toHaveTextContent("39 / 50 passengers");
    expect(result).toHaveTextContent("78% occupied");
    expect(result).toHaveTextContent("11 seats available");
    expect(boardedCalls()).toBe(1); // dashboard asked to refresh
  });

  it("shows the backend's numbers as given — no local occupancy maths", async () => {
    // deliberately inconsistent numbers: the UI must not "fix" them
    show({
      "POST /api/v1/boarding/scan": () =>
        json(fx.scanResult({ occupancy: 10, available_seats: 3, occupancy_percentage: 91 })),
    });
    await simulate();
    const result = await screen.findByRole("alert");
    expect(result).toHaveTextContent("10 / 50 passengers");
    expect(result).toHaveTextContent("91% occupied");
    expect(result).toHaveTextContent("3 seats available");
  });

  it("shows already-boarded for a repeat scan", async () => {
    show({
      "POST /api/v1/boarding/scan": () =>
        json(
          fx.scanResult({
            status: "already_boarded",
            message: "You have already boarded this trip.",
          }),
        ),
    });
    await simulate();
    const result = await screen.findByRole("alert");
    expect(result).toHaveTextContent("Already boarded");
    expect(result).toHaveTextContent("You have already boarded this trip.");
  });

  it("shows bus full when the backend rejects with bus_full", async () => {
    show({
      "POST /api/v1/boarding/scan": () =>
        json({ error: { code: "bus_full", message: "Bus BX7 is full" } }, 409),
    });
    await simulate();
    const result = await screen.findByRole("alert");
    expect(result).toHaveTextContent("Bus full");
    expect(result).toHaveTextContent("No seats are currently available.");
  });

  it("shows other backend rejections verbatim", async () => {
    show({
      "POST /api/v1/boarding/scan": () =>
        json(
          { error: { code: "stop_passed", message: "Bus BX7 has already passed Test Stop B." } },
          409,
        ),
    });
    await simulate();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Bus BX7 has already passed Test Stop B.",
    );
  });

  it("can't scan without a running trip, and offers no bus / stop / student choice", async () => {
    show({
      "GET /api/v1/students/me/boarding": () =>
        json({
          ...fx.myBoarding,
          trip_id: null,
          ready: false,
          reason_code: "trip_inactive",
          reason: "Bus BX7 has no trip running right now.",
        }),
    });
    const button = await screen.findByRole("button", { name: "Simulate Scan" });
    expect(button).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Bus BX7 has no trip running right now.");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("simulatedPayload uses only the assigned student / bus / trip", () => {
    expect(simulatedPayload(fx.myBoarding, SIM_NOW)).toEqual({
      student_id: fx.me.id,
      bus_id: "BX7",
      trip_id: "T-TEST-T2",
      timestamp: SIM_NOW,
    });
    expect(simulatedPayload({ ...fx.myBoarding, trip_id: null }, SIM_NOW)).toBeNull();
  });
});
