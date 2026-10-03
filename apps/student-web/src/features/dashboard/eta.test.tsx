import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as fx from "../../test/fixtures";
import { EtaCountdown } from "./LiveCards";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
  vi.setSystemTime(new Date("2030-01-01T10:00:00Z"));
});
afterEach(() => vi.useRealTimers());

describe("EtaCountdown (backend ETA, display-only countdown)", () => {
  it("ticks down from the backend timestamp at simulation speed", () => {
    render(
      <EtaCountdown
        eta={fx.eta(7)}
        simRef={{ fetchedAtMs: Date.now(), speed: 5, paused: false }}
      />,
    );
    expect(screen.getByLabelText("ETA 7 min")).toHaveTextContent("Moderate traffic");
    expect(screen.getByLabelText("ETA 7 min")).toHaveTextContent("High confidence");
    act(() => {
      vi.advanceTimersByTime(60_000); // 60 s wall × 5 = 300 s sim
    });
    expect(screen.getByLabelText("ETA 2 min")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(19_000); // 395 s sim → 25 s left
    });
    expect(screen.getByLabelText("ETA <1 min")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(screen.getByLabelText("ETA Arriving")).toBeInTheDocument();
  });

  it("freezes while the simulation is paused", () => {
    render(
      <EtaCountdown eta={fx.eta(7)} simRef={{ fetchedAtMs: Date.now(), speed: 5, paused: true }} />,
    );
    act(() => {
      vi.advanceTimersByTime(120_000);
    });
    expect(screen.getByLabelText("ETA 7 min")).toBeInTheDocument();
  });

  it("shows backend terminal states without traffic/confidence noise", () => {
    render(<EtaCountdown eta={fx.eta(0, { status: "at_stop" })} simRef={null} />);
    expect(screen.getByLabelText("ETA Arrived")).not.toHaveTextContent("traffic");
  });
});
