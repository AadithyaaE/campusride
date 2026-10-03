import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { RecoveryOut } from "../../api/types";
import * as fx from "../../test/fixtures";
import { RecoveryCard } from "./RecoveryCard";

function show(r: RecoveryOut, onViewOptions = vi.fn()) {
  const { container } = render(
    <RecoveryCard recovery={r} simRef={null} onViewOptions={onViewOptions} />,
  );
  return {
    card: screen.queryByRole("region", { name: "Missed-bus recovery" }),
    container,
    onViewOptions,
  };
}

describe("Missed-bus recovery card (backend result, rendered as given)", () => {
  it("is hidden when recovery is not needed or the student is unassigned", () => {
    expect(show(fx.recoveryNotNeeded).card).toBeNull();
    expect(
      show(
        fx.recovery({ status: "unassigned", trigger: null, recommended: null, alternatives: [] }),
      ).card,
    ).toBeNull();
  });

  it("appears on RISK with the recommended bus and its backend values", () => {
    const { card } = show(fx.recovery());
    expect(within(card!).getByRole("status")).toHaveTextContent("You may miss BUS BX7");
    expect(card).toHaveTextContent("Try BUS BX8 instead");
    expect(within(card!).getByLabelText("ETA 9 min")).toBeInTheDocument();
    const occ = within(card!).getByLabelText("Recommended bus occupancy");
    expect(occ).toHaveTextContent("24 / 50 passengers");
    expect(occ).toHaveTextContent("48% occupied");
    expect(occ).toHaveTextContent("26 seats available");
    expect(card).toHaveTextContent("StatusOn time");
    expect(card).toHaveTextContent(
      "“Bus BX8 serves your stop and gives you a 5-minute safety buffer.”",
    );
  });

  it("appears on MISSED", () => {
    const { card } = show(fx.recovery({ trigger: "missed", commute_decision: "MISSED" }));
    expect(within(card!).getByRole("status")).toHaveTextContent("You missed BUS BX7");
    expect(card).toHaveClass("recovery-missed");
    expect(card).toHaveTextContent("Try BUS BX8 instead");
  });

  it("appears on a significant delay", () => {
    const { card } = show(
      fx.recovery({
        trigger: "significantly_delayed",
        commute_decision: "YES",
        assigned_bus_delay_minutes: 7,
      }),
    );
    expect(within(card!).getByRole("status")).toHaveTextContent("BUS BX7 is delayed +7 min");
    expect(card).toHaveTextContent("Consider BUS BX8");
  });

  it("lists the other recovery options in the backend's order", () => {
    const { card } = show(fx.recovery());
    const list = within(card!).getByRole("list", { name: "Other recovery options" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows.map((r) => r.getAttribute("aria-label"))).toEqual(["Recovery option BUS BX9"]);
    expect(rows[0]).toHaveTextContent("40 seats");
  });

  it("shows a delayed alternative's status", () => {
    const { card } = show(
      fx.recovery({
        recommended: fx.recoveryOption("BX8", { status: "delayed", delay_minutes: 6 }),
      }),
    );
    expect(card).toHaveTextContent("StatusDelayed +6 min");
  });

  it("explains when no alternative can be caught", () => {
    const { card } = show(
      fx.recovery({
        status: "no_alternative",
        trigger: "missed",
        recommended: null,
        alternatives: [],
      }),
    );
    expect(within(card!).getByRole("status")).toHaveTextContent("You missed BUS BX7");
    expect(card).toHaveTextContent("No other bus serving Test Stop B can be caught right now.");
    expect(card).not.toHaveTextContent("Try BUS");
  });

  it("is a suggestion only — no way to change the assigned bus", () => {
    const { card, onViewOptions } = show(fx.recovery());
    expect(card).toHaveTextContent("Suggestion only — your college-assigned bus stays BUS BX7.");
    const buttons = within(card!).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["View bus options"]);
    expect(within(card!).queryByRole("combobox")).not.toBeInTheDocument();
    fireEvent.click(buttons[0]!);
    expect(onViewOptions).toHaveBeenCalled();
  });

  it("does no ranking or maths of its own", () => {
    // values that a browser rule would reorder or recompute — shown exactly as sent
    const { card } = show(
      fx.recovery({
        recommended: fx.recoveryOption("BX9", {
          eta_minutes: 20,
          occupancy: 49,
          available_seats: 7,
          occupancy_percentage: 12,
        }),
        alternatives: [fx.recoveryOption("BX8", { eta_minutes: 2 })],
      }),
    );
    expect(card).toHaveTextContent("Try BUS BX9 instead"); // not "corrected" to the sooner BX8
    const occ = within(card!).getByLabelText("Recommended bus occupancy");
    expect(occ).toHaveTextContent("49 / 50 passengers");
    expect(occ).toHaveTextContent("12% occupied");
    expect(occ).toHaveTextContent("7 seats available");
  });
});
