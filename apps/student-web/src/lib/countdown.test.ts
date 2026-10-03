import { describe, expect, it } from "vitest";

import * as fx from "../test/fixtures";
import { countdownLabel, remainingSeconds, simNowMs } from "./countdown";

const fetched = Date.parse("2030-01-01T10:00:00Z"); // wall time of the poll

describe("ETA countdown (display only, from the backend timestamp)", () => {
  it("advances simulated time at the simulation speed, frozen when paused", () => {
    const ref = { fetchedAtMs: fetched, speed: 5, paused: false };
    expect(simNowMs(fx.COMPUTED_AT, ref, fetched + 10_000) - Date.parse(fx.COMPUTED_AT)).toBe(
      50_000,
    );
    expect(simNowMs(fx.COMPUTED_AT, { ...ref, paused: true }, fetched + 10_000)).toBe(
      Date.parse(fx.COMPUTED_AT),
    );
  });

  it("counts down whole minutes from the backend's estimated arrival", () => {
    const e = fx.eta(6); // arrival = computed_at + 360 s
    const ref = { fetchedAtMs: fetched, speed: 1, paused: false };
    expect(countdownLabel(e, ref, fetched)).toBe("6 min");
    expect(countdownLabel(e, ref, fetched + 1_000)).toBe("6 min"); // 359 s → still 6
    expect(countdownLabel(e, ref, fetched + 60_000)).toBe("5 min");
    expect(countdownLabel(e, ref, fetched + 300_000)).toBe("1 min");
    expect(countdownLabel(e, ref, fetched + 301_000)).toBe("<1 min");
    expect(countdownLabel(e, ref, fetched + 360_000)).toBe("Arriving");
    expect(countdownLabel(e, ref, fetched + 999_000)).toBe("Arriving");
    expect(remainingSeconds(e, ref, fetched + 1_500)).toBe(359); // integer seconds internally
  });

  it("speeds up with the simulation and never shows decimals", () => {
    const e = fx.eta(11);
    const ref = { fetchedAtMs: fetched, speed: 20, paused: false };
    for (let ms = 0; ms <= 40_000; ms += 777) {
      const label = countdownLabel(e, ref, fetched + ms);
      expect(label).toMatch(/^(\d+ min|<1 min|Arriving)$/);
      expect(label).not.toMatch(/\d\.\d/);
    }
    expect(countdownLabel(e, ref, fetched + 30_000)).toBe("1 min"); // 600 s of sim time later
  });

  it("uses the backend's terminal states", () => {
    expect(countdownLabel(fx.eta(0, { status: "at_stop" }), null, fetched)).toBe("Arrived");
    expect(countdownLabel(fx.eta(null), null, fetched)).toBe("Passed");
    expect(countdownLabel(fx.eta(null, { status: "completed" }), null, fetched)).toBe("Completed");
    expect(remainingSeconds(fx.eta(null), null, fetched)).toBeNull();
  });

  it("without a poll reference shows the backend value as computed", () => {
    expect(countdownLabel(fx.eta(4), null, Date.now())).toBe("4 min");
  });
});
