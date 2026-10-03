import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RouteStatus } from "../../api/types";
import * as fx from "../../test/fixtures";
import { MyBusLiveCard, RouteStatusText } from "./LiveCards";

function card(route_status: RouteStatus | null, deviation_distance_m: number | null) {
  render(
    <MyBusLiveCard
      assignment={fx.assignment.assignment!}
      bus={fx.arrival("BX7", {}, fx.eta(7), { route_status, deviation_distance_m })}
      servingStop
      paused={false}
      simRef={null}
    />,
  );
  return screen.getByRole("region", { name: "My bus live" });
}

describe("Route status on my bus card (backend Feature 10, displayed as given)", () => {
  it("normal: on planned route", () => {
    const c = card("NORMAL", 6.2);
    expect(c).toHaveTextContent("RouteOn planned route");
    expect(within(c).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("minor: shows the backend distance, no alert", () => {
    const c = card("MINOR_DEVIATION", 92.8);
    expect(c).toHaveTextContent("Minor deviation · 93 m off route");
    expect(within(c).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("major: shows the distance and a factual alert", () => {
    const c = card("MAJOR_DEVIATION", 419.6);
    expect(c).toHaveTextContent("Major deviation · 420 m off route");
    expect(within(c).getByRole("alert")).toHaveTextContent(
      "Your bus is currently 420 m from its planned route.",
    );
    expect(c).not.toHaveTextContent(/lost|driver/i); // observed condition only
  });

  it("keeps the rest of the card (ETA, occupancy) next to the route line", () => {
    const c = card("MAJOR_DEVIATION", 300);
    expect(within(c).getByLabelText("ETA 7 min")).toBeInTheDocument();
    expect(within(c).getByLabelText("Live occupancy")).toBeInTheDocument();
  });

  it("uses the backend status — never re-classifies from the distance", () => {
    // a distance that a browser rule would call MAJOR, while the backend says NORMAL
    render(<RouteStatusText status="NORMAL" distance={999} />);
    expect(screen.getByText("On planned route")).toBeInTheDocument();
    render(<RouteStatusText status="STALE" distance={null} />);
    expect(screen.getByText("Route status unavailable")).toBeInTheDocument();
  });
});
