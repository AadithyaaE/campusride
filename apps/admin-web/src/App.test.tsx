import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { fakeBackend, json, PASSWORD_AUTH } from "./test/backend";
import { FakeWebSocket } from "./test/fakeSocket";

vi.mock("./dashboard/FleetMap", () => ({ default: () => <div data-testid="fleet-map" /> }));

class MemoryStorage implements Storage {
  private m = new Map<string, string>();
  get length() {
    return this.m.size;
  }
  clear() {
    this.m.clear();
  }
  getItem(k: string) {
    return this.m.get(k) ?? null;
  }
  key(i: number) {
    return [...this.m.keys()][i] ?? null;
  }
  removeItem(k: string) {
    this.m.delete(k);
  }
  setItem(k: string, v: string) {
    this.m.set(k, v);
  }
}

const settle = async () => {
  for (let i = 0; i < 4; i++) await act(() => new Promise((r) => setTimeout(r, 0)));
};

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
});
afterEach(() => vi.useRealTimers());

async function signIn(role = "admin") {
  const b = fakeBackend((key) =>
    key === "GET /api/v1/me"
      ? json({ id: "U-1", role, name: "Transport Office", email: "admin1@campusride.demo" })
      : undefined,
  );
  const storage = new MemoryStorage();
  render(<App fetchImpl={b.fetchImpl} storage={storage} />);
  await settle(); // sign-in options come from GET /auth/config
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await settle();
  return { b, storage };
}

describe("Admin app — sign in → control room", () => {
  it("only admins can sign in (students and drivers are refused)", async () => {
    for (const role of ["student", "driver"]) {
      const { b } = await signIn(role);
      expect(await screen.findByRole("alert")).toHaveTextContent("This isn't an admin account.");
      expect(screen.queryByRole("region", { name: "Key figures" })).not.toBeInTheDocument();
      expect(b.count("GET /api/v1/admin/fleet")).toBe(0);
      document.body.innerHTML = "";
    }
  });

  it("is the shared CampusRide sign-in: Admin selected, Student links to the student sign-in", async () => {
    const b = fakeBackend();
    render(<App fetchImpl={b.fetchImpl} storage={new MemoryStorage()} />);
    await settle();
    const form = screen.getByRole("form", { name: "Admin sign in" });
    expect(within(form).getByRole("heading", { level: 1 })).toHaveTextContent("CampusRide");
    const who = within(form).getByRole("group", { name: "Who are you?" });
    expect(within(who).getByText("Admin").closest("[aria-current]")).not.toBeNull();
    expect(within(who).getByRole("link", { name: "Student" })).toHaveAttribute(
      "href",
      "http://localhost:5173/",
    );
    expect(within(form).getByLabelText("Admin email")).toBeInTheDocument();
    // no control-room chrome before sign-in
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
  });

  it("a refused (non-admin) sign-in stores no session", async () => {
    const { storage } = await signIn("student");
    expect(await screen.findByRole("alert")).toHaveTextContent("This isn't an admin account.");
    expect(storage.getItem("campusride.admin.session")).toBeNull();
  });

  it("an admin lands on the transport control room fed by /admin/*", async () => {
    const { b, storage } = await signIn();
    const kpis = await screen.findByRole("region", { name: "Key figures" });
    expect(within(kpis).getByRole("group", { name: "Total buses" })).toHaveTextContent("12");
    expect(screen.getByRole("table", { name: "Fleet table" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Sections" })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Live status" })).toHaveTextContent("07:40:00");
    for (const k of ["overview", "fleet", "routes", "schedule", "analytics"]) {
      expect(b.count(`GET /api/v1/admin/${k}`)).toBe(1);
    }
    expect(storage.getItem("campusride.admin.session")).toContain("mock.t");
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(screen.getByRole("form", { name: "Admin sign in" })).toBeInTheDocument();
  });

  it("labels development sign-in clearly and uses /auth/dev-login", async () => {
    const { b } = await signIn();
    expect(b.calls.map((c) => c.key)).toContain("POST /api/v1/auth/dev-login");
    expect(b.calls.map((c) => c.key)).not.toContain("POST /api/v1/auth/mock-login");
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await settle();
    expect(screen.getByRole("note")).toHaveTextContent("Demo sign-in — use any demo admin account");
  });

  it("password mode: email + password, wrong password refused, password never stored", async () => {
    const b = fakeBackend((key) =>
      key === "GET /api/v1/auth/config" ? json(PASSWORD_AUTH) : undefined,
    );
    const storage = new MemoryStorage();
    render(<App fetchImpl={b.fetchImpl} storage={storage} />);
    await settle();
    expect(screen.queryByText(/Demo sign-in/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrong-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await settle();
    expect(screen.getByRole("alert")).toHaveTextContent("invalid email or password");
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "right-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await settle();
    expect(await screen.findByRole("region", { name: "Key figures" })).toBeInTheDocument();
    const login = b.calls.filter((c) => c.key === "POST /api/v1/auth/login").at(-1);
    expect(login?.body).toEqual({ email: "admin1@campusride.demo", password: "right-password" });
    expect(storage.getItem("campusride.admin.session")).not.toContain("right-password");
  });

  it("a refused WebSocket session (4401) signs the admin out", async () => {
    const { storage } = await signIn();
    expect(screen.getByRole("region", { name: "Key figures" })).toBeInTheDocument();
    const sock = FakeWebSocket.last;
    await act(async () => sock.drop(4401));
    await settle();
    expect(screen.getByRole("form", { name: "Admin sign in" })).toBeInTheDocument();
    expect(storage.getItem("campusride.admin.session")).toBeNull();
  });

  it("a 401 from any REST call signs the admin out", async () => {
    const b = fakeBackend((key) =>
      key === "GET /api/v1/admin/fleet"
        ? json({ error: { code: "unauthorized", message: "account is disabled" } }, 401)
        : undefined,
    );
    render(<App fetchImpl={b.fetchImpl} storage={new MemoryStorage()} />);
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await settle();
    await settle();
    expect(screen.getByRole("form", { name: "Admin sign in" })).toBeInTheDocument();
  });
});
