import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BusOptionsOut } from "../../api/types";
import * as fx from "../../test/fixtures";
import { BusOptions } from "./BusOptions";

function show(options: BusOptionsOut = fx.myBusOptions, selected: string | null = null) {
  const onSelectBus = vi.fn();
  render(
    <BusOptions
      options={options}
      simRef={null}
      selectedBusId={selected}
      onSelectBus={onSelectBus}
    />,
  );
  return { onSelectBus, region: screen.getByRole("region", { name: "Bus options" }) };
}

const card = (bus: string) => screen.getByRole("button", { name: `Bus ${bus}` });

describe("Bus options (backend multi-bus comparison)", () => {
  it("renders every option in the backend's order with a prominent ETA", () => {
    const { region } = show();
    expect(region).toHaveTextContent("Bus options · Test Stop B");
    const cards = within(region).getAllByRole("button", { name: /^Bus / });
    expect(cards.map((c) => c.getAttribute("aria-label"))).toEqual([
      "Bus BX8",
      "Bus BX7",
      "Bus BX9",
    ]);
    const eta = within(card("BX8")).getByLabelText("ETA 2 min");
    expect(eta.querySelector(".eta-value")).toHaveTextContent("2 min");
    expect(eta).not.toHaveTextContent("confidence"); // compact: traffic shown on its own line
  });

  it("shows occupancy and crowding as plain values", () => {
    show();
    expect(card("BX8")).toHaveTextContent("46 / 50");
    expect(card("BX8")).toHaveTextContent("High crowding");
    expect(card("BX9")).toHaveTextContent("9 / 50");
    expect(card("BX9")).toHaveTextContent("Low crowding");
    expect(card("BX8")).toHaveClass("crowd-high");
    expect(card("BX8").textContent).not.toMatch(/\d\.\d/); // no decimals anywhere
  });

  it("shows the backend's indicator badges, several on one bus if so", () => {
    show();
    expect(card("BX8")).toHaveTextContent("Fastest");
    expect(card("BX7")).toHaveTextContent("Assigned");
    expect(card("BX7")).toHaveTextContent("Best alternative");
    expect(card("BX9")).toHaveTextContent("Least crowded");
    expect(card("BX7")).toHaveClass("is-mine");
    expect(card("BX7").querySelectorAll(".opt-badge")).toHaveLength(2);
  });

  it("shows traffic, stops away, delay and the backend's trade-off text", () => {
    show();
    expect(card("BX8")).toHaveTextContent("Low traffic · next stop");
    expect(card("BX7")).toHaveTextContent("+2 min delay");
    expect(card("BX7")).toHaveTextContent("+5 min vs BX8 · 22 more seats free");
    expect(card("BX8")).not.toHaveTextContent("delay");
  });

  it("never shows a score or internal weights", () => {
    const { region } = show();
    expect(region).not.toHaveTextContent(/score|weight|cost/i);
  });

  it("uses the backend's indicators as given — the browser computes no comparison", () => {
    // Deliberately inconsistent with the numbers: the UI must not "correct" it.
    const odd: BusOptionsOut = {
      ...fx.myBusOptions,
      options: [
        { ...fx.myBusOptions.options[0]!, indicators: ["LEAST_CROWDED"] }, // the 92 % bus
        { ...fx.myBusOptions.options[2]!, indicators: [] }, // the 18 % bus
      ],
    };
    show(odd);
    expect(card("BX8")).toHaveTextContent("Least crowded");
    expect(card("BX9")).not.toHaveTextContent("Least crowded");
    expect(card("BX8")).not.toHaveTextContent("Fastest");
  });

  it("explains when there is no alternative, and why my bus is missing", () => {
    show({
      ...fx.myBusOptions,
      assigned_bus_available: false,
      assigned_bus_note: "Bus BX7 has already passed Test Stop B.",
      options: [{ ...fx.myBusOptions.options[2]!, indicators: [], trade_off: null }],
    });
    expect(screen.getByText("Bus BX7 has already passed Test Stop B.")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Bus / })).toHaveLength(1);
    cleanup();
    show({ ...fx.myBusOptions, options: [fx.myBusOptions.options[1]!] });
    expect(
      screen.getByText("No other bus serves your stop in your direction right now."),
    ).toBeInTheDocument();
  });

  it("shows an empty state when no bus is due, and lists excluded buses briefly", () => {
    const { region } = show({ ...fx.myBusOptions, options: [] });
    expect(region).toHaveTextContent("No bus is due at your stop right now");
    expect(region).toHaveTextContent("Not shown: BX6 (passed your stop)");
  });

  it("selecting a card asks to highlight that bus; tapping again clears it", () => {
    const { onSelectBus } = show(fx.myBusOptions, "BX9");
    expect(card("BX9")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(card("BX8"));
    expect(onSelectBus).toHaveBeenLastCalledWith("BX8");
    fireEvent.click(card("BX9"));
    expect(onSelectBus).toHaveBeenLastCalledWith(null);
  });
});
