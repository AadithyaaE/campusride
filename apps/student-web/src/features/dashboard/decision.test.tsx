import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CommuteDecisionOut } from "../../api/types";
import * as fx from "../../test/fixtures";
import { DecisionCard } from "./LiveCards";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
  vi.setSystemTime(new Date("2030-01-01T10:00:00Z"));
});
afterEach(() => vi.useRealTimers());

function show(d: CommuteDecisionOut, opts: { speed?: number; onViewOptions?: () => void } = {}) {
  render(
    <DecisionCard
      commute={d}
      simRef={{ fetchedAtMs: Date.now(), speed: opts.speed ?? 1, paused: false }}
      onViewOptions={opts.onViewOptions}
    />,
  );
  return screen.getByRole("region", { name: "Will I make my bus?" });
}

const RISK = fx.commute({
  decision: "RISK",
  reason: "You may reach the stop, but there is little time to spare.",
  bus_eta_minutes: 5,
  eta: fx.eta(5),
  spare_minutes: 1,
});

const MISSED = fx.commute({
  decision: "MISSED",
  reason: "Your assigned bus has already passed your stop.",
  walking_time_minutes: null,
  bus_eta_minutes: null,
  bus_arrival_time: null,
  required_arrival_time: null,
  eta: null,
  proximity: "passed_stop",
});

describe('"Will I make my bus?" — backend commute decision', () => {
  it("renders YES with arrival, walking time, buffer and reason", () => {
    const card = show(fx.myCommute);
    expect(card).toHaveTextContent("Can I catch bus BX7?");
    expect(within(card).getByRole("status")).toHaveAccessibleName("Decision: YES");
    expect(card).toHaveClass("decision-yes");
    expect(within(card).getByLabelText("Bus arrives in 7 min")).toBeInTheDocument();
    expect(card).toHaveTextContent("Walking time4 min");
    expect(card).toHaveTextContent("Safety buffer2 min");
    expect(card).toHaveTextContent("You should reach your stop before the bus.");
  });

  it("renders RISK", () => {
    const card = show(RISK);
    expect(within(card).getByRole("status")).toHaveAccessibleName("Decision: RISK");
    expect(card).toHaveClass("decision-risk");
    expect(within(card).getByLabelText("Bus arrives in 5 min")).toBeInTheDocument();
    expect(card).toHaveTextContent("You may reach the stop, but there is little time to spare.");
    expect(card).toHaveTextContent("2 other buses serve your stop.");
  });

  it("renders MISSED without timing rows and points to the alternatives", () => {
    const onViewOptions = vi.fn();
    const card = show(MISSED, { onViewOptions });
    expect(within(card).getByRole("status")).toHaveAccessibleName("Decision: MISSED");
    expect(card).toHaveClass("decision-missed");
    expect(card).toHaveTextContent("Your assigned bus has already passed your stop.");
    expect(card).not.toHaveTextContent("Walking time");
    expect(card).toHaveTextContent("Your assigned bus stays BX7"); // never switched
    fireEvent.click(within(card).getByRole("button", { name: "See bus options" }));
    expect(onViewOptions).toHaveBeenCalled();
  });

  it("counts the bus down from the backend arrival timestamp, whole minutes only", () => {
    const card = show(fx.myCommute, { speed: 5 });
    expect(within(card).getByLabelText("Bus arrives in 7 min")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(60_000); // 60 s × 5 = 5 sim minutes
    });
    expect(within(card).getByLabelText("Bus arrives in 2 min")).toBeInTheDocument();
    expect(card).toHaveClass("decision-yes"); // the countdown never re-decides
    expect(card.textContent).not.toMatch(/\d\.\d/);
  });

  it("shows a walk under a minute as <1 min and the bus at the stop plainly", () => {
    const card = show(
      fx.commute({
        decision: "RISK",
        reason: "Your bus is at the stop now — go straight there.",
        walking_time_minutes: 0,
        bus_eta_minutes: 0,
        eta: fx.eta(0, { status: "at_stop" }),
      }),
    );
    expect(card).toHaveTextContent("Walking time<1 min");
    expect(within(card).getByLabelText("Bus arrives in At your stop now")).toBeInTheDocument();
  });

  it("shows location unavailable instead of a fake YES / RISK", () => {
    const card = show(
      fx.commute({
        decision: "LOCATION_UNAVAILABLE",
        reason: "Your location is unavailable, so your walking time can't be estimated.",
        student_location: null,
        walking_distance_m: null,
        walking_time_minutes: null,
      }),
    );
    expect(within(card).getByRole("status")).toHaveAccessibleName("Decision: Location unavailable");
    expect(card).toHaveTextContent("Location unavailable — we can’t estimate your walk");
    expect(within(card).getByRole("status")).not.toHaveTextContent(/YES|RISK|MISSED/);
    expect(card).not.toHaveTextContent("Walking time");
  });

  it("labels the student location as simulated (demo, not GPS)", () => {
    const card = show(fx.myCommute);
    expect(card).toHaveTextContent("Simulated location");
    expect(card).toHaveTextContent("Walk ≈ 340 m from your demo location");
  });

  it("uses the backend decision directly — it never re-decides from the numbers", () => {
    // Numbers that would look like RISK to a naive browser rule; the backend said YES.
    const card = show(
      fx.commute({ walking_time_minutes: 12, bus_eta_minutes: 3, eta: fx.eta(3), decision: "YES" }),
    );
    expect(within(card).getByRole("status")).toHaveAccessibleName("Decision: YES");
    // …and the opposite: comfortable numbers, backend says RISK (e.g. stale telemetry).
    const stale = fx.commute({
      decision: "RISK",
      stale: true,
      reason: "Bus location is not updating, so arrival timing is uncertain.",
    });
    render(<DecisionCard commute={stale} simRef={null} />);
    const cards = screen.getAllByRole("region", { name: "Will I make my bus?" });
    expect(within(cards[1]!).getByRole("status")).toHaveAccessibleName("Decision: RISK");
    expect(cards[1]).toHaveTextContent("Bus location is not updating");
  });
});
