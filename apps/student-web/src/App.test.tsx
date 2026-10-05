import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { ApiClient } from "./api/client";
import type { MapViewProps } from "./map/MapView";
import { SessionStore } from "./session/sessionStore";
import * as fx from "./test/fixtures";
import { fakeBackend, json, MemoryStorage } from "./test/helpers";

// Leaflet needs a real browser; the adapter is replaced by a probe that records its props.
const mapProps: { current: MapViewProps | null } = { current: null };
vi.mock("./map/MapView", () => ({
  default: (props: MapViewProps) => {
    mapProps.current = props;
    return (
      <div data-testid="map">{`${props.routes.length} routes, ${props.stops.length} stops`}</div>
    );
  },
}));

function setup(overrides: Parameters<typeof fakeBackend>[0] = {}, storage = new MemoryStorage()) {
  const store = new SessionStore(storage);
  const backend = fakeBackend(overrides);
  const api = new ApiClient({
    baseUrl: "http://backend.test/api/v1",
    getToken: () => store.get()?.token ?? null,
    onUnauthorized: () => store.clear(),
    fetchImpl: backend.fetchImpl,
  });
  const utils = render(<App api={api} store={store} />);
  return { ...utils, store, storage, backend };
}

beforeEach(() => {
  mapProps.current = null;
  window.history.replaceState(null, "", "/");
});

describe("App", () => {
  it("signs in (development sign-in, clearly labelled) and loads the network from the backend", async () => {
    const { backend } = setup();
    expect(await screen.findByRole("note")).toHaveTextContent(
      "Demo sign-in — use any demo student account",
    );
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByTestId("map")).toHaveTextContent("2 routes, 4 stops");
    expect(screen.getByText("Test Student")).toBeInTheDocument();
    // Bus markers: the real fleet (from GET /buses) at SIMULATED positions; the assigned bus highlighted.
    await waitFor(() => expect(mapProps.current?.buses.map((b) => b.id)).toContain("BX7"));
    // only real fleet ids (buses in end-of-trip layover are hidden)
    expect(mapProps.current?.buses.every((b) => ["BX7", "BX8", "BX9"].includes(b.id))).toBe(true);
    expect(mapProps.current?.buses.filter((b) => b.highlight).map((b) => b.id)).toEqual(["BX7"]);
    expect(mapProps.current?.buses.every((b) => b.title?.includes("simulated"))).toBe(true);
    expect(mapProps.current?.stops.find((s) => s.id === "X2")?.shared).toBe(true);
    expect(backend.calls).toEqual(
      expect.arrayContaining([
        "POST /api/v1/auth/dev-login",
        "GET /api/v1/stops",
        "GET /api/v1/routes",
        "GET /api/v1/routes/T1",
        "GET /api/v1/routes/T2",
        "GET /api/v1/students/me/assignment",
        "GET /api/v1/buses",
      ]),
    );
    expect(await screen.findByRole("status", { name: "Connection" })).toBeInTheDocument();
    expect(screen.getAllByText(/Simulated/i).length).toBeGreaterThan(0);
  });

  it("is the shared CampusRide sign-in: Student selected, Admin links to the admin sign-in", async () => {
    setup();
    const form = await screen.findByRole("form", { name: "Student sign in" });
    expect(within(form).getByRole("heading", { level: 1 })).toHaveTextContent("CampusRide");
    const who = within(form).getByRole("group", { name: "Who are you?" });
    expect(within(who).getByText("Student").closest("[aria-current]")).not.toBeNull();
    // choosing Admin only navigates to the Admin app's sign-in: no credentials or token travel
    expect(within(who).getByRole("link", { name: "Admin" })).toHaveAttribute(
      "href",
      "http://localhost:5174/",
    );
    expect(within(form).getByLabelText("Student email")).toBeInTheDocument();
  });

  it("refuses an admin account on the Student sign-in and stores nothing", async () => {
    const { store } = setup({
      "POST /api/v1/auth/dev-login": () => json({ ...fx.token, user: { ...fx.me, role: "admin" } }),
    });
    await screen.findByRole("note");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This isn't a student account.");
    expect(store.get()).toBeNull();
    expect(screen.getByRole("form", { name: "Student sign in" })).toBeInTheDocument();
  });

  it("shows the backend's login error", async () => {
    setup({
      "POST /api/v1/auth/dev-login": () =>
        json(
          { error: { code: "unauthorized", message: "no seeded user with email 'x@y.z'" } },
          401,
        ),
    });
    await screen.findByRole("note");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("no seeded user");
  });

  it("refuses non-student accounts", async () => {
    setup({
      "POST /api/v1/auth/dev-login": () => json({ ...fx.token, user: { ...fx.me, role: "admin" } }),
    });
    await screen.findByRole("note");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("student account");
  });

  it("password mode: signs in with email + password (no development label, nothing stored but the token)", async () => {
    const storage = new MemoryStorage();
    const store = new SessionStore(storage);
    const backend = fakeBackend({ "GET /api/v1/auth/config": () => json(fx.passwordAuth) });
    const api = new ApiClient({
      baseUrl: "http://backend.test/api/v1",
      getToken: () => store.get()?.token ?? null,
      onUnauthorized: () => store.clear(),
      fetchImpl: backend.fetchImpl,
    });
    render(<App api={api} store={store} />);
    const password = await screen.findByLabelText("Password");
    expect(screen.queryByText(/Demo sign-in/)).not.toBeInTheDocument();
    await userEvent.type(password, "wrong-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid email or password");
    await userEvent.type(screen.getByLabelText("Password"), "right-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Test Student")).toBeInTheDocument();
    expect(backend.calls).toContain("POST /api/v1/auth/login");
    expect(backend.calls).not.toContain("POST /api/v1/auth/dev-login");
    expect(
      JSON.stringify([...Array(storage.length)].map((_, i) => storage.getItem(storage.key(i)!))),
    ).not.toContain("right-password");
  });

  it("restores the session, view and My Bus from the backend after a refresh", async () => {
    const storage = new MemoryStorage();
    new SessionStore(storage).set({
      token: "mock.saved",
      expiresAt: "2099-01-01T00:00:00Z",
      userId: "U-T1",
    });
    window.history.replaceState(null, "", "/?tab=mybus");

    const { backend } = setup({}, storage);
    const card = await screen.findByRole("region", { name: "My bus" });
    expect(card).toHaveTextContent("BX7");
    expect(card).toHaveTextContent("Test Line Two");
    expect(card).toHaveTextContent("Test Stop B");
    expect(backend.calls[0]).toBe("GET /api/v1/me"); // identity comes from the backend
    expect(backend.calls).toContain("GET /api/v1/students/me/assignment");
    await waitFor(() => expect(mapProps.current?.myStopId).toBe("X2"));
    // the only thing the browser stores is the session token — never the transport assignment
    expect(Array.from({ length: storage.length }, (_, i) => storage.key(i))).toEqual([
      "campusride.session",
    ]);
  });

  it("shows 'not available yet' for a student the college has not assigned", async () => {
    const storage = new MemoryStorage();
    new SessionStore(storage).set({
      token: "mock.saved",
      expiresAt: "2099-01-01T00:00:00Z",
      userId: "U-T1",
    });
    setup({ "GET /api/v1/students/me/assignment": () => json(fx.unassigned) }, storage);
    expect(
      await screen.findByText("Your bus assignment is not available yet."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "My Bus" }));
    expect(await screen.findByRole("region", { name: "My bus" })).toHaveTextContent(
      "not available yet",
    );
    expect(mapProps.current?.myStopId).toBeNull();
  });

  it("drops an expired/invalid session and returns to sign-in", async () => {
    const storage = new MemoryStorage();
    new SessionStore(storage).set({
      token: "mock.bad",
      expiresAt: "2099-01-01T00:00:00Z",
      userId: "U-T1",
    });
    setup(
      {
        "GET /api/v1/me": () =>
          json({ error: { code: "unauthorized", message: "invalid token" } }, 401),
      },
      storage,
    );
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(storage.getItem("campusride.session")).toBeNull();
  });

  it("explains when the backend is down", async () => {
    const storage = new MemoryStorage();
    new SessionStore(storage).set({
      token: "mock.saved",
      expiresAt: "2099-01-01T00:00:00Z",
      userId: "U-T1",
    });
    setup(
      {
        "GET /api/v1/me": () => {
          throw new TypeError("Failed to fetch");
        },
      },
      storage,
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Can't reach CampusRide");
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("tells the developer to seed when the backend has no data", async () => {
    const storage = new MemoryStorage();
    new SessionStore(storage).set({
      token: "mock.saved",
      expiresAt: "2099-01-01T00:00:00Z",
      userId: "U-T1",
    });
    setup({ "GET /api/v1/stops": () => json([]), "GET /api/v1/routes": () => json([]) }, storage);
    expect(await screen.findByText("No network data")).toBeInTheDocument();
  });

  it("selecting a stop on the map opens its backend details", async () => {
    const storage = new MemoryStorage();
    new SessionStore(storage).set({
      token: "mock.saved",
      expiresAt: "2099-01-01T00:00:00Z",
      userId: "U-T1",
    });
    setup({}, storage);
    await screen.findByTestId("map");
    await userEvent.click(screen.getByRole("button", { name: "Dashboard" })); // ensure shell is interactive
    mapProps.current!.onSelectStop("X2");
    expect(await screen.findByRole("heading", { name: "Test Stop B" })).toBeInTheDocument();
    expect(window.location.search).toContain("stop=X2");
    expect(
      await screen.findByRole("list", { name: "Routes serving this stop" }),
    ).toBeInTheDocument();
  });
});
